import importlib
import logging
from types import SimpleNamespace

import pytest
from hio.base import doing
from keri import kering
from keri.app import habbing
from keri.core import coring, eventing, parsing
from keri.db import dbing
from keri.vdr import credentialing

from locksmith.core.remoting import message_version
from locksmith.db.basing import (
    BrowserPluginSettings,
    IdentifierMetaInfo,
    LocksmithBaser,
    MailboxListener,
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
        db.mbx.pin(
            keys=("MBOX_1",),
            val=MailboxListener(cid="CID_1", eid="MBOX_1", name="Mailbox One"),
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
        assert list(db.mbx.getTopItemIter(keys=())) == [
            (("MBOX_1",), MailboxListener(cid="CID_1", eid="MBOX_1", name="Mailbox One"))
        ]
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
    with habbing.openHab(name="v1-sender", temp=True) as (_hby, hab):
        msg = bytes(hab.makeOwnEvent(sn=0))

    assert b"KERI10" in msg[:32]
    assert message_version(msg) == kering.Vrsn_1_0


def test_keri_v2_parser_accepts_existing_keri10_event_with_detected_version():
    with habbing.openHab(name="v1-sender", temp=True) as (_hby, hab):
        msg = bytes(hab.makeOwnEvent(sn=0))

    with habbing.openHby(name="v1-receiver", temp=True) as hby:
        kvy = eventing.Kevery(db=hby.db, lax=True)
        parsing.Parser(kvy=kvy, local=False, version=message_version(msg)).parse(
            ims=bytearray(msg)
        )

        assert hab.pre in kvy.kevers


def test_vault_constructs_with_real_keri_v2_stores(monkeypatch, tmp_path):
    from locksmith.core import vaulting

    class FakeTurretDoer(doing.DoDoer):
        def __init__(self, *args, **kwargs):
            super().__init__(doers=[])

    def locksmith_baser(name, reopen=True):
        return LocksmithBaser(
            name=f"{name}-locksmith",
            headDirPath=str(tmp_path),
            reopen=reopen,
        )

    monkeypatch.setattr(vaulting, "LocksmithBaser", locksmith_baser)
    monkeypatch.setattr(vaulting, "TurretDoer", FakeTurretDoer)

    with habbing.openHby(name="vault-v2", temp=True) as hby:
        rgy = credentialing.Regery(hby=hby, name=hby.name, temp=True)
        vault = None
        try:
            vault = vaulting.Vault(app=SimpleNamespace(), hby=hby, rgy=rgy)

            assert vault.hby is hby
            assert vault.counseling_completion_doers == {}
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

        rgy = credentialing.Regery(hby=hby, name=hby.name, temp=True)
        try:
            assert hasattr(rgy.reger, "tels")
            assert hasattr(rgy.reger, "ancs")
            assert not hasattr(rgy.reger, "getTel")
            assert not hasattr(rgy.reger, "putAnc")
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


def test_registry_creation_uses_keri_v2_nonce(monkeypatch):
    from locksmith.core import credentialing as locksmith_credentialing

    class StopAfterNonce(Exception):
        pass

    captured = {}
    doer = locksmith_credentialing.LoadSchemaDoer.__new__(
        locksmith_credentialing.LoadSchemaDoer
    )
    doer.hby = SimpleNamespace(
        habs={"ISSUER_AID": SimpleNamespace(name="issuer", pre="ISSUER_AID")}
    )
    doer.rgy = SimpleNamespace(regs={})
    doer.issuer_aid = "ISSUER_AID"
    doer.auth_codes = None
    doer.tock = 0.0
    doer.extend = lambda doers: None

    def make_registry(name, prefix, **kwa):
        captured.update(name=name, prefix=prefix, nonce=kwa["nonce"])
        raise StopAfterNonce

    doer.rgy.makeRegistry = make_registry

    monkeypatch.setattr(
        locksmith_credentialing.grouping,
        "Counselor",
        lambda hby: object(),
    )
    monkeypatch.setattr(
        locksmith_credentialing.forwarding,
        "Poster",
        lambda hby: object(),
    )
    monkeypatch.setattr(
        locksmith_credentialing,
        "Registrar",
        lambda **kwargs: object(),
    )

    with pytest.raises(StopAfterNonce):
        next(doer._create_registry("SCHEMA_SAID", "Schema Title"))

    assert captured["name"] == "SCHEMA_SAID"
    assert captured["prefix"] == "ISSUER_AID"
    assert len(captured["nonce"]) == 24


def test_locksmith_receiptor_uses_keri_v2_httping(monkeypatch):
    from locksmith.core import receipting

    class FakeClient:
        def __init__(self):
            self.responses = ["one", "two"]
            self.responded = 0

        def respond(self):
            self.responses.pop(0)
            self.responded += 1

    class FakeHab:
        def replay(self, pre):
            assert pre == "AID"
            return b"replayed-kel"

    client = FakeClient()
    captured = {}
    hby = SimpleNamespace(prefixes={"AID"}, habs={"AID": FakeHab()})
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
    }
    assert client.responded == 2


def test_watcher_inquisitor_treats_204_as_accepted(monkeypatch, caplog):
    from locksmith.core import adjudication

    class FakeClient:
        responses = [SimpleNamespace(status=204, body=b"")]

        def respond(self):
            return self.responses.pop(0)

    class FakeHab:
        def query(self, target, *, src, route, query):
            captured.update(target=target, src=src, route=route, query=query)
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
