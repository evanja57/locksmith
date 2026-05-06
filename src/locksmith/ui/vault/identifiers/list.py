# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.identifiers.list module

Identifier list content page (displayed within VaultPage container).
"""
from typing import Dict, Any, TYPE_CHECKING, List

from PySide6.QtWidgets import QVBoxLayout, QSizePolicy
from keri import help
import keri.app.habbing as keri_habbing

from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.core.grouping import check_pending_multisig
from locksmith.ui.vault.shared.base_list_page import BaseListPage
from locksmith.ui.vault.shared.export import export_identifier_to_cesr
from locksmith.ui.vault.identifiers.accept_delegate import AcceptDelegateDialog
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog
from locksmith.ui.vault.identifiers.create import CreateIdentifierDialog
from locksmith.ui.vault.identifiers.delete import DeleteIdentifierDialog
from locksmith.ui.vault.identifiers.interact import InteractDialog
from locksmith.ui.vault.identifiers.rotate import RotateIdentifierDialog
from locksmith.ui.vault.identifiers.view import ViewIdentifierDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class IdentifierListPage(BaseListPage):
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
        self.icon_path = ":/assets/custom/identifiers.png"
        self.table = PaginatedTableWidget(
            columns=["Alias", "Prefix", "Seq No.", "Witnesses", "Actions"],
            column_widths={"Alias": 250, "Witnesses": 150, "Seq No.": 150, "Actions": 50},
            title="Local Identifiers",
            icon_path=self.icon_path,
            items_per_page=10,
            show_search=True,
            show_add_button=True,
            add_button_text="Add Identifier",
            row_actions=["View", "Interact", "Rotate", "Delete", "Export", "Accept Delegate"],
            row_actions_callback=self._get_row_actions
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

    def _load_identifier_data(self):
        """
        Load actual identifier data from the opened vault's hby.

        This method is called after a vault is opened and hby is available.
        """
        try:
            identifier_data = []
            for (ns, alias), prefix in self.app.vault.hby.db.names.getTopItemIter(keys=()):
                if ns != "":
                    continue

                hab = self.app.vault.hby.habByName(alias)

                # Filter: Skip GroupHab instances (they appear in Group Identifiers)
                if isinstance(hab, keri_habbing.GroupHab):
                    logger.debug(f"Skipping group identifier: {alias}")
                    continue

                if hab.kever:
                    identifier_dict = {"Alias": alias,
                                       "Prefix": prefix,
                                       "Seq No.": hab.kever.sn,
                                       "Witnesses": len(hab.kever.wits)
                                       }
                else:
                    identifier_dict = {"Alias": alias,
                                       "Prefix": prefix,
                                       "Seq No.": "N/A",
                                       "Witnesses": "N/A"}

                # Check for pending multisig state
                is_pending_multisig = False
                try:
                    is_pending_multisig = check_pending_multisig(self.app, hab)
                    if is_pending_multisig:
                        logger.info(f"Pending multisig for {identifier_dict['Prefix']}")
                        # Apply blue color and tooltip for pending multisig
                        for field in ["Alias", "Prefix", "Seq No.", "Witnesses"]:
                            identifier_dict[f"{field}_color"] = colors.BLUE_SELECTION
                            identifier_dict[f"{field}_tooltip"] = "Pending multisig collaboration - waiting for other participants"
                        identifier_dict["_pending_multisig"] = True
                except Exception as e:
                    logger.warning(f"Error checking pending multisig for {identifier_dict['Prefix']}: {e}")

                # Check for auth_pending state (only if not pending multisig)
                if not is_pending_multisig:
                    try:
                        metadata = self.app.vault.db.idm.get(identifier_dict["Prefix"])
                        if metadata and metadata.auth_pending:
                            logger.info(f"Auth pending for {identifier_dict['Prefix']}")

                            # Apply orange color and tooltip to all fields
                            for field in ["Alias", "Prefix", "Seq No.", "Witnesses"]:
                                identifier_dict[f"{field}_color"] = colors.PRIMARY
                                identifier_dict[f"{field}_tooltip"] = "Authentication pending - witnesses need to be authenticated"
                        else:
                            # No auth pending, use default color
                            identifier_dict["Prefix_color"] = colors.TEXT_PRIMARY
                    except Exception as e:
                        logger.warning(f"Error checking auth_pending for {identifier_dict['Prefix']}: {e}")
                        identifier_dict["Prefix_color"] = colors.TEXT_PRIMARY  # Default on error
                identifier_data.append(identifier_dict)
            self.table.set_static_data(identifier_data)
        except Exception as e:
            logger.exception(f"Error loading identifier data: {e}")
            # Fallback to empty table or test data
            self.table.set_static_data([])

    def _get_row_actions(self, row_data: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        """
        Get dynamic row actions based on identifier state.

        Args:
            row_data: Dictionary containing row data (Alias, Prefix, etc.)

        Returns:
            Tuple of (actions_list, action_icons_dict)
        """
        identifier_prefix = row_data.get('Prefix', '')

        # Check auth_pending state
        try:
            metadata = self.app.vault.db.idm.get(identifier_prefix)
            auth_pending = metadata.auth_pending if metadata else False
        except Exception as e:
            logger.warning(f"Error checking auth_pending in row actions: {e}")
            auth_pending = False

        # Define action icons (same for all rows)
        action_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Interact": ":/assets/material-icons/interact.svg",
            "Rotate": ":/assets/material-icons/rotate_right.svg",
            "Authenticate": ":/assets/material-icons/authenticate.svg",
            "Delete": ":/assets/material-icons/delete.svg",
            "Export": ":/assets/material-icons/export.svg",
            "Accept Delegate": ":/assets/material-icons/delegate.svg"
        }

        if auth_pending:
            # Show Authenticate instead of Rotate
            actions = ["View", "Interact", "Authenticate", "Delete", "Export", "Accept Delegate"]
        else:
            # Normal actions
            actions = ["View", "Interact", "Rotate", "Delete", "Export", "Accept Delegate"]

        return actions, action_icons

    def _on_add_identifier(self):
        """Handle add identifier button click."""
        logger.info("Add identifier clicked")

        dialog = CreateIdentifierDialog(icon_path=self.icon_path, app=self.app, parent=self.parent, config=self.app.config)

        dialog.open()
        # TODO: Open add identifier dialog

    def _export_identifier(self, identifier_alias: str):
        """Export an identifier to a CESR file."""
        export_identifier_to_cesr(self, self.app, identifier_alias)

    def _on_row_action(self, row_data: Dict[str, Any], action: str):
        """Handle row action from skewer menu."""
        identifier_alias = row_data.get('Alias', 'Unknown')
        identifier_prefix = row_data.get('Prefix', 'Unknown')
        logger.info(f"Row action '{action}' triggered for: {identifier_alias}")

        if action == "View":
            # Open view identifier dialog
            try:
                dialog = ViewIdentifierDialog(
                    icon_path=self.icon_path,
                    app=self.app,
                    identifier_alias=identifier_alias,
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening view dialog: {e}")
        elif action == "Interact":
            # Open interact dialog
            try:
                dialog = InteractDialog(
                    identifier_alias=identifier_alias,
                    icon_path=self.icon_path,
                    app=self.app,
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening interact dialog: {e}")
        elif action == "Delete":
            # Open delete confirmation dialog
            dialog = DeleteIdentifierDialog(
                identifier_alias=identifier_alias,
                icon_path=self.icon_path,
                app=self.app,
                parent=self.parent
            )
            dialog.open()
        elif action == "Export":
            # Export identifier to CESR file
            self._export_identifier(identifier_alias)
        elif action == "Rotate":
            metadata = self.app.vault.db.idm.get(identifier_prefix)
            if metadata and metadata.auth_pending:
                logger.error("Cannot rotate identifier with pending authentication")
                hab = self.app.vault.hby.habByName(identifier_alias)

                dialog = WitnessAuthenticationDialog(app=self.app,
                                                     hab=hab,
                                                     witness_ids=hab.kever.wits,
                                                     parent=self.parent)
            else:
                dialog = RotateIdentifierDialog(
                    identifier_alias=identifier_alias,
                    icon_path=self.icon_path,
                    app=self.app,
                    parent=self.parent
                )

            dialog.open()
        elif action == "Authenticate":
            # Retry witness authentication for pending rotation
            logger.info(f"Authenticating witnesses for {identifier_alias}")
            try:
                hab = self.app.vault.hby.habByName(identifier_alias)
                if not hab:
                    logger.error(f"Identifier '{identifier_alias}' not found")
                    return

                # Open authentication dialog (it will handle authentication internally)
                dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=hab.kever.wits,
                    auth_only=True,
                    parent=self.parent
                )
                dialog.open()

            except Exception as e:
                logger.exception(f"Error opening authentication dialog: {e}")
        elif action == "Accept Delegate":
            # Open accept delegate dialog
            try:
                dialog = AcceptDelegateDialog(
                    app=self.app,
                    identifier_prefix=identifier_prefix,
                    identifier_alias=identifier_alias,
                    parent=self.parent
                )
                dialog.open()
            except Exception as e:
                logger.exception(f"Error opening accept delegate dialog: {e}")
        else:
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
            self._load_identifier_data()

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
        logger.debug(f"IdentifierListPage received doer_event: {doer_name} - {event_type}")

        # Refresh list when an identifier is created
        if doer_name == "InceptDoer" and event_type == "identifier_created":
            logger.info(f"Identifier created: {data.get('alias')} ({data.get('pre')}), refreshing list")
            self._load_identifier_data()

        # Refresh list when a group identifier is created or joined
        elif doer_name == "GroupMultisigInceptDoer" and event_type in ("group_identifier_created", "group_inception_started", "group_inception_waiting"):
            logger.info(f"Group identifier event: {event_type} - {data.get('alias')}, refreshing list")
            self._load_identifier_data()

        elif doer_name == "MultisigJoinDoer" and event_type in ("group_identifier_joined", "group_join_waiting"):
            logger.info(f"Group join event: {event_type} - {data.get('alias')}, refreshing list")
            self._load_identifier_data()

        # Refresh list when an identifier is deleted
        elif doer_name == "DeleteIdentifier" and event_type == "identifier_deleted":
            logger.info(f"Identifier deleted: {data.get('alias')}, refreshing list")
            self._load_identifier_data()

        elif doer_name == "RotateDoer" and event_type == "rotation_complete":
            logger.info(f"Rotation complete: {data.get('alias')} ({data.get('pre')})")
            # Refresh to show auth_pending state (orange prefix) if witnesses exist
            self._load_identifier_data()

        # Refresh on rotation failure
        elif doer_name == "RotateDoer" and event_type == "rotation_failed":
            logger.error(f"Rotation failed: {data.get('alias')}, refreshing list")
            self._load_identifier_data()

        elif doer_name == "InteractDoer" and event_type == "interaction_complete":
            logger.info(f"Interaction complete: {data.get('alias')} ({data.get('pre')})")
            # Refresh to show auth_pending state (orange prefix) if witnesses exist
            self._load_identifier_data()

        elif doer_name == "MenuDoer" and event_type == "load" and data.get('subpage') == "IDENTIFIERS":
            logger.info(f"Load complete: IDENTIFIERS")
            # Refresh to show auth_pending state (orange prefix) if witnesses exist
            self._load_identifier_data()


        # Refresh on authentication retry success
        elif doer_name == "AuthenticateWitnessesDoer" and event_type == "witness_authentication_success":
            logger.info(f"Witness authentication succeeded: {data.get('alias')}, refreshing list")
            self._load_identifier_data()

        # Refresh on authentication retry failure
        elif doer_name == "AuthenticateWitnessesDoer" and event_type == "witness_authentication_failed":
            logger.warning(f"Witness authentication failed: {data.get('alias')}, refreshing list")
            self._load_identifier_data()
