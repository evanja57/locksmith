"""Registry transport must retain only complete, anchored, current evidence."""
from collections import deque
from contextlib import ExitStack
import json
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from hio.base import doing
from PySide6.QtNetwork import QHostAddress, QTcpServer
from keri import kering
from keri.acdc import Registrar, Regery, acdcmap, blindate
from keri.app import habbing
from keri.core import Diger, Kevery, Parser

from locksmith.core import registries


@pytest.fixture
def wallets():
    with ExitStack() as stack:
        def make(name):
            hby = stack.enter_context(habbing.openHby(name=name, temp=True, version=kering.Vrsn_2_0))
            rgy = Regery(hby=hby, name=name, temp=True)
            stack.callback(rgy.close)
            return SimpleNamespace(hby=hby, rgy=rgy, exc=SimpleNamespace(cues=deque()))
        yield make('registry-sender'), make('registry-receiver')


def _anchor(hab, registry, event):
    hab.interact(data=[dict(i=registry.regk, s=event.sad['n'], d=event.said)], gvrsn=kering.Vrsn_2_0)
    assert registry.anchorMsg(event.said)


def _issue(vault):
    hab = vault.hby.makeHab(name='issuer')
    registrar = Registrar(rgy=vault.rgy)
    registry = registrar.makeRegistry(name='registry', prefix=hab.pre)
    rip = vault.rgy.store.event(registry.regk)
    _anchor(hab, registry, rip)
    acdc = acdcmap(israid=hab.pre, regid=registry.regk, attribute={'d': '', 'value': 'example'})
    _, update = registrar.issue(registry, acdc=acdc, state='issued')
    _anchor(hab, registry, update)
    return hab, registrar, registry, acdc


def _copy_kel(source, receiver):
    raw = b''.join(source.db.clonePreIter(pre=source.pre, gvrsn=kering.Vrsn_2_0))
    Parser(version=kering.Vrsn_2_0).parse(
        ims=bytearray(raw), kvy=Kevery(db=receiver.hby.db, local=False, lax=False))


def test_registry_ingest_persists_chain_and_rejects_rollback_and_conflict(wallets):
    sender, receiver = wallets
    hab, registrar, registry, acdc = _issue(sender)
    _copy_kel(hab, receiver)
    initial = sender.rgy.store.cloneTel(registry.regk)
    result = registries.ingest(receiver, registry.regk, initial)
    assert result.sn == 1
    assert receiver.rgy.store.cloneTel(registry.regk) == initial
    assert all(receiver.rgy.store.anchor(event.said) for event in registries._events(initial))
    assert registries.ingest(receiver, registry.regk, initial).said == result.said
    _, update = registrar.issue(registry, acdc=acdc, state='revoked')
    _anchor(hab, registry, update)
    _copy_kel(hab, receiver)
    full = sender.rgy.store.cloneTel(registry.regk)
    assert registries.ingest(receiver, registry.regk, full).sn == 2
    with pytest.raises(kering.ValidationError, match='older'):
        registries.ingest(receiver, registry.regk, initial)
    assert receiver.rgy.store.headEvent(registry.regk).said == update.said

    # A different anchored event at the same sequence must not replace history.
    original_events = registries._events(full)
    fork = blindate(regid=registry.regk, prior=original_events[1].said,
                    blid=Diger(ser=b'conflicting state').qb64, sn=2)
    hab.interact(data=[dict(i=registry.regk, s=fork.sad['n'], d=fork.said)], gvrsn=kering.Vrsn_2_0)
    _copy_kel(hab, receiver)
    with pytest.raises(kering.ValidationError, match='Conflicting'):
        registries.ingest(receiver, registry.regk, initial + fork.raw)
    assert receiver.rgy.store.event(fork.said) is None
    assert receiver.rgy.store.cloneTel(registry.regk) == full
    assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    receiver.rgy.baser.close(clear=False)
    receiver.rgy.baser.reopen(reuse=True)
    assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    assert receiver.rgy.store.cloneTel(registry.regk) == full


@pytest.mark.parametrize('failure', ['unknown-issuer', 'missing-anchor', 'truncated', 'wrong-registry', 'gap'])
def test_registry_ingest_failure_leaves_store_unchanged(wallets, failure):
    sender, receiver = wallets
    hab, registrar, registry, acdc = _issue(sender)
    if failure != 'unknown-issuer':
        _copy_kel(hab, receiver)
    stream, regk = sender.rgy.store.cloneTel(registry.regk), registry.regk
    if failure == 'missing-anchor':
        _, pending = registrar.issue(registry, acdc=acdc, state='revoked')
        stream += pending.raw
    elif failure == 'truncated':
        stream = stream[:-1]
    elif failure == 'wrong-registry':
        regk = Diger(ser=b'another registry').qb64
    elif failure == 'gap':
        _, pending = registrar.issue(registry, acdc=acdc, state='revoked')
        stream = sender.rgy.store.seqEvent(regk, 0).raw + pending.raw
    expected = (kering.MissingAnchorError if failure in ('unknown-issuer', 'missing-anchor')
                else kering.ShortageError if failure == 'truncated' else kering.ValidationError)
    with pytest.raises(expected):
        registries.ingest(receiver, regk, stream)
    assert list(receiver.rgy.baser.tels.getAllItemIter()) == []
    assert list(receiver.rgy.baser.evts.getTopItemIter()) == []
    assert receiver.rgy.store.head(regk) is None


@pytest.fixture
def service(qapp):
    server = QTcpServer()
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
    connections, buffers, requests = [], {}, []
    state = {'respond': lambda method, path, body: (200, b'{}')}
    def read(connection):
        buffers[connection].extend(bytes(connection.readAll()))
        raw = buffers[connection]
        while b'\r\n\r\n' in raw:
            header, body = bytes(raw).split(b'\r\n\r\n', 1)
            headers = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:])
            length = int(next(value for key, value in headers.items() if key.lower() == b'content-length'))
            if len(body) < length:
                return
            del raw[:len(header) + 4 + length]
            method, path = [part.decode() for part in header.split(b' ')[:2]]
            requests.append((method, path, body[:length]))
            result = state['respond'](method, path, body[:length])
            if result is None:
                return
            status, response = result
            connection_mode = 'keep-alive' if state.get('keepalive') else 'close'
            connection.write(f'HTTP/1.1 {status} Reply\r\nContent-Length: {len(response)}\r\nConnection: {connection_mode}\r\n\r\n'.encode() + response)
            if not state.get('keepalive'):
                connection.disconnectFromHost()
                return
    def accept():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connections.append(connection)
            buffers[connection] = bytearray()
            connection.readyRead.connect(lambda connection=connection: read(connection))
    server.newConnection.connect(accept)
    yield f'http://127.0.0.1:{server.serverPort()}', state, requests
    for connection in connections:
        connection.abort()
    server.close()
    server.deleteLater()
    qapp.processEvents()


def _advance(runner, qapp):
    qapp.processEvents()
    runner.tyme = monotonic()
    runner.recur()
    sleep(0.001)


def _run(doer, qapp):
    runner = doing.Doist(doers=[doer], tyme=monotonic(), tock=0.0)
    runner.enter()
    try:
        deadline = monotonic() + 4
        while not doer.done and monotonic() < deadline:
            _advance(runner, qapp)
        assert doer.done
    finally:
        runner.exit()


@pytest.mark.parametrize('accepted', [True, False])
def test_publish_requires_registrar_acceptance(wallets, service, qapp, accepted):
    sender, _ = wallets
    hab, _, registry, _ = _issue(sender)
    url, state, requests = service
    summary = {'accepted': {registry.regk: 2} if accepted else {},
               'pending': {} if accepted else {registry.regk: 2}, 'rejected': {}}
    state['respond'] = lambda method, path, body: (200, json.dumps(summary).encode())
    doer = registries.RegistrySyncDoer(sender, hab, registry.regk, registrar_url=url)
    _run(doer, qapp)
    assert (doer.result == summary) is accepted
    assert bool(doer.error) is not accepted
    method, path, body = requests[0]
    payload = json.loads(body)
    assert (method, path) == ('POST', '/ingest')
    assert payload['kel'].encode() == b''.join(hab.db.clonePreIter(pre=hab.pre, gvrsn=kering.Vrsn_2_0))
    assert payload['tel'].encode() == sender.rgy.store.cloneTel(registry.regk)
    assert doer.manager is None


def test_observer_fetch_introduces_signer_and_verifies_reply(wallets, service, qapp):
    sender, receiver = wallets
    issuer, _, registry, _ = _issue(sender)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='holder')
    url, state, requests = service
    stream = sender.rgy.store.cloneTel(registry.regk)
    state['respond'] = lambda method, path, body: (204, b'') if method == 'PUT' else (200, stream)
    doer = registries.RegistrySyncDoer(receiver, holder, registry.regk, observer_url=url)
    _run(doer, qapp)
    assert doer.error == ''
    assert doer.result.said == sender.rgy.store.headEvent(registry.regk).said
    assert [(method, path) for method, path, _ in requests] == [('PUT', '/'), ('POST', '/')]
    parsed = Parser(version=kering.Vrsn_2_0).parse(ims=bytearray(requests[1][2]), processive=False)
    assert parsed[0].serder.sad['q']['i'] == registry.regk
    assert parsed[0].serder.sad['r'] == 'tels'
    assert receiver.rgy.store.cloneTel(registry.regk) == stream
    assert doer.manager is None


@pytest.mark.parametrize('status', [404, 405])
def test_observer_reports_rejected_signer_ingress(wallets, service, qapp, status):
    sender, receiver = wallets
    issuer, _, registry, _ = _issue(sender)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='holder')
    url, state, requests = service
    state['respond'] = lambda method, path, body: (status, b'{}')
    doer = registries.RegistrySyncDoer(receiver, holder, registry.regk, observer_url=url)
    _run(doer, qapp)
    assert 'Observer signer key history could not be submitted' in doer.error
    assert f'HTTP {status}' in doer.error
    assert [(method, path) for method, path, _ in requests] == [('PUT', '/')]
    assert doer.result is None and doer.manager is None
    assert receiver.rgy.store.head(registry.regk) is None


def test_registry_timeout_aborts_request(wallets, service, qapp, monkeypatch):
    sender, _ = wallets
    hab, _, registry, _ = _issue(sender)
    url, state, requests = service
    doer = registries.RegistrySyncDoer(sender, hab, registry.regk, registrar_url=url)
    clock = [monotonic()]
    monkeypatch.setattr(registries, 'monotonic', lambda: clock[0])
    def stall(method, path, body):
        clock[0] += doer.Timeout + 1
    state['respond'] = stall
    _run(doer, qapp)
    assert requests
    assert 'timed out' in doer.error
    assert doer.result is None and doer.manager is None


def test_registry_worker_rebuilds_requests_and_refreshes_revocation(wallets, service, qapp, request):
    from keri.peer import exchanging
    from locksmith.db.basing import LocksmithBaser

    sender, receiver = wallets
    issuer, registrar, registry, acdc = _issue(sender)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='holder')
    # Existing accepted state must trigger a refresh after the worker restarts.
    registries.ingest(receiver, registry.regk, sender.rgy.store.cloneTel(registry.regk))
    receiver.db = LocksmithBaser(name='registry-worker', temp=True)
    request.addfinalizer(receiver.db.close)
    receiver.exc = exchanging.Exchanger(hby=receiver.hby, handlers=[])
    url, state, requests = service
    receiver.hby.cf.put({'registries': {'observer': url}})
    def respond(method, path, body):
        return (204, b'') if method == 'PUT' else (200, sender.rgy.store.cloneTel(registry.regk))
    state['respond'] = respond
    worker = registries.RegistryEvidenceDoer(receiver)
    checks = []
    receiver.signals = SimpleNamespace(emit_doer_event=lambda name, event, data: checks.append(
        (name, event, data, worker.ensure(registry.regk, holder))))
    worker.Refresh = 0.05
    assert not worker.ensure(registry.regk, holder)
    assert not worker.ensure(registry.regk, holder)  # Repeated UI reads coalesce.
    runner = doing.Doist(doers=[worker], tyme=monotonic(), tock=0.0)
    runner.enter()
    def until(predicate):
        deadline = monotonic() + 5
        while not predicate() and monotonic() < deadline:
            _advance(runner, qapp)
        assert predicate()
    try:
        until(lambda: worker.ensure(registry.regk, holder))
        assert [path for method, path, _ in requests if method == 'POST'].count('/') == 1
        _, update = registrar.issue(registry, acdc=acdc, state='revoked')
        _anchor(issuer, registry, update)
        _copy_kel(issuer, receiver)
        until(lambda: receiver.rgy.store.headEvent(registry.regk).said == update.said)
        until(lambda: worker.ensure(registry.regk, holder))
        assert [path for method, path, _ in requests if method == 'POST'].count('/') == 2
        assert any(name == 'RegistryEvidence' and event == 'status_checked' and data['success'] and fresh
                   for name, event, data, fresh in checks)
        state['respond'] = lambda method, path, body: (503, b'')
        until(lambda: registry.regk in worker.errors)
        assert any(name == 'RegistryEvidence' and event == 'status_checked' and not data['success'] and not fresh
                   for name, event, data, fresh in checks)
        receiver.hby.cf.put({'registries': {'observer': url + '/changed'}})
        assert not worker.ensure(registry.regk, holder)
        state['respond'] = respond
        until(lambda: worker.ensure(registry.regk, holder))
        assert [path for method, path, _ in requests if method == 'PUT'].count('/changed/') == 1
        assert [path for method, path, _ in requests if method == 'POST'].count('/changed/') == 1
        assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    finally:
        runner.exit()
    assert not worker._active
    # A replacement worker must discover accepted heads and fetch them again.
    worker = registries.RegistryEvidenceDoer(receiver)
    runner = doing.Doist(doers=[worker], tyme=monotonic(), tock=0.0)
    runner.enter()
    try:
        until(lambda: [path for method, path, _ in requests if method == 'POST'].count('/changed/') == 2)
        until(lambda: worker.ensure(registry.regk, holder))
        assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    finally:
        runner.exit()
    assert not worker._active


def test_registry_worker_without_services_stays_idle(wallets, qapp):
    sender, _ = wallets
    issuer, _, registry, _ = _issue(sender)
    sender.hby.cf.put({})
    sender.exc.cues.extend([{'kin': 'saved', 'said': 'saved'},
                           {'kin': 'proof', 'said': 'pending'}, {'kin': 'other'}])
    worker = registries.RegistryEvidenceDoer(sender)
    assert not worker.ensure(registry.regk, issuer)
    assert 'observer' in worker.errors[registry.regk]
    runner = doing.Doist(doers=[worker], tyme=monotonic(), tock=0.0)
    runner.enter()
    try:
        for _ in range(5):
            runner.recur()
        assert not worker._active
        assert not worker.published(registry.regk)
        assert list(sender.exc.cues) == [{'kin': 'other'}]
    finally:
        runner.exit()


def test_registry_worker_publishes_owned_history_without_registry_cache(wallets, service, qapp):
    sender, _ = wallets
    issuer, _, registry, _ = _issue(sender)
    url, state, requests = service
    sender.hby.cf.put({'registries': {'registrar': url}})
    sender.rgy.regs.clear()
    state['respond'] = lambda method, path, body: (200, json.dumps({
        'accepted': {registry.regk: 2}, 'pending': {}, 'rejected': {}}).encode())
    worker = registries.RegistryEvidenceDoer(sender)
    runner = doing.Doist(doers=[worker], tyme=monotonic(), tock=0.0)
    runner.enter()
    try:
        deadline = monotonic() + 4
        while not worker.published(registry.regk) and monotonic() < deadline:
            _advance(runner, qapp)
        assert worker.published(registry.regk)
        assert [path for method, path, _ in requests if method == 'POST'] == ['/ingest']
        sender.hby.cf.put({'registries': {'registrar': url + '/changed'}})
        assert not worker.published(registry.regk)
        deadline = monotonic() + 4
        while not worker.published(registry.regk) and monotonic() < deadline:
            _advance(runner, qapp)
        assert worker.published(registry.regk)
        assert [path for method, path, _ in requests if method == 'POST'] == ['/ingest', '/changed/ingest']
    finally:
        runner.exit()
    assert not worker._active


@pytest.mark.parametrize('outcome', ['replay', 'timeout', 'close', 'failure'])
def test_observer_refresh_waits_for_native_issuer_anchor(wallets, service, qapp, monkeypatch, outcome):
    sender, receiver = wallets
    issuer, registrar, registry, acdc = _issue(sender)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='holder')
    previous = sender.rgy.store.cloneTel(registry.regk)
    registries.ingest(receiver, registry.regk, previous)
    _, update = registrar.issue(registry, acdc=acdc, state='revoked')
    _anchor(issuer, registry, update)
    queries, closed = [], []
    clock = [monotonic()]
    if outcome == 'timeout':
        monkeypatch.setattr(registries, 'monotonic', lambda: clock[0])

    # Replace only network delivery. The native AnchorQuerier still waits for
    # the replay to pass Kevery and for the exact accepted seal to be present.
    class ReplayTransport(doing.DoDoer):
        def __init__(self, hby):
            super().__init__(doers=[doing.doify(self.replay)])
        def query(self, **kwa):
            queries.append(kwa)
        def replay(self, tymth, **opts):
            self.wind(tymth)
            try:
                yield self.tock
                if outcome == 'failure':
                    raise kering.ColdStartError('bad child framing')
                if outcome == 'timeout':
                    clock[0] += worker.Timeout + 1
                if outcome == 'replay':
                    _copy_kel(issuer, receiver)
                while True:
                    yield self.tock
            finally:
                closed.append(True)
    monkeypatch.setattr(registries.querying, 'WitnessInquisitor', ReplayTransport)
    url, state, _ = service
    state['respond'] = lambda method, path, body: ((204, b'') if method == 'PUT'
                                                  else (200, sender.rgy.store.cloneTel(registry.regk)))
    worker = registries.RegistrySyncDoer(receiver, holder, registry.regk, observer_url=url)
    worker.Timeout = 2.0
    if outcome == 'close':
        runner = doing.Doist(doers=[worker], tyme=monotonic(), tock=0.0)
        runner.enter()
        try:
            deadline = monotonic() + 3
            while not queries and monotonic() < deadline:
                _advance(runner, qapp)
            assert queries
        finally:
            runner.exit()
    else:
        _run(worker, qapp)
    assert queries[0]['anchor'] == dict(i=registry.regk, s=update.sad['n'], d=update.said)
    assert queries[0]['pre'] == issuer.pre
    assert queries[0]['version'] == kering.Vrsn_2_0
    assert queries[0]['kind'] == kering.Kinds.json
    assert worker.querier is None and worker.manager is None
    assert not worker.deeds and closed
    if outcome == 'replay':
        assert worker.error == ''
        assert worker.result.said == update.said
        assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    else:
        assert worker.result is None
        assert receiver.rgy.store.cloneTel(registry.regk) == previous
        if outcome == 'timeout':
            assert 'key event retrieval timed out' in worker.error
        elif outcome == 'failure':
            assert 'bad child framing' in worker.error


def test_v1_identifier_introduction_and_v2_json_query_fit_native_http():
    from keri.app import forwarding, httping
    from keri.core import SerderKERI

    requests = []
    client = SimpleNamespace(requester=SimpleNamespace(path='/'), request=lambda **kwa: requests.append(kwa))
    with habbing.openHby(name='default-query-framing', temp=True, version=kering.Vrsn_1_0) as hby:
        hab = hby.makeHab(name='holder', version=kering.Vrsn_1_0)
        witness = hby.makeHab(name='witness', transferable=False, version=kering.Vrsn_1_0)
        assert hby.version == kering.Vrsn_1_0
        assert hab.kever.serder.pvrsn == kering.Vrsn_1_0
        introduction = forwarding.introduce(hab, witness.pre, gvrsn=hby.version)
        query = hab.query(witness.pre, src=witness.pre, route='logs', query={},
                          version=kering.Vrsn_2_0, gvrsn=kering.Vrsn_2_0, kind=kering.Kinds.json)
        httping.streamCESRRequests(client, bytearray(introduction), witness.pre)
        httping.streamCESRRequests(client, bytearray(query), witness.pre)
        assert SerderKERI(raw=requests[-1]['body']).pvrsn == kering.Vrsn_2_0
        assert all(request['headers'][httping.CESR_DESTINATION_HEADER] == witness.pre for request in requests)
        assert all(request['headers'][httping.CESR_ATTACHMENT_HEADER] for request in requests)


def test_native_anchor_query_posts_json_then_accepts_injected_kel(wallets, service, qapp, monkeypatch):
    from keri.core import SerderKERI

    source, receiver = wallets
    issuer, registrar, registry, acdc = _issue(source)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='holder')
    previous = source.rgy.store.cloneTel(registry.regk)
    registries.ingest(receiver, registry.regk, previous)
    _, update = registrar.issue(registry, acdc=acdc, state='revoked')
    _anchor(issuer, registry, update)
    url, state, requests = service
    witness = source.hby.makeHab(name='witness', transferable=False)
    # Exercise the outgoing JSON query through HTTPMessenger and HIO. The
    # responder injects KEL replay into native verification below; it does not
    # return replay through the HTTP response or the mailbox receive path.
    monkeypatch.setattr(holder, 'endsFor', lambda pre: {
        kering.Roles.witness: {witness.pre: {kering.Schemes.http: url}}})
    logs = []
    def respond(method, path, body):
        if method == 'PUT':
            return 204, b''
        if body.startswith(b'{'):
            event = SerderKERI(raw=body)
            if event.ilk == 'qry':
                assert event.sad['r'] == 'logs'
                logs.append(event)
                _copy_kel(issuer, receiver)
            return 200, b''  # KEL replay was supplied directly, not in this body.
        return 200, source.rgy.store.cloneTel(registry.regk)
    state['respond'] = respond
    state['keepalive'] = True
    worker = registries.RegistrySyncDoer(receiver, holder, registry.regk, observer_url=url)
    worker.Timeout = 3.0
    _run(worker, qapp)
    assert worker.error == ''
    assert worker.result.said == update.said
    assert len(logs) == 1
    assert logs[0].pvrsn == kering.Vrsn_2_0 and logs[0].kind == kering.Kinds.json
    assert logs[0].sad['q']['a'] == dict(i=registry.regk, s=update.sad['n'], d=update.said)
    assert receiver.rgy.store.headEvent(registry.regk).said == update.said
    assert worker.querier is None and not worker.deeds


@pytest.mark.parametrize('rotations', [0, 4, 32])
def test_wallet_query_uses_native_observer_ingress(wallets, qapp, rotations):
    serving = pytest.importorskip('kfobserver.core.serving')
    from hio.core import http, tcp

    source, receiver = wallets
    issuer, _, registry, _ = _issue(source)
    _copy_kel(issuer, receiver)
    holder = receiver.hby.makeHab(name='querying-holder')
    for _ in range(rotations):
        holder.rotate(gvrsn=kering.Vrsn_2_0)
    stream = source.rgy.store.cloneTel(registry.regk)
    with habbing.openHby(name='independent-observer', temp=True,
                         version=kering.Vrsn_2_0) as hby:
        ctx = serving.makeContext(hby)
        summary = ctx.observer.ingest(issuer.replay(gvrsn=kering.Vrsn_2_0) + stream)
        assert registry.regk in summary['accepted']
        if rotations == 32:
            ctx.parser.ims.extend(issuer.replay(gvrsn=kering.Vrsn_2_0) * 128)
        assert holder.pre not in hby.kevers
        servant = tcp.Server(ha=('127.0.0.1', 0))
        assert servant.reopen()
        servant.eha = servant.ha
        server = http.Server(servant=servant, ha=servant.ha, app=ctx.app)
        worker = registries.RegistrySyncDoer(
            receiver, holder, registry.regk,
            observer_url=f'http://127.0.0.1:{servant.ha[1]}')
        runner = doing.Doist(doers=[ctx, http.ServerDoer(server=server), worker], tyme=monotonic(), tock=0.0)
        runner.enter()
        try:
            deadline = monotonic() + 5
            while not worker.done and monotonic() < deadline:
                _advance(runner, qapp)
            assert worker.done
            assert worker.error == ''
            assert hby.kevers[holder.pre].sn == holder.kever.sn
            assert worker.result.said == source.rgy.store.headEvent(registry.regk).said
            assert receiver.rgy.store.cloneTel(registry.regk) == stream
            assert worker.manager is None
        finally:
            runner.exit()
            ctx.observer.close()
