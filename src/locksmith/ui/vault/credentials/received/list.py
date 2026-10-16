# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.received.list module

Received credentials list content page (displayed within VaultPage container).
"""
from typing import Dict, Any, TYPE_CHECKING

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QVBoxLayout, QSizePolicy
from keri import help

from locksmith.ui import colors
from locksmith.core import credentialing
from locksmith.ui.vault.credentials.presentation import credential_name, identifier_name, date_label, status_label
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.toolkit.widgets import LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from locksmith.ui.vault.shared.base_list_page import BaseListPage
from locksmith.ui.vault.credentials.received.accept import AcceptCredentialDialog
from locksmith.ui.vault.credentials.received.delete import DeleteReceivedCredentialDialog
from locksmith.ui.vault.credentials.issued.view import ViewIssuedCredentialDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ReceivedCredentialsListPage(BaseListPage):
    """
    Received credentials list content page.

    This is a content-only page that displays within the VaultPage container.
    The VaultPage manages the navigation menu.
    """

    def __init__(self, parent: "VaultPage" = None):
        """
        Initialize the ReceivedCredentialsListPage.

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
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create table widget
        self.icon_path = ":/assets/material-icons/in-badge.svg"
        self.table = PaginatedTableWidget(
            columns=["Credential", "From", "Status", "Accepted", "Actions"],
            column_widths={"Credential": 220, "Status": 120, "Accepted": 165, "Actions": 50},
            title="Received Credentials",
            icon_path=self.icon_path,
            items_per_page=10,
            show_search=True,
            show_add_button=True,
            add_button_text="Apply for credential…",
            separate_toolbar=True,
            row_actions=["View", "Offer", "View exchange history", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Offer": ":/assets/material-icons/share.svg",
                "View exchange history": ":/assets/material-icons/swap_horiz.svg",
                "Delete": ":/assets/material-icons/delete.svg"
            }
        )

        # Connect signals
        self.table.search_changed.connect(self._on_search)
        self.table.page_changed.connect(self._on_page_changed)
        self.table.sort_changed.connect(self._on_sort_changed)
        self.table.add_clicked.connect(lambda: self.parent.start_credential_exchange('Apply'))
        self.table.row_action_triggered.connect(self._on_row_action)
        self.table.row_clicked.connect(self._on_row_clicked)

        main_layout.addWidget(self.table)

        import_button = LocksmithInvertedButton('Import Grant…')
        import_button.clicked.connect(self._on_accept_credential)
        self.table.header.add_action_button(import_button)
        self.inventory = FloatingLabelComboBox('Show')
        self.inventory.addItem('Held credentials', True)
        self.inventory.addItem('Verified presentations', False)
        self.inventory.currentIndexChanged.connect(
            lambda *_: self._load_received_credentials_data(reset_page=True))
        self.table.header.add_action_button(self.inventory)

        logger.info("ReceivedCredentialsListPage initialized with table widget")

    def _load_received_credentials_data(self, *, reset_page=False):
        """
        Load received credentials data from the opened vault.

        This method is called after a vault is opened and hby is available.
        """
        try:
            received_credentials_data = []
            creds = credentialing.credentials(self.app.vault, received=True)

            for credential in creds:
                if credential['held'] != self.inventory.currentData():
                    continue
                sad = credential['sad']
                schemer = credential.get("schema") or {}
                status = credential.get("status", {})

                recipient_name = identifier_name(self.app.vault, credential['sender'])
                status_text = status_label(status)
                cred_dict = {
                    "Credential": credential_name(schemer),
                    "From": recipient_name,
                    "Status": status_text,
                    "Accepted": date_label(credential['accepted_at']),
                    "SAID": sad['d'],
                    "_actions": (["View", "Offer", "View exchange history", "Delete"]
                                 if credential['held'] else ["View", "View exchange history", "Delete"]),
                }
                received_credentials_data.append(cred_dict)

            self.table.set_static_data(received_credentials_data, reset_page=reset_page)
            logger.info(f"Loaded {len(received_credentials_data)} received credentials")
        except Exception as e:
            logger.exception(f"Error loading received credentials data: {e}")
            self.table.set_static_data([])

    def _on_accept_credential(self):
        """Handle accept credential button click."""
        logger.info("Accept credential clicked")
        dialog = AcceptCredentialDialog(app=self.app, parent=self.parent)
        dialog.open()

    def _on_row_action(self, row_data: Dict[str, Any], action: str):
        """Handle row action from skewer menu."""
        credential_schema = row_data.get('Credential', 'Unknown')
        credential_issuer = row_data.get('Issuer', 'Unknown')
        credential_said = row_data.get('SAID', '')
        logger.info(f"Row action '{action}' triggered for: {credential_schema} <- {credential_issuer}")

        if action == "View exchange history":
            self.parent.show_credential_activity(credential_said, received=True)
        elif action == "Offer":
            self.parent.start_credential_exchange('Offer', credential_said=credential_said, received=True)
        elif action == "View":
            dialog = ViewIssuedCredentialDialog(icon_path=self.icon_path, app=self.app,
                                                credential_said=credential_said,
                                                parent=self.parent, received=True)
            dialog.open()
        elif action == "Delete":
            # Open delete confirmation dialog
            dialog = DeleteReceivedCredentialDialog(
                schema_name=credential_schema,
                said=credential_said,
                icon_path=self.icon_path,
                app=self.app,
                parent=self.parent
            )
            dialog.open()
        elif action == "Export":
            # TODO: Export credential
            logger.info(f"Export received credential: {credential_schema} (SAID: {credential_said})")
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
            self._load_received_credentials_data(reset_page=True)

            # Connect to vault signal bridge for automatic list updates
            if hasattr(self.app.vault, 'signals'):
                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                logger.info("ReceivedCredentialsListPage: Connected to vault signal bridge")
        else:
            logger.warning(f"Cannot load received credentials data - vault or hby not available")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        logger.debug(f"ReceivedCredentialsListPage received doer_event: {doer_name} - {event_type}")

        if doer_name == 'RegistryEvidence' and event_type == 'status_checked':
            self._load_received_credentials_data()

        # Refresh list when a credential is received
        if doer_name == "ReceiveCredentialDoer" and event_type == "credential_received":
            logger.info(f"Credential received: {data.get('schema')}, refreshing list")
            self._load_received_credentials_data()

        # Refresh list when a credential is deleted
        elif doer_name == "DeleteReceivedCredential" and event_type == "credential_deleted":
            logger.info(f"Received credential deleted: {data.get('schema')}, refreshing list")
            self._load_received_credentials_data()

        elif doer_name == "Ipex" and event_type in ("accepted", "transport_submitted", "send_failed"):
            self._load_received_credentials_data()
