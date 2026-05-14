# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.plugin module

KERI Foundation plugin — account-gated witness and watcher flows for
Locksmith users.
"""
from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QDialog
from PySide6.QtCore import Qt, QEvent, QObject
from keri import help

from locksmith.plugins.base import AccountProviderPlugin, PluginBase, WitnessProviderPlugin
from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_FAILED,
    ACCOUNT_STATUS_ONBOARDED,
    KFBaser,
    KFAccountRecord,
)
from locksmith.plugins.kerifoundation.onboarding.page import KFOnboardingPage
from locksmith.plugins.kerifoundation.onboarding.service import (
    KFBootClient,
    KFBootError,
    KFOnboardingService,
    KFVaultDeletionService,
)
from locksmith.ui.vault.menu import MenuButton, MenuSpacer
from locksmith.ui.vault.identifiers.rotate import RotateIdentifierDialog
from locksmith.ui.toolkit.widgets.buttons import BackButton

from locksmith.plugins.kerifoundation.identifiers.list import IdentifierListPage
from locksmith.plugins.kerifoundation.witnesses.list import WitnessOverviewPage
from locksmith.plugins.kerifoundation.witnesses.provision import WitnessProvisionPage
from locksmith.plugins.kerifoundation.watchers.list import WatcherListPage
from locksmith.plugins.kerifoundation.watchers.register import WatcherRegisterPage

logger = help.ogler.getLogger(__name__)


class KeriFoundationPlugin(PluginBase, WitnessProviderPlugin, AccountProviderPlugin):
    """KERI Foundation witness/watcher provider plugin.

    Entry is gated by a plugin-local account record. Until the record
    reaches the onboarded state, the plugin stays on the onboarding
    shell page and does not expose the normal witness/watcher menu.
    """

    ONBOARDING_SHUTDOWN_TIMEOUT_MS = 2000

    @property
    def plugin_id(self) -> str:
        return "kerifoundation"

    def initialize(self, app: Any) -> None:
        self._app = app
        self._db = None
        self._wit_btn = None
        self._id_btn = None
        self._wat_btn = None
        self._boot_client = KFBootClient(app)
        self._onboarding_task: asyncio.Task | None = None
        self._deferred_db_close_tasks: set[asyncio.Task] = set()
        self._closing_vault = False

        # Build pages
        self._onboarding_page = KFOnboardingPage(app)
        self._onboarding_page.set_boot_client(self._boot_client)
        self._witness_overview = WitnessOverviewPage(app)
        self._identifiers_page = IdentifierListPage(app)
        self._witness_provision = WitnessProvisionPage(app)
        self._watcher_list = WatcherListPage(app)
        self._watcher_register = WatcherRegisterPage(app)

        # Wire internal signals
        self._wire_internal_signals()

        logger.info("KeriFoundationPlugin initialized")

    def _wire_internal_signals(self):
        """Connect page signals for navigation."""
        self._onboarding_page.confirm_requested.connect(self._on_onboarding_confirm)
        self._onboarding_page.open_account_requested.connect(self._show_witnesses)

        self._witness_overview.add_witnesses_requested.connect(self._show_identifiers)
        self._identifiers_page.add_witnesses_requested.connect(self._on_add_witnesses)
        self._witness_provision.completed.connect(self._on_provision_completed)
        self._witness_provision.cancelled.connect(self._on_provision_cancelled)

    def _on_add_witnesses(self, hab_pre):
        """Navigate to the provision page for a specific identifier."""
        if not self._has_onboarded_account():
            self._show_onboarding(
                reason="witness provisioning blocked until the local KF account is onboarded"
            )
            return

        self._witness_provision.set_identifier(hab_pre)
        self._navigate("kf_provision")
        self._witness_provision.on_show()

    def _on_provision_completed(self, hab_pre: str, created_witnesses: list[dict]):
        """Open rotation for the selected identifier after successful provisioning."""
        hab = self._app.vault.hby.habByPre(hab_pre) if self._app and self._app.vault else None
        if hab is None:
            self._show_witnesses()
            return

        dialog = RotateIdentifierDialog(
            identifier_alias=hab.name,
            icon_path=":/assets/material-icons/witness1.svg",
            app=self._app,
            parent=self._witness_overview,
            prepopulate_witnesses=created_witnesses,
        )
        dialog.finished.connect(self._on_rotation_dialog_finished)
        dialog.open()

    def _on_provision_cancelled(self):
        """Return to witness overview on cancel."""
        self._show_witnesses()

    def _on_rotation_dialog_finished(self, result):
        if result == QDialog.DialogCode.Accepted:
            self._show_witnesses()

    def _set_active_nav(self, active_btn):
        """Highlight the active nav button and deactivate the others."""
        for btn in (self._wit_btn, self._id_btn, self._wat_btn):
            if btn is not None:
                btn.set_active(btn is active_btn)

    def _navigate(self, page_key):
        """Show a page by its key via the VaultPage."""
        vault_page = getattr(self._app, "_vault_page", None)
        if vault_page is not None:
            vault_page._show_page(page_key)

    def on_vault_opened(self, vault: Any) -> None:
        self._closing_vault = False
        self._db = KFBaser(name=f"kf_{vault.hby.name}", reopen=True)
        self._boot_client.set_boot_server_aid("")
        self._onboarding_page.set_db(self._db)
        self._onboarding_page.set_boot_client(self._boot_client)
        self._witness_overview.set_db(self._db)
        self._identifiers_page.set_db(self._db)
        self._witness_provision.set_db(self._db)
        self._watcher_list.set_db(self._db)
        self._watcher_list.set_boot_client(self._boot_client)
        self._watcher_register.set_db(self._db)
        self._sync_boot_client_destination()
        logger.info(f"KF plugin DB opened for vault '{vault.hby.name}'")

    def prepare_vault_deletion(self, vault: Any) -> None:
        if self._db is None:
            return

        self._shutdown_background_work(require_onboarding_stopped=True)
        service = KFVaultDeletionService(
            app=self._app,
            db=self._db,
            boot_client=self._boot_client.clone(),
        )
        service.delete_vault_account()

    def on_vault_closed(self, vault: Any, *, clear: bool = False) -> None:
        self._closing_vault = True
        stopped = self._shutdown_background_work(require_onboarding_stopped=False)
        stateful_tasks = self._stateful_shutdown_tasks()
        db = self._db
        self._db = None
        self._onboarding_page.set_db(None)
        self._onboarding_page.set_boot_client(None)
        self._witness_overview.set_db(None)
        self._identifiers_page.set_db(None)
        self._witness_provision.set_db(None)
        self._watcher_list.set_db(None)
        self._watcher_list.set_boot_client(None)
        self._watcher_register.set_db(None)
        self._boot_client.set_boot_server_aid("")
        if db is not None:
            if stopped or not stateful_tasks:
                db.close(clear=clear)
            else:
                self._defer_db_close_until_tasks_finish(db, clear=clear, tasks=stateful_tasks)
        logger.info("KF plugin DB closed")

    def _shutdown_background_work(self, *, require_onboarding_stopped: bool) -> bool:
        stopped = True
        if not self._shutdown_onboarding_task():
            message = (
                "KF onboarding is still active and could not stop promptly. "
                "Try vault deletion again after onboarding finishes or times out."
            )
            if require_onboarding_stopped:
                raise KFBootError(message)
            logger.warning(message)
            stopped = False

        for page in (self._onboarding_page, self._witness_overview, self._witness_provision, self._watcher_list):
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                if shutdown() is False:
                    stopped = False

        if require_onboarding_stopped and not stopped:
            raise KFBootError(
                "KF background work is still active and could not stop promptly. "
                "Try vault deletion again after background work finishes or times out."
            )
        return stopped

    def _shutdown_onboarding_task(self) -> bool:
        task = self._onboarding_task
        if task is None:
            return True
        if task.done():
            self._finish_onboarding_run()
            return True

        logger.info("Cancelling active KF onboarding task before closing vault")
        task.cancel()
        loop = task.get_loop()
        if not loop.is_running():
            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        if task.done() and task is self._onboarding_task:
            self._finish_onboarding_run()
        return False

    def _stateful_shutdown_tasks(self) -> list[asyncio.Task]:
        tasks = []
        for task in (
            self._onboarding_task,
            getattr(self._witness_provision, "_provision_task", None),
        ):
            if task is not None and not task.done():
                tasks.append(task)
        return tasks

    def _defer_db_close_until_tasks_finish(self, db, *, clear: bool, tasks: list[asyncio.Task]) -> None:
        async def close_when_done():
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                        logger.warning(
                            "KF cleanup task failed before deferred DB close",
                            exc_info=(type(result), result, result.__traceback__),
                        )
            finally:
                db.close(clear=clear)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            db.close(clear=clear)
            return

        task = loop.create_task(close_when_done())
        self._deferred_db_close_tasks.add(task)
        task.add_done_callback(self._finish_deferred_db_close_task)

    def _finish_deferred_db_close_task(self, task: asyncio.Task) -> None:
        self._deferred_db_close_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("Deferred KF DB close task failed", exc_info=True)

    def is_setup_complete(self, vault: Any) -> bool:
        record = self._get_account_record()
        setup_complete = record is not None and record.status == ACCOUNT_STATUS_ONBOARDED
        chosen_destination = "kf_witnesses" if setup_complete else "kf_onboarding"
        logger.info(
            f"KF plugin entry decision for vault '{self._vault_name(vault)}': "
            f"account_lookup={self._describe_account_record(record)} "
            f"setup_complete={setup_complete} "
            f"chosen_destination='{chosen_destination}'"
        )
        return setup_complete

    def get_setup_page(self, vault: Any) -> tuple[str, bool]:
        record = self._get_account_record()
        if record is None and self._db is not None:
            record, created = self._db.ensure_account()
            if created:
                logger.info(
                    f"KF account status transition for vault '{self._vault_name(vault)}': "
                    f"missing -> '{record.status}' "
                    f"account_lookup={self._describe_account_record(record)}"
                )

        page_key = "kf_onboarding"
        should_push_menu = True
        if record is not None and record.status == ACCOUNT_STATUS_ONBOARDED:
            page_key = "kf_witnesses"

        if page_key == "kf_onboarding":
            self._set_active_nav(None)
            self._onboarding_page.on_show()

        logger.info(
            f"KF plugin gated destination for vault '{self._vault_name(vault)}': "
            f"page='{page_key}' push_menu={should_push_menu} "
            f"account_lookup={self._describe_account_record(record)}"
        )
        return page_key, should_push_menu

    def get_menu_entry(self) -> MenuButton:
        icon = QIcon(":/assets/custom/SymbolLogo.svg")
        return MenuButton(icon=icon, label="KERI Foundation")

    def get_menu_section(self) -> list[QWidget]:
        items = []

        # Back button
        back = BackButton(dark_mode=False)
        items.append(back)

        # Logo + label (clickable → navigate to default page)
        logo_widget = self._build_logo_widget()
        logo_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logo_click_filter = self._make_logo_click_filter()
        logo_widget.installEventFilter(self._logo_click_filter)
        items.append(logo_widget)

        # Spacer
        items.append(MenuSpacer(15))

        self._id_btn = MenuButton(
            icon=QIcon(":/assets/custom/identifiers.png"),
            label="Identifiers",
        )
        self._id_btn.clicked.connect(self._show_identifiers)
        items.append(self._id_btn)

        # Witnesses nav button
        self._wit_btn = MenuButton(
            icon=QIcon(":/assets/material-icons/witness1.svg"),
            label="Witnesses",
        )
        self._wit_btn.clicked.connect(self._show_witnesses)
        items.append(self._wit_btn)

        # Watchers nav button
        self._wat_btn = MenuButton(
            icon=QIcon(":/assets/material-icons/watcher.svg"),
            label="Watchers",
        )
        self._wat_btn.clicked.connect(self._show_watchers)
        items.append(self._wat_btn)

        return items

    def _make_logo_click_filter(self):
        """Create a QObject event filter for the clickable logo."""
        plugin = self

        class _LogoClickFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.MouseButtonRelease:
                    plugin._show_default_page()
                    return True
                return False

        return _LogoClickFilter()

    def get_pages(self) -> dict[str, QWidget]:
        return {
            "kf_onboarding": self._onboarding_page,
            "kf_witnesses": self._witness_overview,
            "kf_identifiers": self._identifiers_page,
            "kf_provision": self._witness_provision,
            "kf_watchers": self._watcher_list,
            "kf_watcher_register": self._watcher_register,
        }

    def get_witness_batches(self, vault: Any, hab_pre: str) -> Any | None:
        """Return batch groupings for KF witnesses belonging to this hab."""
        if not self._db:
            return None

        batches = self._db.witBatches.get(keys=(hab_pre,))
        if batches and batches.batches:
            return batches
        return None

    def get_witness_state(self, vault: Any, wit_eid: str) -> Any | None:
        if not self._db:
            return None
        for (_, eid), record in self._db.witnesses.getTopItemIter(keys=()):
            if eid == wit_eid:
                return record
        return None

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _on_onboarding_confirm(self, alias: str, witness_profile: str, account_aid: str):
        if self._closing_vault:
            logger.warning("Ignoring KF onboarding request while the vault is closing")
            return

        if self._onboarding_task is not None and not self._onboarding_task.done():
            logger.warning("Ignoring duplicate KF onboarding request while a run is already active")
            return

        if self._db is None:
            self._onboarding_page.fail_run("Onboarding failed: KF account database is not available.")
            return

        logger.info(
            "KF onboarding started for alias='%s' witness_profile='%s' account_aid='%s'",
            alias,
            witness_profile,
            account_aid or "create_new",
        )
        self._sync_boot_client_destination()
        self._onboarding_page.begin_run()

        self._onboarding_task = asyncio.create_task(self._run_onboarding(
            alias=alias,
            witness_profile=witness_profile,
            account_aid=account_aid,
            db=self._db,
            boot_client=self._boot_client.clone(),
            vault=getattr(self._app, "vault", None),
        ))

    async def _run_onboarding(
        self,
        *,
        alias: str,
        witness_profile: str,
        account_aid: str,
        db,
        boot_client,
        vault,
    ):
        task = asyncio.current_task()
        service = KFOnboardingService(app=self._app, db=db, boot_client=boot_client)

        def progress(**kwa):
            if self._is_current_onboarding_task(task, vault=vault, db=db):
                self._handle_onboarding_progress(dict(kwa))

        try:
            outcome = await service.onboard_async(
                alias=alias,
                witness_profile_code=witness_profile,
                account_aid=account_aid,
                progress=progress,
            )
        except asyncio.CancelledError:
            logger.info("KF onboarding task cancelled for alias='%s'", alias)
            raise
        except Exception as ex:
            logger.exception("KF onboarding failed")
            if self._is_current_onboarding_task(task, vault=vault, db=db):
                self._handle_onboarding_failure(alias, str(ex))
        else:
            if self._is_current_onboarding_task(task, vault=vault, db=db):
                self._handle_onboarding_success(alias, outcome)
        finally:
            if task is self._onboarding_task:
                self._finish_onboarding_run()

    def _is_current_onboarding_task(self, task, *, vault, db) -> bool:
        if self._closing_vault:
            return False
        if task is not self._onboarding_task:
            return False
        if db is not self._db:
            return False
        if vault is not getattr(self._app, "vault", None):
            return False
        return True

    def _handle_onboarding_progress(self, kwa: dict):
        if self._closing_vault:
            return

        detail = kwa.get("detail", "")
        logger.info("KF onboarding progress: %s", detail)
        self._onboarding_page.update_run(
            stage=kwa.get("stage", ""),
            detail=detail,
            boot_verified=bool(kwa.get("boot_verified", False)),
            completed=bool(kwa.get("completed", False)),
        )

    def _handle_onboarding_success(self, alias: str, outcome):
        if self._closing_vault:
            return

        self._sync_boot_client_destination()
        self._onboarding_page.complete_run(
            account_aid=outcome.account_aid,
            results=outcome.witness_registration.results,
            batch_mode=outcome.witness_registration.batch_mode,
        )
        self._emit_identifier_created(alias=alias, pre=outcome.account_aid)
        logger.info(
            "KF onboarding completed for alias='%s' account_aid='%s'",
            alias,
            outcome.account_aid,
        )

    def _handle_onboarding_failure(self, alias: str, message: str):
        if self._closing_vault:
            return

        record = self._get_account_record()
        preserved_session = bool(
            record is not None and record.onboarding_session_id and record.onboarding_auth_alias
        )
        if record is not None:
            record.status = ACCOUNT_STATUS_FAILED
            self._db.pin_account(record)
        follow_up = (
            "Local progress was preserved. Start onboarding again to resume the saved session."
            if preserved_session
            else "This onboarding attempt was abandoned. Start again to continue."
        )
        self._onboarding_page.fail_run(
            f"Onboarding failed: {message}\n\n{follow_up}"
        )
        logger.error("KF onboarding failed for alias='%s': %s", alias, message)

    def _finish_onboarding_run(self):
        self._onboarding_task = None

    def _emit_identifier_created(self, *, alias: str, pre: str) -> None:
        vault = getattr(self._app, "vault", None)
        signals = getattr(vault, "signals", None)
        if signals is None or not pre:
            return

        signals.emit_doer_event(
            "InceptDoer",
            "identifier_created",
            {"alias": alias, "pre": pre},
        )

    def _show_default_page(self):
        if self._has_onboarded_account():
            self._show_witnesses()
            return

        self._show_onboarding(reason="default plugin landing blocked by local KF account status")

    def _show_onboarding(self, reason: str):
        logger.info(
            f"KF plugin gated destination: page='kf_onboarding' "
            f"reason='{reason}' account_lookup={self._describe_account_record(self._get_account_record())}"
        )
        self._navigate("kf_onboarding")
        self._onboarding_page.on_show()
        self._set_active_nav(None)

    def _show_witnesses(self, checked=False):
        if not self._has_onboarded_account():
            self._show_onboarding(reason="witness navigation blocked by local KF account status")
            return

        logger.info(
            f"KF plugin gated destination: page='kf_witnesses' "
            f"account_lookup={self._describe_account_record(self._get_account_record())}"
        )
        self._navigate("kf_witnesses")
        self._witness_overview.on_show()
        self._set_active_nav(self._wit_btn)

    def _show_identifiers(self, checked=False):
        if not self._has_onboarded_account():
            self._show_onboarding(reason="identifier navigation blocked by local KF account status")
            return

        logger.info(
            f"KF plugin gated destination: page='kf_identifiers' "
            f"account_lookup={self._describe_account_record(self._get_account_record())}"
        )
        self._navigate("kf_identifiers")
        self._identifiers_page.on_show()
        self._set_active_nav(self._id_btn)

    def _show_watchers(self, checked=False):
        if not self._has_onboarded_account():
            self._show_onboarding(reason="watcher navigation blocked by local KF account status")
            return

        logger.info(
            f"KF plugin gated destination: page='kf_watchers' "
            f"account_lookup={self._describe_account_record(self._get_account_record())}"
        )
        self._navigate("kf_watchers")
        self._watcher_list.on_show()
        self._set_active_nav(self._wat_btn)

    def _has_onboarded_account(self) -> bool:
        record = self._get_account_record()
        return record is not None and record.status == ACCOUNT_STATUS_ONBOARDED

    def _get_account_record(self) -> KFAccountRecord | None:
        if self._db is None:
            return None
        return self._db.get_account()

    def _sync_boot_client_destination(self):
        record = self._get_account_record()
        self._boot_client.set_boot_server_aid(
            record.boot_server_aid if record is not None else ""
        )

    @staticmethod
    def _vault_name(vault: Any) -> str:
        hby = getattr(vault, "hby", None)
        return getattr(hby, "name", "unknown")

    @staticmethod
    def _describe_account_record(record: KFAccountRecord | None) -> str:
        if record is None:
            return "missing"

        return (
            f"status='{record.status}' "
            f"account_aid='{record.account_aid or '-'}' "
            f"account_alias='{record.account_alias or '-'}' "
            f"witness_profile_code='{record.witness_profile_code or '-'}' "
            f"region_id='{record.region_id or '-'}'"
        )

    def _build_logo_widget(self):
        """Build a small logo + text widget for the plugin submenu header."""
        widget = QWidget()
        widget.setFixedHeight(72)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        icon_label = QLabel()
        pixmap = QPixmap(":/assets/custom/SymbolLogo.svg")
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap.scaled(
                40, 40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_label = QLabel("KERI Foundation")
        text_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #333;")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label)

        return widget
