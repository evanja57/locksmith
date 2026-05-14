import os
import asyncio
import threading
import time
import warnings
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_ONBOARDED,
    KFBaser,
    KFAccountRecord,
    WitnessRecord,
)
from locksmith.plugins.kerifoundation.core.configing import WitnessServerConfig
from locksmith.plugins.kerifoundation.onboarding.service import (
    AccountWatcherRow,
)
from locksmith.plugins.kerifoundation.watchers.list import WatcherListPage
from locksmith.plugins.kerifoundation.witnesses.list import WitnessOverviewPage
from locksmith.plugins.kerifoundation.witnesses.provision import (
    HostedWitnessAllocation,
    HostedWitnessRegistrar,
    WitnessProvisionPage,
)


class FakeOrg:
    def __init__(self):
        self.data = {}

    def get(self, pre):
        return self.data.get(pre)

    def rem(self, pre):
        self.data.pop(pre, None)


class FakeHby:
    def __init__(self, habs):
        self._by_pre = {hab.pre: hab for hab in habs}

    def habByPre(self, pre):
        return self._by_pre.get(pre)


class FakeVault:
    def __init__(self, habs):
        self.hby = FakeHby(habs)
        self.org = FakeOrg()


class FakeApp:
    def __init__(self, habs):
        self.vault = FakeVault(habs)


def make_hab(name, pre, wits=None, toad=1):
    return SimpleNamespace(
        name=name,
        pre=pre,
        kever=SimpleNamespace(
            wits=list(wits or []),
            toader=SimpleNamespace(num=toad),
        ),
    )


class FakeBootClient:
    def __init__(self, witness_rows=None, watcher_rows=None, watcher_error=None):
        self.witness_rows = list(witness_rows or [])
        self.watcher_rows = list(watcher_rows or [])
        self.watcher_error = watcher_error
        self.calls = []

    def list_account_witnesses(self, hab, *, account_aid: str, destination: str = ""):
        self.calls.append(("witnesses", hab.pre, account_aid, destination))
        return list(self.witness_rows)

    def list_account_watchers(self, hab, *, account_aid: str, destination: str = ""):
        self.calls.append(("watchers", hab.pre, account_aid, destination))
        if self.watcher_error:
            raise RuntimeError(self.watcher_error)
        return list(self.watcher_rows)


def _make_db(tmp_path, name):
    return KFBaser(name=name, headDirPath=str(tmp_path), reopen=True)


def _event_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                return asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return loop


def _drive_async(qapp, predicate, timeout=1.0):
    loop = _event_loop()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        loop.run_until_complete(asyncio.sleep(0.01))
        qapp.processEvents()
    qapp.processEvents()


def _run_on_show(page):
    async def show():
        page.on_show()
        await asyncio.sleep(0)

    _event_loop().run_until_complete(show())


def _run(coro):
    return _event_loop().run_until_complete(coro)


async def _false_async():
    return False


def test_witness_overview_page_uses_local_provider_rows(qapp, tmp_path):
    account_hab = make_hab("kf-account", "AID_ACCOUNT")
    attached_hab = make_hab("shared-aid", "AID_SHARED")
    unrelated_hab = make_hab("other-aid", "AID_OTHER")
    app = FakeApp([account_hab, attached_hab, unrelated_hab])
    app.vault.org.data["WIT_1"] = {"alias": "Witness One"}
    app.vault.org.data["WIT_2"] = {"alias": "Witness Two"}
    db = _make_db(tmp_path, "kf-witness-overview")

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid=account_hab.pre,
                account_alias=account_hab.name,
                status=ACCOUNT_STATUS_ONBOARDED,
                boot_server_aid="BOOT_AID",
            )
        )
        db.attach_identifier(attached_hab.pre)
        db.witnesses.pin(
            keys=(account_hab.pre, "WIT_1"),
            val=WitnessRecord(
                eid="WIT_1",
                hab_pre=account_hab.pre,
                oobi="https://wit-1.example/oobi/WIT_1/controller",
                url="https://wit-1.example",
                totp_seed="SEED1",
                batch_mode=True,
            ),
        )
        db.witnesses.pin(
            keys=(attached_hab.pre, "WIT_2"),
            val=WitnessRecord(
                eid="WIT_2",
                hab_pre=attached_hab.pre,
                oobi="https://wit-2.example/oobi/WIT_2/controller",
                url="https://wit-2.example",
                totp_seed="SEED2",
                batch_mode=False,
            ),
        )
        db.witnesses.pin(
            keys=(unrelated_hab.pre, "WIT_3"),
            val=WitnessRecord(
                eid="WIT_3",
                hab_pre=unrelated_hab.pre,
                url="https://wit-3.example",
            ),
        )

        page = WitnessOverviewPage(app=app)
        page.set_db(db)
        page.on_show()

        rows = page._table._static_data
        assert [row["Witness AID"] for row in rows] == ["WIT_1", "WIT_2"]
        assert rows[0]["Identifier"] == "kf-account (Account)"
        assert rows[0]["Name"] == "Witness One"
        assert rows[0]["Auth"] == "Batch TOTP configured"
        assert rows[1]["Identifier"] == "shared-aid"
        assert rows[1]["Name"] == "Witness Two"
        assert rows[1]["Auth"] == "TOTP configured"
    finally:
        db.close()


def test_witness_overview_page_emits_add_witnesses_request(qapp, tmp_path):
    account_hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([account_hab])
    db = _make_db(tmp_path, "kf-witness-add-target")

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid=account_hab.pre,
                account_alias=account_hab.name,
                status=ACCOUNT_STATUS_ONBOARDED,
                boot_server_aid="BOOT_AID",
            )
        )

        page = WitnessOverviewPage(app=app)
        page.set_db(db)
        selected = []
        page.add_witnesses_requested.connect(lambda: selected.append(True))

        page.on_show()
        page._table.add_clicked.emit()
        qapp.processEvents()

        assert selected == [True]
    finally:
        db.close()


def test_watcher_list_page_uses_boot_rows(qapp, tmp_path):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-watcher-overview")
    boot_client = FakeBootClient(
        watcher_rows=[
            AccountWatcherRow(
                eid="WAT_1",
                name="Watcher One",
                url="https://watch-1.example",
                region_name="US West",
                status="Ready",
            )
        ]
    )

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid=hab.pre,
                account_alias=hab.name,
                status=ACCOUNT_STATUS_ONBOARDED,
                boot_server_aid="BOOT_AID",
            )
        )

        page = WatcherListPage(app=app)
        page.set_db(db)
        page.set_boot_client(boot_client)
        _run_on_show(page)
        _drive_async(qapp, lambda: page._refresh_task is None)

        assert boot_client.calls == [("watchers", hab.pre, hab.pre, "BOOT_AID")]
        assert page._table._static_data[0]["Watcher AID"] == "WAT_1"
        assert page._table._static_data[0]["Status"] == "Ready"
    finally:
        db.close()


def test_watcher_list_refresh_failure_keeps_existing_rows_visible(qapp, tmp_path):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-watcher-refresh-failure")

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid=hab.pre,
                account_alias=hab.name,
                status=ACCOUNT_STATUS_ONBOARDED,
                boot_server_aid="BOOT_AID",
            )
        )

        page = WatcherListPage(app=app)
        page.set_db(db)
        page.set_boot_client(FakeBootClient(watcher_error="account service unavailable"))
        stale_rows = [{"Name": "Cached", "Watcher AID": "WAT_OLD", "Region": "US", "Status": "Ready", "Endpoint": "—"}]
        page._table.set_static_data(stale_rows)

        _run_on_show(page)
        _drive_async(qapp, lambda: page._refresh_task is None)

        assert page._table._static_data == stale_rows
        assert not page._error_label.isHidden()
        assert "account service unavailable" in page._error_label.text()
    finally:
        db.close()


def test_watcher_list_missing_local_account_shows_recovery_message_and_clears_rows(qapp, tmp_path):
    app = FakeApp([])
    db = _make_db(tmp_path, "kf-watcher-missing-account")
    boot_client = FakeBootClient()

    try:
        db.pin_account(
            KFAccountRecord(
                account_aid="AID_MISSING",
                account_alias="missing-account",
                status=ACCOUNT_STATUS_ONBOARDED,
                boot_server_aid="BOOT_AID",
            )
        )

        page = WatcherListPage(app=app)
        page.set_db(db)
        page.set_boot_client(boot_client)
        page._table.set_static_data([
            {
                "Name": "Cached",
                "Watcher AID": "WAT_OLD",
                "Region": "US",
                "Status": "Ready",
                "Endpoint": "—",
            }
        ])

        _run_on_show(page)
        _drive_async(qapp, lambda: page._refresh_task is None)

        assert page._table._static_data == []
        assert not page._error_label.isHidden()
        assert "AID_MISSING" in page._error_label.text()
        assert "Restore that identifier" in page._error_label.text()
        assert boot_client.calls == []
    finally:
        db.close()


def test_hosted_witness_registrar_persists_registration_state(tmp_path, monkeypatch):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-hosted-registrar")

    async def fake_resolve_oobi(*args, **kwa):
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.register_with_witness",
        lambda hab, witness_eid, witness_url, secret=None: {
            "eid": witness_eid,
            "totp_seed": "SEED",
            "oobi": "",
        },
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.resolve_oobi",
        fake_resolve_oobi,
    )

    try:
        registrar = HostedWitnessRegistrar(app=app, db=db)
        result = _run(
            registrar.register(
                hab=hab,
                witnesses=[
                    HostedWitnessAllocation(
                        eid="WIT_1",
                        witness_url="https://wit-1.example",
                        boot_url="https://boot-1.example",
                        oobi="https://wit-1.example/oobi/WIT_1/controller",
                        name="Witness One",
                    ),
                    HostedWitnessAllocation(
                        eid="WIT_2",
                        witness_url="https://wit-2.example",
                        boot_url="https://boot-2.example",
                        oobi="https://wit-2.example/oobi/WIT_2/controller",
                        name="Witness Two",
                    ),
                ],
                batch_mode=True,
            )
        )

        assert result.batch_mode is True
        assert len(result.results) == 2
        assert db.witnesses.get(keys=(hab.pre, "WIT_1")) is not None
        assert db.witnesses.get(keys=(hab.pre, "WIT_2")) is not None
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example")) is not None
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-2.example")) is not None
        batches = db.witBatches.get(keys=(hab.pre,))
        assert batches is not None
        assert batches.batches == [["WIT_1", "WIT_2"]]
    finally:
        db.close()


def test_hosted_witness_registrar_persists_recovery_state_when_rollback_fails(tmp_path, monkeypatch):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-hosted-registrar-rollback")

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.register_with_witness",
        lambda hab, witness_eid, witness_url, secret=None: {
            "eid": witness_eid,
            "totp_seed": "SEED",
            "oobi": f"{witness_url}/oobi/{witness_eid}/controller",
        },
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.resolve_oobi",
        lambda *args, **kwa: _false_async(),
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.deprovision_witness",
        lambda eid, boot_url: False,
    )

    try:
        registrar = HostedWitnessRegistrar(app=app, db=db)
        with pytest.raises(ValueError) as excinfo:
            _run(
                registrar.register(
                    hab=hab,
                    witnesses=[
                        HostedWitnessAllocation(
                            eid="WIT_1",
                            witness_url="https://wit-1.example",
                            boot_url="https://boot-1.example",
                            oobi="https://wit-1.example/oobi/WIT_1/controller",
                            name="Witness One",
                        )
                    ],
                    batch_mode=True,
                )
            )
        message = str(excinfo.value)
        assert "Failed to resolve OOBI for witness WIT_1." in message
        assert "Boot URL: https://boot-1.example" in message
        assert "Resolver: resolver_state=unknown(no_hby_db)" in message
        assert "Cleanup after witness registration failure was incomplete:" in message
        assert "rollback=WIT_1..." in message
        assert "pending=WIT_1..." in message

        record = db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example"))
        assert record is not None
        assert record.eid == "WIT_1"
        assert db.witnesses.get(keys=(hab.pre, "WIT_1")) is None
    finally:
        db.close()


def test_hosted_witness_registrar_preserves_primary_oobi_failure_when_cleanup_succeeds(tmp_path, monkeypatch):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-hosted-registrar-primary-error")
    purged_oobis = []

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.register_with_witness",
        lambda hab, witness_eid, witness_url, secret=None: {
            "eid": witness_eid,
            "totp_seed": "SEED",
            "oobi": f"{witness_url}/oobi/{witness_eid}/controller",
        },
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.resolve_oobi",
        lambda *args, **kwa: _false_async(),
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.deprovision_witness",
        lambda eid, boot_url: True,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.purge_oobi_resolution_state",
        lambda app, *, oobi: purged_oobis.append(oobi),
    )

    try:
        registrar = HostedWitnessRegistrar(app=app, db=db)
        with pytest.raises(ValueError) as excinfo:
            _run(
                registrar.register(
                    hab=hab,
                    witnesses=[
                        HostedWitnessAllocation(
                            eid="WIT_1",
                            witness_url="https://wit-1.example",
                            boot_url="https://boot-1.example",
                            oobi="https://wit-1.example/oobi/WIT_1/controller",
                            name="Witness One",
                        )
                    ],
                    batch_mode=True,
                )
            )

        message = str(excinfo.value)
        assert "Failed to resolve OOBI for witness WIT_1." in message
        assert "WIT_1" in message
        assert "Cleanup after witness registration failure was incomplete:" not in message
        assert purged_oobis == ["https://wit-1.example/oobi/WIT_1/controller"]
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example")) is None
    finally:
        db.close()


def test_hosted_witness_registrar_deprovisions_partial_registration_failure(tmp_path, monkeypatch):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-hosted-registrar-partial-failure")
    deprovisioned = []

    def fake_register(hab, witness_eid, witness_url, secret=None):
        if witness_eid == "WIT_2":
            raise RuntimeError("register failed")
        return {
            "eid": witness_eid,
            "totp_seed": "SEED",
            "oobi": f"{witness_url}/oobi/{witness_eid}/controller",
        }

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.register_with_witness",
        fake_register,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.deprovision_witness",
        lambda eid, boot_url: deprovisioned.append((eid, boot_url)) or True,
    )

    try:
        registrar = HostedWitnessRegistrar(app=app, db=db)
        with pytest.raises(RuntimeError, match="register failed"):
            _run(
                registrar.register(
                    hab=hab,
                    witnesses=[
                        HostedWitnessAllocation(
                            eid="WIT_1",
                            witness_url="https://wit-1.example",
                            boot_url="https://boot-1.example",
                            oobi="https://wit-1.example/oobi/WIT_1/controller",
                            name="Witness One",
                        ),
                        HostedWitnessAllocation(
                            eid="WIT_2",
                            witness_url="https://wit-2.example",
                            boot_url="https://boot-2.example",
                            oobi="https://wit-2.example/oobi/WIT_2/controller",
                            name="Witness Two",
                        ),
                    ],
                    batch_mode=True,
                )
            )

        assert deprovisioned == [("WIT_1", "https://boot-1.example")]
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example")) is None
        assert db.witnesses.get(keys=(hab.pre, "WIT_1")) is None
    finally:
        db.close()


def test_witness_parallel_provision_failure_deprovisions_late_success(
    qapp, tmp_path, monkeypatch
):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-witness-provision-parallel-fail")
    page = WitnessProvisionPage(app=app)
    page.set_db(db)
    page.set_identifier(hab.pre)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    deprovisioned = []

    def fake_provision(hab_pre, boot_url):
        if boot_url == "https://boot-1.example":
            first_started.set()
            release_first.wait(timeout=1.0)
            return {
                "eid": "WIT_1",
                "oobi": "https://wit-1.example/oobi/WIT_1/controller",
            }
        second_started.set()
        first_started.wait(timeout=1.0)
        raise RuntimeError("provision failed")

    def fake_deprovision(eid, boot_url):
        deprovisioned.append((eid, boot_url))
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.provision_witness",
        fake_provision,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.deprovision_witness",
        fake_deprovision,
    )

    async def wait_until(predicate, timeout=0.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.01)
        return predicate()

    async def run_failed_provision():
        task = asyncio.create_task(
            page._run_provision_registration(
                hab_pre=hab.pre,
                hab=hab,
                servers=[
                    WitnessServerConfig(
                        witness_url="https://wit-1.example",
                        boot_url="https://boot-1.example",
                        region="US",
                        label="Witness One",
                    ),
                    WitnessServerConfig(
                        witness_url="https://wit-2.example",
                        boot_url="https://boot-2.example",
                        region="US",
                        label="Witness Two",
                    ),
                ],
                secret=None,
                db=db,
                vault=app.vault,
            )
        )
        page._provision_task = task
        both_started = await wait_until(
            lambda: first_started.is_set() and second_started.is_set()
        )
        release_first.set()
        await task
        return both_started

    try:
        assert _run(run_failed_provision()) is True

        assert deprovisioned == [("WIT_1", "https://boot-1.example")]
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example")) is None
        assert page._provision_task is None
    finally:
        release_first.set()
        page.shutdown()
        db.close()


def test_witness_provision_cancellation_after_provision_deprovisions(
    qapp, tmp_path, monkeypatch
):
    hab = make_hab("kf-account", "AID_ACCOUNT")
    app = FakeApp([hab])
    db = _make_db(tmp_path, "kf-witness-provision-cancel")
    page = WitnessProvisionPage(app=app)
    page.set_db(db)
    page.set_identifier(hab.pre)
    started = threading.Event()
    release = threading.Event()
    deprovisioned = []

    def fake_provision(hab_pre, boot_url):
        started.set()
        release.wait(timeout=1.0)
        return {
            "eid": "WIT_1",
            "oobi": "https://wit-1.example/oobi/WIT_1/controller",
        }

    def fake_deprovision(eid, boot_url):
        deprovisioned.append((eid, boot_url))
        return True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.provision_witness",
        fake_provision,
    )
    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.witnesses.provision.deprovision_witness",
        fake_deprovision,
    )

    async def run_cancelled_provision():
        task = asyncio.create_task(
            page._run_provision_registration(
                hab_pre=hab.pre,
                hab=hab,
                servers=[
                    WitnessServerConfig(
                        witness_url="https://wit-1.example",
                        boot_url="https://boot-1.example",
                        region="US",
                        label="Witness One",
                    )
                ],
                secret=None,
                db=db,
                vault=app.vault,
            )
        )
        page._provision_task = task
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        _run(run_cancelled_provision())

        assert deprovisioned == [("WIT_1", "https://boot-1.example")]
        assert db.provisionedWitnesses.get(keys=(hab.pre, "https://boot-1.example")) is None
        assert page._provision_task is None
    finally:
        release.set()
        page.shutdown()
        db.close()
