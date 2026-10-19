"""Native wallet issuance and explicit acceptance with independent stores."""
from time import monotonic, sleep

import pytest
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer
from hio.base import doing
from keri import kering
from keri.acdc.messaging import acmSchemaDefault
from keri.core import scheming, SerderKERI

from locksmith.core import credentialing, ipexing
from locksmith.core.remoting import identifier_introduction
from test_keri_v2_compat import _deliver_ipex, _retry_ipex, _ipex_fixture
from test_keri_v2_compat import ipex_vaults as ipex_vaults
from test_keri_v2_compat import ipex_mailbox as ipex_mailbox


@pytest.fixture
def schema_server(qapp):
    _, schema = acmSchemaDefault()
    schemer = scheming.Schemer(sed=schema)
    server = QTcpServer()
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
    requests, connections, buffers = [], [], {}

    def respond(connection):
        buffers[connection].extend(bytes(connection.readAll()))
        if b'\r\n\r\n' not in buffers[connection]:
            return
        path = bytes(buffers[connection]).split(b' ')[1].decode()
        buffers[connection].clear()
        requests.append(path)
        if path.startswith('/stall'):
            return
        status, headers, body = b'200 OK', b'', schemer.raw
        if path in ('/redirect', '/redirect308'):
            status = b'302 Found' if path == '/redirect' else b'308 Permanent Redirect'
            headers, body = b'Location: /schema\r\n', b''
        elif path == '/failure':
            status, body = b'503 Service Unavailable', b''
        elif path == '/invalid':
            body = b'not a schema'
        connection.write(b'HTTP/1.1 ' + status + b'\r\n' + headers +
                         f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
        connection.disconnectFromHost()

    def accept():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connections.append(connection)
            buffers[connection] = bytearray()
            connection.readyRead.connect(lambda connection=connection: respond(connection))

    server.newConnection.connect(accept)
    yield f'http://127.0.0.1:{server.serverPort()}', schemer, requests, connections
    for connection in connections:
        connection.abort()
    server.close()
    server.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize('path', ['/schema', '/redirect', '/redirect308', '/failure',
                                  '/invalid', '/stall-timeout', '/stall-close'])
def test_schema_url_loading_and_cleanup(ipex_vaults, schema_server, qapp, monkeypatch, path):
    url, schemer, requests, connections = schema_server
    app = ipex_vaults('schema-download')
    events, clock = [], [0.0]
    monkeypatch.setattr(credentialing, 'monotonic', lambda: clock[0])
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    doer = credentialing.LoadSchemaDoer(app, oobi=url + path)
    app.qtask.extend([doer])
    deadline = monotonic() + 3.0
    while path not in requests and monotonic() < deadline:
        qapp.processEvents()
        app.qtask.run()
        sleep(0.001)
    assert path in requests
    if path.startswith('/stall'):
        assert not doer.done
        assert not events
        assert app.hby.db.schema.get((schemer.said,)) is None
    if path == '/stall-close':
        app.close_vault()
    else:
        if path == '/stall-timeout':
            clock[0] = doer.Timeout + 1
        while not doer.done and monotonic() < deadline:
            qapp.processEvents()
            app.qtask.run()
            sleep(0.001)
        assert doer.done
        if path in ('/schema', '/redirect', '/redirect308'):
            assert events[-1][0] == 'schema_loaded'
            assert app.hby.db.schema.get((schemer.said,)).raw == schemer.raw
        else:
            assert events[-1][0] == 'schema_load_failed'
            assert app.hby.db.schema.get((schemer.said,)) is None
        if path == '/stall-timeout':
            assert 'timed out' in events[-1][1]['error']
    while any(connection.state() != QAbstractSocket.SocketState.UnconnectedState
              for connection in connections) and monotonic() < deadline:
        qapp.processEvents()
        sleep(0.001)
    assert all(connection.state() == QAbstractSocket.SocketState.UnconnectedState
               for connection in connections)
    if path == '/stall-close':
        assert not events


def _load_schema(app, issuer):
    _, schema = acmSchemaDefault()
    schemer = scheming.Schemer(sed=schema)
    doer = credentialing.LoadSchemaDoer(
        app, file_content=schemer.raw, enable_issuance=True, issuer_aid=issuer.pre)
    doing.Doist(doers=[doer], tock=0.03125, limit=1.0).do()
    assert app.vault.db.issuers.get((schemer.said,)) == issuer.pre
    assert app.vault.rgy.regs == {}
    return schemer


def _issue(app, schema, recipient, attributes=None, edges=None, authentication='registry', rules=None):
    events = []
    callback = lambda name, event, data: events.append((name, event, data))
    app.vault.signals.doer_event.connect(callback)
    doer = credentialing.IssueCredentialDoer(
        app, schema.said, recipient.pre, attributes or {'LEI': '254900OPPU84GM83MG36'},
        edges=edges, authentication=authentication, rules=rules)
    doing.Doist(doers=[doer], tock=0.03125, limit=1.0).do()
    app.vault.signals.doer_event.disconnect(callback)
    assert doer.done
    assert events[-1][1] == 'credential_issued', events
    return events[-1][2]['credential_said']


def test_native_issuance_keeps_independent_credentials_valid_after_reopen(ipex_vaults):
    app = ipex_vaults('native-issuer')
    issuer = app.hby.makeHab(name='issuer')
    holder = app.hby.makeHab(name='holder')
    schema = _load_schema(app, issuer)
    first = _issue(app, schema, holder)
    second = _issue(app, schema, holder)
    assert first != second
    views = credentialing.credentials(app.vault, received=False)
    assert len(views) == 2
    assert {view['status']['et'] for view in views} == {'issued'}
    assert len({view['sad']['rd'] for view in views}) == 2
    assert all(view['sad']['a']['i'] == holder.pre for view in views)
    assert not credentialing.credentials(app.vault, received=True)
    app.close_vault()
    app = ipex_vaults('native-issuer')
    assert {view['sad']['d'] for view in credentialing.credentials(app.vault)} == {first, second}
    assert credentialing.credential(app.vault, first)['status']['et'] == 'issued'
    assert credentialing.delete_credential(app.vault, first)
    assert [view['sad']['d'] for view in credentialing.credentials(app.vault)] == [second]
    assert len(app.vault.rgy.regs) == 2


def test_grant_collects_shared_sources_without_hiding_inventory_after_deletion(ipex_vaults):
    from keri.peer import exchanging

    app = ipex_vaults('shared-source')
    hab = app.hby.makeHab(name='issuer')
    schema = _load_schema(app, hab)
    leaf_a = _issue(app, schema, hab)
    leaf_b = _issue(app, schema, hab)
    source = _issue(app, schema, hab, edges={
        'leaf': {'n': leaf_a, 's': schema.said},
    })
    sibling = _issue(app, schema, hab, edges={
        'leaf': {'n': leaf_b, 's': schema.said},
    })
    child = _issue(app, schema, hab, edges={
        'source_a': {'n': source, 's': schema.said},
        'source_b': {'n': source, 's': schema.said},
        'sibling': {'n': sibling, 's': schema.said},
    })
    grant, atc = ipexing.grant(app.vault, hab, child, hab.pre)
    assert grant.sad['q']['dp'] == [[
        [schema.said, '/', []],
        [schema.said, '/e/source_a/_/', []],
        [schema.said, '/e/sibling/_/', []],
        [schema.said, '/e/source_a/_/e/leaf/_/', []],
        [schema.said, '/e/sibling/_/e/leaf/_/', []],
    ]]
    ipexing.prepare(app.vault, hab, grant, atc)
    assert app.vault.exc.complete(grant.said)
    nested = exchanging.loadParsedNestedSubstreams(app.hby, grant.said)
    assert {nest.serder.said for nest in nested} == {child, source, sibling, leaf_a, leaf_b}

    holder = app.hby.makeHab(name='holder')
    offered = ipexing.start(app.vault, hab, holder.pre, 'Offer', credential_said=child)
    previews = exchanging.loadParsedNestedSubstreams(app.hby, offered)
    # Both leaves and both parents make identical public promises.
    assert len(previews) == 3
    private_saids = {child, source, sibling, leaf_a, leaf_b}
    assert not private_saids & {nest.serder.said for nest in previews}
    assert all(nest.serder.sad['u'] == nest.serder.sad['a'] == nest.serder.sad['rd'] == ''
               for nest in previews)
    root_edges = previews[0].serder.sad['e']
    assert root_edges['source_a']['n'] == root_edges['source_b']['n'] == root_edges['sibling']['n']
    disclosed = app.hby.db.exns.get((offered,)).raw + b''.join(nest.serder.raw for nest in previews)
    assert not any(value.encode() in disclosed for value in private_saids)
    assert credentialing.credential(app.vault, child)['sad']['rd'].encode() not in disclosed
    assert b'254900OPPU84GM83MG36' not in disclosed
    agreed = ipexing.respond(app.vault, offered, 'Agree')
    negotiated = ipexing.respond(app.vault, agreed, 'Grant', credential_said=child)
    assert app.vault.exc.complete(negotiated)
    assert len(exchanging.loadParsedNestedSubstreams(app.hby, negotiated)) == 5

    assert credentialing.delete_credential(app.vault, source)
    assert {view['sad']['d'] for view in credentialing.credentials(app.vault)} == {child, sibling, leaf_a, leaf_b}
    assert credentialing.credential(app.vault, child)['status']['et'] == 'issued'
    with pytest.raises(kering.ValidationError, match='not in this wallet'):
        ipexing.grant(app.vault, hab, child, hab.pre)


@pytest.mark.parametrize('hidden_issuee', [False, True])
def test_grant_preserves_compacted_retained_disclosure(ipex_vaults, hidden_issuee):
    from keri.acdc import acdcmap
    from keri.core import Compactor, Noncer, SealSource, messagize
    from keri.peer import exchanging
    from locksmith.db.basing import IssuedCredential

    sender, receiver = ipex_vaults('compact-sender'), ipex_vaults('compact-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    receiver.hby.db.schema.pin((schema.said,), schema)
    compactor = Compactor(mad={'d': '', 'i': holder.pre, 'details': {'d': '', 'LEI': 'private-LEI'}},
                          makify=True, kind=kering.Kinds.json)
    compactor.compact(paths=[''])
    attributes = compactor.partials[('',)].mad
    full = acdcmap(israid=issuer.pre, uuid=Noncer().qb64, schema=schema.said, attribute=attributes)
    compactor = Compactor(mad=full.sad['a'], makify=True, kind=kering.Kinds.json)
    compactor.compact(paths=['i'])
    compact = acdcmap(israid=issuer.pre, uuid=full.sad['u'], schema=schema.said,
                      attribute=attributes['d'] if hidden_issuee else compactor.partials[('i',)].mad)
    assert compact.said == full.said
    anchor = SerderKERI(raw=issuer.interact(data=[{'d': full.said}]))
    proof = messagize(serder=compact, bonds=[SealSource(s=anchor.snh, d=anchor.said)])
    said = compact.said
    sender.vault.db.issued.pin((said,), IssuedCredential(compact.raw.decode(), stream=proof.decode()))
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(sender.vault, holder.replay(gvrsn=kering.Vrsn_2_0))

    if hidden_issuee:
        with pytest.raises(kering.ValidationError, match='Disclose the issuee block'):
            ipexing.grant(sender.vault, issuer, said, holder.pre)
        # Even an externally built, authenticated Grant cannot establish who
        # holds the credential when its entire issuee block remains hidden.
        from keri.acdc import ipexing as native
        grant, atc = native.grant(issuer, holder.pre, 'Hidden subject', proof,
                                  modifiers={'dp': [[[schema.said, '/', []]]]})
        _deliver_ipex(receiver.vault, grant.raw + atc)
        assert receiver.vault.exc.complete(grant.said)
        with pytest.raises(kering.ValidationError, match='Disclose the issuee block'):
            ipexing.admit(receiver.vault, holder, grant.said)
        assert receiver.vault.db.accepted.get((said,)) is None
        return
    grant, atc = ipexing.grant(sender.vault, issuer, said, holder.pre)
    assert grant.sad['q']['dp'] == [[[schema.said, '/', []]]]
    _deliver_ipex(receiver.vault, ipexing.prepare(sender.vault, issuer, grant, atc))
    ipexing.admit(receiver.vault, holder, grant.said)
    presentation, atc = ipexing.grant(receiver.vault, holder, said, issuer.pre)
    stream = ipexing.prepare(receiver.vault, holder, presentation, atc)
    assert b'private-LEI' not in stream
    nested, = exchanging.loadParsedNestedSubstreams(receiver.hby, presentation.said)
    assert nested.serder.raw == compact.raw


def test_native_grant_requires_evidence_schema_and_consent_before_inventory(ipex_vaults):
    from keri.peer import exchanging

    sender, receiver = ipex_vaults('issue-sender'), ipex_vaults('issue-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    said = _issue(sender, schema, holder)
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(sender.vault, holder.replay(gvrsn=kering.Vrsn_2_0))
    grant, attachment = ipexing.grant(sender.vault, issuer, said, holder.pre)
    assert grant.sad['q']['dp'] == [[[schema.said, '/', []]]]
    stream = ipexing.prepare(sender.vault, issuer, grant, attachment)
    _deliver_ipex(receiver.vault, stream)
    assert not receiver.vault.exc.complete(grant.said)
    with pytest.raises(kering.ValidationError):
        ipexing.admit(receiver.vault, holder, grant.said)
    assert not credentialing.credentials(receiver.vault)
    # Prepared TEL is fixture input; observer ingestion is a separate service boundary.
    regk = credentialing.credential(sender.vault, said)['sad']['rd']
    for sn in (0, 1):
        receiver.vault.rgy.store.accept(regk, sn, sender.vault.rgy.store.seqEvent(regk, sn))
    _retry_ipex(receiver.vault)
    assert not receiver.vault.exc.complete(grant.said)
    assert receiver.hby.db.emse.get((grant.said, schema.said)) is not None
    assert not credentialing.credentials(receiver.vault)
    with pytest.raises(kering.ValidationError):
        ipexing.admit(receiver.vault, holder, grant.said)
    assert receiver.vault.db.receipts.get((holder.pre, grant.said)) is None
    receiver.hby.db.schema.pin((schema.said,), schema)
    _retry_ipex(receiver.vault)
    assert receiver.vault.exc.complete(grant.said)
    assert receiver.hby.db.emse.get((grant.said, schema.said)) is None
    assert not credentialing.credentials(receiver.vault)
    admit, atc = ipexing.admit(receiver.vault, holder, grant.said)
    assert receiver.vault.exc.complete(admit.said)
    _deliver_ipex(sender.vault, admit.raw + atc)
    assert sender.vault.exc.complete(admit.said)
    assert ipexing.admit(receiver.vault, holder, grant.said)[0].said == admit.said
    assert [view['sad']['d'] for view in credentialing.credentials(receiver.vault, received=True)] == [said]
    assert not credentialing.credentials(receiver.vault, received=False)
    receiver.close_vault()
    receiver = ipex_vaults('issue-receiver')
    view = credentialing.credential(receiver.vault, said)
    assert view['status']['et'] == 'issued'
    assert view['status']['auth'] == 'registry'
    assert view['proof']
    assert receiver.vault.db.accepted.get((said,)).admit == admit.said
    assert not receiver.vault.db.receipts.get((holder.pre, grant.said)).send
    assert list(receiver.vault.db.outbox.getTopItemIter()) == []

    retained = exchanging.serializeMessage(receiver.hby, admit.said)
    assert credentialing.delete_credential(receiver.vault, said, received=True)
    receiver.close_vault()
    receiver = ipex_vaults('issue-receiver')
    holder = receiver.hby.habByName('holder')
    assert not credentialing.credentials(receiver.vault, received=True)
    _deliver_ipex(receiver.vault, stream)
    restored, restored_atc = ipexing.admit(receiver.vault, holder, grant.said,
                                          message='Restore this credential')
    assert restored.raw == admit.raw
    assert restored.raw + restored_atc == retained
    assert receiver.vault.db.accepted.get((said,)).admit == admit.said
    assert receiver.hby.db.erpy.get((grant.said,)).qb64 == admit.said
    assert [view['sad']['d'] for view in credentialing.credentials(receiver.vault, received=True)] == [said]


@pytest.mark.parametrize('authentication', ['anchor', 'signature'])
def test_registry_free_exchange_uses_mailbox_and_retains_presentation_evidence(
        ipex_vaults, ipex_mailbox, authentication, tmp_path, monkeypatch, qapp):
    from keri.acdc import ipexing as native
    from keri.peer import exchanging

    sender, receiver = ipex_vaults('free-sender'), ipex_vaults('free-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    receiver.hby.db.schema.pin((schema.said,), schema)
    rules = {'d': '', 'l': 'Example terms: use only for this test.'}
    said = _issue(sender, schema, holder, authentication=authentication, rules=rules)

    def send(source, target, hab, message):
        queued = isinstance(message, str)
        if queued:
            exn = source.hby.db.exns.get((message,))
            stream = exchanging.serializeMessage(source.hby, message)
        else:
            exn, atc = message
            stream = ipexing.prepare(source.vault, hab, exn, atc)
        ipex_mailbox(source, target, hab, exn, stream, queued=queued)
        assert target.vault.exc.complete(exn.said)
        return exn

    request = send(receiver, sender, holder, native.apply(
        holder, issuer.pre, 'Request', modifiers={'dp': [[[schema.said, '/', []]]]}, ax=[True]))
    offer = send(sender, receiver, issuer, ipexing.respond(
        sender.vault, request.said, 'Offer', credential_said=said))
    agree = send(receiver, sender, holder, ipexing.respond(receiver.vault, offer.said, 'Agree'))
    grant = send(sender, receiver, issuer, ipexing.respond(sender.vault, agree.said, 'Grant', credential_said=said))
    assert receiver.vault.db.accepted.get((said,)) is None
    admit = send(receiver, sender, holder, ipexing.admit(receiver.vault, holder, grant.said, send=True))
    proof = credentialing.credential(receiver.vault, said)['proof']
    created_at = sender.vault.db.issued.get((said,)).created_at
    accepted_at = receiver.vault.db.accepted.get((said,)).accepted_at
    assert created_at and accepted_at
    assert offer.sad['a']['ax'] == agree.sad['a']['ax'] == grant.sad['a']['ax'] == [True]
    preview, = exchanging.loadParsedNestedSubstreams(receiver.hby, offer.said)
    assert preview.serder.said != said
    assert preview.serder.sad['u'] == preview.serder.sad['a'] == ''
    assert preview.serder.sad['r']['l'] == rules['l']
    assert not any((preview.sigers, preview.cigars, preview.tsgs, preview.lsgs,
                    preview.sscs, preview.ssts, preview.bsqs, preview.bsss))
    assert b'254900OPPU84GM83MG36' not in exchanging.serializeMessage(receiver.hby, offer.said)
    sender.close_vault()
    receiver.close_vault()
    sender, receiver = ipex_vaults('free-sender'), ipex_vaults('free-receiver')
    issuer, holder = sender.hby.habByName('issuer'), receiver.hby.habByName('holder')
    assert credentialing.credential(receiver.vault, said)['proof'] == proof
    assert sender.vault.db.issued.get((said,)).created_at == created_at
    assert receiver.vault.db.accepted.get((said,)).accepted_at == accepted_at
    assert receiver.vault.db.accepted.get((said,)).admit == admit.said
    assert sender.vault.rgy.regs == receiver.vault.rgy.regs == {}
    offered = send(receiver, sender, holder, ipexing.start(
        receiver.vault, holder, issuer.pre, 'Offer', credential_said=said))
    consent = send(sender, receiver, issuer, ipexing.respond(sender.vault, offered.said, 'Agree'))
    presented = send(receiver, sender, holder, ipexing.respond(
        receiver.vault, consent.said, 'Grant', credential_said=said))
    nest, = exchanging.loadParsedNestedSubstreams(sender.hby, presented.said)
    assert exchanging.serializeParsedSubstream(nest) == proof
    assert credentialing.authentication(sender.vault, nest)['auth'] == authentication

    # A file presentation can arrive without a KEL replay after the verifier reopens.
    from locksmith.ui.vault.credentials.received.accept import AcceptCredentialDialog
    from locksmith.ui.vault.credentials.received.accept_grant import AcceptGrantDialog

    verifier = ipex_vaults('free-verifier')
    checking = verifier.hby.makeHab(name='verifier')
    _deliver_ipex(verifier.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(verifier.vault, holder.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(receiver.vault, checking.replay(gvrsn=kering.Vrsn_2_0))
    verifier.hby.db.schema.pin((schema.said,), schema)
    grant, atc = ipexing.grant(receiver.vault, holder, said, checking.pre)
    path = tmp_path / 'presentation.cesr'
    path.write_bytes(ipexing.prepare(receiver.vault, holder, grant, atc))
    verifier.close_vault()
    verifier = ipex_vaults('free-verifier')
    opened = []
    monkeypatch.setattr(AcceptGrantDialog, 'open', lambda dialog: opened.append(dialog))
    importer = AcceptCredentialDialog(app=verifier, parent=None)
    importer._admit_credential(str(path))
    assert verifier.vault.exc.complete(grant.said)
    assert len(opened) == 1 and opened[0].credential_said == said
    assert verifier.vault.db.accepted.get((said,)) is None
    checking = verifier.hby.habByName('verifier')
    ipexing.admit(verifier.vault, checking, grant.said)
    assert credentialing.credential(verifier.vault, said)['status']['auth'] == authentication
    opened[0].close()
    importer.close()


def test_imported_presentation_requires_subject_sender_and_does_not_transfer_rights(ipex_vaults, ipex_mailbox):
    source, receiver = ipex_vaults('subject-source'), ipex_vaults('subject-receiver')
    target = ipex_vaults('subject-verifier')
    issuer, subject = source.hby.makeHab(name='issuer'), source.hby.makeHab(name='subject')
    reviewer = receiver.hby.makeHab(name='reviewer')
    verifier = target.hby.makeHab(name='verifier')
    schema = _load_schema(source, issuer)
    for app in (receiver, target):
        app.hby.db.schema.pin((schema.said,), schema)
    said = _issue(source, schema, subject, authentication='signature')
    _deliver_ipex(source.vault, identifier_introduction(reviewer))
    _deliver_ipex(receiver.vault, identifier_introduction(issuer))
    with pytest.raises(kering.ValidationError, match='must address the credential issuee'):
        ipexing.grant(source.vault, issuer, said, reviewer.pre)

    # The actual subject may present its credential. Its outer signature needs
    # the subject KEL; knowing only the original issuer is insufficient.
    grant, atc = ipexing.grant(source.vault, subject, said, reviewer.pre)
    stream = ipexing.prepare(source.vault, subject, grant, atc)
    _deliver_ipex(receiver.vault, stream)
    assert not receiver.vault.exc.complete(grant.said)
    _deliver_ipex(receiver.vault, identifier_introduction(subject))
    # File import can retry the unchanged signed stream after introduction.
    _deliver_ipex(receiver.vault, stream)
    _retry_ipex(receiver.vault)
    assert receiver.vault.exc.complete(grant.said)
    ipexing.admit(receiver.vault, reviewer, grant.said)
    assert not credentialing.credential(receiver.vault, said)['held']
    with pytest.raises(kering.ValidationError, match='issuee or original issuer'):
        ipexing.grant(receiver.vault, reviewer, said, verifier.pre)

    # A second valid presentation still comes from the subject, not the reviewer.
    presentation, atc = ipexing.grant(source.vault, subject, said, verifier.pre)
    stream = ipexing.prepare(source.vault, subject, presentation, atc)
    ipex_mailbox(source, target, subject, presentation, stream)
    assert target.vault.exc.complete(presentation.said)
    ipexing.admit(target.vault, verifier, presentation.said)
    view = credentialing.credential(target.vault, said)
    assert view['status']['et'] == 'authenticated'
    assert view['sad']['i'] == issuer.pre
    assert view['sad']['a']['i'] == subject.pre
    assert view['sender'] == subject.pre
    assert view['recipient'] == verifier.pre
    assert subject.pre in target.hby.kevers
    assert not view['held']


@pytest.mark.parametrize('authentication', ['anchor', 'signature'])
def test_issuer_rotation_rechecks_new_acceptance_and_preserves_committed_receipts(ipex_vaults, authentication):
    from keri.peer import exchanging

    sender, receiver = ipex_vaults('rotation-sender'), ipex_vaults('rotation-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    receiver.hby.db.schema.pin((schema.said,), schema)
    said = _issue(sender, schema, holder, authentication=authentication)
    _deliver_ipex(sender.vault, holder.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    grants = []
    for message in ('Accept now', 'Review later'):
        grant, atc = ipexing.grant(sender.vault, issuer, said, holder.pre, message)
        _deliver_ipex(receiver.vault, ipexing.prepare(sender.vault, issuer, grant, atc))
        assert receiver.vault.exc.complete(grant.said)
        grants.append(grant)
    admit, _ = ipexing.admit(receiver.vault, holder, grants[0].said)
    original = exchanging.serializeMessage(receiver.hby, admit.said)
    issuer.rotate()
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    sender.close_vault()
    receiver.close_vault()
    sender, receiver = ipex_vaults('rotation-sender'), ipex_vaults('rotation-receiver')
    issuer, holder = sender.hby.habByName('issuer'), receiver.hby.habByName('holder')
    for vault in (sender.vault, receiver.vault):
        assert credentialing.credential(vault, said)['status']['et'] == (
            'authenticated' if authentication == 'anchor' else 'unknown')
    restored, atc = ipexing.admit(receiver.vault, holder, grants[0].said)
    assert restored.raw + atc == original
    if authentication == 'signature':
        with pytest.raises(kering.ValidationError, match='authentication failed'):
            ipexing.admit(receiver.vault, holder, grants[1].said)
        with pytest.raises(kering.ValidationError, match='issuer authentication'):
            ipexing.grant(receiver.vault, holder, said, issuer.pre)
        assert receiver.vault.db.receipts.get((holder.pre, grants[1].said)) is None
    else:
        assert ipexing.admit(receiver.vault, holder, grants[1].said)[0].route == '/ipex/admit'
        assert ipexing.grant(receiver.vault, holder, said, issuer.pre)[0].route == '/ipex/grant'


@pytest.mark.parametrize('authentication', ['registry', 'anchor'])
def test_declared_authentication_cannot_fall_back_to_valid_signature(ipex_vaults, authentication):
    from keri.core import SealSource, SerderACDC, messagize

    app = ipex_vaults('no-fallback')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    schema = _load_schema(app, issuer)
    said = _issue(app, schema, holder, authentication=authentication)
    record = app.vault.db.issued.get((said,))
    acdc = SerderACDC(raw=record.raw.encode())
    if authentication == 'registry':
        # Correct issuer signature, but no disclosure for the declared registry.
        stream = issuer.endorse(acdc)
    else:
        # Correct issuer signature with a supplied issuer seal that does not bind this ACDC.
        inception = SerderKERI(raw=issuer.msgOwnInception())
        stream = messagize(serder=acdc, sigers=issuer.sign(acdc.raw),
                           bonds=[SealSource(s='0', d=inception.said)])
    record.stream = stream.decode()
    app.vault.db.issued.pin((said,), record)
    assert credentialing.credential(app.vault, said)['status']['et'] == 'unknown'
    with pytest.raises(kering.ValidationError, match='issuer authentication'):
        ipexing.grant(app.vault, issuer, said, holder.pre)


def test_retained_graph_rechecks_linked_issuer_evidence(ipex_vaults):
    from keri.peer import exchanging

    sender, receiver = ipex_vaults('graph-sender'), ipex_vaults('graph-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    receiver.hby.db.schema.pin((schema.said,), schema)
    source = _issue(sender, schema, holder, authentication='signature')
    origin = _issue(sender, schema, holder, authentication='anchor', edges={
        'source': {'n': source, 's': schema.said}})
    _deliver_ipex(sender.vault, identifier_introduction(holder))
    _deliver_ipex(receiver.vault, identifier_introduction(issuer))
    grants = []
    for message in ('Accept now', 'Review later'):
        grant, atc = ipexing.grant(sender.vault, issuer, origin, holder.pre, message)
        assert grant.sad['q']['dp'] == [[
            [schema.said, '/', []], [schema.said, '/e/source/_/', []]]]
        _deliver_ipex(receiver.vault, ipexing.prepare(sender.vault, issuer, grant, atc))
        grants.append(grant)
    ipexing.admit(receiver.vault, holder, grants[0].said)
    assert receiver.vault.db.accepted.get((source,)) is None
    assert ipexing.grant(receiver.vault, holder, origin, issuer.pre)[0].route == '/ipex/grant'
    offer = ipexing.start(receiver.vault, holder, issuer.pre, 'Offer', credential_said=origin)
    offered = receiver.hby.db.exns.get((offer,))
    assert offered.route == '/ipex/offer'
    assert offered.sad['q']['dp'] == grants[0].sad['q']['dp']
    apply = ipexing.start(sender.vault, issuer, holder.pre, 'Apply', schema=schema.said)
    _deliver_ipex(receiver.vault, exchanging.serializeMessage(sender.hby, apply))
    with pytest.raises(ValueError, match='agreed disclosure plan'):
        ipexing.respond(receiver.vault, apply, 'Grant', credential_said=origin)
    assert receiver.hby.db.erpy.get((apply,)) is None
    offer = ipexing.respond(receiver.vault, apply, 'Offer', credential_said=origin)
    assert receiver.hby.db.exns.get((offer,)).sad['q']['dp'] == grants[0].sad['q']['dp']
    _deliver_ipex(sender.vault, exchanging.serializeMessage(receiver.hby, offer))
    agree = ipexing.respond(sender.vault, offer, 'Agree')
    _deliver_ipex(receiver.vault, exchanging.serializeMessage(sender.hby, agree))
    presentation = ipexing.respond(receiver.vault, agree, 'Grant', credential_said=origin)
    assert receiver.hby.db.exns.get((presentation,)).sad['q']['dp'] == [[]]
    _deliver_ipex(sender.vault, exchanging.serializeMessage(receiver.hby, presentation))
    assert sender.vault.exc.complete(presentation)
    issuer.rotate()
    _deliver_ipex(receiver.vault, identifier_introduction(issuer))
    assert credentialing.credential(receiver.vault, origin)['status']['et'] == 'authenticated'
    # The origin anchor is still valid; its retained signed source is no longer current.
    with pytest.raises(kering.ValidationError, match='authentication failed'):
        ipexing.grant(receiver.vault, holder, origin, issuer.pre)
    with pytest.raises(kering.ValidationError, match='authentication failed'):
        ipexing.admit(receiver.vault, holder, grants[1].said)


def _verified_grant(ipex_vaults, anchored=False):
    from keri.acdc import ipexing as native

    sender, receiver = ipex_vaults('receipt-sender'), ipex_vaults('receipt-receiver')
    issuer, holder, reg, rip, issued, credential, proof = _ipex_fixture(sender, receiver)
    receiver.vault.rgy.store.accept(reg.regk, 0, rip)
    receiver.vault.rgy.store.accept(reg.regk, 1, issued)
    grant, atc = native.grant(issuer, holder.pre, 'Grant', proof, ax=[anchored])
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    _deliver_ipex(receiver.vault, ipexing.prepare(sender.vault, issuer, grant, atc))
    assert receiver.vault.exc.complete(grant.said)
    return sender, receiver, issuer, holder, credential, grant


def test_declined_grant_reimport_stays_terminal_after_reopen(ipex_vaults):
    from keri.peer import exchanging

    _, receiver, _, holder, credential, grant = _verified_grant(ipex_vaults)
    spurn = ipexing.respond(receiver.vault, grant.said, 'Spurn')
    stream = exchanging.serializeMessage(receiver.hby, grant.said)
    pre = holder.pre
    receiver.close_vault()
    receiver = ipex_vaults('receipt-receiver')
    _deliver_ipex(receiver.vault, stream)
    with pytest.raises(kering.ValidationError, match='terminal reply'):
        ipexing.admit(receiver.vault, receiver.hby.habByPre(pre), grant.said)
    assert receiver.hby.db.erpy.get((grant.said,)).qb64 == spurn
    assert receiver.vault.db.receipts.get((pre, grant.said)) is None
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    exchange, = ipexing.exchanges(receiver.vault)
    assert exchange['messages'][-1].route == '/ipex/spurn'
    assert exchange['actions'] == []
    assert exchange['receipts'] == []


@pytest.mark.parametrize('boundary', ['before_inventory', 'submission_write_failure',
                                      'claim_write_failure', 'inventory_write_failure', 'receipt_write_failure'])
def test_acceptance_recovers_original_admit_after_interruption(
        ipex_vaults, ipex_mailbox, monkeypatch, boundary):
    from keri.peer import exchanging

    sender, receiver, issuer, holder, credential, grant = _verified_grant(ipex_vaults, anchored=True)
    if boundary == 'before_inventory':
        class Interrupted(BaseException):
            pass

        def interrupted_put(*args, **kwa):
            raise Interrupted()

        with monkeypatch.context() as patch:
            patch.setattr(receiver.vault.db.accepted, 'put', interrupted_put)
            with pytest.raises(Interrupted):
                ipexing.admit(receiver.vault, holder, grant.said, send=True)
        admit_said = receiver.hby.db.erpy.get((grant.said,)).qb64
        admit = receiver.hby.db.exns.get((admit_said,))
    elif boundary == 'receipt_write_failure':
        with monkeypatch.context() as patch:
            def fail_receipt(*args, **kwa):
                raise OSError('Temporary receipt write failure')
            patch.setattr(receiver.vault.db.receipts, 'pin', fail_receipt)
            with pytest.raises(OSError):
                ipexing.admit(receiver.vault, holder, grant.said, send=True)
        accepted = receiver.vault.db.accepted.get((credential.said,))
        admit = receiver.hby.db.exns.get((accepted.admit,))
        assert receiver.vault.db.receipts.get((holder.pre, grant.said)).status == 'preparing'
    elif boundary == 'inventory_write_failure':
        with monkeypatch.context() as patch:
            def fail_inventory(*args, **kwa):
                raise OSError('Temporary inventory write failure')
            patch.setattr(receiver.vault.db.accepted, 'put', fail_inventory)
            with pytest.raises(OSError):
                ipexing.admit(receiver.vault, holder, grant.said, send=True)
            admit_said = receiver.hby.db.erpy.get((grant.said,)).qb64
            admit = receiver.hby.db.exns.get((admit_said,))
            for _ in range(64):
                receiver.qtask.run()
        assert receiver.vault.db.outbox.get((admit.said,)).status == 'failed'
        assert receiver.vault.db.accepted.get((credential.said,)) is None
    elif boundary == 'claim_write_failure':
        admit, _ = ipexing.admit(receiver.vault, holder, grant.said, send=True)
        pin = receiver.vault.db.outbox.pin
        def fail_claim(keys, record):
            if record.status == 'sending':
                raise OSError('Temporary claim write failure')
            return pin(keys, record)
        with monkeypatch.context() as patch:
            patch.setattr(receiver.vault.db.outbox, 'pin', fail_claim)
            for _ in range(64):
                receiver.qtask.run()
        assert receiver.vault.db.outbox.get((admit.said,)).status == 'failed'
        assert not sender.vault.exc.complete(admit.said)
    else:
        # Model a caught failure to persist a successful delivery result.
        admit, _ = ipexing.admit(receiver.vault, holder, grant.said, send=True)
        pin = receiver.vault.db.outbox.pin
        def lose_submission_result(keys, record):
            if record.status == 'submitted':
                raise OSError('Delivery result could not be saved')
            return pin(keys, record)

        with monkeypatch.context() as patch:
            patch.setattr(receiver.vault.db.outbox, 'pin', lose_submission_result)
            ipex_mailbox(receiver, sender, holder, admit,
                          exchanging.serializeMessage(receiver.hby, admit.said),
                          queued=True, outcome='send_failed')
        assert sender.vault.exc.complete(admit.said)
        assert receiver.vault.db.outbox.get((admit.said,)).status == 'failed'

    stream = exchanging.serializeMessage(receiver.hby, admit.said)
    pre, sn = holder.pre, holder.kever.sn
    receiver.close_vault()
    receiver = ipex_vaults('receipt-receiver')
    holder = receiver.hby.habByPre(pre)
    receipt = receiver.vault.db.receipts.get((pre, grant.said))
    assert receipt.status == 'accepted' and receipt.admit == admit.said
    assert receipt.send
    assert receiver.vault.db.accepted.get((credential.said,)).admit == admit.said
    assert exchanging.serializeMessage(receiver.hby, admit.said) == stream
    assert holder.kever.sn == sn
    # The reopened worker retries failed delivery after its saved delay.
    from datetime import timedelta
    from keri.help import helping
    future = helping.nowUTC() + timedelta(seconds=31)
    with monkeypatch.context() as patch:
        patch.setattr(helping, 'nowUTC', lambda: future)
        ipex_mailbox(receiver, sender, holder, admit, stream, queued=True)
    assert receiver.vault.db.outbox.get((admit.said,)).status == 'submitted'
    assert sender.vault.exc.complete(admit.said)
    assert sender.hby.db.exns.get((admit.said,)).raw == admit.raw
    assert [keys for keys, _ in receiver.vault.db.accepted.getTopItemIter()] == [(credential.said,)]
    assert [keys for keys, _ in receiver.vault.db.receipts.getTopItemIter()] == [(pre, grant.said)]
    assert holder.kever.sn == sn


@pytest.mark.parametrize('interrupted', [False, True])
def test_distinct_grants_keep_separate_receipts_and_one_inventory_entry(ipex_vaults, monkeypatch, interrupted):
    from keri.acdc import ipexing as native

    sender, receiver, issuer, holder, credential, first = _verified_grant(ipex_vaults)
    first_admit, _ = ipexing.admit(receiver.vault, holder, first.said)
    accepted_at = receiver.vault.db.accepted.get((credential.said,)).accepted_at
    assert accepted_at
    proof, = sender.hby.db.enst.get((first.said,))
    second, atc = native.grant(issuer, holder.pre, 'Another grant', proof.encode())
    _deliver_ipex(receiver.vault, ipexing.prepare(sender.vault, issuer, second, atc))
    if interrupted:
        with monkeypatch.context() as patch:
            def fail_receipt(*args, **kwa):
                raise OSError('Temporary receipt write failure')
            patch.setattr(receiver.vault.db.receipts, 'pin', fail_receipt)
            with pytest.raises(OSError):
                ipexing.admit(receiver.vault, holder, second.said)
        second_admit = receiver.hby.db.exns.get((receiver.hby.db.erpy.get((second.said,)).qb64,))
        from keri.acdc import Registrar
        reg = sender.vault.rgy.registryByName('fixture')
        _, update = Registrar(rgy=sender.vault.rgy).issue(reg, acdc=credential, state='revoked')
        issuer.interact(data=[dict(i=reg.regk, s=update.sad['n'], d=update.said)])
        assert reg.anchorMsg(update.said)
        _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
        receiver.vault.rgy.store.accept(reg.regk, 2, update)
        pre = holder.pre
        receiver.close_vault()
        receiver = ipex_vaults('receipt-receiver')
        assert receiver.vault.db.receipts.get((pre, second.said)).status == 'interrupted'
        assert receiver.vault.db.receipts.get((pre, first.said)).status == 'accepted'
    else:
        second_admit, _ = ipexing.admit(receiver.vault, holder, second.said)
    assert second_admit.said != first_admit.said
    assert len(list(receiver.vault.db.receipts.getTopItemIter())) == 2
    assert receiver.vault.db.accepted.get((credential.said,)).grant == first.said
    assert receiver.vault.db.accepted.get((credential.said,)).accepted_at == accepted_at
    assert len(list(receiver.vault.db.accepted.getTopItemIter())) == 1
    assert list(receiver.vault.db.outbox.getTopItemIter()) == []


@pytest.mark.parametrize('send', [False, True])
def test_witnessed_admit_resumes_same_anchor_after_timeout_and_reopen(ipex_vaults, monkeypatch, send):
    from keri.peer import exchanging

    _, receiver, _, holder, credential, grant = _verified_grant(ipex_vaults, anchored=True)
    witness = receiver.hby.makeHab(name='receipt-witness', transferable=False)
    holder.rotate(adds=[witness.pre], toad=1)
    before, pre = holder.kever.sn, holder.pre
    admit, _ = ipexing.admit(receiver.vault, holder, grant.said, send=send)
    stream = exchanging.serializeMessage(receiver.hby, admit.said)
    (_, anchor_diger), = receiver.hby.db.ests.get((admit.said, pre))
    assert holder.kever.sn == before + 1
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    consent = receiver.vault.db.receipts.get((pre, grant.said))
    assert consent.status == 'preparing' and consent.admit == admit.said
    assert consent.send == send
    requested, closed = [], []

    def receipt(self, pre, sn=None, auths=None):
        requested.append((pre, sn))
        try:
            while True:
                yield self.tock
        finally:
            closed.append(sn)

    monkeypatch.setattr(ipexing.LocksmithReceiptor, 'receipt', receipt)
    doer = ipexing.SendIpexDoer(receiver.vault, admit.said)
    doing.Doist(doers=[doer], tock=0.03125, limit=31.0).do()
    assert doer.done and not doer.deeds
    assert requested == [(pre, before + 1)] and closed == [before + 1]
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    assert holder.kever.sn == before + 1
    if send:
        assert receiver.vault.db.outbox.get((admit.said,)).status == 'failed'
    else:
        assert receiver.vault.db.receipts.get((pre, grant.said)).status == 'interrupted'
        assert list(receiver.vault.db.outbox.getTopItemIter()) == []

    receiver.close_vault()
    receiver = ipex_vaults('receipt-receiver')
    holder, witness = receiver.hby.habByPre(pre), receiver.hby.habByName('receipt-witness')
    assert holder.kever.sn == before + 1
    assert exchanging.serializeMessage(receiver.hby, admit.said) == stream
    assert receiver.vault.db.receipts.get((pre, grant.said)).status == 'preparing'
    restored, _ = ipexing.admit(receiver.vault, holder, grant.said, send=send)
    assert restored.said == admit.said and holder.kever.sn == before + 1
    _deliver_ipex(receiver.vault, witness.witness(SerderKERI(raw=holder.msgOwnEvent(sn=before + 1))))
    assert len(receiver.hby.db.wigs.get((pre, anchor_diger.qb64))) == 1
    # Local acceptance resumes independently of permission to send the Admit.
    if send:
        restored, _ = ipexing.admit(receiver.vault, holder, grant.said, send=True)
    else:
        for _ in range(64):
            receiver.qtask.run()
    assert receiver.vault.db.accepted.get((credential.said,)).admit == admit.said
    assert receiver.vault.db.receipts.get((pre, grant.said)).status == 'accepted'
    assert receiver.vault.db.receipts.get((pre, grant.said)).send == send
    assert exchanging.serializeMessage(receiver.hby, admit.said) == stream
    assert holder.kever.sn == before + 1
    assert [keys for keys, _ in receiver.vault.db.outbox.getTopItemIter()] == ([(admit.said,)] if send else [])


@pytest.mark.parametrize('current_threshold', [0, 2])
def test_pending_ipex_anchor_keeps_its_quorum_after_witness_rotation(
        ipex_vaults, monkeypatch, current_threshold):
    from keri.peer import exchanging

    _, receiver, _, holder, credential, grant = _verified_grant(ipex_vaults, anchored=True)
    witness = receiver.hby.makeHab(name='original-witness', transferable=False)
    holder.rotate(adds=[witness.pre], toad=1)
    admit, _ = ipexing.admit(receiver.vault, holder, grant.said)
    anchor_sn = holder.kever.sn
    stream = exchanging.serializeMessage(receiver.hby, admit.said)
    original_receipt = witness.witness(SerderKERI(raw=holder.msgOwnEvent(sn=anchor_sn)))
    if current_threshold:
        added = receiver.hby.makeHab(name='added-witness', transferable=False)
        holder.rotate(adds=[added.pre], toad=current_threshold)
    else:
        holder.rotate(cuts=[witness.pre], toad=current_threshold)
    assert holder.kever.toader.num == current_threshold
    requested, release = [], [False]

    def receipt(self, pre, sn=None, auths=None):
        requested.append((pre, sn))
        if release[0]:
            _deliver_ipex(receiver.vault, original_receipt)
        yield self.tock

    monkeypatch.setattr(ipexing.LocksmithReceiptor, 'receipt', receipt)
    restored, _ = ipexing.admit(receiver.vault, holder, grant.said)
    assert restored.said == admit.said
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    first = ipexing.SendIpexDoer(receiver.vault, admit.said)
    doing.Doist(doers=[first], tock=0.03125, limit=1.0).do()
    assert first.done and not first.deeds
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    assert receiver.vault.db.receipts.get((holder.pre, grant.said)).status == 'interrupted'
    release[0] = True
    restored, _ = ipexing.admit(receiver.vault, holder, grant.said)
    second = ipexing.SendIpexDoer(receiver.vault, admit.said)
    doing.Doist(doers=[second], tock=0.03125, limit=1.0).do()
    assert second.done and not second.deeds
    assert requested == [(holder.pre, anchor_sn), (holder.pre, anchor_sn)]
    assert restored.said == admit.said
    assert receiver.vault.db.accepted.get((credential.said,)).admit == admit.said
    assert receiver.vault.db.receipts.get((holder.pre, grant.said)).status == 'accepted'
    assert not receiver.vault.db.receipts.get((holder.pre, grant.said)).send
    assert list(receiver.vault.db.outbox.getTopItemIter()) == []
    assert exchanging.serializeMessage(receiver.hby, admit.said) == stream
    assert holder.kever.sn == anchor_sn + 1


@pytest.mark.parametrize('expired', [False, True])
def test_interrupted_anchored_preparation_does_not_repeat_kel_action(ipex_vaults, monkeypatch, expired):
    sender, receiver, issuer, holder, credential, grant = _verified_grant(ipex_vaults, anchored=True)
    sn, pre = holder.kever.sn, holder.pre
    if expired:
        from datetime import timedelta
        from keri.help import helping
        now = helping.fromIso8601(grant.stamp) + timedelta(days=2)
        monkeypatch.setattr(helping, 'nowUTC', lambda: now)
        assert 'Ask the sender' in ipexing.expiry_error(receiver.vault, grant)
        assert 'Start a new offer' in ipexing.expiry_error(sender.vault, grant)
        with pytest.raises(kering.ValidationError, match='exchange has expired'):
            ipexing.admit(receiver.vault, holder, grant.said, send=True)
        assert holder.kever.sn == sn
        assert receiver.vault.db.receipts.get((pre, grant.said)) is None
        assert receiver.vault.db.accepted.get((credential.said,)) is None
        assert receiver.hby.db.erpy.get((grant.said,)) is None
        assert not list(receiver.vault.db.outbox.getTopItemIter())
        return
    with monkeypatch.context() as patch:
        def interrupt(*args, **kwa):
            raise OSError('Interrupted before retaining the signed admit')
        patch.setattr(ipexing, 'prepare', interrupt)
        with pytest.raises(OSError):
            ipexing.admit(receiver.vault, holder, grant.said, send=True)
    assert holder.kever.sn == sn + 1
    receiver.close_vault()
    receiver = ipex_vaults('receipt-receiver')
    holder = receiver.hby.habByPre(pre)
    receipt = receiver.vault.db.receipts.get((pre, grant.said))
    assert receipt.status == 'interrupted' and receipt.error
    with pytest.raises(kering.ValidationError, match='preparation is incomplete'):
        ipexing.admit(receiver.vault, holder, grant.said, send=True)
    assert holder.kever.sn == sn + 1
    assert receiver.vault.db.accepted.get((credential.said,)) is None
    assert list(receiver.vault.db.outbox.getTopItemIter()) == []


@pytest.mark.real_routes
@pytest.mark.parametrize('anchored', [False, True])
def test_witnessed_five_stage_exchange_over_http_and_reopen(ipex_vaults, anchored):
    import socket
    from keri.app import habbing, indirecting, storing
    from keri.db import openLMDB
    from keri.peer import exchanging
    from locksmith.core.receipting import LocksmithReceiptor

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with habbing.openHab(name='exchange-witness', transferable=False, temp=True,
                         version=kering.Vrsn_2_0) as (whby, witness), \
            openLMDB(cls=storing.Mailboxer, name='exchange-witness') as mailbox:
        server = doing.Doist(doers=indirecting.setupWitness(
            whby, alias=witness.name, mbx=mailbox, tcpPort=None, httpPort=port,
            version=kering.Vrsn_2_0), tock=0.03125)
        server.enter()
        try:
            issuer_app, holder_app = ipex_vaults('http-issuer'), ipex_vaults('http-holder')
            issuer = issuer_app.hby.makeHab(name='issuer', wits=[witness.pre], toad=1)
            holder = holder_app.hby.makeHab(name='holder', wits=[witness.pre], toad=1)
            witness_intro = witness.replay(gvrsn=kering.Vrsn_2_0) + witness.makeLocScheme(
                url=f'http://127.0.0.1:{port}', scheme='http')
            for app, hab in ((issuer_app, issuer), (holder_app, holder)):
                _deliver_ipex(app.vault, witness_intro)
                receiptor = LocksmithReceiptor(hby=app.hby)
                receipts = doing.Doist(doers=[receiptor], tock=0.03125)
                receipts.enter()
                try:
                    receiptor.msgs.append(dict(pre=hab.pre, sn=0))
                    deadline = monotonic() + 10
                    while not app.hby.db.wigs.get((hab.pre, hab.kever.serder.said)) and monotonic() < deadline:
                        server.recur()
                        receipts.recur()
                        sleep(0.001)
                    assert len(app.hby.db.wigs.get((hab.pre, hab.kever.serder.said))) == 1
                finally:
                    receipts.exit()
            _deliver_ipex(issuer_app.vault, identifier_introduction(holder))
            _deliver_ipex(holder_app.vault, identifier_introduction(issuer))
            schema = _load_schema(issuer_app, issuer)
            holder_app.hby.db.schema.pin((schema.said,), schema)
            credential = _issue(issuer_app, schema, holder, authentication='signature')

            def receive(app, said):
                deadline = monotonic() + 15
                while not app.vault.exc.complete(said) and monotonic() < deadline:
                    server.recur()
                    issuer_app.qtask.run()
                    holder_app.qtask.run()
                    sleep(0.001)
                assert app.vault.exc.complete(said), (said, list(app.vault.db.inbox.getTopItemIter()))

            before = issuer.kever.sn, holder.kever.sn
            apply = ipexing.start(holder_app.vault, holder, issuer.pre, 'Apply', schema=schema.said,
                                  ax=[anchored])
            receive(issuer_app, apply)
            offer = ipexing.respond(issuer_app.vault, apply, 'Offer', credential_said=credential)
            receive(holder_app, offer)
            agree = ipexing.respond(holder_app.vault, offer, 'Agree')
            receive(issuer_app, agree)
            grant = ipexing.respond(issuer_app.vault, agree, 'Grant', credential_said=credential)
            receive(holder_app, grant)
            admit, _ = ipexing.admit(holder_app.vault, holder, grant, send=True)
            receive(issuer_app, admit.said)
            assert holder_app.vault.db.accepted.get((credential,)).admit == admit.said
            messages = ipexing.exchanges(issuer_app.vault)[0]['messages']
            assert [exn.route for exn in messages] == [
                '/ipex/apply', '/ipex/offer', '/ipex/agree', '/ipex/grant', '/ipex/admit']
            assert all(exn.sad['a'].get('ax', [False])[0] == anchored for exn in messages)
            assert (issuer.kever.sn, holder.kever.sn) == (before[0] + anchored, before[1] + 2 * anchored)
            if anchored:
                for exn in messages[2:]:
                    app = issuer_app if exn.pre == issuer.pre else holder_app
                    (_, diger), = app.hby.db.ests.get((exn.said, exn.pre))
                    assert len(app.hby.db.wigs.get((exn.pre, diger.qb64))) == 1
            streams = {exn.said: exchanging.serializeMessage(issuer_app.hby, exn.said) for exn in messages}
            issuer_app.close_vault()
            holder_app.close_vault()
            issuer_app, holder_app = ipex_vaults('http-issuer'), ipex_vaults('http-holder')
            assert issuer_app.vault.exc.complete(admit.said)
            assert holder_app.vault.db.accepted.get((credential,)).admit == admit.said
            for said, stream in streams.items():
                assert exchanging.serializeMessage(issuer_app.hby, said) == stream
                assert exchanging.serializeMessage(holder_app.hby, said) == stream
            holder = holder_app.hby.habByName('holder')
            followup = ipexing.start(holder_app.vault, holder, issuer.pre, 'Apply', schema=schema.said)
            receive(issuer_app, followup)
        finally:
            server.exit()


def test_issuance_rejects_schema_mismatch(ipex_vaults):
    app = ipex_vaults('schema-mismatch')
    hab = app.hby.makeHab(name='issuer')
    _, schema = acmSchemaDefault()
    schema['properties']['a'] = {
        'type': 'object', 'required': ['LEI'],
        'properties': {'LEI': {'type': 'string'}}}
    schema['$id'] = ''
    schemer = scheming.Schemer(sed=schema)
    app.hby.db.schema.pin((schemer.said,), schemer)
    app.vault.db.issuers.pin((schemer.said,), hab.pre)
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    doer = credentialing.IssueCredentialDoer(app, schemer.said, hab.pre, {'LEI': 123})
    doing.Doist(doers=[doer], tock=0.03125, limit=1.0).do()
    assert events[-1][0] == 'credential_issuance_failed'
    assert 'credential_issued' not in [event for event, _ in events]
    assert not credentialing.credentials(app.vault)
    assert hab.kever.sn == 0


@pytest.mark.parametrize(('authentication', 'ends_early'), [('registry', False), ('anchor', True)])
def test_witness_timeout_preserves_pending_issuance_and_closes_receiptor(
        ipex_vaults, monkeypatch, authentication, ends_early):
    app = ipex_vaults('issuance-timeout')
    witness = app.hby.makeHab(name='witness', transferable=False)
    hab = app.hby.makeHab(name='issuer', wits=[witness.pre], toad=1)
    schema = _load_schema(app, hab)
    receipts = []
    def receipt(self, pre, sn=None, auths=None):
        receipts.append(sn)
        if sn == 1 and authentication == 'registry':
            _deliver_ipex(app.vault, witness.witness(SerderKERI(raw=hab.msgOwnEvent(sn=sn))))
            return
        try:
            if ends_early:
                return
            while True:
                yield self.tock
        finally:
            receipts.append('closed')
    monkeypatch.setattr(credentialing.LocksmithReceiptor, 'receipt', receipt)
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    doer = credentialing.IssueCredentialDoer(app, schema.said, hab.pre, {'LEI': 'test'},
                                            authentication=authentication)
    doing.Doist(doers=[doer], tock=0.03125, limit=31.0).do()
    assert doer.done
    assert not doer.deeds
    assert receipts == ([1, 2, 'closed'] if authentication == 'registry' else [1, 'closed']), (receipts, events)
    assert events[-1][0] == 'credential_issuance_failed'
    ((said,), _), = app.vault.db.issued.getTopItemIter()
    app.vault.rgy.processEscrows()
    assert credentialing.credential(app.vault, said)['status']['et'] == 'pending'
    with pytest.raises(kering.ValidationError, match='verified issued state'):
        ipexing.grant(app.vault, hab, said, hab.pre)
    app.close_vault()
    reopened = ipex_vaults('issuance-timeout')
    assert len(list(reopened.vault.db.issued.getTopItemIter())) == 1
    reopened.vault.rgy.processEscrows()
    assert credentialing.credential(reopened.vault, said)['status']['et'] == 'pending'
    hab = reopened.hby.habByName('issuer')
    witness = reopened.hby.habByName('witness')
    sn = 2 if authentication == 'registry' else 1
    _deliver_ipex(reopened.vault, witness.witness(SerderKERI(raw=hab.msgOwnEvent(sn=sn))))
    reopened.vault.rgy.processEscrows()
    assert credentialing.credential(reopened.vault, said)['status']['et'] == (
        'issued' if authentication == 'registry' else 'authenticated')


@pytest.mark.parametrize('kind', [kering.Kinds.json, kering.Kinds.cbor, kering.Kinds.mgpk])
@pytest.mark.parametrize('state', ['issued', 'revoked'])
def test_native_credential_content_kind_and_acceptance_state(ipex_vaults, kind, state):
    from keri.acdc import Registrar, acdcmap
    from keri.acdc import ipexing as native_ipexing
    from keri.core import messagize
    from keri.peer import exchanging

    sender, receiver = ipex_vaults('content-sender'), ipex_vaults('content-receiver')
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    registrar = Registrar(rgy=sender.vault.rgy)
    reg = registrar.makeRegistry(name='content', prefix=issuer.pre)
    rip = sender.vault.rgy.store.event(reg.regk)
    issuer.interact(data=[dict(i=reg.regk, s=rip.sad['n'], d=rip.said)])
    assert reg.anchorMsg(rip.said)
    acdc = acdcmap(israid=issuer.pre, regid=reg.regk, iseaid=holder.pre,
                   schema=schema.said, attribute={'d': '', 'LEI': 'test'}, kind=kind)
    blinder, update = registrar.issue(reg, acdc=acdc, state=state)
    issuer.interact(data=[dict(i=reg.regk, s=update.sad['n'], d=update.said)])
    assert reg.anchorMsg(update.said)
    vacuous, update = registrar.vacate(reg)
    issuer.interact(data=[dict(i=reg.regk, s=update.sad['n'], d=update.said)])
    assert reg.anchorMsg(update.said)
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    # Registry data is prepared fixture evidence, not observer delivery.
    for sn in range(3):
        receiver.vault.rgy.store.accept(reg.regk, sn, sender.vault.rgy.store.seqEvent(reg.regk, sn))
    receiver.hby.db.schema.pin((schema.said,), schema)
    proof = messagize(serder=acdc, bonds=[blinder.data, vacuous.data], framed=False)
    grant, attachment = native_ipexing.grant(issuer, holder.pre, 'Credential', origin=proof)
    _deliver_ipex(receiver.vault, grant.raw + attachment)
    assert receiver.vault.exc.complete(grant.said)
    if state == 'issued':
        admit, _ = ipexing.admit(receiver.vault, holder, grant.said)
        assert receiver.vault.exc.complete(admit.said)
        assert credentialing.credential(receiver.vault, acdc.said)['status']['et'] == 'issued'
        nested, = exchanging.loadParsedNestedSubstreams(receiver.hby, grant.said)
        assert nested.serder.kind == kind
        assert nested.serder.raw == acdc.raw
    else:
        with pytest.raises(kering.ValidationError, match='revoked'):
            ipexing.admit(receiver.vault, holder, grant.said)
        assert not credentialing.credentials(receiver.vault)
        assert not receiver.hby.db.erpy.get((grant.said,))


@pytest.mark.parametrize('saved_receipt', ['accepted', 'legacy', 'interrupted'])
def test_accepted_credential_retains_admit_after_revocation(ipex_vaults, monkeypatch, saved_receipt):
    from keri.acdc import Registrar
    from keri.peer import exchanging

    sender, receiver, issuer, holder, credential, grant = _verified_grant(ipex_vaults)
    if saved_receipt == 'interrupted':
        with monkeypatch.context() as patch:
            def fail_receipt(*args, **kwa):
                raise OSError('Temporary receipt write failure')
            patch.setattr(receiver.vault.db.receipts, 'pin', fail_receipt)
            with pytest.raises(OSError):
                ipexing.admit(receiver.vault, holder, grant.said)
        accepted = receiver.vault.db.accepted.get((credential.said,))
        admit = receiver.hby.db.exns.get((accepted.admit,))
        assert receiver.vault.db.receipts.get((holder.pre, grant.said)).status == 'preparing'
    else:
        admit, _ = ipexing.admit(receiver.vault, holder, grant.said)
    retained = exchanging.serializeMessage(receiver.hby, admit.said)
    if saved_receipt == 'legacy':
        # Earlier V2 vaults have the same native evidence and inventory entry,
        # but no separate per-grant receipt.
        receiver.vault.db.receipts.rem((holder.pre, grant.said))
    reg = sender.vault.rgy.registryByName('fixture')
    registrar = Registrar(rgy=sender.vault.rgy)
    revoked, update = registrar.issue(reg, acdc=credential, state='revoked')
    issuer.interact(data=[dict(i=reg.regk, s=update.sad['n'], d=update.said)])
    assert reg.anchorMsg(update.said)
    _deliver_ipex(receiver.vault, issuer.replay(gvrsn=kering.Vrsn_2_0))
    receiver.vault.rgy.store.accept(reg.regk, 2, update)
    assert credentialing.credential_state(receiver.vault, credential, revoked).state == 'revoked'

    # A past acceptance can still be restored after the exchange window closes.
    from datetime import timedelta
    from keri.help import helping
    now = helping.fromIso8601(grant.stamp) + timedelta(days=2)
    monkeypatch.setattr(helping, 'nowUTC', lambda: now)
    receiver.close_vault()
    receiver = ipex_vaults('receipt-receiver')
    holder = receiver.hby.habByName('holder')
    if saved_receipt != 'legacy':
        assert receiver.vault.db.receipts.get((holder.pre, grant.said)).status == 'accepted'
    # Recovery preserves past acceptance; the old disclosure cannot reveal the new state.
    assert credentialing.credential(receiver.vault, credential.said)['status']['et'] == 'unknown'
    restored, atc = ipexing.admit(receiver.vault, holder, grant.said)
    assert restored.raw + atc == retained
    receipt = receiver.vault.db.receipts.get((holder.pre, grant.said))
    assert receipt.status == 'accepted' and receipt.admit == admit.said
    assert not ipexing.exchanges(receiver.vault)[0]['expired']
    assert not receipt.send
    assert list(receiver.vault.db.outbox.getTopItemIter()) == []
    restored, atc = ipexing.admit(receiver.vault, holder, grant.said, send=True)
    assert restored.raw + atc == retained
    assert receiver.vault.db.outbox.get((admit.said,)).status == 'pending'
    with pytest.raises(kering.ValidationError, match='verified issued state'):
        ipexing.grant(receiver.vault, holder, credential.said, issuer.pre)


def test_registry_exchange_requires_observer_even_with_valid_local_evidence(ipex_vaults):
    sender = ipex_vaults('observer-required-issuer', registry_services=True)
    receiver = ipex_vaults('observer-required-holder', registry_services=True)
    issuer, holder = sender.hby.makeHab(name='issuer'), receiver.hby.makeHab(name='holder')
    schema = _load_schema(sender, issuer)
    receiver.hby.db.schema.pin((schema.said,), schema)
    said = _issue(sender, schema, holder)
    view = credentialing.credential(sender.vault, said)
    assert view['status']['et'] == 'issued'
    assert sender.vault.registry_evidence is not None
    with pytest.raises(kering.MissingChainError, match='Configure an observer'):
        ipexing.grant(sender.vault, issuer, said, holder.pre)

    # Valid local TEL fixture evidence does not stand in for an observer check.
    # Service transport itself is exercised in the separate registry tests.
    from keri.acdc import ipexing as native
    _deliver_ipex(receiver.vault, identifier_introduction(issuer))
    regk = view['sad']['rd']
    for sn in (0, 1):
        receiver.vault.rgy.store.accept(regk, sn, sender.vault.rgy.store.seqEvent(regk, sn))
    grant, atc = native.grant(issuer, holder.pre, 'Registry credential', origin=view['proof'],
                              modifiers={'dp': [[[schema.said, '/', []]]]})
    _deliver_ipex(receiver.vault, grant.raw + atc)
    assert receiver.vault.exc.complete(grant.said)
    with pytest.raises(kering.MissingChainError, match='Configure an observer'):
        ipexing.admit(receiver.vault, holder, grant.said)
    assert receiver.vault.db.receipts.get((holder.pre, grant.said)) is None
    assert receiver.vault.db.accepted.get((said,)) is None
