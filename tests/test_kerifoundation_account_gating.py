import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QThread, Signal

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

        page_key, should_push_menu = plugin.get_setup_page(app.vault)
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

        page_key, should_push_menu = plugin.get_setup_page(app.vault)
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


def test_kf_plugin_runs_onboarding_in_background_thread(qapp, tmp_path, monkeypatch):
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

    captured = {"threaded": False, "started": False}

    class FakeWorker(QObject):
        progress = Signal(object)
        succeeded = Signal(str, object)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, *, app, db, boot_client, alias, witness_profile, account_aid):
            super().__init__()
            captured["alias"] = alias
            captured["witness_profile"] = witness_profile
            captured["account_aid"] = account_aid

        def run(self):
            captured["started"] = True
            captured["threaded"] = QThread.currentThread() is not qapp.thread()
            self.progress.emit({"stage": "bootstrap", "detail": "Loading bootstrap"})
            record = plugin._db.get_account()
            record.account_aid = "AID_ACCOUNT"
            record.account_alias = "test-account"
            record.status = ACCOUNT_STATUS_ONBOARDED
            plugin._db.pin_account(record)
            outcome = SimpleNamespace(
                account_aid="AID_ACCOUNT",
                witness_registration=SimpleNamespace(results=[], batch_mode=True),
            )
            self.succeeded.emit("test-account", outcome)
            self.finished.emit()

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin._OnboardingWorker",
        FakeWorker,
    )

    try:
        plugin._on_onboarding_confirm("test-account", "1-of-1", "")
        assert plugin._onboarding_page.phase == "in_progress"

        deadline = time.monotonic() + 1.0
        while plugin._onboarding_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert captured["started"] is True
        assert captured["threaded"] is True
        assert captured["alias"] == "test-account"
        assert captured["witness_profile"] == "1-of-1"
        assert captured["account_aid"] == ""
        assert plugin._onboarding_thread is None
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
    plugin._onboarding_thread = object()
    plugin._onboarding_page.begin_run = lambda: calls.append("begin")

    plugin._on_onboarding_confirm("test-account", "1-of-1", "")

    assert calls == []
    assert plugin._onboarding_thread is not None


def test_kf_plugin_waits_for_active_onboarding_worker_on_vault_close(qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    db = KFBaser(name="kf_close_waits_for_worker", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    cancel_seen = threading.Event()
    release_worker = threading.Event()

    class FakeWorker(QObject):
        progress = Signal(object)
        succeeded = Signal(str, object)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, *, app, db, boot_client, alias, witness_profile, account_aid):
            super().__init__()
            _ = (app, db, boot_client, alias, witness_profile, account_aid)

        def request_cancel(self):
            cancel_seen.set()
            release_worker.set()

        def run(self):
            release_worker.wait(timeout=0.5)
            self.finished.emit()

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin._OnboardingWorker",
        FakeWorker,
    )

    try:
        plugin._on_onboarding_confirm("test-account", "1-of-1", "")
        deadline = time.monotonic() + 1.0
        while plugin._onboarding_thread is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert plugin._onboarding_thread is not None

        plugin.on_vault_closed(app.vault)

        assert cancel_seen.is_set()
        assert plugin._onboarding_thread is None
        assert plugin._onboarding_worker is None
        assert plugin._db is None
    finally:
        db.close()


def test_kf_plugin_prepare_vault_deletion_aborts_when_onboarding_worker_does_not_stop(
        qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)
    plugin.ONBOARDING_SHUTDOWN_TIMEOUT_MS = 10

    db = KFBaser(name="kf_delete_refuses_stuck_worker", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    cancel_seen = threading.Event()
    worker_started = threading.Event()
    release_worker = threading.Event()

    class FakeWorker(QObject):
        progress = Signal(object)
        succeeded = Signal(str, object)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, *, app, db, boot_client, alias, witness_profile, account_aid):
            super().__init__()
            _ = (app, db, boot_client, alias, witness_profile, account_aid)

        def request_cancel(self):
            cancel_seen.set()

        def run(self):
            worker_started.set()
            release_worker.wait()
            self.finished.emit()

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin._OnboardingWorker",
        FakeWorker,
    )

    try:
        plugin._on_onboarding_confirm("test-account", "1-of-1", "")
        deadline = time.monotonic() + 1.0
        while not worker_started.is_set() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert worker_started.is_set()

        with pytest.raises(KFBootError, match="could not stop promptly"):
            plugin.prepare_vault_deletion(app.vault)

        assert cancel_seen.is_set()
        assert plugin._db is db
        assert plugin._onboarding_thread is not None
    finally:
        release_worker.set()
        deadline = time.monotonic() + 1.0
        while plugin._onboarding_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        if plugin._onboarding_thread is not None:
            plugin._onboarding_thread.quit()
            plugin._onboarding_thread.wait(1000)
            plugin._finish_onboarding_run()
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


def test_kf_plugin_vault_close_detaches_state_when_onboarding_worker_does_not_stop(
        qapp, tmp_path, monkeypatch):
    app = FakeApp()
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)
    plugin.ONBOARDING_SHUTDOWN_TIMEOUT_MS = 10

    db = KFBaser(name="kf_close_detaches_stuck_worker", headDirPath=str(tmp_path), reopen=True)
    plugin._db = db
    plugin._onboarding_page.set_db(db)
    db.ensure_account()

    worker_started = threading.Event()
    release_worker = threading.Event()

    class FakeWorker(QObject):
        progress = Signal(object)
        succeeded = Signal(str, object)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, *, app, db, boot_client, alias, witness_profile, account_aid):
            super().__init__()
            _ = (app, db, boot_client, alias, witness_profile, account_aid)

        def request_cancel(self):
            pass

        def run(self):
            worker_started.set()
            release_worker.wait()
            self.finished.emit()

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin._OnboardingWorker",
        FakeWorker,
    )

    try:
        plugin._on_onboarding_confirm("test-account", "1-of-1", "")
        deadline = time.monotonic() + 1.0
        while not worker_started.is_set() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert worker_started.is_set()

        plugin.on_vault_closed(app.vault)

        assert plugin._db is None
        assert plugin._onboarding_page._db is None
        assert plugin._witness_overview._db is None
        assert plugin._watcher_list._db is None
    finally:
        release_worker.set()
        deadline = time.monotonic() + 1.0
        while plugin._onboarding_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        if plugin._onboarding_thread is not None:
            plugin._onboarding_thread.quit()
            plugin._onboarding_thread.wait(1000)
            plugin._finish_onboarding_run()


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
