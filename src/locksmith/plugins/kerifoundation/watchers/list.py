# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.watchers.list module

Boot-backed watcher list for the single onboarded KF account.
"""
from __future__ import annotations

import asyncio

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QLabel
from keri import help

from locksmith.plugins.kerifoundation.db.basing import ACCOUNT_STATUS_ONBOARDED
from locksmith.ui import colors
from locksmith.ui.toolkit.tables.paginated import PaginatedTableWidget

logger = help.ogler.getLogger(__name__)


class MissingAccountIdentifierError(RuntimeError):
    """Raised when the persisted KF account AID is not present in the local wallet."""

    def __init__(self, account_aid: str):
        super().__init__(account_aid)
        self.account_aid = account_aid


def _shrink_empty_state_title(table: PaginatedTableWidget, font_size: int = 20):
    """Reduce the plugin empty-state title size without changing shared table code."""
    target_text = f"NO {table.title.upper()}"
    for label in table.empty_state.findChildren(QLabel):
        if label.text() != target_text:
            continue
        label.setStyleSheet(
            label.styleSheet().replace("font-size: 24px;", f"font-size: {font_size}px;")
        )
        break


class WatcherListPage(QWidget):
    """Shows hosted watcher rows for the permanent KF account AID."""

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self._app = app
        self._db = None
        self._boot_client = None
        self._refresh_task: asyncio.Task | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

    def set_app(self, app):
        self._app = app

    def set_db(self, db):
        if db is not self._db:
            self.shutdown()
        self._db = db

    def set_boot_client(self, boot_client):
        if boot_client is not self._boot_client:
            self.shutdown()
        self._boot_client = boot_client

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        self._error_label.setStyleSheet(
            f"font-size: 13px; color: {colors.DANGER}; padding: 8px 16px;"
        )
        layout.addWidget(self._error_label)

        self._table = PaginatedTableWidget(
            columns=["Name", "Watcher AID", "Region", "Status", "Endpoint"],
            title="KERI Foundation Watchers",
            icon_path=":/assets/material-icons/watcher.svg",
            show_search=True,
            show_add_button=False,
            items_per_page=10,
            monospace_columns=["Watcher AID"],
        )
        _shrink_empty_state_title(self._table)
        self._table.set_static_data([])
        layout.addWidget(self._table)

    def on_show(self):
        if not self._app or not self._db or not self._boot_client:
            self._clear_load_error()
            self._table.set_static_data([])
            return

        if self._refresh_task is not None and not self._refresh_task.done():
            return

        self._refresh_task = asyncio.create_task(
            self._refresh_rows_async(
                db=self._db,
                boot_client=self._boot_client,
                vault=getattr(self._app, "vault", None),
            )
        )

    async def _refresh_rows_async(self, *, db, boot_client, vault):
        task = asyncio.current_task()
        try:
            record, hab = self._load_account_context(db=db, vault=vault)
            if record is None:
                rows = []
            else:
                watchers = await asyncio.to_thread(
                    boot_client.list_account_watchers,
                    hab,
                    account_aid=record.account_aid,
                    destination=record.boot_server_aid,
                )
                rows = self._watcher_rows(watchers)
        except asyncio.CancelledError:
            raise
        except MissingAccountIdentifierError as exc:
            if task is not self._refresh_task or db is not self._db or boot_client is not self._boot_client:
                return
            message = (
                f"The KF account AID {exc.account_aid} is missing from this local wallet. "
                "Restore that identifier or complete KF onboarding again before checking hosted watchers."
            )
            logger.warning("%s", message)
            self._table.set_static_data([])
            self._show_load_error(message)
            self._table.load_error.emit(message)
        except Exception as exc:
            if task is not self._refresh_task or db is not self._db or boot_client is not self._boot_client:
                return
            logger.exception("Failed loading boot-backed KF watcher rows")
            detail = str(exc).strip()
            message = "Could not load hosted watchers for this KF account."
            if detail:
                message += f" {detail}"
            message = (
                f"{message} Reopen the Watchers page to retry after the KF account "
                "service is reachable."
            )
            self._show_load_error(message)
            self._table.load_error.emit(message)
        else:
            if (
                task is not self._refresh_task
                or db is not self._db
                or boot_client is not self._boot_client
                or vault is not getattr(self._app, "vault", None)
            ):
                return
            self._clear_load_error()
            self._table.set_static_data(rows)
        finally:
            if task is self._refresh_task:
                self._refresh_task = None

    def shutdown(self):
        task = self._refresh_task
        if task is not None and not task.done():
            task.cancel()
            loop = task.get_loop()
            if not loop.is_running():
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
            return False
        self._refresh_task = None
        return True

    def _load_account_context(self, *, db=None, vault=None):
        db = db if db is not None else self._db
        vault = vault if vault is not None else getattr(self._app, "vault", None)

        record = db.get_account() if db else None
        if record is None or record.status != ACCOUNT_STATUS_ONBOARDED or not record.account_aid:
            return None, None

        hab = vault.hby.habByPre(record.account_aid) if vault else None
        if hab is None:
            raise MissingAccountIdentifierError(record.account_aid)
        return record, hab

    @staticmethod
    def _watcher_rows(watchers):
        rows = []
        for watcher in watchers:
            rows.append(
                {
                    "Name": watcher.name or f"KF Watcher {watcher.eid[:12]}",
                    "Watcher AID": watcher.eid,
                    "Region": watcher.region_name or watcher.region_id or "—",
                    "Status": watcher.status or "Ready",
                    "Endpoint": watcher.url or "—",
                }
            )
        return rows

    def _show_load_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _clear_load_error(self) -> None:
        self._error_label.clear()
        self._error_label.setVisible(False)
