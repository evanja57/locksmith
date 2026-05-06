# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.witnesses.list module

Provider-local witness list for the KF account and attached identifiers.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget, QLabel
from keri import help

from locksmith.ui import colors
from locksmith.ui.toolkit.tables.paginated import PaginatedTableWidget

logger = help.ogler.getLogger(__name__)


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


class WitnessOverviewPage(QWidget):
    """Shows witnesses provisioned through this provider."""

    add_witnesses_requested = Signal()

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self._app = app
        self._db = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

    def set_app(self, app):
        self._app = app

    def set_db(self, db):
        self._db = db
        if db is None:
            self._table.set_static_data([])

    def shutdown(self) -> bool:
        self._table.set_static_data([])
        return True

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = PaginatedTableWidget(
            columns=["Identifier", "Name", "Witness AID", "Auth", "Endpoint"],
            title="KERI Foundation Witnesses",
            icon_path=":/assets/material-icons/witness1.svg",
            show_search=True,
            show_add_button=True,
            add_button_text="Add Witnesses",
            items_per_page=10,
            row_actions=[],
            row_actions_callback=self._get_row_actions,
            monospace_columns=["Witness AID"],
        )
        _shrink_empty_state_title(self._table)
        self._table.add_clicked.connect(self._on_add_witnesses_clicked)
        self._table.row_action_triggered.connect(self._on_row_action)
        layout.addWidget(self._table)

    def on_show(self):
        if not self._app or not self._db or not getattr(self._app, "vault", None):
            self._table.set_static_data([])
            return
        self._table.set_static_data(self._build_rows())

    def _build_rows(self):
        rows = []
        account_record = self._db.get_account() if self._db else None
        account_aid = getattr(account_record, "account_aid", "")
        attached_prefixes = set(self._db.list_attached_identifier_prefixes()) if self._db else set()
        hby = self._app.vault.hby
        org = self._app.vault.org

        for (hab_pre, eid), record in self._db.witnesses.getTopItemIter(keys=()):
            if hab_pre != account_aid and hab_pre not in attached_prefixes:
                continue

            hab = hby.habByPre(hab_pre)
            if hab is None:
                continue
            hab_alias = getattr(hab, "name", hab_pre)
            identifier_label = f"{hab_alias} (Account)" if hab_pre == account_aid else hab_alias

            remote_id = org.get(eid) if org else None
            witness_name = (
                remote_id.get("alias")
                if remote_id and remote_id.get("alias")
                else f"KF Witness {eid[:12]}"
            )
            auth = "Batch TOTP configured" if record.batch_mode else "TOTP configured"

            rows.append(
                {
                    "Identifier": identifier_label,
                    "Name": witness_name,
                    "Witness AID": eid,
                    "Auth": auth,
                    "Endpoint": record.url or "—",
                    "_Auth_color": colors.SUCCESS_TEXT,
                    "_sort_key": (
                        0 if hab_pre == account_aid else 1,
                        identifier_label.lower(),
                        witness_name.lower(),
                        eid,
                    ),
                }
            )

        rows.sort(key=lambda row: row["_sort_key"])
        for row in rows:
            row.pop("_sort_key", None)
        return rows

    def _on_add_witnesses_clicked(self):
        self.add_witnesses_requested.emit()

    @staticmethod
    def _get_row_actions(_row_data):
        return [], {}

    @staticmethod
    def _on_row_action(_data, _action):
        return
