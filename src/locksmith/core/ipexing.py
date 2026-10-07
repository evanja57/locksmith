# -*- encoding: utf-8 -*-
"""Native exchanges with V2 JSON bodies and V2 CESR attachments."""
from contextlib import closing
from itertools import islice

from hio.base import doing
from keri import help, kering
from keri.acdc import ipexing
from keri.app import agenting, forwarding
from keri.core import SerderACDC, SerderKERI, parsing
from keri.help import helping
from keri.peer import exchanging

from locksmith.core import credentialing
from locksmith.db.basing import AcceptedCredential, GrantReceipt, IpexSubmission

logger = help.ogler.getLogger(__name__)


class IpexHandler(ipexing.IpexHandler):
    """Apply the wallet's endpoint and incoming-notification policy."""

    def __init__(self, *args, signals=None, **kwa):
        super().__init__(*args, **kwa)
        self.signals = signals

    def verify(self, serder, attachments=None, nests=None, sscs=None, evidence=None):
        if serder.pvrsn.major != 2 or not ({serder.pre, serder.ked.get('ri')} & self.hby.prefixes):
            return False
        for nest in nests or []:
            credential = nest.get('serder') if isinstance(nest, dict) else nest.serder
            issuer = getattr(credential, 'israid', None)
            if issuer:
                try:
                    # Native current-key checks use get(), which does not load disk state.
                    self.hby.db.kevers[issuer]
                except KeyError:
                    pass
        return super().verify(serder, attachments=attachments, nests=nests,
                              sscs=sscs, evidence=evidence)

    def handle(self, serder, attachments=None, nests=None, sscs=None):
        if serder.pre not in self.hby.prefixes:
            super().handle(serder, attachments=attachments, nests=nests, sscs=sscs)
        if self.signals is not None:
            self.signals.emit_doer_event('Ipex', 'saved', {'said': serder.said})


def _require_vault(vault, hab=None):
    if getattr(vault, 'closed', False) or not vault.db.opened or not vault.hby.db.opened:
        raise ValueError('The vault is closed')
    if hab is not None and hab is not vault.hby.habByPre(hab.pre):
        raise ValueError('The identifier does not belong to this vault')


def prepare(vault, hab, serder, attachment):
    """Retain a new local message, or reuse its previously verified copy.

    This is submission preparation, not intake of additional attachments.
    """
    _require_vault(vault, hab)
    if hab is not vault.hby.habByPre(serder.pre) or serder.pvrsn.major != 2:
        raise ValueError('IPEX must be signed by this vault')
    if not serder.route.startswith('/ipex/'):
        raise ValueError('Expected an IPEX message')
    if not vault.exc.complete(serder.said):
        vault.mbx.parser.parse(ims=bytearray(serder.raw + attachment), local=True,
                               version=kering.Vrsn_2_0)
    if not vault.exc.complete(serder.said):
        raise kering.ValidationError('Outgoing IPEX has not passed protocol verification')
    return exchanging.serializeMessage(vault.hby, serder.said)


def submit(vault, hab, serder, attachment):
    """Retain a signed message and authorize its delivery by the vault worker."""
    prepare(vault, hab, serder, attachment)
    if vault.db.outbox.put((serder.said,), IpexSubmission()):
        vault.signals.emit_doer_event('Ipex', 'queued', {'said': serder.said})
    return serder.said


def retry(vault, said):
    """Retry an existing submission without building or signing another message."""
    _require_vault(vault)
    record = vault.db.outbox.get((said,))
    if record is None:
        raise ValueError('No saved submission to retry')
    if record.status == 'blocked':
        raise ValueError(record.error)
    if record.status != 'sending':
        record.status, record.error, record.retry_at = 'pending', '', 0.0
        vault.db.outbox.pin((said,), record)
        vault.signals.emit_doer_event('Ipex', 'queued', {'said': said})


def grant_credential(vault, grant_said):
    """Load the origin credential from a retained, verified grant."""
    exn = vault.hby.db.exns.get(keys=(grant_said,))
    if exn is None or exn.route != '/ipex/grant' or exn.pvrsn.major != 2:
        raise kering.ValidationError('Verified native grant not found')
    exchanging.verify(vault.hby, exn)
    origin = exn.sad['a']['o'][0]
    for nest in exchanging.loadParsedNestedSubstreams(vault.hby, grant_said):
        if nest.serder.said == origin:
            return nest.serder
    raise kering.ValidationError('Grant origin evidence is missing')


def _credential_evidence(vault, credential_said):
    """Load the retained origin and its linked credentials."""
    view = credentialing.credential(vault, credential_said)
    if view['status']['et'] not in ('issued', 'authenticated'):
        raise kering.ValidationError('Credential does not have a verified issued state or issuer authentication')
    artifacts = dict(view['artifacts'])
    # Received credentials already retain the native Grant's complete evidence.
    pending = [view] if vault.db.issued.get((credential_said,)) else []
    while pending:
        current = pending.pop()
        for edge in current['sad'].get('e', {}).values():
            if not isinstance(edge, dict) or not isinstance(edge.get('n'), str):
                continue
            said = edge['n']
            if said == credential_said or said in artifacts:
                continue
            source = credentialing.credential(vault, said)
            if source['status']['et'] not in ('issued', 'authenticated'):
                raise kering.ValidationError(f'Source credential {said} is not issued')
            artifacts[said] = source['proof']
            artifacts.update(source['artifacts'])
            if vault.db.issued.get((said,)):
                pending.append(source)
    for stream in artifacts.values():
        ims = bytearray(stream)
        parsed = parsing.Parser().parse(ims=ims, processive=False, version=kering.Vrsn_2_0)
        if len(parsed) != 1 or ims or not isinstance(parsed[0].serder, SerderACDC):
            raise kering.ValidationError('Invalid retained credential evidence')
        state = credentialing.authentication(vault, parsed[0])
        if state['et'] not in ('issued', 'authenticated'):
            raise kering.ValidationError('Source credential does not have a verified issued state')
    return view, list(artifacts.values())


def grant(vault, hab, credential_said, recipient, message=''):
    """Build a grant from the wallet's retained issuance or received evidence."""
    _require_vault(vault, hab)
    view, artifacts = _credential_evidence(vault, credential_said)
    return ipexing.grant(hab, recipient, message, origin=view['proof'], artifacts=artifacts,
                         kind=kering.Kinds.json)


def request_schema(exn):
    """Read the simple whole-credential request supported by the composer."""
    plan = exn.sad['q'].get('dp', [])
    if len(plan) == 1 and len(plan[0]) == 1:
        schema, path, fields = plan[0][0]
        if path == '/' and not fields:
            return schema
    return None


def start(vault, hab, recipient, action, message='', *, schema=None, credential_said=None):
    """Start a schema request or a credential offer after explicit consent."""
    _require_vault(vault, hab)
    if not recipient or recipient == hab.pre:
        raise ValueError('Choose another identifier for this exchange')
    if action == 'Apply':
        if not schema or vault.hby.db.schema.get((schema,)) is None:
            raise ValueError('Choose a loaded schema')
        exn, atc = ipexing.apply(hab, recipient, message,
                                 modifiers={'dp': [[[schema, '/', []]]]}, kind=kering.Kinds.json)
    elif action == 'Offer':
        view, _ = _credential_evidence(vault, credential_said)
        schema = view['sad']['s']
        schema = schema if isinstance(schema, str) else schema['$id']
        exn, atc = ipexing.offer(hab, message, view['proof'], recp=recipient,
                                 modifiers={'dp': [[[schema, '/', []]]]}, kind=kering.Kinds.json)
    else:
        raise ValueError('Start with Apply or Offer')
    return submit(vault, hab, exn, atc)


def responses(vault, exn):
    """Return decisions available to the local recipient of a saved message."""
    if (exn is None or exn.sad['ri'] not in vault.hby.prefixes
            or vault.hby.db.erpy.get((exn.said,)) is not None):
        return []
    match exn.route:
        case '/ipex/apply':
            return ['Offer', 'Grant', 'Spurn']
        case '/ipex/offer':
            return ['Agree', 'Spurn']
        case '/ipex/agree':
            return ['Grant', 'Spurn']
        case '/ipex/grant':
            return ['Admit', 'Spurn'] if not exn.sad['p'] else ['Admit']
    return []


def anchor_error(hab):
    """Return why this wallet cannot prepare an IPEX KEL anchor, if any."""
    if not hab.kever.prefixer.transferable:
        return 'This step requires an identifier that supports KEL anchoring.'
    if hab.kever.wits:
        return 'Witnessed IPEX anchoring is not supported yet. No KEL event was created.'
    return None


def respond(vault, said, action, message='', credential_said=None):
    """Validate the current decision before building and saving one response."""
    _require_vault(vault)
    prior = vault.hby.db.exns.get((said,))
    if action not in responses(vault, prior):
        raise ValueError('This exchange has changed. Review its current status.')
    hab = vault.hby.habByPre(prior.sad['ri'])
    if action in ('Agree', 'Grant') and prior.sad['a'].get('ax', [False])[0]:
        if error := anchor_error(hab):
            raise kering.ValidationError(error)
    if action == 'Admit':
        exn, _ = admit(vault, hab, said, message, send=True)
        vault.signals.emit_doer_event('Ipex', 'accepted', {'said': exn.said})
        return exn.said
    if action in ('Offer', 'Grant'):
        view, artifacts = _credential_evidence(vault, credential_said)
        request = (vault.hby.db.exns.get((prior.sad['p'],))
                   if prior.route == '/ipex/agree' else prior)
        schema = request_schema(request)
        if request.sad['q'].get('dp') not in (None, [[]]) and schema is None:
            raise ValueError('This disclosure plan is not supported by the whole-credential form')
        offered = request.sad['a'].get('o', []) if request.route == '/ipex/offer' else []
        if offered and credential_said != offered[0]:
            raise ValueError('Grant must disclose the credential identified by the Offer')
        actual = view['sad']['s']
        actual = actual if isinstance(actual, str) else actual['$id']
        if schema and schema != actual:
            raise ValueError('The credential does not match the requested schema')
        if action == 'Offer':
            exn, atc = ipexing.offer(hab, message, view['proof'], apply=prior,
                                    ax=prior.sad['a'].get('ax'), kind=kering.Kinds.json)
        else:
            link = {'apply': prior} if prior.route == '/ipex/apply' else {'agree': prior}
            exn, atc = ipexing.grant(hab, prior.pre, message, view['proof'], artifacts=artifacts,
                                    ax=prior.sad['a'].get('ax'), kind=kering.Kinds.json, **link)
    elif action == 'Agree':
        exn, atc = ipexing.agree(hab, message, prior, kind=kering.Kinds.json)
    else:
        exn, atc = ipexing.spurn(hab, message, prior, kind=kering.Kinds.json)
    return submit(vault, hab, exn, atc)


def exchanges(vault):
    """Read saved IPEX chains, with transport and acceptance records attached.

    The root fixes credential direction. Reply links fix stage; signed dates
    are display metadata and never select a winner.
    """
    _require_vault(vault)
    messages = {exn.said: exn for _, exn in vault.hby.db.exns.getTopItemIter()
                if exn.pvrsn.major == 2 and exn.route.startswith('/ipex/')
                and {exn.pre, exn.sad['ri']} & vault.hby.prefixes}
    submissions = {said: record for (said,), record in vault.db.outbox.getTopItemIter()}
    receipts = list(vault.db.receipts.getTopItemIter())
    result, visited = [], set()
    for root in messages.values():
        if root.sad['p'] in messages:
            continue
        chain, tip = [], root
        problem = 'Earlier message is missing.' if root.sad['p'] else ''
        while tip.said not in visited:
            visited.add(tip.said)
            chain.append(tip)
            reply = vault.hby.db.erpy.get((tip.said,))
            if reply is None:
                break
            if reply.qb64 not in messages or reply.qb64 in visited:
                problem = 'Saved reply history is incomplete.'
                break
            tip = messages[reply.qb64]
        sender, recipient = root.pre, root.sad['ri']
        if root.route == '/ipex/apply':
            sender, recipient = recipient, sender
        saids = {exn.said for exn in chain}
        result.append(dict(root=root.said, messages=chain, sender=sender, recipient=recipient,
                           actions=responses(vault, tip) if not problem else [], problem=problem,
                           submissions={said: submissions[said] for said in saids if said in submissions},
                           receipts=[(keys, record) for keys, record in receipts if keys[1] in saids]))
    # Keep damaged saved work reachable without inventing a protocol stage.
    for said, record in submissions.items():
        if said not in messages:
            result.append(dict(root=said, messages=[], sender='', recipient='', actions=[],
                               problem='Saved message is missing.', submissions={said: record}, receipts=[]))
    for keys, record in receipts:
        if keys[1] not in messages and record.status != 'accepted':
            result.append(dict(root=keys[1], messages=[], sender='', recipient=keys[0], actions=[],
                               problem='Original grant is missing.', submissions={}, receipts=[(keys, record)]))
    return result


def _validate_credential(vault, credential, grant_said):
    grant = vault.hby.db.exns.get((grant_said,))
    prior = vault.hby.db.exns.get((grant.sad['p'],)) if grant.sad['p'] else None
    if prior and prior.route == '/ipex/agree':
        prior = vault.hby.db.exns.get((prior.sad['p'],))
    expected = request_schema(prior) if prior else None
    actual = credential.schema if isinstance(credential.schema, str) else credential.schema['$id']
    if expected and actual != expected:
        raise kering.ValidationError('The disclosed credential does not match the agreed schema')
    credentialing.validate_schema(vault, credential)
    for nest in exchanging.loadParsedNestedSubstreams(vault.hby, grant_said):
        state = credentialing.authentication(vault, nest)
        if state['et'] not in ('issued', 'authenticated'):
            raise kering.ValidationError(f"Credential state is {state['et']}, not issued")


def _finish_receipt(vault, pre, grant_said, receipt, restore=False):
    """Reconcile native evidence, the send permission and wallet membership."""
    grant = vault.hby.db.exns.get((grant_said,))
    reply = vault.hby.db.erpy.get((grant_said,))
    exn = vault.hby.db.exns.get((reply.qb64,)) if reply else None
    if (grant is None or grant.route != '/ipex/grant' or grant.sad['ri'] != pre
            or exn is None or exn.route != '/ipex/admit' or exn.pre != pre
            or exn.sad['ri'] != grant.pre or exn.sad['p'] != grant_said
            or (receipt.admit and receipt.admit != exn.said)):
        raise kering.ValidationError('Acceptance preparation is incomplete; a new exchange may be required')
    credential = grant_credential(vault, grant_said)
    if credential.said != receipt.credential:
        raise kering.ValidationError('Acceptance does not match the grant credential')
    stream = exchanging.serializeMessage(vault.hby, exn.said)
    if receipt.status != 'accepted':
        accepted = vault.db.accepted.get((credential.said,))
        # Inventory can commit before the final receipt write is interrupted.
        if (accepted is None or accepted.grant != grant_said
                or accepted.admit != exn.said):
            _validate_credential(vault, credential, grant_said)
    receipt.admit = exn.said
    if receipt.send:
        vault.db.outbox.put((exn.said,), IpexSubmission())
    if receipt.status != 'accepted' or restore:
        # Keep the original inventory provenance when another grant contains C.
        vault.db.accepted.put((credential.said,), AcceptedCredential(grant_said, exn.said,
                                                                    helping.nowIso8601()))
    receipt.status, receipt.error = 'accepted', ''
    vault.db.receipts.pin((pre, grant_said), receipt)
    return exn, stream[exn.size:]


def admit(vault, hab, grant_said, message='', *, send=False):
    """Record consent, retain one admit and optionally authorize its delivery."""
    _require_vault(vault, hab)
    grant = vault.hby.db.exns.get((grant_said,))
    if grant is None or grant.route != '/ipex/grant' or grant.sad['ri'] != hab.pre:
        raise kering.ValidationError('Grant is not addressed to the selected identifier')
    reply = vault.hby.db.erpy.get((grant_said,))
    if reply:
        saved = vault.hby.db.exns.get((reply.qb64,))
        if saved is None or saved.route != '/ipex/admit':
            raise kering.ValidationError('This Grant already has a terminal reply and cannot be accepted')
    receipt = vault.db.receipts.get((hab.pre, grant_said))
    if receipt is None:
        credential = grant_credential(vault, grant_said)
        accepted = vault.db.accepted.get((credential.said,))
        if accepted is not None and accepted.grant == grant_said:
            # Earlier V2 vaults saved acceptance without a separate receipt.
            receipt = GrantReceipt(credential=credential.said, admit=accepted.admit,
                                   send=send, status='accepted')
            return _finish_receipt(vault, hab.pre, grant_said, receipt, restore=True)
        if grant.sad['a'].get('ax', [False])[0] and vault.hby.db.erpy.get((grant_said,)) is None:
            if error := anchor_error(hab):
                raise kering.ValidationError(error)
        _validate_credential(vault, credential, grant_said)
        receipt = GrantReceipt(credential=credential.said, send=send)
        # Save consent before the native builder can create an AX anchor.
        vault.db.receipts.put((hab.pre, grant_said), receipt)
        if vault.hby.db.erpy.get((grant_said,)) is None:
            exn, atc = ipexing.admit(hab, message, grant, kind=kering.Kinds.json)
            prepare(vault, hab, exn, atc)
    elif send and not receipt.send:
        receipt.send = True
        vault.db.receipts.pin((hab.pre, grant_said), receipt)
    # Never repeat the builder after interrupted preparation.
    return _finish_receipt(vault, hab.pre, grant_said, receipt, restore=True)


class IpexOutboxDoer(doing.DoDoer):
    """Resume saved decisions and submit one pending message at a time."""

    ScanBatch = 256
    ScanDelay = 1.0

    def __init__(self, vault, **kwa):
        self.vault = vault
        for keys, receipt in vault.db.receipts.getTopItemIter():
            try:
                _finish_receipt(vault, *keys, receipt)
            except Exception as ex:
                receipt.error = str(ex)
                if receipt.status != 'accepted':
                    receipt.status = 'interrupted'
                vault.db.receipts.pin(keys, receipt)
        for keys, record in vault.db.outbox.getTopItemIter():
            if record.status == 'sending':
                record.status = 'pending'
                vault.db.outbox.pin(keys, record)
        super().__init__(doers=[doing.doify(self.sendDo)], **kwa)

    def sendDo(self, tymth=None, tock=0.0, **kwa):
        self.wind(tymth)
        yield self.tock
        while not getattr(self.vault, 'closed', False):
            pending = []
            # Yield while scanning history, and close the read transaction
            # before delivery can change records or wait on the network.
            with closing(self.vault.db.outbox.getTopItemIter()) as records:
                while batch := list(islice(records, self.ScanBatch)):
                    now = helping.nowUTC().timestamp()
                    pending.extend(said for (said,), record in batch
                                   if record.status in ('pending', 'failed')
                                   and record.retry_at <= now)
                    yield self.tock
            for said in pending:
                if getattr(self.vault, 'closed', False):
                    return
                delivery = SendIpexDoer(self.vault, said)
                self.extend([delivery])
                try:
                    while not delivery.done:
                        yield self.tock
                finally:
                    self.remove([delivery])
            yield self.ScanDelay


class SendIpexDoer(doing.DoDoer):
    """Submit a retained native exchange and report the transport result."""

    Timeout = 30.0

    RetryDelay = 30.0

    def __init__(self, vault, said, **kwa):
        self.vault, self.said = vault, said
        super().__init__(doers=[doing.doify(self.sendDo)], **kwa)

    def sendDo(self, tymth=None, tock=0.0, **kwa):
        self.wind(tymth)
        yield self.tock
        delivery = None
        record = None
        claimed = False
        try:
            _require_vault(self.vault)
            record = self.vault.db.outbox.get((self.said,))
            if (record is None or record.status not in ('pending', 'failed')
                    or record.retry_at > helping.nowUTC().timestamp()):
                return
            self.serder = self.vault.hby.db.exns.get((self.said,))
            if self.serder is None:
                raise kering.ValidationError('Saved submission has no retained message')
            self.hab = self.vault.hby.habByPre(self.serder.pre)
            if self.hab is None:
                raise kering.ValidationError('Saved submission has no local sender')
            stream = exchanging.serializeMessage(self.vault.hby, self.said)
            receipt = self.vault.db.receipts.get((self.hab.pre, self.serder.sad['p']))
            if self.serder.route == '/ipex/admit' and receipt is not None:
                if not receipt.send:
                    raise kering.ValidationError('Network delivery was not authorized')
                _finish_receipt(self.vault, self.hab.pre, self.serder.sad['p'], receipt)
            record.status, record.error = 'sending', ''
            record.attempts += 1
            self.vault.db.outbox.pin((self.said,), record)
            claimed = True
            self.vault.signals.emit_doer_event('Ipex', 'sending', {'said': self.said})
            poster = forwarding.StreamPoster(hby=self.vault.hby, hab=self.hab,
                                              recp=self.serder.sad['ri'], topic='credential')
            prefixes = [self.hab.pre]
            if self.serder.route == '/ipex/grant':
                for nest in exchanging.loadParsedNestedSubstreams(self.vault.hby, self.serder.said):
                    prefixes.append(nest.serder.israid)
                    issuee = nest.serder.iseaid
                    if issuee is not None and issuee != self.serder.sad['ri']:
                        prefixes.append(issuee)
            for pre in dict.fromkeys(prefixes):
                kever = self.vault.hby.kevers[pre]
                for msg in self.vault.hby.db.cloneDelegation(kever, gvrsn=kering.Vrsn_2_0):
                    event = SerderKERI(raw=msg)
                    poster.send(serder=event, attachment=msg[event.size:])
                for msg in self.vault.hby.db.clonePreIter(pre=pre, gvrsn=kering.Vrsn_2_0):
                    event = SerderKERI(raw=msg)
                    poster.send(serder=event, attachment=msg[event.size:])
            poster.send(serder=self.serder, attachment=stream[self.serder.size:])
            doers = poster.deliver()
            if not doers:
                raise kering.ConfigurationError('No transport could submit this IPEX message')
            delivery = doing.DoDoer(doers=doers)
            self.extend([delivery])
            deadline = self.tyme + self.Timeout
            while not delivery.done:
                if self.tyme >= deadline:
                    raise TimeoutError('IPEX transport did not finish before its deadline')
                yield self.tock
            for messenger in poster.messagers:
                if isinstance(messenger, agenting.HTTPStreamMessenger):
                    if messenger.rep is None or not 200 <= messenger.rep.status < 300:
                        raise kering.ValidationError('IPEX transport request failed')
            record.status = 'submitted'
            self.vault.db.outbox.pin((self.said,), record)
            self.vault.signals.emit_doer_event('Ipex', 'transport_submitted', {'said': self.said})
        except Exception as ex:
            if record is not None and self.vault.db.opened:
                failure = ('blocked' if not claimed and isinstance(ex, kering.ValidationError)
                           else 'failed')
                record.status, record.error = failure, str(ex)
                record.retry_at = helping.nowUTC().timestamp() + self.RetryDelay
                self.vault.db.outbox.pin((self.said,), record)
                self.vault.signals.emit_doer_event('Ipex', 'send_failed',
                                                   {'said': self.said, 'error': record.error})
            logger.exception('IPEX submission failed')
        finally:
            if delivery is not None:
                self.remove([delivery])
            if claimed and record.status == 'sending' and self.vault.db.opened:
                record.status = 'pending'
                self.vault.db.outbox.pin((self.said,), record)
