import asyncio
import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from hio.base import doing
from keri import kering
from keri.app import habbing, organizing
from keri.core import eventing

from locksmith.core import remoting


class _FakeStore:
    def __init__(self):
        self._values = {}

    def get(self, keys):
        return self._values.get(keys)

    def put(self, keys, val):
        self._values[keys] = val

    def rem(self, keys):
        self._values.pop(keys, None)


class _FakeOrg:
    def __init__(self):
        self.records = {}

    def update(self, pre, data):
        self.records.setdefault(pre, {}).update(data)

    def get(self, pre):
        return self.records.get(pre)


@pytest.mark.parametrize("signature", ["valid", "unsigned", "corrupt"])
def test_import_native_identifier_requires_verified_key_state(tmp_path, signature):
    with (
        habbing.openHby(name="import-source", temp=True) as source,
        habbing.openHby(name="import-target", temp=True) as target,
    ):
        hab = source.makeHab(name="source", kind=kering.Kinds.cesr, version=kering.Vrsn_2_0)
        if signature == "valid":
            kel = b"".join(hab.db.clonePreIter(pre=hab.pre))
        elif signature == "unsigned":
            kel = hab.iserder.raw
        else:
            kel = eventing.messagize(
                serder=hab.iserder,
                sigers=hab.sign(ser=b"corrupted message"),
                gvrsn=kering.Vrsn_2_0,
            )
        role = hab.makeEndRole(eid=hab.pre, kind=kering.Kinds.cesr)
        location = hab.makeLocScheme(url="http://127.0.0.1:9999", kind=kering.Kinds.cesr)
        path = tmp_path / "introduction.cesr"
        path.write_bytes(bytes(kel) + bytes(role) + bytes(location))

        org = organizing.Organizer(hby=target)
        app = SimpleNamespace(vault=SimpleNamespace(hby=target, org=org))
        events = []
        signals = SimpleNamespace(emit_doer_event=lambda **event: events.append(event))
        doer = remoting.ImportDoer(app=app, file=str(path), alias="source", signal_bridge=signals)
        doing.Doist(tock=0.03125, real=False, limit=1.0).do(doers=[doer])

        event, = events
        assert event["doer_name"] == "ImportDoer"
        if signature == "valid":
            assert event["event_type"] == "remote_identifier_imported"
            assert event["data"]["success"] is True
            assert event["data"]["pre"] == hab.pre
            assert hab.pre in target.kevers
            assert org.get(hab.pre)["alias"] == "source"
            assert target.db.ends.get(keys=(hab.pre, "controller", hab.pre)).allowed is True
            assert target.db.locs.get(keys=(hab.pre, "http")).url == "http://127.0.0.1:9999"
        else:
            assert event["event_type"] == "import_failed"
            assert event["data"]["success"] is False
            assert "No verified key state" in event["data"]["error"]
            assert hab.pre not in target.kevers
            assert org.get(hab.pre) is None


def test_resolve_oobi_blocking_waits_for_live_oobi_resolution(monkeypatch):
    roobi = _FakeStore()
    oobis = _FakeStore()
    db = SimpleNamespace(roobi=roobi, oobis=oobis)
    hby = SimpleNamespace(db=db, kevers={})
    vault = SimpleNamespace(hby=hby, org=_FakeOrg())
    app = SimpleNamespace(vault=vault, qtask=SimpleNamespace(run=lambda: None))

    oobi = "http://example.test/oobi/AID_1/controller"

    def complete_resolution():
        roobi.put(keys=(oobi,), val=SimpleNamespace(state="resolved"))
        hby.kevers["AID_1"] = object()

    timer = threading.Timer(0.01, complete_resolution)
    timer.start()
    try:
        resolved = remoting.resolve_oobi_blocking(
            app,
            pre="AID_1",
            oobi=oobi,
            alias="witness-1",
            timeout_seconds=0.5,
            tock=0.01,
        )
    finally:
        timer.cancel()

    assert resolved is True
    assert oobis.get(keys=(oobi,)) is not None
    assert vault.org.get("AID_1")["alias"] == "witness-1"


def test_resolve_oobi_blocking_times_out_without_live_resolution():
    roobi = _FakeStore()
    oobis = _FakeStore()
    db = SimpleNamespace(roobi=roobi, oobis=oobis)
    hby = SimpleNamespace(db=db, kevers={})
    vault = SimpleNamespace(hby=hby, org=_FakeOrg())
    app = SimpleNamespace(vault=vault, qtask=SimpleNamespace(run=lambda: None))

    resolved = remoting.resolve_oobi_blocking(
        app,
        pre="AID_TIMEOUT",
        oobi="http://example.test/oobi/AID_TIMEOUT/controller",
        alias="timeout-witness",
        timeout_seconds=0.0,
        tock=0.01,
    )

    assert resolved is False


def test_resolve_oobi_returns_false_when_doer_finishes_unresolved(monkeypatch):
    class FakeResolveOobiDoer:
        def __init__(self, **kwa):
            self.kwa = kwa
            self.done = False
            self.resolved = False

    class FakeVault:
        def __init__(self):
            self.extended = []
            self.removed = []

        def extend(self, doers):
            self.extended.extend(doers)
            doers[0].done = True

        def remove(self, doers):
            self.removed.extend(doers)

    monkeypatch.setattr(remoting, "ResolveOobiDoer", FakeResolveOobiDoer)

    vault = FakeVault()
    app = SimpleNamespace(vault=vault, qtask=SimpleNamespace(run=lambda: None))
    resolved = asyncio.run(
        remoting.resolve_oobi(
            app,
            pre="AID_1",
            oobi="http://example.test/oobi/AID_1/controller",
            alias="witness-1",
        )
    )

    assert resolved is False
    assert len(vault.extended) == 1
    assert vault.removed == vault.extended


def test_resolve_oobi_removes_unfinished_doer_after_timeout(monkeypatch):
    class FakeResolveOobiDoer:
        def __init__(self, **kwa):
            self.kwa = kwa
            self.done = False
            self.resolved = False

    class FakeVault:
        def __init__(self):
            self.extended = []
            self.removed = []

        def extend(self, doers):
            self.extended.extend(doers)

        def remove(self, doers):
            self.removed.extend(doers)

    monkeypatch.setattr(remoting, "ResolveOobiDoer", FakeResolveOobiDoer)

    vault = FakeVault()
    app = SimpleNamespace(vault=vault, qtask=SimpleNamespace(run=lambda: None))
    resolved = asyncio.run(
        remoting.resolve_oobi(
            app,
            pre="AID_TIMEOUT",
            oobi="http://example.test/oobi/AID_TIMEOUT/controller",
            alias="timeout-witness",
            timeout_seconds=0.0,
        )
    )

    assert resolved is False
    assert len(vault.extended) == 1
    assert vault.removed == vault.extended


def test_purge_oobi_resolution_state_removes_retry_records():
    oobi = "http://example.test/oobi/AID_1/controller"
    stores = {
        name: _FakeStore()
        for name in ("oobis", "coobi", "eoobi", "roobi", "moobi")
    }
    for store in stores.values():
        store.put(keys=(oobi,), val=object())

    db = SimpleNamespace(**stores)
    app = SimpleNamespace(vault=SimpleNamespace(hby=SimpleNamespace(db=db)))

    remoting.purge_oobi_resolution_state(app, oobi=oobi)

    assert all(store.get(keys=(oobi,)) is None for store in stores.values())


def test_introduce_watcher_observed_aid_sends_kel_and_add_reply(monkeypatch):
    parsed = []
    sent = []
    replies = []
    delivered = []

    class FakeSerder:
        def __init__(self, raw):
            self.raw = bytes(raw)
            self.size = len(self.raw)

    class FakePoster:
        def __init__(self, *, hby, hab, recp, topic):
            _ = (hby, hab)
            sent.append(("init", recp, topic))

        def send(self, *, serder, attachment):
            sent.append((serder.raw, bytes(attachment)))

        def deliver(self):
            delivered.append(True)
            return []

    class FakeDoDoer:
        def __init__(self, *, doers):
            self.doers = doers

    class FakeDoist:
        def __init__(self, *args, **kwargs):
            pass

        def do(self, *, doers, limit):
            delivered.append((doers, limit))

    def fake_parse_one(*, ims):
        parsed.append(bytes(ims))
        if isinstance(ims, bytearray):
            ims.clear()

    hab = SimpleNamespace(
        pre="AID_ACCOUNT",
        kever=SimpleNamespace(),
        db=SimpleNamespace(
            ends=_FakeStore(),
            cloneDelegation=lambda _kever, *, gvrsn: [b"delegation"],
            clonePreIter=lambda pre, *, gvrsn: [b"icp", b"rot"],
        ),
        psr=SimpleNamespace(parseOne=fake_parse_one),
    )

    def fake_reply(*, route, data):
        replies.append((route, data))
        return f"reply:{route}".encode("utf-8")

    hab.reply = fake_reply
    app = SimpleNamespace(vault=SimpleNamespace(hby=object()))

    monkeypatch.setattr(remoting.forwarding, "StreamPoster", FakePoster)
    monkeypatch.setattr(remoting.serdering, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting.doing, "DoDoer", FakeDoDoer)
    monkeypatch.setattr(remoting.doing, "Doist", FakeDoist)

    remoting.introduce_watcher_observed_aid(
        app,
        hab=hab,
        watcher_eid="WAT_1",
        observed_aid="AID_ACCOUNT",
        observed_oobis=[
            "https://wit-1.example/oobi/AID_ACCOUNT/witness/WIT_1",
            "https://wit-2.example/oobi/AID_ACCOUNT/witness/WIT_2",
        ],
    )

    assert replies == [
        ("/end/role/add", {"cid": "AID_ACCOUNT", "role": "watcher", "eid": "WAT_1"}),
        (
            "/watcher/WAT_1/add",
            {
                "cid": "AID_ACCOUNT",
                "oid": "AID_ACCOUNT",
                "oobi": "https://wit-1.example/oobi/AID_ACCOUNT/witness/WIT_1",
            },
        ),
        (
            "/watcher/WAT_1/add",
            {
                "cid": "AID_ACCOUNT",
                "oid": "AID_ACCOUNT",
                "oobi": "https://wit-2.example/oobi/AID_ACCOUNT/witness/WIT_2",
            },
        ),
    ]
    assert parsed == [
        b"reply:/end/role/add",
        b"reply:/watcher/WAT_1/add",
        b"reply:/watcher/WAT_1/add",
    ]
    assert sent == [
        ("init", "WAT_1", "reply"),
        (b"delegation", b""),
        (b"icp", b""),
        (b"rot", b""),
        (b"reply:/watcher/WAT_1/add", b""),
        (b"reply:/watcher/WAT_1/add", b""),
    ]
    assert delivered


def test_introduce_watcher_observed_aid_skips_role_add_when_already_allowed(monkeypatch):
    parsed = []
    sent = []
    replies = []

    class FakeSerder:
        def __init__(self, raw):
            self.raw = bytes(raw)
            self.size = len(self.raw)

    class FakePoster:
        def __init__(self, *, hby, hab, recp, topic):
            _ = (hby, hab)
            sent.append(("init", recp, topic))

        def send(self, *, serder, attachment):
            sent.append((serder.raw, bytes(attachment)))

        def deliver(self):
            return []

    class FakeDoDoer:
        def __init__(self, *, doers):
            self.doers = doers

    class FakeDoist:
        def __init__(self, *args, **kwargs):
            pass

        def do(self, *, doers, limit):
            _ = (doers, limit)

    def fake_parse_one(*, ims):
        parsed.append(bytes(ims))

    hab = SimpleNamespace(
        pre="AID_ACCOUNT",
        kever=SimpleNamespace(),
        db=SimpleNamespace(
            ends=_FakeStore(),
            cloneDelegation=lambda _kever, *, gvrsn: [],
            clonePreIter=lambda pre, *, gvrsn: [b"icp"],
        ),
        psr=SimpleNamespace(parseOne=fake_parse_one),
    )
    hab.db.ends.put(
        keys=(hab.pre, "watcher", "WAT_1"),
        val=SimpleNamespace(allowed=True),
    )

    def fake_reply(*, route, data):
        replies.append((route, data))
        return f"reply:{route}".encode("utf-8")

    hab.reply = fake_reply
    app = SimpleNamespace(vault=SimpleNamespace(hby=object()))

    monkeypatch.setattr(remoting.forwarding, "StreamPoster", FakePoster)
    monkeypatch.setattr(remoting.serdering, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting.doing, "DoDoer", FakeDoDoer)
    monkeypatch.setattr(remoting.doing, "Doist", FakeDoist)

    remoting.introduce_watcher_observed_aid(
        app,
        hab=hab,
        watcher_eid="WAT_1",
        observed_aid="AID_ACCOUNT",
        observed_oobis=[
            "https://wit-1.example/oobi/AID_ACCOUNT/witness/WIT_1",
            "https://wit-2.example/oobi/AID_ACCOUNT/witness/WIT_2",
        ],
    )

    assert replies == [
        (
            "/watcher/WAT_1/add",
            {
                "cid": "AID_ACCOUNT",
                "oid": "AID_ACCOUNT",
                "oobi": "https://wit-1.example/oobi/AID_ACCOUNT/witness/WIT_1",
            },
        ),
        (
            "/watcher/WAT_1/add",
            {
                "cid": "AID_ACCOUNT",
                "oid": "AID_ACCOUNT",
                "oobi": "https://wit-2.example/oobi/AID_ACCOUNT/witness/WIT_2",
            },
        ),
    ]
    assert parsed == [
        b"reply:/watcher/WAT_1/add",
        b"reply:/watcher/WAT_1/add",
    ]
    assert sent == [
        ("init", "WAT_1", "reply"),
        (b"icp", b""),
        (b"reply:/watcher/WAT_1/add", b""),
        (b"reply:/watcher/WAT_1/add", b""),
    ]


def test_introduce_watcher_observed_aid_wraps_delivery_failures(monkeypatch):
    class FakePoster:
        def __init__(self, *, hby, hab, recp, topic):
            _ = (hby, hab, recp, topic)

        def send(self, *, serder, attachment):
            _ = (serder, attachment)

        def deliver(self):
            return []

    class FakeSerder:
        def __init__(self, raw):
            self.raw = bytes(raw)
            self.size = len(self.raw)

    class FakeDoDoer:
        def __init__(self, *, doers):
            self.doers = doers

    class FakeDoist:
        def __init__(self, *args, **kwargs):
            pass

        def do(self, *, doers, limit):
            _ = (doers, limit)
            raise RuntimeError("boom")

    hab = SimpleNamespace(
        pre="AID_ACCOUNT",
        kever=SimpleNamespace(),
        db=SimpleNamespace(
            ends=_FakeStore(),
            cloneDelegation=lambda _kever, *, gvrsn: [],
            clonePreIter=lambda pre, *, gvrsn: [],
        ),
        psr=SimpleNamespace(parseOne=lambda ims: None),
        reply=lambda *, route, data: f"reply:{route}".encode("utf-8"),
    )
    app = SimpleNamespace(vault=SimpleNamespace(hby=object()))

    monkeypatch.setattr(remoting.forwarding, "StreamPoster", FakePoster)
    monkeypatch.setattr(remoting.serdering, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting, "SerderKERI", FakeSerder)
    monkeypatch.setattr(remoting.doing, "DoDoer", FakeDoDoer)
    monkeypatch.setattr(remoting.doing, "Doist", FakeDoist)

    with pytest.raises(
        ValueError,
        match="Failed introducing observed AID AID_ACCOUNT to watcher WAT_1: boom",
    ):
        remoting.introduce_watcher_observed_aid(
            app,
            hab=hab,
            watcher_eid="WAT_1",
            observed_aid="AID_ACCOUNT",
            observed_oobis=["https://wit-1.example/oobi/AID_ACCOUNT/witness/WIT_1"],
        )


def test_resolve_oobi_blocking_uses_sync_doer_when_qtask_is_missing(monkeypatch):
    captured = {}

    class FakeResolveOobiDoer:
        def __init__(self, **kwa):
            captured["doer_kwargs"] = dict(kwa)
            self.resolved = True

    class FakeDoist:
        def __init__(self, *args, **kwargs):
            captured["doist_kwargs"] = dict(kwargs)

        def do(self, *, doers, limit):
            captured["doers"] = list(doers)
            captured["limit"] = limit

    monkeypatch.setattr(remoting, "ResolveOobiDoer", FakeResolveOobiDoer)
    monkeypatch.setattr(remoting.doing, "Doist", FakeDoist)

    app = SimpleNamespace(vault=SimpleNamespace())

    resolved = remoting.resolve_oobi_blocking(
        app,
        pre="AID_1",
        oobi="https://example.test/oobi/AID_1/controller",
        alias="witness-1",
        timeout_seconds=1.25,
        tock=0.01,
    )

    assert resolved is True
    assert captured["doer_kwargs"]["app"] is app
    assert captured["doer_kwargs"]["pre"] == "AID_1"
    assert captured["doer_kwargs"]["oobi"] == "https://example.test/oobi/AID_1/controller"
    assert captured["doer_kwargs"]["alias"] == "witness-1"
    assert captured["doer_kwargs"]["timeout_seconds"] == 1.25
    assert len(captured["doers"]) == 1
    assert captured["limit"] == pytest.approx(1.26)


@pytest.mark.parametrize('transferable_endpoint', [False, True])
def test_identifier_export_repairs_delivery_routes(tmp_path, monkeypatch, transferable_endpoint):
    from keri.app import forwarding
    from locksmith.ui.vault.shared.export import export_identifier_to_cesr

    with (
        habbing.openHby(name='export-owner', temp=True, version=kering.Vrsn_2_0) as source,
        habbing.openHby(name='export-service', temp=True, version=kering.Vrsn_2_0) as service,
        habbing.openHby(name='export-recipient', temp=True, version=kering.Vrsn_2_0) as target,
    ):
        hab = source.makeHab(name='owner', version=kering.Vrsn_2_0, kind=kering.Kinds.cesr)
        mailbox = service.makeHab(name='mailbox', transferable=transferable_endpoint,
                                 version=kering.Vrsn_2_0)
        unrelated = source.makeHab(name='unrelated', version=kering.Vrsn_2_0)
        sender = target.makeHab(name='sender', version=kering.Vrsn_2_0)
        source.psr.parse(ims=mailbox.replay(gvrsn=kering.Vrsn_2_0), version=kering.Vrsn_2_0)
        source.psr.parse(ims=mailbox.makeLocScheme(url='http://127.0.0.1:9999',
                                                version=kering.Vrsn_2_0),
                         version=kering.Vrsn_2_0)
        source.psr.parse(ims=hab.makeEndRole(eid=mailbox.pre, role=kering.Roles.mailbox,
                                           version=kering.Vrsn_2_0), version=kering.Vrsn_2_0)
        org = organizing.Organizer(hby=target)
        app = SimpleNamespace(vault=SimpleNamespace(hby=target, org=org))
        path = tmp_path / 'introduction.cesr'
        path.write_bytes(hab.replay(gvrsn=kering.Vrsn_2_0))

        def import_contact():
            events = []
            signals = SimpleNamespace(emit_doer_event=lambda **event: events.append(event))
            doer = remoting.ImportDoer(app=app, file=str(path), alias='owner', signal_bridge=signals)
            doing.Doist(tock=0.03125, real=False, limit=1.0).do(doers=[doer])
            assert events[0]['event_type'] == 'remote_identifier_imported'

        # The old KEL-only export creates a contact but cannot route a message.
        import_contact()
        poster = forwarding.StreamPoster(hby=target, hab=sender, recp=hab.pre, topic='credential')
        attachment = eventing.messagize(serder=sender.iserder,
                                        sigers=sender.sign(ser=sender.iserder.raw),
                                        gvrsn=kering.Vrsn_2_0)[sender.iserder.size:]
        with pytest.raises(kering.ValidationError, match='No end roles'):
            poster.send(sender.iserder, attachment=attachment, gvrsn=kering.Vrsn_2_0)

        monkeypatch.setattr('locksmith.ui.vault.shared.export.QFileDialog.getSaveFileName',
                            lambda *args, **kwargs: (str(path), 'CESR Files (*.cesr)'))
        export_identifier_to_cesr(None, SimpleNamespace(vault=SimpleNamespace(hby=source)), 'owner')
        assert path.read_bytes() == remoting.identifier_introduction(hab)
        import_contact()
        assert target.db.ends.get(keys=(hab.pre, 'mailbox', mailbox.pre)).allowed is True
        assert target.db.locs.get(keys=(mailbox.pre, 'http')).url == 'http://127.0.0.1:9999'
        assert mailbox.pre in target.kevers
        assert unrelated.pre not in target.kevers
        assert org.get(hab.pre)['alias'] == 'owner'
        assert sender.endsFor(hab.pre)['mailbox'][mailbox.pre]['http'] == 'http://127.0.0.1:9999'
        poster.send(sender.iserder, attachment=attachment, gvrsn=kering.Vrsn_2_0)
        assert len(poster.evts) == 1  # Resolve/queue only; no network delivery.
