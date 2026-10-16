"""Publish registry evidence and verify observer replies against the wallet KEL."""
import json
from time import monotonic

from hio.base import doing
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from keri import kering
from keri.acdc import regeventing
from keri.app import querying
from keri.app.httping import CESR_CONTENT_TYPE
from keri.core import Diger, Number, Saider, SerderACDC, eventing
from keri.help import helping


def _events(stream):
    """Read only complete V2 registry event bodies, with one inception first."""
    ims, events = bytearray(stream), []
    while ims:
        event = SerderACDC(raw=ims)
        if event.pvrsn != kering.Vrsn_2_0 or event.ilk != ('rip' if not events else 'bup'):
            raise kering.ValidationError('Expected a V2 registry inception followed by updates')
        if Number(numh=event.sad['n']).num != len(events):
            raise kering.ValidationError('Registry response must contain a complete ordered chain')
        events.append(event)
        del ims[:event.size]
    if not events:
        raise kering.ValidationError('The registry response is empty')
    return events


def ingest(vault, regk, stream):
    """Verify an observer chain before extending accepted local registry history.

    A response cannot replace accepted events or roll back the known head.
    Native TEL acceptance markers are written in order after full validation.
    An interrupted append leaves a verified prefix that a retry can complete.
    """
    events = _events(stream)
    if events[0].said != regk:
        raise kering.ValidationError('The observer returned a different registry')
    state = regeventing.vet(rip=events[0], updates=events[1:], db=vault.hby.db)
    store = vault.rgy.store
    accepted = list(store.baser.tels.getAllItemIter(keys=regk))
    if accepted and max(sn for _, sn, _ in accepted) > state.sn:
        raise kering.ValidationError('The observer returned older registry history')
    for _, sn, said in accepted:
        if sn >= len(events) or said.qb64 != events[sn].said:
            raise kering.ValidationError(f'Conflicting registry history at sequence {sn}')
    for event, (sn, said) in zip(events, state.anchors, strict=True):
        store.putEvent(event)
        store.putAnchor(event.said, Number(num=sn), Diger(qb64=said))
        number = Number(numh=event.sad['n']).num
        if store.seqSaider(regk, number) is None:
            store.accept(regk, number, event)
    store.baser.heads.pin(keys=regk, val=Saider(qb64=state.said))
    return state


class RegistrySyncDoer(doing.DoDoer):
    """Publish to a registrar or retrieve from an observer without blocking Qt.

    Exactly one endpoint is required. ``result`` holds the verified state or
    accepted publication summary. ``error`` remains empty on success.
    """

    Timeout = 20.0
    MaxResponse = 8 * 1024 * 1024

    def __init__(self, vault, hab, regk, *, observer_url=None, registrar_url=None, **kwa):
        if bool(observer_url) == bool(registrar_url):
            raise ValueError('Provide either an observer URL or a registrar URL')
        self.vault, self.hab, self.regk = vault, hab, regk
        self.observer_url, self.registrar_url = observer_url, registrar_url
        self.result, self.error, self.manager = None, '', None
        self.querier = None
        super().__init__(doers=[doing.doify(self.sync_do)], **kwa)

    def recur(self, tyme, deeds=None):
        try:
            return super().recur(tyme, deeds)
        except Exception as ex:
            # HIO child exceptions otherwise escape the vault's scheduler. The
            # parent doer's normal exit closes the query, client, and Qt reply.
            self.error = f'Issuer key event retrieval failed: {ex}'
            if signals := getattr(self.vault, 'signals', None):
                signals.emit_doer_event('RegistrySync', 'registry_failed', {
                    'registry': self.regk, 'success': False, 'error': self.error})
            return True

    def _open(self):
        if (getattr(self.vault, 'closed', False) or not self.vault.hby.db.opened
                or not self.vault.rgy.store.opened):
            raise ValueError('The vault is closed')
        if self.vault.hby.habByPre(self.hab.pre) is not self.hab:
            raise ValueError('The query identifier does not belong to this vault')

    def _request(self, url, body, content_type, *, method="POST"):
        self._open()
        target = QUrl(url)
        if target.scheme() not in ('http', 'https') or not target.host():
            raise ValueError('Registry services require an HTTP or HTTPS URL')
        request = QNetworkRequest(target)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, content_type)
        # A signed request must not be redirected to another endpoint.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = (self.manager.put(request, body) if method == "PUT"
                 else self.manager.post(request, body))
        reply.setReadBufferSize(self.MaxResponse + 1)
        deadline = monotonic() + self.Timeout
        try:
            while not reply.isFinished():
                self._open()
                if reply.bytesAvailable() > self.MaxResponse:
                    raise ValueError('Registry response exceeds the size limit')
                if monotonic() >= deadline:
                    raise TimeoutError('Registry service request timed out')
                yield self.tock
            self._open()
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            expected = 204 if method == "PUT" else 200
            if status != expected or reply.error() != QNetworkReply.NetworkError.NoError:
                raise kering.ValidationError(f'Registry service refused the request (HTTP {status})')
            if reply.bytesAvailable() > self.MaxResponse:
                raise ValueError('Registry response exceeds the size limit')
            return bytes(reply.readAll())
        finally:
            if not reply.isFinished():
                reply.abort()
            reply.deleteLater()

    def sync_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        yield self.tock
        try:
            self._open()
            self.manager = QNetworkAccessManager()
            kel = b''.join(self.hab.db.clonePreIter(pre=self.hab.pre, gvrsn=kering.Vrsn_2_0))
            if self.registrar_url:
                tel = self.vault.rgy.store.cloneTel(self.regk)
                events = _events(tel)
                if events[0].said != self.regk or events[0].israid != self.hab.pre:
                    raise ValueError('Only the registry issuer can publish this registry')
                regeventing.vet(rip=events[0], updates=events[1:], db=self.vault.hby.db)
                payload = json.dumps({'kel': kel.decode(), 'tel': tel.decode()}).encode()
                raw = yield from self._request(self.registrar_url.rstrip('/') + '/ingest', payload,
                                            'application/json')
                summary = json.loads(raw)
                if (not isinstance(summary, dict)
                        or summary.get('accepted', {}).get(self.regk) != len(events)
                        or self.regk in summary.get('pending', {})
                        or self.regk in summary.get('rejected', {})):
                    raise kering.ValidationError('The registrar has not accepted the complete registry')
                self.result = summary
                event = 'registry_published'
            else:
                base = self.observer_url.rstrip('/')
                try:
                    yield from self._request(base + '/', kel, CESR_CONTENT_TYPE, method="PUT")
                except kering.ValidationError as ex:
                    raise kering.ValidationError(
                        f'Observer signer key history could not be submitted. {ex}') from ex
                query = eventing.query(pre=self.hab.pre, route='tels', query={'i': self.regk},
                                       stamp=helping.nowIso8601(), version=kering.Vrsn_2_0)
                signed = self.hab.endorse(query, last=True, framed=False, gvrsn=kering.Vrsn_2_0)
                raw = yield from self._request(base + '/', bytes(signed), CESR_CONTENT_TYPE)
                try:
                    self.result = ingest(self.vault, self.regk, raw)
                except kering.MissingAnchorError:
                    events = _events(raw)
                    issuer, head = events[0].israid, events[-1]
                    # A TEL body does not authorize endpoints for an unknown issuer.
                    if issuer not in self.vault.hby.kevers:
                        raise
                    seal = dict(i=self.regk, s=head.sad['n'], d=head.said)
                    self.querier = querying.AnchorQuerier(
                        hby=self.vault.hby, hab=self.hab, pre=issuer, anchor=seal,
                        version=kering.Vrsn_2_0, gvrsn=kering.Vrsn_2_0, kind=kering.Kinds.json)
                    self.extend([self.querier])
                    deadline = monotonic() + self.Timeout
                    while not self.querier.done:
                        self._open()
                        if monotonic() >= deadline:
                            raise TimeoutError('Issuer key event retrieval timed out')
                        yield self.tock
                    # The normal mailbox parser and Kevery must accept the replay.
                    self.result = ingest(self.vault, self.regk, raw)
                event = 'registry_loaded'
            if signals := getattr(self.vault, 'signals', None):
                signals.emit_doer_event('RegistrySync', event, {'registry': self.regk, 'success': True})
        except Exception as ex:
            self.error = str(ex)
            if signals := getattr(self.vault, 'signals', None):
                signals.emit_doer_event('RegistrySync', 'registry_failed',
                                       {'registry': self.regk, 'success': False, 'error': self.error})
        finally:
            if self.querier is not None:
                self.remove([self.querier])
                self.querier = None
            if self.manager is not None:
                self.manager.deleteLater()
                self.manager = None
        return True


def required(sad):
    """List registry declarations actually disclosed in this credential."""
    sections = [sad]
    if isinstance(sad.get('a'), dict):
        sections.append(sad['a'])
    aggregate = sad.get('A')
    if isinstance(aggregate, list):
        sections.extend(block for block in aggregate[1:] if isinstance(block, dict))
    return list(dict.fromkeys(section['rd'] for section in sections
                             if isinstance(section.get('rd'), str) and section['rd']))


class RegistryEvidenceDoer(doing.DoDoer):
    """Keep disclosed registry evidence current for one open vault.

    Work is reconstructed from issued credentials, accepted Grants, and native
    proof escrow. Successful freshness and publication checks are never carried
    across a vault reopen. Services are configured in ``hby.cf['registries']``.
    """

    Refresh = 60.0
    Retry = 5.0

    def __init__(self, vault, **kwa):
        self.vault = vault
        config = (vault.hby.cf.get() or {}).get('registries', {})
        self.registrar_url = config.get('registrar')
        self.observer_url = config.get('observer')
        self.errors = {}
        self._requests, self._fetched, self._published = {}, {}, {}
        self._active, self._retry = {}, {}
        super().__init__(doers=[doing.doify(self.sync_do)], **kwa)

    def _configure(self):
        config = (self.vault.hby.cf.get() or {}).get('registries', {})
        endpoints = config.get('registrar'), config.get('observer')
        if endpoints != (self.registrar_url, self.observer_url):
            self.remove(list(self._active.values()))
            self._active.clear()
            self._fetched.clear()
            self._published.clear()
            self._retry.clear()
            self.errors.clear()
            self.registrar_url, self.observer_url = endpoints

    def ensure(self, regk, hab):
        """Queue a registry check and return whether its observer evidence is fresh."""
        self._configure()
        if self.vault.hby.habByPre(hab.pre) is not hab:
            raise ValueError('The query identifier does not belong to this vault')
        self._requests[regk] = hab
        if not self.observer_url:
            self.errors[regk] = 'Open Settings and configure an observer URL to verify current registry status'
            return False
        fetched = self._fetched.get(regk)
        head = self.vault.rgy.store.head(regk)
        return bool(fetched and head and fetched[0] == head.qb64
                    and monotonic() - fetched[1] < self.Refresh)

    def published(self, regk):
        """Return whether the registrar accepted the current local registry head."""
        self._configure()
        head = self.vault.rgy.store.head(regk)
        return bool(head and self._published.get(regk) == head.qb64)

    def _discover(self, proofs):
        from keri.peer import exchanging

        default = next(iter(self.vault.hby.habs.values()), None)
        if default is None:
            return
        # Existing accepted registry heads are polled even after a restart.
        for (regk,), _ in self.vault.rgy.baser.heads.getTopItemIter():
            self._requests.setdefault(regk, default)
        grants = {record.grant for _, record in self.vault.db.accepted.getTopItemIter()}
        grants.update(said for (said,), _ in self.vault.hby.db.epse.getTopItemIter())
        grants.update(proofs)
        for said in grants:
            exn = (self.vault.hby.db.epse.get((said,))
                   or self.vault.hby.db.exns.get((said,)))
            if exn is None:
                continue
            hab = self.vault.hby.habByPre(exn.sad.get('ri', '')) or default
            for nest in exchanging.loadParsedNestedSubstreams(self.vault.hby, said):
                for regk in required(nest.serder.sad):
                    self._requests.setdefault(regk, hab)

    def sync_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        yield self.tock
        try:
            while not getattr(self.vault, 'closed', False) and self.vault.hby.db.opened:
                self._configure()
                now = monotonic()
                for key, worker in list(self._active.items()):
                    if not worker.done:
                        continue
                    operation, regk = key
                    del self._active[key]
                    if worker.error:
                        self.errors[regk] = worker.error
                        self._retry[key] = now + self.Retry
                    else:
                        self.errors.pop(regk, None)
                        self._retry.pop(key, None)
                        if operation == 'fetch':
                            self._fetched[regk] = (worker.result.said, now)
                        else:
                            self._published[regk] = worker.published_head
                    if signals := getattr(self.vault, 'signals', None):
                        signals.emit_doer_event('RegistryEvidence', 'status_checked', {
                            'registry': regk, 'operation': operation,
                            'success': not bool(worker.error), 'error': worker.error})
                proofs = set()
                cues = self.vault.exc.cues
                for _ in range(len(cues)):
                    cue = cues.popleft()
                    if cue.get('kin') == 'proof':
                        if cue.get('said'):
                            proofs.add(cue['said'])
                    elif cue.get('kin') != 'saved':
                        cues.append(cue)
                # Saved messages already notify the UI through IpexHandler.handle.
                # Proof escrows persist, so retrieval can resume after configuration.
                if self.observer_url:
                    self._discover(proofs)
                    for regk, hab in list(self._requests.items()):
                        key = ('fetch', regk)
                        if (not self.ensure(regk, hab) and key not in self._active
                                and now >= self._retry.get(key, 0)):
                            worker = RegistrySyncDoer(self.vault, hab, regk,
                                                      observer_url=self.observer_url)
                            self._active[key] = worker
                            self.extend([worker])
                if self.registrar_url:
                    for (regk,), head in self.vault.rgy.baser.heads.getTopItemIter():
                        rip = self.vault.rgy.store.seqEvent(regk, 0)
                        hab = self.vault.hby.habByPre(rip.israid) if rip else None
                        if hab is None:
                            continue
                        key = ('publish', regk)
                        if (head is not None and not self.published(regk) and key not in self._active
                                and now >= self._retry.get(key, 0)):
                            worker = RegistrySyncDoer(self.vault, hab, regk,
                                                      registrar_url=self.registrar_url)
                            worker.published_head = head.qb64
                            self._active[key] = worker
                            self.extend([worker])
                yield 1.0
        finally:
            self.remove(list(self._active.values()))
            self._active.clear()
