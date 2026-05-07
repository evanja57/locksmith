import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from keri import kering

from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_FAILED,
    ACCOUNT_STATUS_ONBOARDED,
    KFBaser,
    KFAccountRecord,
)
from locksmith.plugins.kerifoundation.onboarding.service import (
    BootstrapConfig,
    BootstrapOption,
    CESR_CONTENT_TYPE,
    HostedWatcherAllocation,
    HostedWitnessAllocation,
    HostedWitnessRegistration,
    KFBootClient,
    KFBootError,
    KFSurfaceConfig,
    KFOnboardingService,
    ONBOARDING_AUTH_NAMESPACE,
    OnboardingStartReply,
    load_kf_surfaces,
    parse_cesr_http_reply,
)
from locksmith.plugins.kerifoundation.witnesses.provision import HostedWitnessRegistrar


class FakeHab:
    def __init__(self, name, pre, wits=None, toad=1, ns="", sn=0, cloned_messages=None):
        self.name = name
        self.pre = pre
        self.ns = ns
        self._cloned_messages = list(cloned_messages or [])
        self.kever = SimpleNamespace(
            sn=sn,
            wits=list(wits or []),
            toader=SimpleNamespace(num=toad),
        )
        self.db = SimpleNamespace(clonePreIter=lambda pre: list(self._cloned_messages))

    def makeOwnEvent(self, sn=0, allowPartiallySigned=False):
        return f"evt-{self.pre}-{sn}".encode("utf-8")


class FakeHby:
    def __init__(self, habs=None):
        self._by_pre = {}
        self._by_name = {}
        self.make_hab_calls = []
        self.deleted_habs = []
        for hab in habs or []:
            self._by_pre[hab.pre] = hab
            self._by_name[(getattr(hab, "ns", ""), hab.name)] = hab

    def habByPre(self, pre):
        return self._by_pre.get(pre)

    def habByName(self, alias, ns=None):
        return self._by_name.get((ns or "", alias))

    def makeHab(self, *, name, ns=None, transferable=True, **kwa):
        if ns == ONBOARDING_AUTH_NAMESPACE:
            pre = "EPHEMERAL_AID"
        else:
            pre = f"AID_{name.upper()}"
        hab = FakeHab(
            name=name,
            pre=pre,
            wits=kwa.get("wits", []),
            toad=kwa.get("toad", 0),
            ns=ns or "",
        )
        self._by_pre[hab.pre] = hab
        self._by_name[(hab.ns, hab.name)] = hab
        self.make_hab_calls.append(
            {
                "name": name,
                "ns": ns or "",
                "transferable": transferable,
                "kwargs": dict(kwa),
            }
        )
        return hab

    def deleteHab(self, name, ns=None):
        hab = self._by_name.pop((ns or "", name), None)
        if hab is None:
            return False
        self._by_pre.pop(hab.pre, None)
        self.deleted_habs.append((ns or "", name))
        return True


class FakeVault:
    def __init__(self, habs=None):
        self.hby = FakeHby(habs=habs)
        self.org = SimpleNamespace(rem=lambda pre: None)


class FakeApp:
    def __init__(self, habs=None):
        self.vault = FakeVault(habs=habs)


@pytest.fixture(autouse=True)
def _stub_watcher_introduction(monkeypatch):
    calls = []

    def fake_introduce(*args, **kwa):
        calls.append(kwa)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.introduce_watcher_observed_aid",
        fake_introduce,
    )
    return calls


class FakeBootClient:
    def __init__(self):
        self.boot_server_aid = ""
        self.calls = []
        self.status_calls = 0
        self.session_state = "witness_pool_allocated"
        self.session_failure_reason = ""
        self._reply = None

    def fetch_bootstrap_config(self):
        self.calls.append(("bootstrap",))
        return BootstrapConfig(
            watcher_required=True,
            region_id="us-west-2",
            region_name="US West",
            account_options=[BootstrapOption(code="3-of-4", witness_count=4, toad=3)],
        )

    def send_ephemeral_inception(self, hab):
        self.calls.append(("inception", hab.pre))

    def start_onboarding(self, hab, *, alias, account_aid, witness_profile_code, region_id, watcher_required):
        self.boot_server_aid = "BOOT_SERVER_AID"
        self.calls.append(
            ("start", hab.pre, alias, account_aid, witness_profile_code, region_id, watcher_required)
        )
        self.session_state = "witness_pool_allocated"
        self.session_failure_reason = ""
        self._reply = OnboardingStartReply(
            session_id="SESSION_1",
            witnesses=[
                HostedWitnessAllocation(
                    eid="WIT_1",
                    witness_url="https://wit-1.example",
                    boot_url="https://boot.example",
                    oobi="https://wit-1.example/oobi/WIT_1/controller",
                    name="Witness One",
                ),
                HostedWitnessAllocation(
                    eid="WIT_2",
                    witness_url="https://wit-2.example",
                    boot_url="https://boot.example",
                    oobi="https://wit-2.example/oobi/WIT_2/controller",
                    name="Witness Two",
                ),
                HostedWitnessAllocation(
                    eid="WIT_3",
                    witness_url="https://wit-3.example",
                    boot_url="https://boot.example",
                    oobi="https://wit-3.example/oobi/WIT_3/controller",
                    name="Witness Three",
                ),
                HostedWitnessAllocation(
                    eid="WIT_4",
                    witness_url="https://wit-4.example",
                    boot_url="https://boot.example",
                    oobi="https://wit-4.example/oobi/WIT_4/controller",
                    name="Witness Four",
                ),
            ],
            watcher=HostedWatcherAllocation(
                eid="WAT_1",
                url="https://watch-1.example",
                oobi="https://watch-1.example/oobi/WAT_1/controller",
                name="Watcher One",
            ),
            toad=3,
            witness_count=4,
            region_id="us-west-2",
            region_name="US West",
            state=self.session_state,
            account_aid=account_aid,
        )
        return self._reply

    def session_status(self, hab, *, session_id, destination="", fallback_region_id=""):
        _ = (destination, fallback_region_id)
        self.status_calls += 1
        self.calls.append(("status", hab.pre, session_id))
        if self._reply is None:
            raise KFBootError("missing saved session")
        return OnboardingStartReply(
            session_id=self._reply.session_id,
            witnesses=list(self._reply.witnesses),
            watcher=self._reply.watcher,
            toad=self._reply.toad,
            witness_count=self._reply.witness_count,
            region_id=self._reply.region_id,
            region_name=self._reply.region_name,
            state=self.session_state,
            account_aid=self._reply.account_aid,
            failure_reason=self.session_failure_reason,
        )

    def create_account(
        self,
        hab,
        *,
        session_id,
        account_aid,
        alias,
        witness_profile_code,
        witnesses,
        watcher,
        region_id,
    ):
        self.calls.append(
            (
                "create_account",
                hab.pre,
                session_id,
                account_aid,
                alias,
                witness_profile_code,
                [wit.eid for wit in witnesses],
                watcher.eid if watcher is not None else "",
                region_id,
            )
        )
        self.session_state = "account_created"

    def complete_onboarding(self, hab, *, session_id, account_aid):
        self.calls.append(("complete", hab.pre, session_id, account_aid))
        self.session_state = "completed"

    def cancel_onboarding(self, hab, *, session_id, account_aid="", reason=""):
        self.calls.append(("cancel", hab.pre, session_id, account_aid, reason))
        self.session_state = "cancelled"


class RetryThenSucceedBootClient(FakeBootClient):
    def __init__(self):
        super().__init__()
        self.start_calls = 0
        self.complete_calls = 0

    def start_onboarding(self, hab, *, alias, account_aid, witness_profile_code, region_id, watcher_required):
        self.start_calls += 1
        return super().start_onboarding(
            hab,
            alias=alias,
            account_aid=account_aid,
            witness_profile_code=witness_profile_code,
            region_id=region_id,
            watcher_required=watcher_required,
        )

    def complete_onboarding(self, hab, *, session_id, account_aid):
        self.complete_calls += 1
        if self.complete_calls == 1:
            self.calls.append(("complete", hab.pre, session_id, account_aid))
            self.session_state = "account_created"
            raise KFBootError("simulated completion failure")
        super().complete_onboarding(hab, session_id=session_id, account_aid=account_aid)


class FailingCreateAccountBootClient(FakeBootClient):
    def start_onboarding(self, hab, *, alias, account_aid, witness_profile_code, region_id, watcher_required):
        reply = super().start_onboarding(
            hab,
            alias=alias,
            account_aid=account_aid,
            witness_profile_code=witness_profile_code,
            region_id=region_id,
            watcher_required=watcher_required,
        )

        witnesses = []
        for index, witness in enumerate(reply.witnesses, start=1):
            witnesses.append(
                HostedWitnessAllocation(
                    eid=witness.eid,
                    witness_url=witness.witness_url,
                    boot_url=f"https://boot-{index}.example",
                    oobi=witness.oobi,
                    name=witness.name,
                    region_id=witness.region_id,
                    region_name=witness.region_name,
                )
            )

        return OnboardingStartReply(
            session_id=reply.session_id,
            witnesses=witnesses,
            watcher=reply.watcher,
            toad=reply.toad,
            witness_count=reply.witness_count,
            region_id=reply.region_id,
            region_name=reply.region_name,
        )

    def create_account(
        self,
        hab,
        *,
        session_id,
        account_aid,
        alias,
        witness_profile_code,
        witnesses,
        watcher,
        region_id,
    ):
        super().create_account(
            hab,
            session_id=session_id,
            account_aid=account_aid,
            alias=alias,
            witness_profile_code=witness_profile_code,
            witnesses=witnesses,
            watcher=watcher,
            region_id=region_id,
        )
        raise KFBootError("simulated account-create failure")


class WrongTopologyBootClient(FakeBootClient):
    def start_onboarding(self, hab, *, alias, account_aid, witness_profile_code, region_id, watcher_required):
        reply = super().start_onboarding(
            hab,
            alias=alias,
            account_aid=account_aid,
            witness_profile_code=witness_profile_code,
            region_id=region_id,
            watcher_required=watcher_required,
        )
        return OnboardingStartReply(
            session_id=reply.session_id,
            witnesses=reply.witnesses[:3],
            watcher=reply.watcher,
            toad=2,
            witness_count=3,
            region_id=reply.region_id,
            region_name=reply.region_name,
        )


class FakeWitnessRegistrar:
    def __init__(self):
        self.calls = []

    def register(self, *, hab, witnesses, batch_mode=True, persist=True):
        self.calls.append((hab.pre, [wit.eid for wit in witnesses], batch_mode, persist))
        return HostedWitnessRegistration(
            results=[
                {
                    "eid": witness.eid,
                    "totp_seed": f"SEED_{index}",
                    "oobi": witness.oobi,
                    "boot_url": witness.boot_url,
                    "witness_url": witness.witness_url,
                    "name": witness.name,
                }
                for index, witness in enumerate(witnesses, start=1)
            ],
            batch_mode=batch_mode,
        )


def _make_db(tmp_path, name):
    return KFBaser(name=name, headDirPath=str(tmp_path), reopen=True)

def stub_rotation(service):
    calls = []

    def fake_rotate(*, hab, registration, allocated_witness_eids, toad):
        hab.kever.wits = list(allocated_witness_eids)
        hab.kever.toader.num = toad
        calls.append(
            {
                "hab_pre": hab.pre,
                "witness_eids": list(allocated_witness_eids),
                "toad": toad,
                "result_eids": [result["eid"] for result in registration.results],
            }
        )

    service._rotate_account_to_allocated_witnesses = fake_rotate
    return calls


def test_single_witness_rotation_posts_direct_receipt(tmp_path, monkeypatch):
    app = FakeApp()
    db = _make_db(tmp_path, "kf-onboarding-single-witness-rotation")
    service = KFOnboardingService(
        app=app,
        db=db,
        boot_client=FakeBootClient(),
        witness_registrar=FakeWitnessRegistrar(),
    )

    calls = []

    class FakeSerder:
        def __init__(self, raw):
            self.raw = b"RAW"
            self.size = 3

    class FakeWigs:
        def __init__(self):
            self.records = []

        def append(self, val):
            self.records.append(val)

        def get(self, keys):
            _ = keys
            return list(self.records)

    class FakeDB:
        def __init__(self):
            self.wigs = FakeWigs()

    fake_db = FakeDB()

    class RotHab:
        def __init__(self):
            self.pre = "AID_ROT"
            self.db = fake_db
            self.kever = SimpleNamespace(
                sn=0,
                wits=[],
                toader=SimpleNamespace(num=0),
                serder=SimpleNamespace(said="SAID_ROT_1"),
            )
            self.psr = SimpleNamespace(parseOne=lambda ims: fake_db.wigs.append(bytes(ims)))

        def rotate(self, *, toad, cuts, adds):
            calls.append(("rotate", toad, list(cuts), list(adds)))
            self.kever.sn = 1
            self.kever.wits = list(adds)
            self.kever.toader.num = toad
            self.kever.serder = SimpleNamespace(said="SAID_ROT_1")

        def makeOwnEvent(self, sn=0, allowPartiallySigned=False):
            _ = allowPartiallySigned
            calls.append(("makeOwnEvent", sn))
            return bytearray(b"RAWATT")

    def fake_post(url, *, headers, data, timeout):
        calls.append(("post", url, dict(headers), data, timeout))
        return SimpleNamespace(status_code=200, content=b"receipt")

    def fail_receiptor(*args, **kwargs):
        raise AssertionError("single-witness rotation should not use agenting.Receiptor")

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.SerderKERI",
        FakeSerder,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.requests.post",
        fake_post,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.agenting.Receiptor",
        fail_receiptor,
    )

    hab = RotHab()
    registration = HostedWitnessRegistration(
        results=[
            {
                "eid": "WIT_1",
                "totp_seed": "JBSWY3DPEHPK3PXP",
                "witness_url": "https://wit-1.example",
                "oobi": "https://wit-1.example/oobi/WIT_1/controller",
            }
        ],
        batch_mode=True,
    )

    try:
        service._rotate_account_to_allocated_witnesses(
            hab=hab,
            registration=registration,
            allocated_witness_eids=["WIT_1"],
            toad=1,
        )
    finally:
        db.close()

    auth_header = calls[2][2]["Authorization"]
    assert calls == [
        ("rotate", 1, [], ["WIT_1"]),
        ("makeOwnEvent", 1),
        (
            "post",
            "https://wit-1.example/receipts",
            {
                "Content-Type": CESR_CONTENT_TYPE,
                "CESR-ATTACHMENT": "ATT",
                "CESR-DESTINATION": "WIT_1",
                "Authorization": auth_header,
            },
            b"RAW",
            15,
        ),
    ]
    assert auth_header
    assert fake_db.wigs.get(keys=None) == [b"receipt"]


def test_onboarding_service_runs_step_4_5_6_flow(tmp_path, monkeypatch):
    app = FakeApp()
    db = _make_db(tmp_path, "kf-onboarding-service")
    boot_client = FakeBootClient()
    witness_registrar = FakeWitnessRegistrar()
    progress = []
    watcher_bind_calls = []

    def fake_resolve_oobi(*args, **kwa):
        return True

    def fake_introduce_watcher(*args, **kwa):
        watcher_bind_calls.append(kwa)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.introduce_watcher_observed_aid",
        fake_introduce_watcher,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=witness_registrar,
        )
        rotation_calls = stub_rotation(service)
        outcome = service.onboard(
            alias="my account",
            witness_profile_code="3-of-4",
            progress=lambda **kwa: progress.append(kwa),
        )

        record = db.get_account()
        assert outcome.account_aid == "AID_MY ACCOUNT"
        assert app.vault.hby.make_hab_calls[0] == {
            "name": "my account",
            "ns": "",
            "transferable": True,
            "kwargs": {
                "algo": "randy",
                "icount": 1,
                "isith": "1",
                "ncount": 1,
                "nsith": "1",
                "wits": [],
                "toad": 0,
            },
        }
        assert app.vault.hby.make_hab_calls[1] == {
            "name": app.vault.hby.make_hab_calls[1]["name"],
            "ns": ONBOARDING_AUTH_NAMESPACE,
            "transferable": False,
            "kwargs": {
                "icount": 1,
                "isith": "1",
                "ncount": 0,
                "nsith": "0",
                "wits": [],
                "toad": 0,
            },
        }
        assert rotation_calls == [
            {
                "hab_pre": "AID_MY ACCOUNT",
                "witness_eids": ["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
                "toad": 3,
                "result_eids": ["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
            }
        ]
        assert witness_registrar.calls == [
            ("AID_MY ACCOUNT", ["WIT_1", "WIT_2", "WIT_3", "WIT_4"], True, True)
        ]
        assert watcher_bind_calls == [
            {
                "hab": app.vault.hby.habByPre("AID_MY ACCOUNT"),
                "watcher_eid": "WAT_1",
                "observed_aid": "AID_MY ACCOUNT",
                "observed_oobis": [
                    "https://wit-1.example/oobi/AID_MY ACCOUNT/witness/WIT_1",
                    "https://wit-2.example/oobi/AID_MY ACCOUNT/witness/WIT_2",
                    "https://wit-3.example/oobi/AID_MY ACCOUNT/witness/WIT_3",
                    "https://wit-4.example/oobi/AID_MY ACCOUNT/witness/WIT_4",
                ],
            }
        ]
        assert boot_client.calls == [
            ("bootstrap",),
            ("inception", "EPHEMERAL_AID"),
            ("start", "EPHEMERAL_AID", "my account", "AID_MY ACCOUNT", "3-of-4", "us-west-2", True),
            (
                "create_account",
                "EPHEMERAL_AID",
                "SESSION_1",
                "AID_MY ACCOUNT",
                "my account",
                "3-of-4",
                ["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
                "WAT_1",
                "us-west-2",
            ),
            ("complete", "EPHEMERAL_AID", "SESSION_1", "AID_MY ACCOUNT"),
        ]
        assert record is not None
        assert record.status == ACCOUNT_STATUS_ONBOARDED
        assert record.account_aid == "AID_MY ACCOUNT"
        assert record.boot_server_aid == "BOOT_SERVER_AID"
        assert record.witness_profile_code == "3-of-4"
        assert record.witness_count == 4
        assert record.toad == 3
        assert record.onboarding_session_id == ""
        assert record.onboarding_auth_alias == ""
        assert any(item["stage"] == "boot_reply_verified" for item in progress)
        assert any(item["stage"] == "watcher_binding" for item in progress)
        assert progress[-1]["stage"] == "completed"
    finally:
        db.close()


def test_onboarding_service_reuses_existing_permanent_account_aid(tmp_path, monkeypatch):
    existing = FakeHab(
        name="my account",
        pre="AID_EXISTING",
        wits=["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
        toad=3,
    )
    app = FakeApp(habs=[existing])
    db = _make_db(tmp_path, "kf-onboarding-retry")
    boot_client = FakeBootClient()
    witness_registrar = FakeWitnessRegistrar()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid="AID_EXISTING",
                account_alias="my account",
                status=ACCOUNT_STATUS_FAILED,
            )
        )

        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=witness_registrar,
        )
        rotation_calls = stub_rotation(service)
        outcome = service.onboard(alias="my account", witness_profile_code="3-of-4")

        assert outcome.account_aid == "AID_EXISTING"
        assert [call for call in app.vault.hby.make_hab_calls if call["ns"] == ""] == []
        assert rotation_calls == []
        assert witness_registrar.calls[0][0] == "AID_EXISTING"
        assert witness_registrar.calls[0][3] is True
        assert db.get_account().status == ACCOUNT_STATUS_ONBOARDED
    finally:
        db.close()


def test_onboarding_service_uses_selected_existing_account_aid(tmp_path, monkeypatch):
    existing = FakeHab(
        name="selected-account",
        pre="AID_EXISTING",
        wits=["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
        toad=3,
    )
    app = FakeApp(habs=[existing])
    db = _make_db(tmp_path, "kf-onboarding-selected-aid")
    boot_client = FakeBootClient()
    witness_registrar = FakeWitnessRegistrar()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=witness_registrar,
        )
        rotation_calls = stub_rotation(service)
        outcome = service.onboard(
            alias="selected-account",
            witness_profile_code="3-of-4",
            account_aid="AID_EXISTING",
        )

        assert outcome.account_aid == "AID_EXISTING"
        assert [call for call in app.vault.hby.make_hab_calls if call["ns"] == ""] == []
        assert rotation_calls == []
        assert witness_registrar.calls[0][0] == "AID_EXISTING"
        assert db.get_account().account_aid == "AID_EXISTING"
    finally:
        db.close()


def test_onboarding_service_rotates_selected_unwitnessed_account_aid(tmp_path, monkeypatch):
    existing = FakeHab(name="selected-account", pre="AID_EXISTING", wits=[], toad=0)
    app = FakeApp(habs=[existing])
    db = _make_db(tmp_path, "kf-onboarding-selected-unwitnessed")
    boot_client = FakeBootClient()
    witness_registrar = FakeWitnessRegistrar()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=witness_registrar,
        )
        rotation_calls = stub_rotation(service)

        outcome = service.onboard(
            alias="selected-account",
            witness_profile_code="3-of-4",
            account_aid="AID_EXISTING",
        )

        assert outcome.account_aid == "AID_EXISTING"
        assert rotation_calls == [
            {
                "hab_pre": "AID_EXISTING",
                "witness_eids": ["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
                "toad": 3,
                "result_eids": ["WIT_1", "WIT_2", "WIT_3", "WIT_4"],
            }
        ]
    finally:
        db.close()


def test_onboarding_service_rejects_alias_collision_with_untracked_local_aid(tmp_path, monkeypatch):
    existing = FakeHab(name="my account", pre="AID_OTHER", wits=["WIT_1"], toad=1)
    app = FakeApp(habs=[existing])
    db = _make_db(tmp_path, "kf-onboarding-alias-collision")
    boot_client = FakeBootClient()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=FakeWitnessRegistrar(),
        )

        with pytest.raises(KFBootError, match="already used by another local identifier"):
            service.onboard(alias="my account", witness_profile_code="3-of-4")
    finally:
        db.close()


def test_onboarding_service_rejects_existing_account_with_different_witness_configuration(tmp_path, monkeypatch):
    existing = FakeHab(name="selected-account", pre="AID_EXISTING", wits=["OLD_WIT"], toad=1)
    app = FakeApp(habs=[existing])
    db = _make_db(tmp_path, "kf-onboarding-selected-mismatch")
    boot_client = FakeBootClient()
    witness_registrar = FakeWitnessRegistrar()
    purged_oobis = []

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.purge_oobi_resolution_state",
        lambda app, *, oobi: purged_oobis.append(oobi),
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=witness_registrar,
        )

        with pytest.raises(KFBootError, match="different witness configuration"):
            service.onboard(
                alias="selected-account",
                witness_profile_code="3-of-4",
                account_aid="AID_EXISTING",
            )
        assert witness_registrar.calls == []
        assert ("cancel", "EPHEMERAL_AID", "SESSION_1", "AID_EXISTING", "client_abandoned") in boot_client.calls
        assert len(purged_oobis) == 5
        assert "https://wit-1.example/oobi/WIT_1/controller" in purged_oobis
        assert "https://watch-1.example/oobi/WAT_1/controller" in purged_oobis
    finally:
        db.close()


def test_onboarding_failure_after_completion_preserves_session_and_resumes(tmp_path, monkeypatch):
    app = FakeApp()
    db = _make_db(tmp_path, "kf-onboarding-retry-session")
    boot_client = RetryThenSucceedBootClient()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=FakeWitnessRegistrar(),
        )
        stub_rotation(service)

        with pytest.raises(KFBootError, match="simulated completion failure"):
            service.onboard(alias="my account", witness_profile_code="3-of-4")

        record = db.get_account()
        assert record is not None
        record.status = ACCOUNT_STATUS_FAILED
        db.pin_account(record)

        outcome = service.onboard(alias="my account", witness_profile_code="3-of-4")

        assert outcome.account_aid == "AID_MY ACCOUNT"
        assert boot_client.start_calls == 1
        assert boot_client.status_calls == 1
        assert ("status", "EPHEMERAL_AID", "SESSION_1") in boot_client.calls
        assert ("cancel", "EPHEMERAL_AID", "SESSION_1", "AID_MY ACCOUNT", "client_abandoned") not in boot_client.calls
    finally:
        db.close()


def test_onboarding_failure_after_account_create_preserves_local_state_for_resume(tmp_path, monkeypatch):
    app = FakeApp()
    db = _make_db(tmp_path, "kf-onboarding-rollback")
    boot_client = FailingCreateAccountBootClient()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.resolve_oobi_blocking",
        fake_resolve_oobi,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.register_with_witness",
        lambda hab, witness_eid, witness_url, secret=None: {
            "eid": witness_eid,
            "totp_seed": f"SEED_{witness_eid}",
            "oobi": f"{witness_url}/oobi/{witness_eid}/controller",
        },
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=HostedWitnessRegistrar(app=app, db=db),
        )
        stub_rotation(service)

        with pytest.raises(KFBootError, match="simulated account-create failure"):
            service.onboard(alias="my account", witness_profile_code="3-of-4")

        record = db.get_account()
        assert record is not None
        assert record.account_aid == "AID_MY ACCOUNT"
        assert record.onboarding_session_id == "SESSION_1"
        assert record.onboarding_auth_alias
        assert db.witnesses.get(keys=(record.account_aid, "WIT_1")) is not None
        assert db.witnesses.get(keys=(record.account_aid, "WIT_2")) is not None
        assert db.witBatches.get(keys=(record.account_aid,)) is not None
        assert db.provisionedWitnesses.get(keys=(record.account_aid, "https://boot-1.example")) is not None
        assert db.provisionedWitnesses.get(keys=(record.account_aid, "https://boot-2.example")) is not None
        assert ("cancel", "EPHEMERAL_AID", "SESSION_1", "AID_MY ACCOUNT", "client_abandoned") not in boot_client.calls
    finally:
        db.close()


def test_onboarding_rejects_allocations_that_do_not_match_requested_profile(tmp_path, monkeypatch):
    app = FakeApp()
    db = _make_db(tmp_path, "kf-onboarding-topology")
    boot_client = WrongTopologyBootClient()

    def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve_oobi,
    )

    try:
        service = KFOnboardingService(
            app=app,
            db=db,
            boot_client=boot_client,
            witness_registrar=FakeWitnessRegistrar(),
        )
        stub_rotation(service)

        with pytest.raises(KFBootError, match="witness profile"):
            service.onboard(alias="my account", witness_profile_code="3-of-4")
    finally:
        db.close()


def test_load_kf_surfaces_uses_local_dev_defaults(monkeypatch):
    app = SimpleNamespace(
        config=SimpleNamespace(environment=SimpleNamespace(value="development"))
    )

    monkeypatch.delenv("KF_DEV_ONBOARDING_URL", raising=False)
    monkeypatch.delenv("KF_DEV_ACCOUNT_URL", raising=False)
    monkeypatch.delenv("KF_DEV_ONBOARDING_DESTINATION", raising=False)
    monkeypatch.delenv("KF_DEV_ACCOUNT_DESTINATION", raising=False)

    surfaces = load_kf_surfaces(app)

    assert surfaces.onboarding_url == "http://127.0.0.1:9723/onboarding"
    assert surfaces.account_url == "http://127.0.0.1:9723/account"
    assert surfaces.bootstrap_url == "http://127.0.0.1:9723/bootstrap/config"
    assert surfaces.health_url == "http://127.0.0.1:9723/health"


def test_load_kf_surfaces_rejects_unknown_environment():
    app = SimpleNamespace(
        config=SimpleNamespace(environment=SimpleNamespace(value="preview"))
    )

    with pytest.raises(ValueError, match="Unknown environment: preview"):
        load_kf_surfaces(app)


def test_build_witness_auths_rejects_missing_auth_material(tmp_path):
    service = KFOnboardingService(
        app=FakeApp(),
        db=_make_db(tmp_path, "kf-onboarding-auths"),
        boot_client=FakeBootClient(),
        witness_registrar=FakeWitnessRegistrar(),
    )
    try:
        with pytest.raises(KFBootError, match="authentication material"):
            service._build_witness_auths(
                HostedWitnessRegistration(
                    results=[{"eid": "WIT_1", "totp_seed": ""}],
                    batch_mode=True,
                )
            )
    finally:
        service._db.close()


def test_resolve_watcher_oobi_uses_blocking_hio_helper(monkeypatch, tmp_path):
    service = KFOnboardingService(
        app=FakeApp(),
        db=_make_db(tmp_path, "kf-onboarding-watcher-oobi"),
        boot_client=FakeBootClient(),
        witness_registrar=FakeWitnessRegistrar(),
    )
    calls = []

    def fake_resolve(*args, **kwa):
        calls.append((args, kwa))
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.resolve_oobi_blocking",
        fake_resolve,
    )

    try:
        service._resolve_watcher_oobi(
            account_hab=FakeHab(name="acct", pre="AID_ACCOUNT"),
            watcher=HostedWatcherAllocation(
                eid="WAT_1",
                url="https://watch.example",
                oobi="https://watch.example/oobi/WAT_1/controller",
                name="Watcher One",
            ),
        )

        assert calls == [
            (
                (service._app,),
                {
                    "pre": "WAT_1",
                    "oobi": "https://watch.example/oobi/WAT_1/controller",
                    "force": True,
                    "alias": "Watcher One",
                    "cid": "AID_ACCOUNT",
                    "tag": "watcher",
                },
            )
        ]
    finally:
        service._db.close()


def test_rotate_account_to_allocated_witnesses_rotates_and_receipts(monkeypatch, tmp_path):
    class RotatingHab(FakeHab):
        def __init__(self):
            super().__init__(name="rotating", pre="AID_ROTATE", wits=[], toad=0)
            self.rotate_calls = []
            self.kever.sn = 0

        def rotate(self, *, toad, cuts, adds):
            self.rotate_calls.append({"toad": toad, "cuts": list(cuts), "adds": list(adds)})
            self.kever.wits = list(adds)
            self.kever.toader.num = toad
            self.kever.sn += 1

    class FakeReceiptor:
        def __init__(self, hby):
            self.hby = hby
            self.calls = []

        def wind(self, tymth):
            self.tymth = tymth

        def receipt(self, pre, sn=None, auths=None):
            self.calls.append((pre, sn, auths))
            if False:
                yield 0.0

    fake_receiptor = FakeReceiptor(hby=object())

    class FakeDoist:
        def __init__(self, *args, **kwa):
            pass

        def do(self, doers=None, limit=None, tyme=None, temp=None):
            _ = (limit, tyme, temp)
            runner = doers[1]
            gen = runner(tymth=lambda: 0.0, tock=0.0)
            next(gen)
            with pytest.raises(StopIteration):
                next(gen)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.agenting.Receiptor",
        lambda hby: fake_receiptor,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.doing.doify",
        lambda fn: fn,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.doing.Doist",
        FakeDoist,
    )

    service = KFOnboardingService(
        app=FakeApp(),
        db=_make_db(tmp_path, "kf-onboarding-rotate"),
        boot_client=FakeBootClient(),
        witness_registrar=FakeWitnessRegistrar(),
    )
    hab = RotatingHab()
    registration = HostedWitnessRegistration(
        results=[
            {"eid": "WIT_1", "totp_seed": "JBSWY3DPEHPK3PXP"},
            {"eid": "WIT_2", "totp_seed": "JBSWY3DPEHPK3PXP"},
        ],
        batch_mode=True,
    )
    try:
        service._rotate_account_to_allocated_witnesses(
            hab=hab,
            registration=registration,
            allocated_witness_eids=["WIT_1", "WIT_2"],
            toad=2,
        )
        assert hab.rotate_calls == [{"toad": 2, "cuts": [], "adds": ["WIT_1", "WIT_2"]}]
        assert fake_receiptor.calls
        assert fake_receiptor.calls[0][0] == "AID_ROTATE"
        assert fake_receiptor.calls[0][1] == 1
        assert set(fake_receiptor.calls[0][2].keys()) == {"WIT_1", "WIT_2"}
        assert all("#" in value for value in fake_receiptor.calls[0][2].values())
    finally:
        service._db.close()


def test_parse_cesr_http_reply_rejects_non_reply_messages(monkeypatch):
    class FakeParser:
        def __init__(self, *args, **kwa):
            pass

        def parse(self, ims):
            return None

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

    fake_serder = SimpleNamespace(
        pre="BOOT_SERVER_AID",
        ked={
            "t": "exn",
            "r": "/account/witnesses",
            "a": {"witnesses": []},
        },
        said="SAID_1",
    )
    response = SimpleNamespace(content=b"{}", headers={})

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.parsing.Parser",
        FakeParser,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.message_version",
        lambda ims: kering.Vrsn_1_0,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.split_cesr_stream",
        lambda ims: [fake_serder],
    )

    with pytest.raises(KFBootError, match="expected rpy"):
        parse_cesr_http_reply(
            app,
            response,
            expected_kinds=("rpy",),
            expected_route="/account/witnesses",
        )


def test_parse_cesr_http_reply_rejects_sender_mismatch(monkeypatch):
    class FakeParser:
        def __init__(self, *args, **kwa):
            pass

        def parse(self, ims):
            return None

    app = SimpleNamespace(
        vault=SimpleNamespace(
            hby=SimpleNamespace(
                kvy=SimpleNamespace(processEscrows=lambda: None),
                rvy=object(),
                exc=object(),
                kevers={"BOOT_SERVER_AID": object(), "OTHER_BOOT_AID": object()},
            )
        )
    )

    fake_serder = SimpleNamespace(
        pre="OTHER_BOOT_AID",
        ked={
            "t": "rpy",
            "r": "/account/witnesses",
            "a": {"witnesses": []},
        },
        said="SAID_2",
    )
    response = SimpleNamespace(content=b"{}", headers={})

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.parsing.Parser",
        FakeParser,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.message_version",
        lambda ims: kering.Vrsn_1_0,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.split_cesr_stream",
        lambda ims: [fake_serder],
    )

    with pytest.raises(KFBootError, match="did not match expected boot service"):
        parse_cesr_http_reply(
            app,
            response,
            expected_kinds=("rpy",),
            expected_route="/account/witnesses",
            expected_sender="BOOT_SERVER_AID",
        )


def test_boot_client_syncs_account_keystate_once_per_surface(monkeypatch):
    client = KFBootClient(
        FakeApp(),
        surfaces=KFSurfaceConfig(
            onboarding_url="https://boot.example/onboarding",
            account_url="https://boot.example/account",
            account_destination="BOOT_SERVER_AID",
        ),
    )
    hab = FakeHab(
        "account",
        "AID_ACCOUNT",
        sn=1,
        cloned_messages=[
            b"clone-AID_ACCOUNT-0-with-receipts",
            b"clone-AID_ACCOUNT-1-with-receipts",
        ],
    )
    calls = []

    def fake_post_cesr(**kwa):
        calls.append(kwa)
        return None

    class FakeSerder:
        def __init__(self, raw):
            text = raw.decode("utf-8")
            self.sn = int(text.split("-")[2])
            self.ked = {"s": str(self.sn)}

    monkeypatch.setattr(client, "_post_cesr", fake_post_cesr)
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.SerderKERI",
        FakeSerder,
    )

    client._ensure_surface_keystate(surface="account", hab=hab, destination="BOOT_SERVER_AID")
    client._ensure_surface_keystate(surface="account", hab=hab, destination="BOOT_SERVER_AID")

    assert [call["ims"] for call in calls] == [
        b"clone-AID_ACCOUNT-0-with-receipts",
        b"clone-AID_ACCOUNT-1-with-receipts",
    ]
    assert all(call["url"] == "https://boot.example/account" for call in calls)
    assert all(call["destination"] == "BOOT_SERVER_AID" for call in calls)
    assert all(call["require_reply"] is False for call in calls)


def test_boot_client_post_cesr_surfaces_http_error_details(monkeypatch):
    client = KFBootClient(
        FakeApp(),
        surfaces=KFSurfaceConfig(
            onboarding_url="https://boot.example/onboarding",
            account_url="https://boot.example/account",
        ),
    )

    response = SimpleNamespace(
        status_code=401,
        reason="Unauthorized",
        url="https://boot.example/account",
        text='{"title":"Wrong account principal","description":"The authenticated sender must match account_aid."}',
        json=lambda: {
            "title": "Wrong account principal",
            "description": "The authenticated sender must match account_aid.",
        },
    )

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.requests.post",
        lambda *args, **kwa: response,
    )

    with pytest.raises(KFBootError, match="Wrong account principal"):
        client._post_cesr(
            url="https://boot.example/account",
            body=b"{}",
            attachment=b"sig",
            require_reply=False,
        )
