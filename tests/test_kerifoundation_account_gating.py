import os
import asyncio
import time
import warnings
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_FAILED,
    ACCOUNT_STATUS_ONBOARDED,
    ACCOUNT_STATUS_PENDING_ONBOARDING,
    KFBaser,
    KFAccountRecord,
)
from locksmith.plugins.kerifoundation.onboarding.service import KFBootError
from locksmith.plugins.kerifoundation.plugin import KeriFoundationPlugin


class FakeHby:
    def __init__(self, name="test-vault"):
        self.name = name
        self.db = SimpleNamespace(names=SimpleNamespace(getTopItemIter=lambda keys=(): iter(())))

    def habByName(self, alias):
        return None

    def habByPre(self, pre):
        return None


class FakeVault:
    def __init__(self, name="test-vault"):
        self.hby = FakeHby(name=name)


class FakeApp:
    def __init__(self, vault_name="test-vault"):
        self.vault = FakeVault(name=vault_name)
        self.config = SimpleNamespace(environment=SimpleNamespace(value="development"))


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


def _get_setup_page(qapp, plugin, vault):
    result = {}

    async def get_page():
        result["value"] = plugin.get_setup_page(vault)
        await asyncio.sleep(0)

    _event_loop().run_until_complete(get_page())
    qapp.processEvents()
    return result["value"]


def _confirm_onboarding(qapp, plugin, alias, witness_profile, account_aid):
    async def confirm():
        plugin._on_onboarding_confirm(alias, witness_profile, account_aid)

    _event_loop().run_until_complete(confirm())
    qapp.processEvents()


def test_kf_account_record_survives_reload(tmp_path):
    db = KFBaser(name="test-kf-account-record", headDirPath=str(tmp_path), reopen=True)

    try:
        record = KFAccountRecord(
            account_aid="AID_ACCOUNT",
            account_alias="public-account",
            status=ACCOUNT_STATUS_ONBOARDED,
            onboarded_at="2026-04-06T12:00:00+00:00",
            witness_profile_code="3-of-4",
            witness_count=4,
            toad=3,
            watcher_required=True,
            region_id="us-west-2",
        )
        db.pin_account(record)
        db.close()

        reopened = KFBaser(name="test-kf-account-record", headDirPath=str(tmp_path), reopen=True)
        try:
            loaded = reopened.get_account()
            assert loaded is not None
            assert loaded.account_aid == "AID_ACCOUNT"
            assert loaded.account_alias == "public-account"
            assert loaded.status == ACCOUNT_STATUS_ONBOARDED
            assert loaded.onboarded_at == "2026-04-06T12:00:00+00:00"
            assert loaded.witness_profile_code == "3-of-4"
            assert loaded.witness_count == 4
            assert loaded.toad == 3
            assert loaded.watcher_required is True
            assert loaded.region_id == "us-west-2"
        finally:
            reopened.close()
    finally:
        try:
            db.close()
        except Exception:
            pass


def test_kf_plugin_initializes_pending_account_and_gates_to_onboarding(
        qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.KFBaser",
        lambda name, reopen=True: KFBaser(
            name=name,
            headDirPath=str(tmp_path),
            reopen=reopen,
        ),
    )

    plugin.on_vault_opened(app.vault)
    try:
        assert plugin.is_setup_complete(app.vault) is False

        page_key, should_push_menu = _get_setup_page(qapp, plugin, app.vault)
        record = plugin._db.get_account()

        assert page_key == "kf_onboarding"
        assert should_push_menu is True
        assert record is not None
        assert record.status == ACCOUNT_STATUS_PENDING_ONBOARDING
        assert record.watcher_required is True
        assert record.created_at
    finally:
        plugin.on_vault_closed(app.vault)


def test_kf_plugin_allows_normal_menu_after_onboarding(qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.KFBaser",
        lambda name, reopen=True: KFBaser(
            name=name,
            headDirPath=str(tmp_path),
            reopen=reopen,
        ),
    )

    plugin.on_vault_opened(app.vault)
    try:
        plugin._db.pin_account(KFAccountRecord(
            account_aid="AID_ACCOUNT",
            account_alias="public-account",
            status=ACCOUNT_STATUS_ONBOARDED,
            onboarded_at="2026-04-06T12:00:00+00:00",
            witness_profile_code="1-of-1",
            witness_count=1,
            toad=1,
            watcher_required=True,
            region_id="local",
        ))

        assert plugin.is_setup_complete(app.vault) is True

        page_key, should_push_menu = _get_setup_page(qapp, plugin, app.vault)
        assert page_key == "kf_witnesses"
        assert should_push_menu is True
    finally:
        plugin.on_vault_closed(app.vault)


def test_kf_plugin_opens_rotate_dialog_after_provision(qapp, monkeypatch):
    app = FakeApp()
    app.vault.hby = SimpleNamespace(
        name="test-vault",
        habByPre=lambda pre: SimpleNamespace(name="shared-aid") if pre == "AID_SHARED" else None,
    )
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    opened = {}

    class FakeSignal:
        def connect(self, callback):
            opened["finished_callback"] = callback

    class FakeDialog:
        def __init__(self, **kwa):
            opened["kwargs"] = kwa
            self.finished = FakeSignal()

        def open(self):
            opened["opened"] = True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.RotateIdentifierDialog",
        FakeDialog,
    )

    plugin._on_provision_completed("AID_SHARED", [{"eid": "WIT_1"}])

    assert opened == {
        "kwargs": {
            "identifier_alias": "shared-aid",
            "icon_path": ":/assets/material-icons/witness1.svg",
            "app": app,
            "parent": plugin._witness_overview,
            "prepopulate_witnesses": [{"eid": "WIT_1"}],
        },
        "finished_callback": plugin._on_rotation_dialog_finished,
        "opened": True,
    }


def test_kf_plugin_runs_onboarding_as_async_task(qapp, tmp_path, monkeypatch):
    app = FakeApp()
    emitted_events = []
    app.vault.signals = SimpleNamespace(
        emit_doer_event=lambda doer_name, event_type, data: emitted_events.append(
            (doer_name, event_type, data)
        )
    )
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_async_onboarding", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    captured = {"started": False}

    async def fake_onboard_async(self, *, alias, witness_profile_code, account_aid, progress):
        captured["started"] = True
        captured["alias"] = alias
        captured["witness_profile"] = witness_profile_code
        captured["account_aid"] = account_aid
        progress(stage="bootstrap", detail="Loading bootstrap")
        record = self._db.get_account()
        record.account_aid = "AID_ACCOUNT"
        record.account_alias = alias
        record.status = ACCOUNT_STATUS_ONBOARDED
        self._db.pin_account(record)
        await asyncio.sleep(0)
        return SimpleNamespace(
            account_aid="AID_ACCOUNT",
            witness_registration=SimpleNamespace(results=[], batch_mode=True),
        )

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.KFOnboardingService.onboard_async",
        fake_onboard_async,
    )

    try:
        _confirm_onboarding(qapp, plugin, "test-account", "1-of-1", "")
        assert plugin._onboarding_page.phase == "in_progress"

        _drive_async(qapp, lambda: plugin._onboarding_task is None)

        assert captured["started"] is True
        assert captured["alias"] == "test-account"
        assert captured["witness_profile"] == "1-of-1"
        assert captured["account_aid"] == ""
        assert plugin._onboarding_task is None
        assert plugin._onboarding_page.phase == "completed"
        assert emitted_events == [
            (
                "InceptDoer",
                "identifier_created",
                {"alias": "test-account", "pre": "AID_ACCOUNT"},
            )
        ]
    finally:
        db.close()


def test_kf_plugin_ignores_duplicate_onboarding_request(qapp):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    calls = []
    loop = _event_loop()
    plugin._onboarding_task = loop.create_task(asyncio.sleep(60))
    plugin._onboarding_page.begin_run = lambda: calls.append("begin")

    try:
        _confirm_onboarding(qapp, plugin, "test-account", "1-of-1", "")

        assert calls == []
        assert plugin._onboarding_task is not None
    finally:
        plugin._onboarding_task.cancel()
        loop.run_until_complete(asyncio.gather(plugin._onboarding_task, return_exceptions=True))
        plugin._finish_onboarding_run()


def test_kf_plugin_ignores_stale_onboarding_success_after_vault_switch(
        qapp, tmp_path, monkeypatch):
    app = FakeApp(vault_name="first-vault")
    emitted_events = []
    app.vault.signals = SimpleNamespace(
        emit_doer_event=lambda doer_name, event_type, data: emitted_events.append(
            (doer_name, event_type, data)
        )
    )
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    first_db = KFBaser(name="kf_stale_first", headDirPath=str(tmp_path), reopen=True)
    second_db = KFBaser(name="kf_stale_second", headDirPath=str(tmp_path), reopen=True)
    first_db.ensure_account()
    second_db.ensure_account()

    outcome = SimpleNamespace(
        account_aid="AID_STALE",
        witness_registration=SimpleNamespace(results=[], batch_mode=True),
    )

    async def fake_onboard_async(self, *, alias, witness_profile_code, account_aid, progress):
        _ = (alias, witness_profile_code, account_aid, progress)
        app.vault = FakeVault(name="second-vault")
        plugin._db = second_db
        await asyncio.sleep(0)
        return outcome

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.KFOnboardingService.onboard_async",
        fake_onboard_async,
    )

    loop = _event_loop()
    try:
        plugin._db = first_db
        stale_vault = app.vault
        task = loop.create_task(
            plugin._run_onboarding(
                alias="stale-account",
                witness_profile="1-of-1",
                account_aid="",
                db=first_db,
                boot_client=SimpleNamespace(),
                vault=stale_vault,
            )
        )
        plugin._onboarding_task = task
        loop.run_until_complete(task)

        assert emitted_events == []
        assert plugin._onboarding_page.phase != "completed"
        assert plugin._onboarding_task is None
    finally:
        first_db.close()
        second_db.close()


def test_kf_plugin_async_onboarding_failure_does_not_mark_account_onboarded(qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_async_onboarding_failure", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    record, _ = db.ensure_account()
    record.status = ACCOUNT_STATUS_PENDING_ONBOARDING
    db.pin_account(record)

    async def fake_onboard_async(self, *, alias, witness_profile_code, account_aid, progress):
        progress(stage="session_start", detail="starting")
        raise RuntimeError("remote complete failed")

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.onboarding.service.KFOnboardingService.onboard_async",
        fake_onboard_async,
    )

    try:
        _confirm_onboarding(qapp, plugin, "test-account", "1-of-1", "")
        _drive_async(qapp, lambda: plugin._onboarding_task is None)

        updated = db.get_account()
        assert updated is not None
        assert updated.status == ACCOUNT_STATUS_FAILED
        assert updated.status != ACCOUNT_STATUS_ONBOARDED
        assert "remote complete failed" in plugin._onboarding_page._progress_error
    finally:
        db.close()


def test_kf_plugin_cancels_active_onboarding_task_on_vault_close(qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_close_cancels_task", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    loop = _event_loop()
    task = loop.create_task(asyncio.sleep(60))
    plugin._onboarding_task = task

    try:
        plugin.on_vault_closed(app.vault)
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))

        assert task.cancelled()
        assert plugin._onboarding_task is None
        assert plugin._db is None
    finally:
        db.close()


def test_kf_plugin_prepare_vault_deletion_aborts_when_onboarding_task_active(
        qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_delete_refuses_active_task", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    loop = _event_loop()
    task = loop.create_task(asyncio.sleep(60))
    plugin._onboarding_task = task

    try:
        with pytest.raises(KFBootError, match="could not stop promptly"):
            plugin.prepare_vault_deletion(app.vault)

        assert plugin._db is db
        assert task.cancelled()
        assert plugin._onboarding_task is None
    finally:
        db.close()


def test_kf_plugin_prepare_vault_deletion_aborts_when_page_shutdown_fails(
        qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_delete_refuses_page_shutdown_failure", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()
    plugin._onboarding_page.shutdown = lambda: False

    try:
        with pytest.raises(KFBootError, match="background work"):
            plugin.prepare_vault_deletion(app.vault)

        assert plugin._db is db
    finally:
        db.close()


def test_kf_plugin_vault_close_detaches_state_when_onboarding_task_active(
        qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_close_detaches_active_task", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    loop = _event_loop()
    task = loop.create_task(asyncio.sleep(60))
    plugin._onboarding_task = task

    try:
        plugin.on_vault_closed(app.vault)
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))

        assert plugin._db is None
        assert plugin._onboarding_page._db is None
        assert plugin._witness_overview._db is None
        assert plugin._watcher_list._db is None
        assert task.cancelled()
    finally:
        if not task.done():
            task.cancel()
            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))


def test_kf_plugin_defers_db_close_until_witness_cleanup_finishes(qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_close_defers_witness_cleanup", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._witness_provision.set_db(db)
    db.ensure_account()

    loop = _event_loop()
    release_cleanup = asyncio.Event()

    async def cleanup_task():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await release_cleanup.wait()
            raise

    task = loop.create_task(cleanup_task())
    loop.run_until_complete(asyncio.sleep(0))
    plugin._witness_provision._provision_task = task

    async def close_and_release():
        plugin.on_vault_closed(app.vault)
        await asyncio.sleep(0)

        assert plugin._db is None
        assert db.opened is True
        assert task.done() is False
        assert len(plugin._deferred_db_close_tasks) == 1
        close_task = next(iter(plugin._deferred_db_close_tasks))
        assert close_task.done() is False

        release_cleanup.set()
        await asyncio.gather(task, return_exceptions=True)
        await close_task
        await asyncio.sleep(0)

        assert db.opened is False
        assert plugin._deferred_db_close_tasks == set()

    try:
        loop.run_until_complete(close_and_release())
    finally:
        if not task.done():
            task.cancel()
            release_cleanup.set()
            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        if db.opened:
            db.close()


def test_kf_plugin_failure_preserves_resumable_session_state(qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_failure_preserved", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db

    record, _ = db.ensure_account()
    record.account_alias = "test-account"
    record.onboarding_session_id = "SESSION_1"
    record.onboarding_auth_alias = "kf-auth-alias"
    db.pin_account(record)

    messages = []
    plugin._onboarding_page.fail_run = lambda message: messages.append(message)

    try:
        plugin._handle_onboarding_failure("test-account", "boom")

        updated = db.get_account()
        assert updated is not None
        assert updated.status == ACCOUNT_STATUS_FAILED
        assert updated.onboarding_session_id == "SESSION_1"
        assert updated.onboarding_auth_alias == "kf-auth-alias"
        assert messages == [
            "Onboarding failed: boom\n\n"
            "Local progress was preserved. Start onboarding again to resume the saved session."
        ]
    finally:
        db.close()


def test_kf_plugin_failure_marks_non_resumable_run_as_abandoned(qapp, tmp_path):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_failure_abandoned", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db

    record, _ = db.ensure_account()
    record.account_alias = "test-account"
    record.status = ACCOUNT_STATUS_PENDING_ONBOARDING
    db.pin_account(record)

    messages = []
    plugin._onboarding_page.fail_run = lambda message: messages.append(message)

    try:
        plugin._handle_onboarding_failure("test-account", "boom")

        updated = db.get_account()
        assert updated is not None
        assert updated.status == ACCOUNT_STATUS_FAILED
        assert updated.onboarding_session_id == ""
        assert updated.onboarding_auth_alias == ""
        assert messages == [
            "Onboarding failed: boom\n\n"
            "This onboarding attempt was abandoned. Start again to continue."
        ]
    finally:
        db.close()
