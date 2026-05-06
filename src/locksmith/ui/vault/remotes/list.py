# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.identifiers.list module

Identifier list content page (displayed within VaultPage container).
"""
from typing import Dict, Any, TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

from PySide6.QtWidgets import QVBoxLayout, QSizePolicy
from keri import help
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.vault.shared.base_list_page import BaseListPage
from locksmith.ui.vault.shared.export import export_identifier_to_cesr
from locksmith.ui.vault.remotes.add import AddRemoteIdentifierDialog
from locksmith.ui.vault.remotes.challenge import ChallengeRemoteIdentifierDialog
from locksmith.ui.vault.remotes.delete import DeleteRemoteIdDialog
from locksmith.ui.vault.remotes.filter import FilterRemoteIdentifiersDialog
from locksmith.ui.vault.remotes.view import ViewRemoteIdentifierDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class RemoteIdentifierListPage(BaseListPage):
    """
    Identifier list content page.

    This is a content-only page that displays within the VaultPage container.
    The VaultPage manages the navigation menu.
    """

    def __init__(self, parent: "VaultPage" = None):
        """
        Initialize the IdentifierListPage.

        Args:
            parent: Parent widget (VaultPage container)
        """
        super().__init__(parent)

        self.vault_name = None
        self.parent = parent
        self.app = self.parent.app

        # Track current filter settings
        self.current_identifier_filter = "both"

        # Ensure widget fills parent
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Create main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Set background using palette instead of stylesheet for better control
        from PySide6.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create table widget
        self.icon_path = ":/assets/custom/remoteIds.png"
        self.table = PaginatedTableWidget(
            columns=["Alias", "Prefix", "Seq No.", "Roles"],
            column_widths={"Alias": 250, "Seq No.": 150, "Roles": 150, "Actions": 50},
            title="Remote Identifiers",
            icon_path=self.icon_path,
            items_per_page=10,
            show_search=True,
            show_add_button=True,
            add_button_text="Add Remote Identifier",
            row_actions=["View", "Challenge", "Delete"],
            row_action_icons = {"View": ":/assets/material-icons/view.svg",
                                "Challenge": ":/assets/material-icons/swords.svg",
                                "Delete": ":/assets/material-icons/delete.svg"},
            filter_func=self._open_filter_dialog
        )

        # Connect signals
        self.table.search_changed.connect(self._on_search)
        self.table.page_changed.connect(self._on_page_changed)
        self.table.sort_changed.connect(self._on_sort_changed)
        self.table.add_clicked.connect(self._on_add_identifier)
        self.table.row_action_triggered.connect(self._on_row_action)
        self.table.row_clicked.connect(self._on_row_clicked)

        main_layout.addWidget(self.table)

        logger.info("IdentifierListPage initialized with table widget")

    def _open_filter_dialog(self):
        """Open the filter dialog for remote identifiers."""
        logger.info("Opening filter dialog")

        # Create dialog
        dialog = FilterRemoteIdentifiersDialog(parent=self.parent)

        # Set current filter state
        dialog.set_current_filter(self.current_identifier_filter)

        # Connect to filter applied signal
        dialog.filter_applied.connect(self._on_filter_applied)

        # Open dialog
        dialog.open()

    def _on_filter_applied(self, filter_data: dict):
        """
        Handle filter applied from dialog.

        Args:
            filter_data: Dictionary with filter settings {"identifier_type": "transferable"|"non-transferable"|"both"}
        """
        identifier_type = filter_data.get("identifier_type", "both")
        logger.info(f"Filter applied: identifier_type={identifier_type}")

        # Update current filter state
        self.current_identifier_filter = identifier_type

        # Reload data with filter
        self._load_remote_identifier_data()

    def _load_remote_identifier_data(self):
        """
        Load actual identifier data from the opened vault's hby.

        This method is called after a vault is opened and hby is available.
        """
        logger.info("Loading remote identifier data")
        org = self.app.vault.org
        try:
            remote_identifier_data_raw = org.list()
            remote_identifier_data = []
            for rm_id in remote_identifier_data_raw:
                pre = rm_id["id"]
                kever = self.app.vault.hby.kevers[pre]
                sn = "None"

                if kever and kever.sner:
                    sn = kever.sn

                try:
                    oobi = rm_id['oobi']
                    parsed_oobi = urlparse(oobi)
                    query_params = parse_qs(parsed_oobi.query)
                    tags = query_params.get('tag', [])
                except KeyError:
                    tags = []

                if not tags:
                    for (cid, role, eid), end in self.app.hby.db.ends.getTopItemIter():
                        if eid == rm_id['id'] and end.allowed:
                            tags.append(str.title(role))

                if not tags:
                    tags.append("No Roles")

                roles_str = "\n".join(r.title() for r in tags)


                rm_id_dict = {"Alias": rm_id["alias"],
                              "Prefix": pre,
                              "Seq No.": sn,
                              "Roles": roles_str
                              }

                remote_identifier_data.append(rm_id_dict)

            # Apply filters if not "both"
            if self.current_identifier_filter != "both":
                filtered_data = []
                for rm_id_dict in remote_identifier_data:
                    pre = rm_id_dict["Prefix"]
                    if pre in self.app.vault.hby.kevers:
                        kever = self.app.vault.hby.kevers[pre]

                        # Filter by transferability
                        if self.current_identifier_filter == "transferable" and kever.transferable:
                            filtered_data.append(rm_id_dict)
                        elif self.current_identifier_filter == "non-transferable" and not kever.transferable:
                            filtered_data.append(rm_id_dict)

                remote_identifier_data = filtered_data

            self.table.set_static_data(remote_identifier_data)
        except Exception as e:
            logger.exception(f"Error loading remote identifier data: {e}")
            # Fallback to empty table or test data
            self.table.set_static_data([])


    def _on_add_identifier(self):
        """Handle add identifier button click."""
        logger.info("Add identifier clicked")

        dialog = AddRemoteIdentifierDialog(app=self.app, parent=self.parent)

        dialog.open()

    def _export_identifier(self, identifier_alias: str):
        """Export an identifier to a CESR file."""
        export_identifier_to_cesr(self, self.app, identifier_alias)

    def _on_row_action(self, row_data: Dict[str, Any], action: str):
        """Handle row action from skewer menu."""
        remote_identifier_alias = row_data.get('Alias', 'Unknown')
        remote_identifier_prefix = row_data.get('Prefix', 'Unknown')
        logger.info(f"Row action '{action}' triggered for: {remote_identifier_alias}")

        if action == "View":
            # Open view identifier dialog
            try:
                dialog = ViewRemoteIdentifierDialog(
                    icon_path=self.icon_path,
                    app=self.app,
                    remote_identifier_prefix=remote_identifier_prefix,
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening view dialog: {e}")
        elif action == "Challenge":
            # Open challenge dialog
            try:
                dialog = ChallengeRemoteIdentifierDialog(
                    app=self.app,
                    remote_identifier_prefix=remote_identifier_prefix,
                    remote_identifier_alias=remote_identifier_alias,
                    icon_path=":/assets/material-icons/swords.svg",
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening challenge dialog: {e}")
        elif action == "Delete":
            # Open delete confirmation dialog
            dialog = DeleteRemoteIdDialog(
                remote_id_alias=remote_identifier_alias,
                prefix=remote_identifier_prefix,
                icon_path=self.icon_path,
                app=self.app,
                parent=self.parent
            )
            dialog.open()
        else:
            # TODO: Implement other actions (Rotate)
            logger.info(f"Action '{action}' not yet implemented")

    def set_vault_name(self, vault_name: str):
        """
        Set the vault name for this page and load identifier data.

        This is called by VaultPage.on_show() after a vault is opened,
        ensuring that self.app.vault.hby is available.

        Args:
            vault_name: Name of the open vault
        """
        self.vault_name = vault_name

        # Now that the vault is open and hby is available, load the data
        if self.app.vault and self.app.vault.hby:
            self._load_remote_identifier_data()

            # Connect to vault signal bridge for automatic list updates
            if hasattr(self.app.vault, 'signals'):
                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                logger.info("IdentifierListPage: Connected to vault signal bridge")
        else:
            logger.warning(f"Cannot load identifier data - vault or hby not available")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        logger.debug(f"RemoteIdentifierListPage received doer_event: {doer_name} - {event_type}")

        # Refresh list when an identifier is created
        if doer_name == "InceptDoer" and event_type == "identifier_created":
            logger.info(f"Identifier created: {data.get('alias')} ({data.get('pre')}), refreshing list")
            self._load_remote_identifier_data()

        # Refresh list when an identifier is deleted
        elif doer_name == "DeleteRemoteIdentifier" and event_type == "remote_identifier_deleted":
            logger.info(f"Remote identifier deleted: {data.get('alias')}, refreshing list")
            self._load_remote_identifier_data()

        # Refresh list when an OOBI is resolved (via URL)
        elif doer_name == "ResolveOobiDoer" and event_type == "oobi_resolved":
            logger.info(f"OOBI resolved: {data.get('alias')} ({data.get('pre')}), refreshing list")
            self._load_remote_identifier_data()

        # Refresh list when a remote identifier is imported (via file)
        elif doer_name == "ImportDoer" and event_type == "remote_identifier_imported":
            logger.info(f"Remote identifier imported: {data.get('alias')} ({data.get('pre')}), refreshing list")
            self._load_remote_identifier_data()

        # Refresh list when a role is set
        elif doer_name == "SetRoleDoer" and event_type in ["role_set", "role_already_set"]:
            logger.info(f"Role set for remote ID {data.get('remote_id_pre')}: {data.get('role')}, refreshing list")
            self._load_remote_identifier_data()

        # Refresh list when a role is deleted
        elif doer_name == "DeleteRole" and event_type == "role_deleted":
            logger.info(f"Role '{data.get('role')}' deleted for remote ID {data.get('eid')}, refreshing list")
            self._load_remote_identifier_data()

        # Refresh to show auth_pending state (orange prefix) if witnesses exist
        elif doer_name == "MenuDoer" and event_type == "load" and data.get('subpage') == "REMOTES":
            self._load_remote_identifier_data()

        # Refresh to show connections as remote identifiers from plugin APIs
        elif doer_name == "AddConnection" and event_type == "connection_added":
            self._load_remote_identifier_data()

