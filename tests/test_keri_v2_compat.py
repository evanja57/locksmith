import importlib
import logging
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from hio.base import doing
from keri import kering
from keri.app import habbing
from keri.core import Codens, Counter, SerderKERI, coring, eventing, parsing
from keri.db import dbing
from keri.acdc import registraring

from locksmith.core.remoting import message_version
from locksmith.core.ipexing import prepare
from locksmith.db.basing import (
    BrowserPluginSettings,
    IdentifierMetaInfo,
    LocksmithBaser,
    OTPSecret,
    OTPSecrets,
)
from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_ONBOARDED,
    KFBaser,
    KFAccountRecord,
    ProvisionedWitnessRecord,
    WitnessRecord,
)
from locksmith.plugins.kerifoundation.onboarding import service as onboarding_service


@pytest.mark.parametrize(
    "module_name",
    [
        "locksmith.core.adjudication",
        "locksmith.core.configing",
        "locksmith.core.credentialing",
        "locksmith.core.grouping",
        "locksmith.core.habbing",
        "locksmith.core.indirecting",
        "locksmith.core.ipexing",
        "locksmith.core.remoting",
        "locksmith.core.vaulting",
        "locksmith.plugins.kerifoundation.onboarding.service",
        "locksmith.plugins.kerifoundation.plugin",
        "locksmith.plugins.kerifoundation.witnesses.list",
        "locksmith.plugins.kerifoundation.witnesses.provision",
        "locksmith.turret.directing",
        "locksmith.ui.vault.credentials.issued.list",
        "locksmith.ui.vault.identifiers.accept_delegate",
        "locksmith.ui.vault.identifiers.create",
        "locksmith.ui.vault.identifiers.list",
        "locksmith.ui.vault.notifications.list",
        "locksmith.ui.vault.remotes.view",
    ],
)
def test_keri_v2_migration_import_surfaces(module_name):
    importlib.import_module(module_name)


def test_locksmith_custom_komer_stores_round_trip_and_iterate(tmp_path):
    otp_db = OTPSecrets(name="otp-secrets-v2", headDirPath=str(tmp_path), reopen=True)
    try:
        otp_db.otpSecrets.pin(
            keys=("vault-a",),
            val=OTPSecret(vault="vault-a", secret="SECRET"),
        )
        assert otp_db.otpSecrets.get(keys=("vault-a",)).secret == "SECRET"
    finally:
        otp_db.close()

    reopened_otp_db = OTPSecrets(name="otp-secrets-v2", headDirPath=str(tmp_path), reopen=True)
    try:
        assert reopened_otp_db.otpSecrets.get(keys=("vault-a",)).vault == "vault-a"
    finally:
        reopened_otp_db.close()

    db = LocksmithBaser(name="locksmith-v2", headDirPath=str(tmp_path), reopen=True)
    try:
        db.idm.pin(
            keys=("AID_1",),
            val=IdentifierMetaInfo(prefix="AID_1", auth_pending=True),
        )
        db.pluginSettings.pin(
            keys=("browser",),
            val=BrowserPluginSettings(
                locksmith_identifier="AID_1",
                locksmith_alias="aid-one",
                plugin_identifier="PLUGIN_1",
            ),
        )

        assert db.idm.get(keys=("AID_1",)).auth_pending is True
        assert db.pluginSettings.get(keys=("browser",)).plugin_identifier == "PLUGIN_1"
    finally:
        db.close()


def test_kf_custom_komer_stores_round_trip_and_iterate(tmp_path):
    db = KFBaser(name="kf-v2", headDirPath=str(tmp_path), reopen=True)
    try:
        account = KFAccountRecord(
            account_aid="AID_ACCOUNT",
            account_alias="account",
            status=ACCOUNT_STATUS_ONBOARDED,
        )
        witness = WitnessRecord(
            eid="WIT_1",
            url="https://wit.example",
            oobi="https://wit.example/oobi/WIT_1/controller",
            hab_pre="AID_ACCOUNT",
        )
        provisioned = ProvisionedWitnessRecord(
            boot_url="https://boot.example",
            witness_url="https://wit.example",
            eid="WIT_1",
            oobi="https://wit.example/oobi/WIT_1/controller",
            hab_pre="AID_ACCOUNT",
        )

        db.pin_account(account)
        db.attach_identifier("AID_ACCOUNT")
        db.witnesses.pin(keys=("AID_ACCOUNT", "WIT_1"), val=witness)
        db.provisionedWitnesses.pin(keys=("AID_ACCOUNT", "https://boot.example"), val=provisioned)

        assert db.get_account() == account
        assert db.list_attached_identifier_prefixes() == ["AID_ACCOUNT"]
        assert list(db.witnesses.getTopItemIter(keys=("AID_ACCOUNT",))) == [
            (("AID_ACCOUNT", "WIT_1"), witness)
        ]
        provisioned_rows = list(db.provisionedWitnesses.getTopItemIter(keys=("AID_ACCOUNT",)))
        assert [row for _, row in provisioned_rows] == [provisioned]
    finally:
        db.close()


def test_parse_cesr_http_reply_uses_detected_parser_version(monkeypatch):
    parser_kwargs = []
    version_inputs = []

    class FakeParser:
        def __init__(self, *args, **kwargs):
            parser_kwargs.append(kwargs)

        def parse(self, ims):
            assert bytes(ims) == b"reply"

    fake_serder = SimpleNamespace(
        pre="BOOT_SERVER_AID",
        ked={"t": "rpy", "r": "/account/witnesses", "a": {"witnesses": []}},
        said="SAID_REPLY",
    )
    app = SimpleNamespace(
        vault=SimpleNamespace(
            hby=SimpleNamespace(
                kvy=SimpleNamespace(processEscrows=lambda: None),
                rvy=object(),
                exc=object(),
                kevers={"BOOT_SERVER_AID": object()},
            )
        )
    )
    response = SimpleNamespace(content=b"reply", headers={})

    monkeypatch.setattr(onboarding_service.parsing, "Parser", FakeParser)
    monkeypatch.setattr(
        onboarding_service,
        "message_version",
        lambda ims: version_inputs.append(bytes(ims)) or kering.Vrsn_1_0,
    )
    monkeypatch.setattr(onboarding_service, "split_cesr_stream", lambda ims: [fake_serder])

    reply = onboarding_service.parse_cesr_http_reply(
        app,
        response,
        expected_kinds=("rpy",),
        expected_route="/account/witnesses",
        expected_sender="BOOT_SERVER_AID",
    )

    assert version_inputs == [b"reply"]
    assert parser_kwargs[0]["version"] == kering.Vrsn_1_0
    assert reply.sender == "BOOT_SERVER_AID"


def test_message_version_detects_existing_keri10_event():
    with habbing.openHab(
        name="v1-sender",
        temp=True,
        version=kering.Vrsn_1_0,
        kind=kering.Kinds.json,
    ) as (_hby, hab):
        msg = bytes(hab.msgOwnEvent(sn=0))

    assert b"KERI10" in msg[:32]
    assert message_version(msg) == kering.Vrsn_1_0


def test_hab_replay_uses_v2_attachments_for_mixed_version_stream():
    with habbing.openHab(
        name="mixed-replay-sender",
        temp=True,
        version=kering.Vrsn_1_0,
        kind=kering.Kinds.json,
    ) as (_hby, hab):
        v1_stream = hab.replay(gvrsn=kering.Version)
        counter = Counter(
            qb64b=v1_stream[hab.kever.serder.size:],
            version=kering.Vrsn_2_0,
        )
        assert counter.name == Codens.AttachmentGroup

        hab.rotate(version=kering.Vrsn_2_0, kind=kering.Kinds.json)
        stream = hab.replay(gvrsn=kering.Version)

        with habbing.openHby(
            name="v2-replay-receiver",
            temp=True,
            version=kering.Vrsn_2_0,
        ) as hby:
            kvy = eventing.Kevery(db=hby.db, lax=True)
            parsing.Parser(kvy=kvy, local=False, version=kering.Vrsn_2_0).parse(
                ims=stream
            )

            assert not stream
            assert kvy.kevers[hab.pre].sn == 1
            assert kvy.kevers[hab.pre].serder.kind == kering.Kinds.json


def test_vault_constructs_with_real_keri_v2_stores(monkeypatch, tmp_path):
    from locksmith.core import vaulting

    class FakeTurretDoer(doing.DoDoer):
        def __init__(self, *args, **kwargs):
            super().__init__(doers=[])

    def locksmith_baser(name, base="", temp=False, reopen=True):
        return LocksmithBaser(
            name=f"{name}-locksmith",
            base=base,
            temp=temp,
            headDirPath=str(tmp_path),
            reopen=reopen,
        )

    monkeypatch.setattr(vaulting, "LocksmithBaser", locksmith_baser)
    monkeypatch.setattr(vaulting, "TurretDoer", FakeTurretDoer)

    with habbing.openHby(name="vault-v2", base="custom", temp=True) as hby:
        rgy = registraring.Regery(
            hby=hby,
            name=hby.name,
            base=hby.base,
            temp=hby.temp,
        )
        vault = None
        try:
            vault = vaulting.Vault(app=SimpleNamespace(), hby=hby, rgy=rgy)

            assert vault.hby is hby
            assert vault.db.base == hby.base
            assert vault.db.temp is hby.temp
            assert vault.rep.mbx.base == hby.base
            assert vault.rep.mbx.temp is hby.temp
            assert vault.notifier.noter.base == hby.base
            assert vault.notifier.noter.temp is hby.temp
            assert vault.counseling_completion_doers == {}
            assert vault.pluginSettings is None
            assert vault.turrent_doer is None
            assert vault.db.pluginSettings.get(keys=("default",)) is None
            assert hby.habByName(f"plugin-{hby.name}", ns="settings") is None

            assert vault.update_plugin_identifier("PLUGIN_AID") is None
            assert vault.db.pluginSettings.get(keys=("default",)) is None
            assert hby.habByName(f"plugin-{hby.name}", ns="settings") is None
        finally:
            if vault is not None:
                vault.db.close()
                vault.rep.mbx.close()
                vault.notifier.noter.close()
            rgy.close()


def test_keri_v2_runtime_object_api_surfaces():
    from keri.app import grouping

    with habbing.openHby(name="runtime-api-v2", temp=True) as hby:
        hab = hby.makeHab(name="runtime-aid")
        dgkey = dbing.dgKey(hab.pre, hab.kever.serder.said)

        assert hby.db.evts.get(keys=dgkey) is not None
        assert hby.db.wigs.get(keys=dgkey) == []

        number = coring.Number(sn=0, code=coring.NumDex.Huge)
        diger = coring.Diger(qb64=hab.kever.serder.said)
        hby.db.aess.pin(keys=dgkey, val=(number, diger))
        assert hby.db.aess.get(keys=dgkey)[0].sn == 0

        counselor = grouping.Counselor(hby=hby)
        assert callable(counselor.start)
        assert callable(counselor.complete)

        rgy = registraring.Regery(hby=hby, name=hby.name, temp=True)
        try:
            reg = rgy.makeRegistry(name='native', prefix=hab.pre)
            assert rgy.store.event(reg.regk).sad['t'] == 'rip'
        finally:
            rgy.close()


def test_add_identifier_flow_opens_dialog_with_keri_v2_salt(qapp):
    from PySide6.QtWidgets import QWidget

    from locksmith.ui.vault.identifiers.create import CreateIdentifierDialog
    from locksmith.ui.vault.identifiers.list import IdentifierListPage

    parent = QWidget()
    parent.app = SimpleNamespace(config=SimpleNamespace(), vault=None)

    page = IdentifierListPage(parent=parent)
    page._on_add_identifier()
    qapp.processEvents()

    dialogs = [
        widget
        for widget in qapp.topLevelWidgets()
        if isinstance(widget, CreateIdentifierDialog)
    ]

    assert dialogs
    assert len(dialogs[0].key_salt_field.text()) == 21


def test_locksmith_config_resalt_uses_keri_v2_salter():
    from locksmith.core.configing import LocksmithConfig

    config = LocksmithConfig()
    old_salt = config.salt
    try:
        salt = config.resalt()

        assert len(salt) == 21
        assert config.salt == salt
    finally:
        config.salt = old_salt


def test_locksmith_receiptor_uses_keri_v2_httping(monkeypatch):
    from locksmith.core import receipting

    class FakeClient:
        def __init__(self):
            self.responses = ["one", "two"]
            self.responded = 0

        def respond(self):
            self.responses.pop(0)
            self.responded += 1

    client = FakeClient()
    captured = {}
    hab = SimpleNamespace()

    def replay(*, pre):
        captured.update(replay_pre=pre)
        return b"replayed-kel"

    hab.replay = replay
    hby = SimpleNamespace(prefixes={"AID"}, habs={"AID": hab})
    receiptor = receipting.LocksmithReceiptor(hby=hby)
    receiptor.tock = 0.0
    receiptor.extend = lambda doers: captured.update(extended=len(doers))
    receiptor.remove = lambda doers: captured.update(removed=len(doers))

    monkeypatch.setattr(
        receipting.agenting,
        "httpClient",
        lambda hab, wit: (client, object()),
    )

    def stream_cesr_requests(client, dest, ims, path=None, headers=None):
        captured.update(client=client, dest=dest, ims=bytes(ims))
        return 2

    monkeypatch.setattr(
        receipting.httping,
        "streamCESRRequests",
        stream_cesr_requests,
    )
    list(receiptor.catchup(pre="AID", wit="WIT"))

    assert captured == {
        "client": client,
        "dest": "WIT",
        "ims": b"replayed-kel",
        "extended": 1,
        "removed": 1,
        "replay_pre": "AID",
    }
    assert client.responded == 2


def test_watcher_inquisitor_treats_204_as_accepted(monkeypatch, caplog):
    from locksmith.core import adjudication

    class FakeClient:
        responses = [SimpleNamespace(status=204, body=b"")]

        def respond(self):
            return self.responses.pop(0)

    class FakeHab:
        def query(self, target, *, src, route, query, **kwa):
            captured.update(target=target, src=src, route=route, query=query, **kwa)
            return b"qry"

    class FakeHby:
        db = SimpleNamespace()

        def habByPre(self, src):
            assert src == "SRC"
            return FakeHab()

    captured = {}
    client = FakeClient()
    client_doer = object()
    inq = adjudication.WatcherInquisitor.__new__(adjudication.WatcherInquisitor)
    inq.hby = FakeHby()
    inq.tock = 0.0
    inq.extend = lambda doers: captured.update(extended=doers)
    inq.remove = lambda doers: captured.update(removed=doers)

    monkeypatch.setattr(
        adjudication,
        "httpClient",
        lambda hab, wat: (client, client_doer),
    )
    monkeypatch.setattr(
        adjudication,
        "streamCESRRequests",
        lambda **kwa: captured.update(stream=kwa),
    )

    with caplog.at_level(logging.INFO):
        list(inq.execute("TARGET", "SRC", "ksn", {"s": "0"}, "WATCHER"))

    assert captured["stream"]["client"] is client
    assert captured["stream"]["dest"] == "WATCHER"
    assert captured["stream"]["ims"] == bytearray(b"qry")
    assert captured["version"] == kering.Vrsn_2_0
    assert captured["gvrsn"] == kering.Vrsn_2_0
    assert captured["kind"] == kering.Kinds.json
    assert captured["removed"] == [client_doer]
    assert "invalid response" not in caplog.text


def test_remote_detail_lookup_preserves_organizer_metadata(monkeypatch):
    from locksmith.core import remoting

    class FakeOrganizer:
        def __init__(self, hby):
            self.hby = hby

        def get(self, pre):
            assert pre == "REMOTE_AID"
            return {
                "alias": "Remote One",
                "oobi": "https://remote.example/oobi/REMOTE_AID/controller",
            }

    monkeypatch.setattr(remoting.organizing, "Organizer", FakeOrganizer)

    kever = SimpleNamespace(sn=7, dater=None)
    app = SimpleNamespace(
        vault=SimpleNamespace(
            hby=SimpleNamespace(
                kevers={"REMOTE_AID": kever},
                db=SimpleNamespace(
                    ends=SimpleNamespace(getTopItemIter=lambda: iter(())),
                    clonePreIter=lambda pre: iter(()),
                ),
            )
        )
    )

    details = remoting.get_remote_id_details(app, "REMOTE_AID")

    assert details["alias"] == "Remote One"
    assert details["oobi"] == "https://remote.example/oobi/REMOTE_AID/controller"
    assert details["sequence_number"] == 7


@pytest.fixture
def ipex_vaults(monkeypatch, tmp_path, mailbox_routes):
    """Real persistent sessions with every store confined to this test directory."""
    from keri.app import configing, keeping, notifying, storing
    from keri.acdc.registering import RegBaser
    from keri.db.basing import Baser
    from locksmith.core import apping, vaulting

    for cls in (configing.Configer, keeping.Keeper, notifying.Noter,
                storing.Mailboxer, RegBaser, Baser, LocksmithBaser):
        monkeypatch.setattr(cls, 'HeadDirPath', str(tmp_path))
    sessions = []

    def open_session(name, base='', *, registry_services=False):
        hby = habbing.Habery(name=name, base=base, temp=False, salt='0AAwMTIzNDU2Nzg5YWJjZGVm')
        mailbox_routes(hby)
        rgy = registraring.Regery(hby=hby, name=name, base=base, temp=False)
        app = apping.LocksmithApplication.__new__(apping.LocksmithApplication)
        app.name, app.hby, app.rgy = name, hby, rgy
        app.plugin_manager = SimpleNamespace(on_vault_closed=lambda *a, **k: None,
                                             get_witness_batches=lambda *a: [])
        # These exchange fixtures isolate native crypto and durable wallet state.
        # Observer transport has dedicated worker/socket tests. Keep the real
        # service gate only when a test explicitly requests that boundary.
        from locksmith.core import credentialing
        with monkeypatch.context() as construction:
            if not registry_services:
                construction.setattr(credentialing, 'require_registry_evidence', lambda *args: None)
            app.vault = vaulting.Vault(app, hby, rgy)
        if not registry_services:
            app.vault.doers.remove(app.vault.registry_evidence)
            app.vault.registry_evidence = None
        # Use the production scheduler and close path; no network pollers are configured.
        doist = doing.Doist(doers=[app.vault], tock=0.03125)
        doist.enter()
        app.qtask = SimpleNamespace(shutdown=lambda: None, cleanup=doist.exit,
                                    extend=doist.extend, run=doist.recur)
        sessions.append(app)
        return app

    yield open_session
    for app in sessions:
        app.close_vault()


def _deliver_ipex(vault, stream):
    """Feed one complete mailbox frame through the actual mailbox doer."""
    vault.mbx.messages.append((bytearray(stream), None))
    gen = vault.mbx.msgDo(tymth=lambda: 0.0)
    try:
        for _ in range(1024):
            next(gen)
            if not vault.mbx.messages and not list(vault.db.inbox.getTopItemIter()):
                return
        pytest.fail('Mailbox processing did not drain queued and retained frames after 1024 advances')
    finally:
        gen.close()


def _retry_ipex(vault):
    gen = vault.mbx.escrowDo(tymth=lambda: 0.0)
    next(gen)
    next(gen)
    gen.close()


def _ipex_status(vault, said):
    if vault.exc.complete(said):
        return 'protocol_verified'
    if vault.hby.db.epse.get((said,)) is not None:
        return 'pending_verification'
    return 'unverified'


def _conversation(vault, xid):
    return sorted((serder for _, serder in vault.hby.db.exns.getTopItemIter()
                   if serder.ked.get('x') == xid), key=lambda serder: serder.ked['dt'])


def _ipex_fixture(issuer, holder, learn_peers=True, delegated=False):
    """Prepare anchored registry/TEL data; this is not observer ingestion."""
    from keri.acdc import Registrar, acdcmap
    from keri.core import Diger, Number, messagize

    delegator = issuer.hby.makeHab(name='delegator') if delegated else None
    ih = issuer.hby.makeHab(name='issuer', delpre=delegator.pre if delegated else None)
    if delegated:
        inception = ih.kever.serder
        delegator.interact(data=[{'i': ih.pre, 's': '0', 'd': inception.said}])
        issuer.hby.db.aess.pin((ih.pre, inception.said),
                               (Number(num=delegator.kever.sn), Diger(qb64=delegator.kever.serder.said)))
    hh = holder.hby.makeHab(name='holder')
    registrar = Registrar(rgy=issuer.vault.rgy)
    reg = registrar.makeRegistry(name='fixture', prefix=ih.pre)
    rip = issuer.vault.rgy.store.event(reg.regk)

    def anchor(event):
        ih.interact(data=[dict(i=reg.regk, s=event.sad['n'], d=event.said)],
                    gvrsn=kering.Vrsn_2_0)
        assert reg.anchorMsg(event.said)

    anchor(rip)
    acdc = acdcmap(israid=ih.pre, regid=reg.regk,
                   attribute=dict(d='', LEI='254900OPPU84GM83MG36'), iseaid=hh.pre)
    blinder, issued = registrar.issue(reg, acdc=acdc, state='issued')
    anchor(issued)
    if learn_peers:
        from locksmith.core.remoting import identifier_introduction
        _deliver_ipex(holder.vault, identifier_introduction(ih))
        _deliver_ipex(issuer.vault, identifier_introduction(hh))
    proofed = messagize(serder=acdc, bonds=[blinder.data], framed=False,
                        gvrsn=kering.Vrsn_2_0)
    return ih, hh, reg, rip, issued, acdc, proofed


@pytest.fixture
def ipex_mailbox(monkeypatch):
    """Forward native streams through a separate witness's HTTP endpoint and mailbox."""
    import falcon
    from hio.core import http, tcp
    from keri.app import forwarding, indirecting as kerindirecting, storing
    from keri.core import parsing
    from keri.db import openLMDB
    from keri.peer import exchanging
    from locksmith.core.ipexing import submit

    with habbing.openHab(name='ipex-witness', transferable=False, temp=True,
                         version=kering.Vrsn_2_0) as (hby, witness), \
            openLMDB(cls=storing.Mailboxer, name='ipex-witness') as mbx:
        parser = parsing.Parser(
            kvy=hby.kvy, framed=True, version=kering.Vrsn_2_0,
            exc=exchanging.Exchanger(hby=hby, handlers=[
                forwarding.ForwardHandler(hby=hby, mbx=mbx)]))
        endpoint = kerindirecting.HttpEnd(rxbs=parser.ims, mbx=mbx)
        app = falcon.App()
        app.add_route('/', endpoint)
        # Bind an ephemeral port and hold it, so no other listener can claim it
        # between selection and use. hio resolves .ha on bind but leaves .eha at
        # the requested port, which accept validates against.
        servant = tcp.Server(ha=('127.0.0.1', 0))
        assert servant.reopen()
        servant.eha = servant.ha
        port = servant.ha[1]
        server = http.Server(servant=servant, ha=servant.ha, app=app)
        doist = doing.Doist(doers=[http.ServerDoer(server=server)], tock=0.03125)
        doist.enter()

        def forward(sender, receiver, hab, exn, stream, queued=False, outcome='transport_submitted'):
            from locksmith.core.remoting import identifier_introduction
            _deliver_ipex(receiver.vault, identifier_introduction(hab))
            recipient = receiver.hby.habByPre(exn.sad['ri'])
            _deliver_ipex(sender.vault, identifier_introduction(recipient))
            topic = f'{exn.sad["ri"]}/credential'
            before = len(list(mbx.cloneTopicIter(topic=topic)))
            with monkeypatch.context() as patch:
                patch.setattr(hab, 'endsFor', lambda pre: {
                    kering.Roles.witness: {
                        witness.pre: {'http': f'http://127.0.0.1:{port}'}}})
                events = []
                def record(name, kind, data):
                    events.append((kind, data))
                sender.vault.signals.doer_event.connect(record)
                if not queued:
                    submit(sender.vault, hab, exn, stream[exn.size:])
                try:
                    deadline = monotonic() + 5
                    while not any(kind == outcome for kind, _ in events) and monotonic() < deadline:
                        doist.recur()
                        sender.qtask.run()
                        parser.parse(local=False)
                        hby.kvy.processEscrows()
                        parser.exc.processEscrow()
                        sleep(0.001)
                    assert any(kind == outcome and data.get('said') == exn.said
                               for kind, data in events), events
                finally:
                    sender.vault.signals.doer_event.disconnect(record)
            assert hab.pre in hby.kevers
            rows = list(mbx.cloneTopicIter(topic=topic, fn=before))
            carried = []
            for _, _, message in rows:
                item, = parsing.Parser(version=kering.Vrsn_2_0).parse(
                    ims=bytearray(message), processive=False)
                carried.append(item.serder)
                _deliver_ipex(receiver.vault, message)
            assert carried[-1].raw == exn.raw
            assert all(item.ilk in ('icp', 'rot', 'ixn', 'dip', 'drt')
                       for item in carried[:-1])
            return carried

        try:
            yield forward
        finally:
            doist.exit()


@pytest.mark.parametrize('anchored', [False, True])
def test_ipex_sessions_five_messages_retry_reopen_and_prune(
        ipex_vaults, ipex_mailbox, monkeypatch, anchored):
    from keri.acdc import ipexing
    from keri.peer import exchanging
    from keri.core import kraming
    from keri.help import helping
    from datetime import timedelta

    issuer, holder = ipex_vaults('issuer-session'), ipex_vaults('holder-session')
    ih, hh, reg, rip, issued, acdc, proofed = _ipex_fixture(issuer, holder, learn_peers=False)
    assert holder.hby.db.states.get(ih.pre) is None
    assert issuer.hby.db.states.get(hh.pre) is None
    messages = []
    schema = acdc.sad['s']['$id']

    def send(sender, receiver, hab, message):
        exn, atc = message
        stream = prepare(sender.vault, hab, exn, atc)
        ipex_mailbox(sender, receiver, hab, exn, stream)
        messages.append((exn, stream))
        return exn

    for app in (issuer, holder):
        assert app.vault.kvy.kramer.enabled is True
        assert app.vault.kvy.kramer is app.vault.kramer
        assert app.hby.db.kramCTYP.get('~').sl == 300000
        assert app.vault.mbx.parser.exc is app.vault.exc

    apply = send(holder, issuer, hh, ipexing.apply(
        hh, ih.pre, 'Apply', modifiers=dict(dp=[[[schema, '/', []]]]), ax=[anchored]))
    offer = send(issuer, holder, ih, ipexing.offer(
        ih, 'Offer', acdc, apply=apply, ax=[anchored]))
    agree = send(holder, issuer, hh, ipexing.agree(hh, 'Agree', offer))
    grant = send(issuer, holder, ih, ipexing.grant(
        ih, hh.pre, 'Grant', proofed, agree=agree, ax=[anchored]))
    assert holder.hby.kevers[ih.pre].sn == ih.kever.sn
    assert _ipex_status(holder.vault, grant.said) == 'pending_verification'
    assert holder.hby.db.exns.get((grant.said,)) is None
    assert holder.vault.notifier.getNoteCnt() == 1  # offer only
    _retry_ipex(holder.vault)
    assert _ipex_status(holder.vault, grant.said) == 'pending_verification'
    # With the service worker intentionally absent, proof cues remain available
    # for its consumer instead of being discarded by the mailbox loop.
    assert {'kin': 'proof', 'said': grant.said} in holder.vault.exc.cues
    assert not holder.vault.kramer.cues

    # Prepared component evidence deliberately arrives after the grant.
    holder.vault.rgy.store.accept(reg.regk, 0, rip)
    holder.vault.rgy.store.accept(reg.regk, 1, issued)
    _retry_ipex(holder.vault)
    assert _ipex_status(holder.vault, grant.said) == 'protocol_verified'
    assert holder.vault.notifier.getNoteCnt() == 2
    hh.rotate()
    admit = send(holder, issuer, hh, ipexing.admit(hh, 'Admit', grant))
    assert issuer.hby.kevers[hh.pre].lastEst == hh.kever.lastEst
    assert _ipex_status(issuer.vault, admit.said) == 'protocol_verified'
    assert issuer.vault.notifier.getNoteCnt() == 3

    for app in (issuer, holder):
        assert len(_conversation(app.vault, apply.ked['x'])) == 5
        for exn, stream in messages:
            assert app.hby.db.kramTMSC.get((exn.pre, exn.ked['x'], exn.said)) is not None
            _deliver_ipex(app.vault, stream)
        assert app.vault.notifier.getNoteCnt() == (3 if app is issuer else 2)

    assert issuer.hby.db.path != holder.hby.db.path
    assert issuer.vault.rgy.baser.path != holder.vault.rgy.baser.path
    old_hab, old_rgy = ih, issuer.vault.rgy
    regk, xid = reg.regk, apply.ked['x']
    old_stores = [issuer.hby.db, issuer.hby.ks, issuer.rgy.baser, issuer.vault.db,
                  issuer.vault.rep.mbx, issuer.vault.notifier.noter]
    issuer.close_vault()
    holder.close_vault()
    assert all(not store.opened for store in old_stores)
    issuer, holder = ipex_vaults('issuer-session'), ipex_vaults('holder-session')
    assert issuer.hby.habByName('issuer') is not old_hab
    assert issuer.vault.rgy is not old_rgy
    assert issuer.vault.rgy.registryByName('fixture').regk == regk
    assert holder.vault.rgy.store.seqEvent(regk, 1).said == issued.said
    future = helping.nowUTC() + timedelta(days=2)
    monkeypatch.setattr(helping, 'nowUTC', lambda: future)
    for app in (issuer, holder):
        # Exercise the library's actual temporary-state pruning doer.
        pruner = kraming.Pruner(app.vault.kramer, tock=1.0)
        # Advance only prune time. Durable evidence verification ignores KRAM age.
        prune = pruner.do(tymth=lambda: 0.0)
        next(prune)
        prune.close()
        assert list(app.hby.db.kramTMSC.getTopItemIter()) == []
        recovered = _conversation(app.vault, xid)
        assert [m.said for m in recovered] == [m.said for m, _ in messages]
        for exn in recovered:
            assert exchanging.verify(app.hby, exn)
            assert exchanging.serializeMessage(app.hby, exn.said)
            if anchored and exn.route in ('/ipex/agree', '/ipex/grant', '/ipex/admit'):
                assert len(app.hby.db.ests.get((exn.said, exn.pre))) == 1
        assert len(exchanging.loadParsedNestedSubstreams(app.hby, grant.said)) == 1
        assert app.vault.notifier.getNoteCnt() == (3 if app is issuer else 2)


def test_ipex_rejects_invalid_proof_wrong_recipient_and_unsigned_messages(ipex_vaults):
    from keri.acdc import ipexing, acdcmap
    issuer, holder = ipex_vaults('invalid-issuer'), ipex_vaults('invalid-holder')
    ih, hh, reg, rip, issued, acdc, proofed = _ipex_fixture(issuer, holder)
    holder.vault.rgy.store.accept(reg.regk, 0, rip)
    holder.vault.rgy.store.accept(reg.regk, 1, issued)
    other = ipex_vaults('outsider')
    other.hby.makeHab(name='outsider')
    _deliver_ipex(other.vault, ih.replay(gvrsn=kering.Vrsn_2_0))

    # A signed outer grant cannot authenticate a substituted credential node.
    substituted = acdcmap(israid=ih.pre, regid=reg.regk,
                          attribute=dict(d='', LEI='different'), iseaid=hh.pre)
    invalid_origin = substituted.raw + proofed[acdc.size:]
    invalid, atc = ipexing.grant(ih, hh.pre, 'Invalid binding', invalid_origin)
    with pytest.raises(kering.ValidationError):
        prepare(issuer.vault, ih, invalid, atc)
    _deliver_ipex(holder.vault, invalid.raw + atc)
    _retry_ipex(holder.vault)
    assert _ipex_status(holder.vault, invalid.said) == 'unverified'
    assert holder.hby.db.exns.get((invalid.said,)) is None
    assert holder.vault.notifier.getNoteCnt() == 0

    exn, atc = ipexing.apply(ih, hh.pre, 'Only for holder', modifiers=dict(dp=[[]]))
    _deliver_ipex(other.vault, exn.raw + atc)
    assert _ipex_status(other.vault, exn.said) == 'unverified'
    assert other.vault.notifier.getNoteCnt() == 0
    # Parser consumes a well-framed but unsigned native exchange, without saving it.
    unsigned = exn.raw + Counter.enclose(qb64=b'', code=Codens.AttachmentGroup,
                                          version=kering.Vrsn_2_0)
    _deliver_ipex(holder.vault, unsigned)
    assert _ipex_status(holder.vault, exn.said) != 'protocol_verified'
    assert holder.vault.notifier.getNoteCnt() == 0
    assert not list(other.hby.db.enst.getTopItemIter())


def test_ipex_missing_sender_key_requires_key_history_before_redelivery(ipex_vaults):
    from keri.acdc import ipexing

    sender, receiver = ipex_vaults('kel-sender'), ipex_vaults('kel-receiver')
    sh = sender.hby.makeHab(name='sender')
    rh = receiver.hby.makeHab(name='receiver')
    exn, atc = ipexing.apply(sh, rh.pre, 'Need sender KEL', modifiers=dict(dp=[[]]))
    _deliver_ipex(receiver.vault, exn.raw + atc)
    assert _ipex_status(receiver.vault, exn.said) != 'protocol_verified'
    assert receiver.vault.notifier.getNoteCnt() == 0
    assert receiver.hby.db.exns.get((exn.said,)) is None
    _deliver_ipex(receiver.vault, sh.replay(gvrsn=kering.Vrsn_2_0))
    # Before KRAM handoff, the native policy permits redelivery after sender KEL arrives.
    _deliver_ipex(receiver.vault, exn.raw + atc)
    assert _ipex_status(receiver.vault, exn.said) == 'protocol_verified'
    assert receiver.vault.notifier.getNoteCnt() == 1


@pytest.mark.parametrize('gvrsn', [kering.Vrsn_1_0, kering.Vrsn_2_0])
@pytest.mark.parametrize('kind', [kering.Kinds.json, kering.Kinds.cbor, kering.Kinds.mgpk])
def test_mailbox_accepts_v1_key_events_and_rejects_legacy_ipex(ipex_vaults, gvrsn, kind):
    from keri.acdc import ipexing
    from keri.vc import protocoling

    sender, receiver = ipex_vaults('mixed-sender'), ipex_vaults('mixed-receiver')
    sh = sender.hby.makeHab(name='sender', version=kering.Vrsn_1_0, kind=kind)
    rh = receiver.hby.makeHab(name='receiver')
    _deliver_ipex(receiver.vault, sh.msgOwnEvent(sn=0, gvrsn=gvrsn))
    assert receiver.hby.kevers[sh.pre].serder.pvrsn == kering.Vrsn_1_0
    sh.interact()
    query = SerderKERI(raw=rh.query(pre=sh.pre, src=sh.pre, route='logs',
                                    version=kering.Vrsn_2_0, gvrsn=kering.Vrsn_2_0))
    sender.hby.kvy.processQuery(query, source=coring.Prefixer(qb64=rh.pre))
    replay = next(cue for cue in sender.hby.kvy.cues if cue['kin'] == 'replay')
    _deliver_ipex(receiver.vault, b''.join(replay['msgs']))
    assert receiver.hby.kevers[sh.pre].sn == 1
    receiptor = sender.hby.makeHab(name='receiptor', transferable=False)
    rserder = eventing.receipt(pre=sh.pre, sn=sh.kever.sn, said=sh.kever.serder.said,
                               version=kering.Vrsn_1_0, kind=kind)
    receipt = eventing.messagize(
        serder=rserder, cigars=receiptor.sign(ser=sh.kever.serder.raw, indexed=False),
        gvrsn=gvrsn, framed=True)
    _deliver_ipex(receiver.vault, receipt)
    receipts = receiver.hby.db.rcts.get(keys=(sh.pre, sh.kever.serder.said))
    assert any(verfer.qb64 == receiptor.pre for verfer, _ in receipts)
    old, old_atc = protocoling.ipexApplyExn(sh, rh.pre, 'Legacy', 'schema', {})
    _deliver_ipex(receiver.vault, old.raw + old_atc)
    assert not receiver.vault.exc.complete(old.said)
    new, new_atc = ipexing.apply(sh, rh.pre, 'Native', modifiers=dict(dp=[[]]))
    receiver.vault.mbx.messages.append((bytearray(b'{malformed'), None))
    _deliver_ipex(receiver.vault, new.raw + new_atc)
    assert receiver.vault.exc.complete(new.said)
    outgoing, outgoing_atc = ipexing.apply(rh, sh.pre, 'Reply in a new conversation',
                                         modifiers={'dp': [[]]})
    assert prepare(receiver.vault, rh, outgoing, outgoing_atc)
    assert receiver.vault.notifier.getNoteCnt() == 1


@pytest.mark.real_routes
def test_native_ipex_submission_retries_failed_delivery_across_reopen(
        ipex_vaults, ipex_mailbox, monkeypatch):
    from datetime import timedelta
    from keri.acdc import ipexing
    from keri.help import helping
    from keri.peer import exchanging
    from locksmith.core.ipexing import retry, start, submit

    sender, receiver = ipex_vaults('submit-sender'), ipex_vaults('submit-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    from locksmith.core.remoting import identifier_introduction
    from keri.app import forwarding

    with pytest.raises(kering.ConfigurationError, match='no known way to reach'):
        start(sender.vault, sh, rh.pre, 'Apply')
    receiver.hby.psr.parse(ims=bytearray(rh.makeLocScheme(url='http://127.0.0.1:1', scheme='http')))
    receiver.hby.psr.parse(ims=bytearray(rh.makeEndRole(eid=rh.pre, role=kering.Roles.mailbox)))
    _deliver_ipex(sender.vault, identifier_introduction(rh))
    with pytest.raises(kering.ConfigurationError, match='cannot receive replies'):
        start(sender.vault, sh, rh.pre, 'Apply')
    sender.hby.psr.parse(ims=bytearray(sh.makeLocScheme(url='http://127.0.0.1:1', scheme='http')))
    sender.hby.psr.parse(ims=bytearray(sh.makeEndRole(eid=sh.pre, role=kering.Roles.mailbox)))
    assert not list(sender.hby.db.exns.getTopItemIter())
    assert sh.kever.sn == 0
    exn, atc = ipexing.apply(sh, rh.pre, 'Submit', modifiers={'dp': [[]]})
    events = []
    sender.vault.signals.doer_event.connect(lambda name, kind, data: events.append(kind))
    submit(sender.vault, sh, exn, atc)
    retained = exchanging.serializeMessage(sender.hby, exn.said)
    now = helping.nowUTC()
    monkeypatch.setattr(helping, 'nowUTC', lambda: now)
    def unavailable(self):
        raise TimeoutError('Mailbox unavailable')

    with monkeypatch.context() as patch:
        patch.setattr(forwarding.StreamPoster, 'deliver', unavailable)
        for attempt, delay in enumerate((30, 60, 120, 10), start=1):
            for _ in range(64):
                sender.qtask.run()
            record = sender.vault.db.outbox.get((exn.said,))
            assert record.attempts == attempt
            assert record.status == 'failed'
            now += timedelta(seconds=delay - 1)
            for _ in range(64):
                sender.qtask.run()
            assert sender.vault.db.outbox.get((exn.said,)).attempts == attempt
            now += timedelta(seconds=2)
    assert events.count('send_failed') == 4
    assert 'transport_submitted' not in events
    assert _ipex_status(sender.vault, exn.said) == 'protocol_verified'
    assert _ipex_status(receiver.vault, exn.said) == 'unverified'
    assert sender.vault.notifier.getNoteCnt() == 0

    sender.close_vault()
    sender = ipex_vaults('submit-sender')
    sh = sender.hby.habByName('sender')
    for _ in range(64):
        sender.qtask.run()
    record = sender.vault.db.outbox.get((exn.said,))
    assert record.status == 'failed' and record.attempts == 4
    retry(sender.vault, exn.said)
    ipex_mailbox(sender, receiver, sh, exn, retained, queued=True)
    record = sender.vault.db.outbox.get((exn.said,))
    assert record.status == 'submitted' and record.attempts == 5
    assert receiver.vault.exc.complete(exn.said)
    assert exchanging.serializeMessage(sender.hby, exn.said) == retained
    assert sh.kever.sn == 0


@pytest.mark.real_routes
@pytest.mark.parametrize('role', [kering.Roles.controller, kering.Roles.agent,
                                  kering.Roles.mailbox, kering.Roles.witness])
@pytest.mark.parametrize('mixed', [False, True])
def test_ipex_outbox_rechecks_revoked_route_before_send(ipex_vaults, monkeypatch, role, mixed):
    from keri.acdc import ipexing as native
    from keri.app import forwarding
    from keri.peer import exchanging
    from locksmith.core import ipexing
    sender = ipex_vaults('route-recheck')
    hab, peer = sender.hby.makeHab(name='sender'), sender.hby.makeHab(name='peer')
    for endpoint in (hab, peer):
        sender.hby.psr.parse(ims=bytearray(endpoint.makeLocScheme(url='http://127.0.0.1:1')))
    sender.hby.psr.parse(ims=bytearray(hab.makeEndRole(eid=hab.pre, role=kering.Roles.mailbox)))
    sender.hby.psr.parse(ims=bytearray(peer.makeEndRole(eid=peer.pre, role=role)))
    if mixed:
        active = sender.hby.makeHab(name='active-endpoint')
        sender.hby.psr.parse(ims=bytearray(active.makeLocScheme(url='http://127.0.0.1:2')))
        sender.hby.psr.parse(ims=bytearray(peer.makeEndRole(eid=active.pre, role=role)))
    deliveries = []
    def unavailable(self):
        deliveries.append(self.recp)
        raise TimeoutError('Endpoint unavailable')
    monkeypatch.setattr(forwarding.StreamPoster, 'deliver', unavailable)
    exn, atc = native.apply(hab, peer.pre, 'Apply', modifiers={'dp': [[]]})
    ipexing.submit(sender.vault, hab, exn, atc)
    retained = exchanging.serializeMessage(sender.hby, exn.said)
    sender.hby.psr.parse(ims=bytearray(peer.makeEndRole(
        eid=peer.pre, role=role, allow=False)))
    for _ in range(64):
        sender.qtask.run()
    record = sender.vault.db.outbox.get((exn.said,))
    assert record.status == 'blocked' and record.attempts == 0
    assert record.missing_route
    assert deliveries == []
    sender.hby.psr.parse(ims=bytearray(peer.makeEndRole(
        eid=peer.pre, role=role, allow=True)))
    ipexing.retry(sender.vault, exn.said)
    for _ in range(64):
        sender.qtask.run()
    record = sender.vault.db.outbox.get((exn.said,))
    assert record.status == 'failed' and record.attempts == 1
    assert not record.missing_route
    assert deliveries == [peer.pre]
    assert exchanging.serializeMessage(sender.hby, exn.said) == retained


def test_ipex_outbox_yields_during_history_scan(ipex_vaults, monkeypatch):
    from contextlib import closing
    from keri.acdc import ipexing as native
    from keri.app import forwarding
    from locksmith.core import ipexing
    from locksmith.db.basing import IpexSubmission

    sender = ipex_vaults('outbox-history')
    hab = sender.hby.makeHab(name='sender')
    peer = sender.hby.makeHab(name='peer')
    outbox = sender.vault.db.outbox
    # Seed completed history before the queued message in one transaction.
    history_count = 2048
    with sender.vault.db.env.begin(write=True) as txn:
        for index in range(history_count):
            txn.put(f'0{index:08}'.encode(), outbox._ser(IpexSubmission(status='submitted')),
                    db=outbox.sdb)
    exn, atc = native.apply(hab, peer.pre, 'Apply', modifiers={'dp': [[]]})
    ipexing.submit(sender.vault, hab, exn, atc)
    scanned, closed, progress, events = [], [], [], []
    records = outbox.getTopItemIter
    def observe_records(*args, **kwa):
        try:
            with closing(records(*args, **kwa)) as items:
                for item in items:
                    scanned.append(item[0])
                    yield item
        finally:
            closed.append(True)
    monkeypatch.setattr(outbox, 'getTopItemIter', observe_records)
    def sibling(tymth, tock=0.0, **opts):
        while True:
            progress.append((len(scanned), bool(closed)))
            yield tock
    sender.vault.extend([doing.doify(sibling)])
    def unavailable(self):
        raise TimeoutError('Mailbox unavailable')
    monkeypatch.setattr(forwarding.StreamPoster, 'deliver', unavailable)
    sender.vault.signals.doer_event.connect(lambda *event: events.append(event))
    # A sibling must run after scanning starts and before the iterator closes.
    # A scan performed in one turn cannot expose an intermediate record count.
    for _ in range(512):
        sender.qtask.run()
        during_scan = any(0 < count < history_count + 1 and not finished
                          for count, finished in progress)
        if during_scan:
            break
    assert during_scan, 'Outbox history scan did not yield to other vault work before completion'
    assert not closed and not events
    assert outbox.get((exn.said,)).status == 'pending'
    sender.close_vault()
    assert closed, 'Closing the vault did not close the native scan iterator and its read transaction'
    sender = ipex_vaults('outbox-history')
    sender.vault.signals.doer_event.connect(lambda *event: events.append(event))
    for _ in range(512):
        sender.qtask.run()
        record = sender.vault.db.outbox.get((exn.said,))
        if record.status == 'failed':
            break
    assert record.status == 'failed' and record.attempts == 1
    assert events[-1][1] == 'send_failed'


@pytest.mark.parametrize('delegated', [False, True])
def test_native_ipex_submission_carries_foreign_issuer_kel(ipex_vaults, ipex_mailbox, delegated):
    from keri.acdc import ipexing

    issuer, holder = ipex_vaults('presentation-issuer'), ipex_vaults('presentation-holder')
    verifier = ipex_vaults('presentation-verifier')
    vh = verifier.hby.makeHab(name='verifier')
    ih, hh, reg, rip, issued, _, proofed = _ipex_fixture(
        issuer, holder, learn_peers=False, delegated=delegated)

    first, atc = ipexing.grant(ih, hh.pre, 'Issue', proofed)
    stream = prepare(issuer.vault, ih, first, atc)
    ipex_mailbox(issuer, holder, ih, first, stream)
    assert _ipex_status(holder.vault, first.said) == 'pending_verification'
    # The holder already obtained the credential's registry evidence. The
    # verifier must still learn the KEL through the production sending path.
    holder.vault.rgy.store.accept(reg.regk, 0, rip)
    holder.vault.rgy.store.accept(reg.regk, 1, issued)
    _retry_ipex(holder.vault)
    assert holder.vault.exc.complete(first.said)

    grant, atc = ipexing.grant(hh, vh.pre, 'Present', proofed)
    stream = prepare(holder.vault, hh, grant, atc)
    assert verifier.hby.db.states.get(ih.pre) is None
    assert verifier.hby.db.states.get(hh.pre) is None
    carried = ipex_mailbox(holder, verifier, hh, grant, stream)
    expected = [(hh.pre, 0)]
    if delegated:
        expected.extend([(ih.kever.delpre, 0), (ih.kever.delpre, 1)])
    expected.extend([(ih.pre, 0), (ih.pre, 1), (ih.pre, 2)])
    assert [(event.pre, event.sn) for event in carried[:-1]] == expected
    assert verifier.hby.kevers[ih.pre].sn == ih.kever.sn
    assert verifier.hby.kevers[hh.pre].sn == hh.kever.sn
    assert _ipex_status(verifier.vault, grant.said) == 'pending_verification'
    assert list(verifier.vault.rgy.baser.evts.getTopItemIter()) == []
    assert list(verifier.vault.db.accepted.getTopItemIter()) == []

    verifier.close_vault()
    verifier = ipex_vaults('presentation-verifier')
    assert verifier.hby.db.states.get(hh.pre) is not None
    assert verifier.hby.kevers.get(hh.pre) is None  # Memory cache is still cold.
    request, atc = ipexing.apply(hh, vh.pre, 'After reopening', modifiers={'dp': [[]]})
    stream = prepare(holder.vault, hh, request, atc)
    ipex_mailbox(holder, verifier, hh, request, stream)
    assert verifier.vault.exc.complete(request.said)


def test_expired_ipex_grant_recovers_in_a_fresh_conversation(ipex_vaults, monkeypatch):
    from datetime import timedelta
    from keri.acdc import ipexing
    from keri.help import helping

    issuer, holder = ipex_vaults('expiry-issuer'), ipex_vaults('expiry-holder')
    ih, hh, reg, rip, issued, acdc, proofed = _ipex_fixture(issuer, holder)
    schema = acdc.sad['s']['$id']

    def deliver(sender, receiver, hab, message):
        exn, atc = message
        _deliver_ipex(receiver.vault, prepare(sender.vault, hab, exn, atc))
        return exn

    def negotiate():
        apply = deliver(holder, issuer, hh, ipexing.apply(
            hh, ih.pre, 'Apply', modifiers={'dp': [[[schema, '/', []]]]}))
        offer = deliver(issuer, holder, ih, ipexing.offer(ih, 'Offer', acdc, apply=apply))
        agree = deliver(holder, issuer, hh, ipexing.agree(hh, 'Agree', offer))
        grant = deliver(issuer, holder, ih, ipexing.grant(ih, hh.pre, 'Grant', proofed, agree=agree))
        return apply, agree, grant

    apply, agree, grant = negotiate()
    assert _ipex_status(holder.vault, grant.said) == 'pending_verification'
    future = helping.nowUTC() + timedelta(seconds=holder.vault.exc.TimeoutPSE + 1)
    monkeypatch.setattr(helping, 'nowUTC', lambda: future)
    _retry_ipex(holder.vault)
    assert _ipex_status(holder.vault, grant.said) == 'unverified'
    holder.vault.rgy.store.accept(reg.regk, 0, rip)
    holder.vault.rgy.store.accept(reg.regk, 1, issued)
    _retry_ipex(holder.vault)
    assert _ipex_status(holder.vault, grant.said) == 'unverified'
    retry, atc = ipexing.grant(ih, hh.pre, 'Retry', proofed, agree=agree)
    with pytest.raises(kering.ValidationError):
        prepare(issuer.vault, ih, retry, atc)
    assert issuer.hby.db.erpy.get((agree.said,)).qb64 == grant.said

    # Advance between messages to meet KRAM's monotonic time requirement.
    def ticking_now():
        nonlocal future
        future += timedelta(milliseconds=1)
        return future

    monkeypatch.setattr(helping, 'nowUTC', ticking_now)
    fresh_apply, _, fresh_grant = negotiate()
    assert fresh_apply.ked['x'] != apply.ked['x']
    assert _ipex_status(holder.vault, fresh_grant.said) == 'protocol_verified'
    assert _ipex_status(holder.vault, grant.said) == 'unverified'


def test_native_ipex_submission_timeout_closes_transport(ipex_vaults, monkeypatch):
    from hio.core.http import clienting
    from keri.acdc import ipexing
    from locksmith.core.ipexing import SendIpexDoer, submit

    sender, receiver = ipex_vaults('timeout-sender'), ipex_vaults('timeout-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    exn, atc = ipexing.apply(sh, rh.pre, 'Submit', modifiers={'dp': [[]]})
    monkeypatch.setattr(sh, 'endsFor', lambda pre: {
        kering.Roles.controller: {rh.pre: {'http': 'http://127.0.0.1:9999'}}})
    # Only network service is inert. Use real Poster, messenger and HIO lifecycle.
    monkeypatch.setattr(clienting.Client, 'reopen', lambda *a, **k: None)
    monkeypatch.setattr(clienting.Client, 'service', lambda *a, **k: None)
    events = []
    sender.vault.signals.doer_event.connect(lambda name, kind, data: events.append(kind))
    submit(sender.vault, sh, exn, atc)
    doer = SendIpexDoer(sender.vault, exn.said)
    doist = doing.Doist(doers=[doer], tock=0.03125, limit=31.0)
    doist.do()
    assert doer.done is True
    assert not doer.deeds
    assert not doist.deeds
    assert events.count('send_failed') == 1
    assert 'transport_submitted' not in events
    assert _ipex_status(receiver.vault, exn.said) == 'unverified'


@pytest.mark.parametrize('failure', ['tls', 'connection', 'http-protocol', 'programming'])
def test_ipex_child_transport_failure_keeps_vault_running_and_retryable(
        ipex_vaults, monkeypatch, failure):
    import ssl
    from hio.core.http import clienting, httping
    from keri.acdc import ipexing as native
    from keri.help import helping
    from keri.peer import exchanging
    from locksmith.core import ipexing

    sender, receiver = ipex_vaults('child-sender'), ipex_vaults('child-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    exn, atc = native.apply(sh, rh.pre, 'Submit', modifiers={'dp': [[]]})
    ipexing.submit(sender.vault, sh, exn, atc)
    retained = exchanging.serializeMessage(sender.hby, exn.said)
    events, closed, progress = [], [], []
    sender.vault.signals.doer_event.connect(lambda name, kind, data: events.append(kind))
    def sibling(tymth, tock=0.0, **opts):
        while True:
            progress.append(tymth())
            yield tock
    sender.vault.extend([doing.doify(sibling)])
    error = {'tls': ssl.SSLCertVerificationError('certificate verification failed'),
             'connection': ConnectionResetError('connection reset'),
             'http-protocol': httping.HTTPException('invalid HTTP response'),
             'programming': RuntimeError('unexpected transport bug')}[failure]
    def service(client):
        if any(request['method'] == 'PUT' for request in client.requests):
            raise error
    close = clienting.Client.close
    def close_client(client):
        closed.append(client)
        close(client)
    with monkeypatch.context() as patch:
        patch.setattr(sh, 'endsFor', lambda pre: {
            kering.Roles.controller: {rh.pre: {'https': 'https://127.0.0.1:9999'}}})
        # Preserve native Poster, HTTP messenger, ClientDoer and HIO cleanup.
        # Substitute only the socket service failure and avoid opening a socket.
        patch.setattr(clienting.Client, 'reopen', lambda *a, **k: None)
        patch.setattr(clienting.Client, 'service', service)
        patch.setattr(clienting.Client, 'close', close_client)
        if failure == 'programming':
            with pytest.raises(RuntimeError, match='unexpected transport bug'):
                for _ in range(64):
                    sender.qtask.run()
        else:
            for _ in range(64):
                sender.qtask.run()
            before = len(progress)
            for _ in range(4):
                sender.qtask.run()
            assert len(progress) > before
    record = sender.vault.db.outbox.get((exn.said,))
    assert record.attempts == 1
    assert closed and all(not client.connector.opened for client in closed)
    assert exchanging.serializeMessage(sender.hby, exn.said) == retained
    assert 'transport_submitted' not in events
    assert _ipex_status(receiver.vault, exn.said) == 'unverified'
    if failure == 'programming':
        assert record.status == 'pending'
        assert 'send_failed' not in events
    else:
        assert events.count('send_failed') == 1
        assert record.status == 'failed' and record.error == str(error)
        assert record.retry_at > helping.nowUTC().timestamp()
        sender.close_vault()
        sender = ipex_vaults('child-sender')
        assert sender.vault.db.outbox.get((exn.said,)) == record
        ipexing.retry(sender.vault, exn.said)
        retried = sender.vault.db.outbox.get((exn.said,))
        assert retried.status == 'pending' and retried.attempts == 1
        assert exchanging.serializeMessage(sender.hby, exn.said) == retained


def test_native_ipex_cannot_fall_back_to_legacy_validation(ipex_vaults):
    from keri.core import exchange

    sender, receiver = ipex_vaults('downgrade-sender'), ipex_vaults('downgrade-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    _deliver_ipex(receiver.vault, sh.replay(gvrsn=kering.Vrsn_2_0))
    # Missing native routing and dp fields do not make an envelope legacy.
    invalid = exchange(sender=sh.pre, receiver='', xid='', route='/ipex/apply',
                       modifiers={}, attributes={'m': 'Malformed native opener'},
                       pvrsn=kering.Vrsn_2_0, gvrsn=kering.Vrsn_2_0,
                       kind=kering.Kinds.json)
    wire = sh.endorse(invalid, last=False, framed=False, gvrsn=kering.Vrsn_2_0)
    _deliver_ipex(receiver.vault, wire)
    assert _ipex_status(receiver.vault, invalid.said) == 'unverified'
    assert not receiver.vault.exc.complete(invalid.said)
    assert receiver.vault.notifier.getNoteCnt() == 0


def test_ipex_close_stops_inflight_delivery_and_reopen_resumes(
        ipex_vaults, ipex_mailbox, monkeypatch):
    from hio.core.http import clienting
    from keri.acdc import ipexing as native
    from keri.peer import exchanging
    from locksmith.core import ipexing

    sender, receiver = ipex_vaults('closing-sender'), ipex_vaults('closing-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    exn, atc = native.apply(sh, rh.pre, 'Send', modifiers={'dp': [[]]})
    ipexing.submit(sender.vault, sh, exn, atc)
    record = sender.vault.db.outbox.get((exn.said,))
    record.attempts = 3
    sender.vault.db.outbox.pin((exn.said,), record)
    retained = exchanging.serializeMessage(sender.hby, exn.said)
    old_vault = sender.vault
    with monkeypatch.context() as patch:
        patch.setattr(sh, 'endsFor', lambda pre: {
            kering.Roles.controller: {rh.pre: {'http': 'http://127.0.0.1:9999'}}})
        patch.setattr(clienting.Client, 'reopen', lambda *a, **k: None)
        patch.setattr(clienting.Client, 'service', lambda *a, **k: None)
        for _ in range(20):
            sender.qtask.run()
        assert sender.vault.db.outbox.get((exn.said,)).status == 'sending'
        delivery = next(doer for doer in old_vault.ipex_outbox.doers
                        if isinstance(doer, ipexing.SendIpexDoer))
        sender.close_vault()
    assert old_vault.closed and not old_vault.db.opened
    assert not delivery.deeds and not old_vault.ipex_outbox.deeds
    with pytest.raises(ValueError, match='closed'):
        ipexing.submit(old_vault, sh, exn, atc)
    sender = ipex_vaults('closing-sender')
    sh = sender.hby.habByName('sender')
    assert sender.vault.db.outbox.get((exn.said,)).status == 'pending'
    ipex_mailbox(sender, receiver, sh, exn, retained, queued=True)
    assert sender.vault.db.outbox.get((exn.said,)).attempts == 5
    assert receiver.vault.exc.complete(exn.said)
    assert exchanging.serializeMessage(sender.hby, exn.said) == retained


def test_ipex_outbox_is_scoped_to_vault_base(ipex_vaults):
    from keri.acdc import ipexing as native
    from locksmith.core import ipexing

    first, second = ipex_vaults('same-name', base='first'), ipex_vaults('same-name', base='second')
    one, two = first.hby.makeHab(name='sender'), second.hby.makeHab(name='sender')
    recipient = first.hby.makeHab(name='recipient')
    exn, atc = native.apply(one, recipient.pre, 'Send', modifiers={'dp': [[]]})
    assert first.vault.db.path != second.vault.db.path
    with pytest.raises(ValueError, match='does not belong'):
        ipexing.submit(second.vault, one, exn, atc)
    ipexing.submit(first.vault, one, exn, atc)
    assert list(second.vault.db.outbox.getTopItemIter()) == []
    assert second.hby.habByPre(two.pre) is two
    first.close_vault()
    first = ipex_vaults('same-name', base='first')
    assert first.vault.db.outbox.get((exn.said,)).status == 'pending'
    assert list(second.vault.db.outbox.getTopItemIter()) == []


def test_ipex_retry_preserves_valid_sender_seal_after_rotation(ipex_vaults, ipex_mailbox):
    from keri.acdc import ipexing as native
    from keri.peer import exchanging
    from locksmith.core import ipexing

    sender, receiver = ipex_vaults('sealed-sender'), ipex_vaults('sealed-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    exn, _ = native.apply(sh, rh.pre, 'Apply', modifiers={'dp': [[]]})
    # This extra authentication seal does not negotiate AX for the reply.
    signed = native._sign(sh, exn, anchor=True)
    ipexing.submit(sender.vault, sh, exn, signed[exn.size:])
    retained = exchanging.serializeMessage(sender.hby, exn.said)
    sh.rotate()
    sn = sh.kever.sn
    ipex_mailbox(sender, receiver, sh, exn, retained, queued=True)
    assert receiver.hby.kevers[sh.pre].sn == sn
    assert receiver.vault.exc.complete(exn.said)
    assert sender.vault.db.outbox.get((exn.said,)).status == 'submitted'
    assert exchanging.serializeMessage(sender.hby, exn.said) == retained
    assert sh.kever.sn == sn


def test_vault_uses_one_app_owned_kram_policy(ipex_vaults):
    app = ipex_vaults('kram-policy')
    assert app.vault.kramer.enabled
    assert app.hby.db.kramCTYP.get('~').sl == 300000
    config = app.hby.cf.get()
    app.close_vault()
    reopened = ipex_vaults('kram-policy')
    assert reopened.hby.cf.get()['kram'] == config['kram']
    assert reopened.vault.kramer.enabled

@pytest.mark.real_routes
def test_vault_listens_through_receiving_endpoints_and_replays_unparsed_mail(ipex_vaults, monkeypatch):
    """Receive over a real mailbox SSE stream and retain frames before advancing."""
    import socket

    from keri.app import indirecting as kerindirecting
    from keri.app import storing
    from keri.db import openLMDB

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with habbing.openHab(name='listen-mailbox', transferable=False, temp=True,
                         version=kering.Vrsn_2_0) as (mhby, mailbox), \
            habbing.openHab(name='listen-sender', temp=True,
                            version=kering.Vrsn_2_0) as (_, sender), \
            openLMDB(cls=storing.Mailboxer, name='listen-mailbox') as mbx:
        mdoist = doing.Doist(doers=kerindirecting.setupWitness(
            mhby, alias='listen-mailbox', mbx=mbx, tcpPort=None, httpPort=port,
            version=kering.Vrsn_2_0), tock=0.03125)
        mdoist.enter()
        try:
            receiver = ipex_vaults('listen-receiver')
            rh = receiver.hby.makeHab(name='listener')
            witnessed = receiver.hby.makeHab(name='witnessed', wits=[mailbox.pre], toad=1)
            role = rh.makeEndRole(eid=mailbox.pre, role=kering.Roles.mailbox, allow=True)
            loc = mailbox.makeLocScheme(url=f'http://127.0.0.1:{port}', scheme='http')
            _deliver_ipex(receiver.vault, mailbox.replay(gvrsn=kering.Vrsn_2_0) + loc + role)
            parsing.Parser(kvy=eventing.Kevery(db=mhby.db, lax=False, local=False), framed=True,
                           version=kering.Vrsn_2_0).parse(
                ims=bytearray(rh.replay(gvrsn=kering.Vrsn_2_0)), local=False)
            assert rh.pre in mhby.kevers
            mbx.storeMsg(topic=f'{rh.pre}/replay',
                         msg=bytearray(sender.replay(gvrsn=kering.Vrsn_2_0)))

            def pollers(app, pre):
                return [poller for poller in app.vault.mbx.pollers
                        if (poller.pre, poller.mailbox) == (pre, mailbox.pre)]

            def run(app, done):
                deadline = monotonic() + 15
                while not done() and monotonic() < deadline:
                    mdoist.recur()
                    app.qtask.run()
                    sleep(0.001)
                assert done()

            # Crash after receiving but before parsing: the stored position must not move.
            with monkeypatch.context() as patch:
                patch.setattr(receiver.vault.mbx, 'processPollIter', lambda: iter(()))
                run(receiver, lambda: any(poller.msgs for poller in pollers(receiver, rh.pre)))
                assert receiver.hby.db.tops.get((rh.pre, mailbox.pre)) is None
                assert sender.pre not in receiver.hby.kevers
                receiver.close_vault()

            # Reopening replays the unparsed message, then takes the next one.
            receiver = ipex_vaults('listen-receiver')
            rh = receiver.hby.habByName('listener')
            rotation = SerderKERI(raw=bytes(sender.rotate()))
            mbx.storeMsg(topic=f'{rh.pre}/replay',
                         msg=bytearray(sender.replay(gvrsn=kering.Vrsn_2_0)))
            run(receiver, lambda: sender.pre in receiver.hby.kevers
                and receiver.hby.kevers[sender.pre].serder.said == rotation.said)
            assert receiver.hby.db.tops.get((rh.pre, mailbox.pre)).topics['/replay'] == 1
            # One poller per identifier and endpoint, from its mailbox role or witness list.
            assert len(pollers(receiver, rh.pre)) == 1
            assert len(pollers(receiver, witnessed.pre)) == 1
            cut = rh.makeEndRole(eid=mailbox.pre, role=kering.Roles.mailbox, allow=False)
            _deliver_ipex(receiver.vault, cut)
            run(receiver, lambda: not pollers(receiver, rh.pre))
            assert len(pollers(receiver, witnessed.pre)) == 1
            _deliver_ipex(receiver.vault, rh.makeEndRole(
                eid=mailbox.pre, role=kering.Roles.mailbox, allow=True))
            run(receiver, lambda: len(pollers(receiver, rh.pre)) == 1)
            witnessed = receiver.hby.habByName('witnessed')
            witnessed.rotate(cuts=[mailbox.pre], toad=0)
            run(receiver, lambda: not pollers(receiver, witnessed.pre))
        finally:
            mdoist.exit()


def test_mailbox_retains_unparsed_frames_across_reopen(ipex_vaults):
    from keri.acdc import ipexing as native
    sender, receiver = ipex_vaults('raw-sender'), ipex_vaults('raw-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    exn, atc = native.apply(sh, rh.pre, 'Saved mail', modifiers={'dp': [[]]})
    committed = []
    # The sender's KEL arrives first. Parsing must keep that order.
    for frame in (sh.replay(gvrsn=kering.Vrsn_2_0), exn.raw + atc):
        receiver.vault.mbx.messages.append((frame, lambda: committed.append(True)))
    process = receiver.vault.mbx.msgDo(tymth=lambda: 0.0)
    next(process)
    next(process)
    next(process)  # Commit each position only after retaining its raw frame.
    process.close()  # Stop before the parser runs.
    assert committed == [True, True]
    assert len(list(receiver.vault.db.inbox.getTopItemIter())) == 2
    assert not receiver.vault.exc.complete(exn.said)
    receiver.close_vault()
    receiver = ipex_vaults('raw-receiver')
    for _ in range(64):
        receiver.qtask.run()
    assert receiver.vault.exc.complete(exn.said)
    assert receiver.vault.notifier.getNoteCnt() == 1
    assert list(receiver.vault.db.inbox.getTopItemIter()) == []


@pytest.mark.parametrize('outcome', ['malformed', 'forged', 'rejected', 'missing_keys'])
def test_mailbox_discards_frames_once_parsed(ipex_vaults, monkeypatch, outcome):
    from keri.acdc import ipexing as native

    sender, receiver = ipex_vaults('bounded-sender'), ipex_vaults('bounded-receiver')
    sh, rh = sender.hby.makeHab(name='sender'), receiver.hby.makeHab(name='receiver')
    if outcome != 'missing_keys':
        _deliver_ipex(receiver.vault, sh.replay(gvrsn=kering.Vrsn_2_0))
    exn, atc = native.apply(sh, rh.pre, 'Mail', modifiers={'dp': [[]]})
    raw = bytes(exn.raw + atc)
    if outcome == 'malformed':
        raw = b'junk'
    elif outcome == 'forged':
        raw = raw.replace(sh.sign(exn.raw)[0].qb64b, sh.sign(b'forged')[0].qb64b)
    elif outcome == 'rejected':
        monkeypatch.setattr(receiver.vault.exc.routes['/ipex/apply'], 'verify', lambda **kwa: False)
    _deliver_ipex(receiver.vault, raw)
    assert list(receiver.vault.db.inbox.getTopItemIter()) == []
    assert not receiver.vault.exc.complete(exn.said)
