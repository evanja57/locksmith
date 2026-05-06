import importlib
from types import SimpleNamespace

import pytest
from keri import kering
from keri.app import habbing
from keri.core import eventing, parsing

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
