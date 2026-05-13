# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.list module

Issued credentials list content page (displayed within VaultPage container).
"""
from typing import Dict, Any, TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QSizePolicy
from keri import help
from keri.app import organizing
from keri.help import helping

from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.vault.shared.base_list_page import BaseListPage
from locksmith.ui.vault.credentials.issued.delete import DeleteIssuedCredentialDialog
from locksmith.ui.vault.credentials.issued.grant import GrantCredentialDialog
from locksmith.ui.vault.credentials.issued.issue import IssueCredentialDialog
from locksmith.ui.vault.credentials.issued.view import ViewIssuedCredentialDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class IssuedCredentialsListPage(BaseListPage):
    """
    Issued credentials list content page.

    This is a content-only page that displays within the VaultPage container.
    The VaultPage manages the navigation menu.
    """

    def __init__(self, parent: "VaultPage" = None):
        """
        Initialize the IssuedCredentialsListPage.

        Args:
            parent: Parent widget (VaultPage container)
        """
        super().__init__(parent)

        self.vault_name = None
        self.parent = parent
        self.app = self.parent.app

        # Ensure widget fills parent
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Create main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Set background using palette instead of stylesheet for better control
        from PySide6.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F8F9FF"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create table widget
        self.icon_path = ":/assets/material-icons/out-badge.svg"
        self.table = PaginatedTableWidget(
            columns=["Schema", "Recipient", "Status", "Issued Date", "Actions"],
            column_widths={"Schema": 220, "Status": 110, "Issued Date": 165, "Actions": 50},
            title="Issued Credentials",
            icon_path=self.icon_path,
            items_per_page=10,
            show_search=True,
            show_add_button=True,
            add_button_text="Issue Credential",
            row_actions=["View", "Send", "Revoke", "Delete", "Export", "Grant"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Send": ":/assets/material-icons/send.svg",
                "Revoke": ":/assets/material-icons/remove_moderator.svg",
                "Delete": ":/assets/material-icons/delete.svg",
                "Export": ":/assets/material-icons/export.svg",
                "Grant": ":/assets/material-icons/share.svg"
            }
        )

        # Connect signals
        self.table.search_changed.connect(self._on_search)
        self.table.page_changed.connect(self._on_page_changed)
        self.table.sort_changed.connect(self._on_sort_changed)
        self.table.add_clicked.connect(self._on_issue_credential)
        self.table.row_action_triggered.connect(self._on_row_action)
        self.table.row_clicked.connect(self._on_row_clicked)

        main_layout.addWidget(self.table)

        logger.info("IssuedCredentialsListPage initialized with table widget")

    def _load_issued_credentials_data(self):
        """
        Load issued credentials data from the opened vault.

        This method is called after a vault is opened and hby is available.
        """
        try:
            org = organizing.Organizer(hby=self.app.vault.hby)

            issued_credentials_data = []
            saids = list()
            for pre in self.app.vault.hby.habs.keys():
                saids.extend([saider for saider in self.app.vault.rgy.reger.issus.get(keys=(pre,))])
            creds = self.app.vault.rgy.reger.cloneCreds(saids, self.app.hby.db)

            for credential in creds:
                sad = credential['sad']
                attribs = sad['a']
                schemer = credential.get("schema")
                status = credential.get("status", {})
                if status['et'] == 'iss' or status['et'] == 'bis':
                    status_text = "Issued / Active"
                elif status['et'] == 'rev' or status['et'] == 'brv':
                    status_text = "Issued / Revoked"
                else:
                    status_text = "Not Issued"

                recp = attribs.get('i')
                recipient_name = f'Unknown ({recp})'
                if (recipient_hab := self.app.vault.hby.habByPre(attribs['i'])) is not None:
                    recipient_name = f'{recipient_hab.name} ({recp})'
                elif (remote_id := org.get(recp)) is not None:
                    recipient_name = f'{remote_id['alias']} ({recp})'

                dt = helping.fromIso8601(status['dt'])

                cred_dict = {
                    "Schema": schemer.get("title", ""),
                    "Recipient": recipient_name,
                    "Issuer": sad['i'],
                    "Status": status_text,
                    "Issued Date": dt.strftime("%b %d, %Y %I:%M %p"),
                    "SAID": sad['d']  # Store SAID for view operation
                }
                issued_credentials_data.append(cred_dict)

            self.table.set_static_data(issued_credentials_data)
            logger.info(f"Loaded {len(issued_credentials_data)} issued credentials")
        except Exception as e:
            logger.exception(f"Error loading issued credentials data: {e}")
            self.table.set_static_data([])

    def _on_issue_credential(self):
        """Handle issue credential button click."""
        logger.info("Issue credential clicked")
        dialog = IssueCredentialDialog(app=self.app, parent=self.parent)
        dialog.open()

    def _on_row_action(self, row_data: Dict[str, Any], action: str):
        """Handle row action from skewer menu."""
        credential_schema = row_data.get('Schema', 'Unknown')
        credential_recipient = row_data.get('Recipient', 'Unknown')
        credential_issuer = row_data.get('Issuer', 'Unknown')
        credential_said = row_data.get('SAID', '')
        logger.info(f"Row action '{action}' triggered for: {credential_schema} -> {credential_recipient}")

        if action == "View":
            # Open view credential dialog
            try:
                dialog = ViewIssuedCredentialDialog(
                    icon_path=self.icon_path,
                    app=self.app,
                    credential_said=credential_said,
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening view dialog: {e}")
        elif action == "Grant":
            # Open grant credential dialog
            if not credential_said:
                logger.error("Credential SAID not found in row data")
                return

            try:
                dialog = GrantCredentialDialog(
                    app=self.app,
                    parent=self.parent,
                    credential_said=credential_said,
                    credential_schema=credential_schema,
                    credential_issuer=credential_issuer
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening grant dialog: {e}")
        elif action == "Revoke":
            logger.info(f"Revoke issued credential: {credential_schema}")
        elif action == "Delete":
            # Open delete confirmation dialog
            dialog = DeleteIssuedCredentialDialog(
                schema_name=credential_schema,
                said=credential_said,
                icon_path=self.icon_path,
                app=self.app,
                parent=self.parent
            )
            dialog.open()
        elif action == "Send":
            logger.info(f"Export issued credential: {credential_schema}")
        elif action == "Export":
            logger.info(f"Export issued credential: {credential_schema}")
        else:
            logger.info(f"Action '{action}' not yet implemented")

    def set_vault_name(self, vault_name: str):
        """
        Set the vault name for this page and load credentials data.

        This is called by VaultPage.on_show() after a vault is opened,
        ensuring that self.app.vault.hby is available.

        Args:
            vault_name: Name of the open vault
        """
        self.vault_name = vault_name

        # Now that the vault is open and hby is available, load the data
        if self.app.vault and self.app.vault.hby:
            self._load_issued_credentials_data()

            # Connect to vault signal bridge for automatic list updates
            if hasattr(self.app.vault, 'signals'):
                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                logger.info("IssuedCredentialsListPage: Connected to vault signal bridge")
        else:
            logger.warning(f"Cannot load issued credentials data - vault or hby not available")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        logger.debug(f"IssuedCredentialsListPage received doer_event: {doer_name} - {event_type}")

        # Refresh list when a credential is issued
        if doer_name == "IssueCredentialDoer" and event_type == "credential_issued":
            logger.info(
                f"Credential issued: {data.get('schema_title', data.get('schema_said'))}, refreshing list"
            )
            self._load_issued_credentials_data()

        # Refresh list when a credential is revoked
        elif doer_name == "RevokeCredentialDoer" and event_type == "credential_revoked":
            logger.info(f"Credential revoked: {data.get('schema')}, refreshing list")
            self._load_issued_credentials_data()

        # Refresh list when an issued credential is deleted
        elif doer_name == "DeleteIssuedCredential" and event_type == "credential_deleted":
            logger.info(f"Issued credential deleted: {data.get('schema')}, refreshing list")
            self._load_issued_credentials_data()
