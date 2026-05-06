
# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.notifications.list module

Notifications list page for vault.
"""
import os
from typing import Any, TYPE_CHECKING

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from keri import help
from keri.app import organizing
from keri.core import scheming
from keri.peer import exchanging
from keri.vc.protocoling import Ipex
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.vault.credentials.received.accept_grant import AcceptGrantDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class NotificationsListPage(QWidget):
    """Notifications list page for vault.

    Shows notifications with:
    - Static data loaded from notifier
    - Message, Timestamp, Status
    - Mark as Read and Delete actions
    """

    def __init__(self, parent: "VaultPage | None" = None):
        """
        Initialize the NotificationsListPage.

        Args:
            parent: Parent widget (VaultPage container)
        """
        super().__init__(parent)
        self._parent = parent
        self.app = parent.app if parent else None
        self.vault_name = ""

        self._setup_ui()

    def _setup_ui(self):
        """Set up the page UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        columns = ["Timestamp", "Type", "Message", "Status"]

        # Base row actions available for all notifications
        self._base_row_actions = ["Mark as Read", "Delete"]
        self._base_row_action_icons = {
            "Mark as Read": ":/assets/material-icons/check_circle.svg",
            "Delete": ":/assets/material-icons/delete.svg",
            "Admit": ":/assets/material-icons/share.svg",
            "Join": ":/assets/material-icons/group_add.svg",
        }

        # Set background using palette
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create the table with dynamic row actions based on notification type
        self.table = PaginatedTableWidget(
            columns=columns,
            column_widths={"Type": 100, "Timestamp": 180, "Status": 100, "Actions": 50},
            title="Notifications",
            icon_path=":/assets/material-icons/big_notifications.svg",
            show_add_button=False,
            row_actions=self._base_row_actions,
            row_action_icons=self._base_row_action_icons,
            row_actions_callback=self._get_row_actions,
            items_per_page=10,
            parent=self
        )

        # Connect table signals
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)

        layout.addWidget(self.table)

        logger.info("NotificationsListPage initialized with table widget")

    def _get_row_actions(self, row_data: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        """
        Determine which row actions to show based on notification type.

        Args:
            row_data: Row data dict with column values

        Returns:
            Tuple of (action_names, action_icons)
        """
        notification_type = row_data.get('Type', '')

        # For GRANT notifications, add the Admit action at the start
        if notification_type == "GRANT":
            actions = ["Admit"] + self._base_row_actions
        # For MULTISIG_ICP notifications, add the Join action at the start
        elif notification_type == "MULTISIG_ICP":
            actions = ["Join"] + self._base_row_actions
        # For MULTISIG_ROT notifications, add the Join action at the start
        elif notification_type == "MULTISIG_ROT":
            actions = ["Join"] + self._base_row_actions
        else:
            actions = self._base_row_actions

        return actions, self._base_row_action_icons

    def _load_notifications(self):
        """Load notifications from notifier and populate table."""
        if not self.app or not self.app.vault:
            logger.warning("No app or vault available to load notifications")
            return

        notifications = []

        try:
            # Iterate through notifications from notifier
            for (dt, rid), note in self.app.vault.notifier.noter.notes.getTopItemIter():
                # Format timestamp
                from keri.help import helping
                try:
                    timestamp_dt = helping.fromIso8601(note.datetime)
                    timestamp_display = timestamp_dt.strftime("%b %d, %Y %I:%M %p")
                except Exception as e:
                    logger.warning(f"Failed to parse notification timestamp: {e}")
                    timestamp_display = note.datetime

                # Check notification type based on route
                route = note.pad.get('a', {}).get('r', '')
                if '/multisig' in route:
                    notification_row = self._format_multisig_notification(note, rid, timestamp_display)
                elif route.startswith('/exn/ipex'):
                    notification_row = self._format_ipex_notification(note, rid, timestamp_display)
                elif route.startswith('/challenge/response'):
                    notification_row = self._format_challenge_response_notification(note, rid, timestamp_display)
                elif route.startswith('/keystate/update'):
                    notification_row = self._format_keystate_update_notification(note, rid, timestamp_display)
                else:
                    notification_row = self._format_generic_notification(note, rid, timestamp_display)

                if notification_row:
                    notifications.append(notification_row)

            # Sort by timestamp (most recent first)
            notifications.reverse()

            # Set data in table
            self.table.set_static_data(notifications)

            logger.info(f"Loaded {len(notifications)} notifications")

        except Exception as e:
            logger.exception(f"Error loading notifications: {e}")

    def _format_generic_notification(self, note, rid: str, timestamp_display: str) -> dict[str, Any]:
        """
        Format a generic (non-IPEX) notification.

        Args:
            note: Notification object
            rid: Notification ID
            timestamp_display: Formatted timestamp string

        Returns:
            Dict with notification row data
        """
        message = str(note.attrs) if note.attrs else "No message"
        if isinstance(note.attrs, dict):
            message = note.attrs.get('message',
                                     note.attrs.get('msg',
                                                    note.attrs.get('d', str(note.attrs))))

        return {
            'Type': 'General',
            'Message': message,
            'Timestamp': timestamp_display,
            'Status': 'Read' if note.read else 'Unread',
            '_rid': rid,
            '_read': note.read,
        }

    def _format_ipex_notification(self, note, rid: str, timestamp_display: str) -> dict[str, Any] | None:
        """
        Format an IPEX protocol notification with credential details.

        Args:
            note: Notification object
            rid: Notification ID
            timestamp_display: Formatted timestamp string

        Returns:
            Dict with notification row data, or None if message cannot be loaded
        """
        if not self.app or not self.app.vault:
            return None

        hby = self.app.vault.hby
        attrs = note.attrs
        said = attrs.get('d', '')

        if not said:
            return self._format_generic_notification(note, rid, timestamp_display)

        try:
            exn, pathed = exchanging.cloneMessage(hby, said)
            if exn is None:
                logger.warning(f"Could not clone IPEX message: {said}")
                return self._format_generic_notification(note, rid, timestamp_display)

            route = exn.ked.get('r', '')
            # Extract the actual message from the exchange if present
            actual_message = exn.ked.get('a', {}).get('m', '')
            message_type, formatted_message = self._format_ipex_message(exn, route, actual_message)

            return {
                'Type': message_type,
                'Message': formatted_message,
                'Timestamp': timestamp_display,
                'Status': 'Read' if note.read else 'Unread',
                '_rid': rid,
                '_read': note.read,
                '_said': said,
                '_route': route,
            }

        except Exception as e:
            logger.warning(f"Error formatting IPEX notification: {e}")
            return self._format_generic_notification(note, rid, timestamp_display)

    def _format_challenge_response_notification(self, note, rid: str, timestamp_display: str) -> dict[str, Any] | None:
        """
        Format an Challenge Response notification with response details.

        Args:
            note: Notification object
            rid: Notification ID
            timestamp_display: Formatted timestamp string

        Returns:
            Dict with notification row data, or None if message cannot be loaded
        """
        if not self.app or not self.app.vault:
            return None

        attrs = note.attrs
        route = attrs.get('r', '')
        signer = attrs.get('signer', '')
        words = attrs.get('words', '')
        said = attrs.get('said', '')

        if not said:
            return self._format_generic_notification(note, rid, timestamp_display)

        try:
            org = organizing.Organizer(hby=self.app.vault.hby)
            signer_contact = org.get(signer)
            if signer_contact is None:
                signer_name = "Unknown"
            else:
                signer_name = signer_contact.get('alias', 'Unknown')
            # Extract the actual message from the exchange if present

            return {
                'Type': "Challenge Response",
                'Message': f"'{signer_name}' successfully signed phrase: {" ".join(words)}",
                'Timestamp': timestamp_display,
                'Status': 'Read' if note.read else 'Unread',
                '_rid': rid,
                '_read': note.read,
                '_said': said,
                '_route': route,
            }

        except Exception as e:
            logger.warning(f"Error formatting IPEX notification: {e}")
            return self._format_generic_notification(note, rid, timestamp_display)


    def _format_keystate_update_notification(self, note, rid: str, timestamp_display: str) -> dict[str, Any] | None:
        """
        Format an Challenge Response notification with response details.

        Args:
            note: Notification object
            rid: Notification ID
            timestamp_display: Formatted timestamp string

        Returns:
            Dict with notification row data, or None if message cannot be loaded
        """
        if not self.app or not self.app.vault:
            return None

        attrs = note.attrs
        route = attrs.get('r', '')

        pre = note.pad.get('a', {}).get('pre', '')
        sn = note.pad.get('a', {}).get('sn', '')
        dig = note.pad.get('a', {}).get('dig', '')

        try:
            org = organizing.Organizer(hby=self.app.vault.hby)
            signer_contact = org.get(pre)
            if signer_contact is None:
                signer_name = "Unknown"
            else:
                signer_name = signer_contact.get('alias', 'Unknown')
            # Extract the actual message from the exchange if present

            return {
                'Type': "Keystate Update",
                'Message': f"Key state update recieved for {signer_name} moving to sequence number {sn} at {dig}",
                'Timestamp': timestamp_display,
                'Status': 'Read' if note.read else 'Unread',
                '_rid': rid,
                '_read': note.read,
                '_said': rid,
                '_route': route,
            }

        except Exception as e:
            logger.warning(f"Error formatting IPEX notification: {e}")
            return self._format_generic_notification(note, rid, timestamp_display)

    def _format_ipex_message(self, exn, route: str, actual_message: str = "") -> tuple[str, str]:
        """
        Format IPEX message details based on message type.

        Args:
            exn: Exchange message object
            route: Message route (e.g., '/ipex/grant')
            actual_message: Optional actual message from the sender

        Returns:
            Tuple of (message_type, formatted_message)
        """
        match route:
            case "/ipex/grant":
                return self._format_grant(exn, actual_message)
            case "/ipex/admit":
                return self._format_admit(exn, actual_message)
            case "/ipex/spurn":
                return self._format_spurn(exn, actual_message)
            case "/ipex/apply":
                return self._format_apply(exn, actual_message)
            case "/ipex/offer":
                return self._format_offer(exn, actual_message)
            case "/ipex/agree":
                return self._format_agree(exn, actual_message)
            case _:
                return "IPEX", f"Unknown IPEX message type: {route}"

    def _resolve_schema_title(self, schema_said: str) -> str | None:
        """
        Resolve schema SAID to get the schema title.

        Args:
            schema_said: SAID of the schema

        Returns:
            Schema title or None if not found
        """
        if not self.app or not self.app.vault:
            return None

        try:
            # Access the verifier's resolver to get schema
            verifier = getattr(self.app.vault, 'vry', None)
            if verifier and hasattr(verifier, 'resolver'):
                scraw = verifier.resolver.resolve(schema_said)
                if scraw:
                    schemer = scheming.Schemer(raw=scraw)
                    return schemer.sed.get('title', schema_said)
        except Exception as e:
            logger.warning(f"Failed to resolve schema {schema_said}: {e}")

        return None

    def _get_response_status(self, exn_said: str) -> tuple[bool, str | None]:
        """
        Check if a grant message has been responded to.

        Args:
            exn_said: SAID of the exchange message

        Returns:
            Tuple of (has_response, response_type)
        """
        if not self.app or not self.app.vault:
            return False, None

        try:
            hby = self.app.vault.hby
            response = hby.db.erpy.get(keys=(exn_said,))
            if response is not None:
                rexn, _ = exchanging.cloneMessage(hby, response.qb64)
                if rexn:
                    verb = os.path.basename(os.path.normpath(rexn.ked.get('r', '')))
                    return True, verb.capitalize()
        except Exception as e:
            logger.warning(f"Error checking response status: {e}")

        return False, None

    def _format_grant(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format a GRANT message."""
        try:
            sad = exn.ked.get('e', {}).get('acdc', {})
            iss = exn.ked.get('e', {}).get('iss', {})

            issuer = sad.get('i', 'Unknown')
            issued_on = iss.get('dt', 'Unknown')
            schema = sad.get('s', '')

            schema_title = self._resolve_schema_title(schema) or 'Unknown Credential'
            has_response, response_type = self._get_response_status(exn.said)

            response_str = f" [Responded: {response_type}]" if has_response else " [Pending Response]"

            # Build the base credential info
            cred_info = (
                f"Credential Offered: {schema_title} | "
                f"From: {issuer[:16]}... | "
                f"Issued: {issued_on[:10]}{response_str}"
            )

            # Append the actual message if present
            if actual_message and actual_message.strip():
                message = f"{cred_info} | Message: {actual_message}"
            else:
                message = cred_info

            return "GRANT", message

        except Exception as e:
            logger.warning(f"Error formatting grant message: {e}")
            return "GRANT", f"Credential grant (SAID: {exn.said[:16]}...)"

    def _format_admit(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format an ADMIT message."""
        try:
            hby = self.app.vault.hby
            dig = exn.ked.get('p', '')

            if dig:
                admitted, _ = exchanging.cloneMessage(hby, said=dig)
                if admitted:
                    sad = admitted.ked.get('e', {}).get('acdc', {})
                    cred_said = sad.get('d', 'Unknown')
                    schema = sad.get('s', '')
                    schema_title = self._resolve_schema_title(schema) or 'Unknown Credential'

                    base_message = f"Credential Accepted: {schema_title} | Credential: {cred_said[:16]}..."

                    # Append the actual message if present
                    if actual_message and actual_message.strip():
                        message = f"{base_message} | Message: {actual_message}"
                    else:
                        message = base_message

                    return "ADMIT", message

            return "ADMIT", f"Credential admission (SAID: {exn.said[:16]}...)"

        except Exception as e:
            logger.warning(f"Error formatting admit message: {e}")
            return "ADMIT", f"Credential admission (SAID: {exn.said[:16]}...)"

    def _format_spurn(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format a SPURN message."""
        try:
            hby = self.app.vault.hby
            dig = exn.ked.get('p', '')

            if dig:
                spurned, _ = exchanging.cloneMessage(hby, said=dig)
                if spurned:
                    sroute = spurned.ked.get('r', '')
                    sverb = os.path.basename(os.path.normpath(sroute))

                    if sverb in (Ipex.grant, Ipex.offer):
                        sad = spurned.ked.get('e', {}).get('acdc', {})
                        schema = sad.get('s', '')
                        schema_title = self._resolve_schema_title(schema) or 'Unknown Credential'

                        base_message = f"Rejected {sverb.capitalize()}: {schema_title}"
                    else:
                        base_message = f"Rejected {sverb.capitalize()} (SAID: {spurned.said[:16]}...)"

                    # Append the actual message if present
                    if actual_message and actual_message.strip():
                        message = f"{base_message} | Message: {actual_message}"
                    else:
                        message = base_message

                    return "SPURN", message

            return "SPURN", f"Message rejection (SAID: {exn.said[:16]}...)"

        except Exception as e:
            logger.warning(f"Error formatting spurn message: {e}")
            return "SPURN", f"Message rejection (SAID: {exn.said[:16]}...)"

    def _format_apply(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format an APPLY message."""
        sender = exn.ked.get('i', 'Unknown')
        base_message = f"Credential application from {sender[:16]}..."

        # Append the actual message if present
        if actual_message and actual_message.strip():
            message = f"{base_message} | Message: {actual_message}"
        else:
            message = base_message

        return "APPLY", message

    def _format_offer(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format an OFFER message."""
        try:
            sad = exn.ked.get('e', {}).get('acdc', {})
            schema = sad.get('s', '')
            schema_title = self._resolve_schema_title(schema) or 'Unknown Credential'
            sender = exn.ked.get('i', 'Unknown')

            base_message = f"Credential Offer: {schema_title} | From: {sender[:16]}..."

            # Append the actual message if present
            if actual_message and actual_message.strip():
                message = f"{base_message} | Message: {actual_message}"
            else:
                message = base_message

            return "OFFER", message

        except Exception as e:
            logger.warning(f"Error formatting offer message: {e}")
            return "OFFER", f"Credential offer (SAID: {exn.said[:16]}...)"

    def _format_agree(self, exn, actual_message: str = "") -> tuple[str, str]:
        """Format an AGREE message."""
        sender = exn.ked.get('i', 'Unknown')
        base_message = f"Agreement from {sender[:16]}..."

        # Append the actual message if present
        if actual_message and actual_message.strip():
            message = f"{base_message} | Message: {actual_message}"
        else:
            message = base_message

        return "AGREE", message

    def _format_multisig_notification(self, note, rid: str, timestamp_display: str) -> dict[str, Any] | None:
        """
        Format a multisig protocol notification.

        Args:
            note: Notification object
            rid: Notification ID
            timestamp_display: Formatted timestamp string

        Returns:
            Dict with notification row data, or None if message cannot be loaded
        """
        if not self.app or not self.app.vault:
            return None

        hby = self.app.vault.hby
        attrs = note.attrs
        said = attrs.get('d', '')
        route = note.pad.get('a', {}).get('r', '')

        if not said:
            return self._format_generic_notification(note, rid, timestamp_display)

        try:
            exn, pathed = exchanging.cloneMessage(hby, said)
            if exn is None:
                logger.warning(f"Could not clone multisig message: {said}")
                return self._format_generic_notification(note, rid, timestamp_display)

            # Determine notification type and format message
            if '/multisig/icp' in route:
                message_type, formatted_message = self._format_multisig_icp(exn, pathed)
            elif '/multisig/rot' in route:
                message_type = "MULTISIG_ROT"
                formatted_message = "Multisig rotation request"
            elif '/multisig/ixn' in route:
                message_type = "MULTISIG_IXN"
                formatted_message = "Multisig interaction request"
            else:
                message_type = "MULTISIG"
                formatted_message = f"Multisig notification: {route}"

            return {
                'Type': message_type,
                'Message': formatted_message,
                'Timestamp': timestamp_display,
                'Status': 'Read' if note.read else 'Unread',
                '_rid': rid,
                '_read': note.read,
                '_said': said,
                '_route': route,
            }

        except Exception as e:
            import traceback
            logger.warning(f"Error formatting multisig notification: {e}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            logger.debug(f"Notification attrs: {attrs}")
            logger.debug(f"Notification route: {route}")
            return self._format_generic_notification(note, rid, timestamp_display)

    def _format_multisig_icp(self, exn, pathed) -> tuple[str, str]:
        """Format a multisig inception proposal message."""
        try:
            payload = exn.ked.get('a', {})
            gid = payload.get('gid', 'Unknown')
            smids = payload.get('smids', [])
            initiator = exn.ked.get('i', 'Unknown')

            # Try to resolve initiator alias
            org = self.app.vault.org
            contact = org.get(initiator)
            initiator_alias = contact.get('alias', '') if contact else ''
            initiator_display = initiator_alias or f"{initiator[:12]}..."

            message = (
                f"Group proposal from {initiator_display} | "
                f"Participants: {len(smids)} | "
                f"Group ID: {gid[:16]}..."
            )
            return "MULTISIG_ICP", message

        except Exception as e:
            logger.warning(f"Error formatting multisig icp: {e}")
            return "MULTISIG_ICP", f"Multisig group proposal (SAID: {exn.said[:16]}...)"

    def _on_row_action_signal(self, row_data: dict[str, Any], action: str):
        """
        Handle row action from skewer menu.

        Args:
            row_data: Row data dict with column values
            action: Action name (Mark as Read, Delete)
        """
        rid = row_data.get('_rid', '')
        message = row_data.get('Message', '')
        is_read = row_data.get('_read', False)

        logger.info(f"Row action '{action}' triggered for notification: {message[:50]}...")

        if action == "Mark as Read":
            if not is_read:
                self._mark_as_read(rid)
            else:
                logger.info(f"Notification already marked as read")
        elif action == "Delete":
            self._delete_notification(rid)
        elif action == "Admit":
            self._show_accept_grant_dialog(row_data)
        elif action == "Join":
            notification_type = row_data.get('Type', '')
            if notification_type == "MULTISIG_ROT":
                self._show_join_multisig_rotation_dialog(row_data)
            else:
                self._show_join_multisig_dialog(row_data)
        else:
            logger.warning(f"Unknown action: {action}")

    def _on_row_clicked(self, row_data: dict[str, Any]):
        """
        Handle row click - mark as read if unread.

        Args:
            row_data: Row data dict with column values
        """
        rid = row_data.get('_rid', '')
        is_read = row_data.get('_read', False)

        if not is_read:
            self._mark_as_read(rid)

    def _mark_as_read(self, rid: str):
        """
        Mark notification as read.

        Args:
            rid: Notification ID to mark as read
        """
        try:
            if self.app and self.app.vault:
                success = self.app.vault.notifier.mar(rid)
                if success:
                    logger.info(f"Notification marked as read: {rid}")
                    # Reload notifications to reflect change
                    self._load_notifications()
                    # Update toolbar icon
                    self.app.vault.signals.emit_doer_event(
                        doer_name="MailboxListener",
                        event_type="mark_as_read",
                        data={
                            'notification_id': rid,
                            'success': True
                        }
                    )
                else:
                    logger.error(f"Failed to mark notification as read: {rid}")
        except Exception as e:
            logger.exception(f"Error marking notification as read: {e}")

    def _delete_notification(self, rid: str):
        """
        Delete notification.

        Args:
            rid: Notification ID to delete
        """
        try:
            if self.app and self.app.vault:
                success = self.app.vault.notifier.rem(rid)
                if success:
                    logger.info(f"Notification deleted: {rid}")
                    # Reload notifications to reflect change
                    self._load_notifications()
                    self.app.vault.signals.emit_doer_event(
                        doer_name="MailboxListener",
                        event_type="delete",
                        data={
                            'notification_id': rid,
                            'success': True
                        }
                    )
                else:
                    logger.error(f"Failed to delete notification: {rid}")
        except Exception as e:
            logger.exception(f"Error deleting notification: {e}")

    def _show_accept_grant_dialog(self, row_data: dict[str, Any]):
        """
        Show the Accept Grant dialog for a GRANT notification.

        Args:
            row_data: Row data dict with column values including _said for grant message
        """
        grant_said = row_data.get('_said', '')
        if not grant_said:
            logger.error("No grant SAID available for Admit action")
            return

        if not self.app or not self._parent:
            logger.error("No app or parent available to show AcceptGrantDialog")
            return

        try:
            dialog = AcceptGrantDialog(
                app=self.app,
                parent=self._parent,
                grant_said=grant_said,
                save=False
            )
            dialog.exec()
        except Exception as e:
            logger.exception(f"Error showing AcceptGrantDialog: {e}")

    def _show_join_multisig_dialog(self, row_data: dict[str, Any]):
        """
        Show the Accept Multisig Proposal dialog for a MULTISIG_ICP notification.

        Args:
            row_data: Row data dict with column values including _said for proposal message
        """
        proposal_said = row_data.get('_said', '')
        if not proposal_said:
            logger.error("No proposal SAID available for Join action")
            return

        if not self.app or not self._parent:
            logger.error("No app or parent available to show AcceptMultisigProposalDialog")
            return

        try:
            from locksmith.ui.vault.groups.accept_multisig import AcceptMultisigProposalDialog
            dialog = AcceptMultisigProposalDialog(
                app=self.app,
                parent=self._parent,
                proposal_said=proposal_said
            )
            dialog.exec()
        except Exception as e:
            logger.exception(f"Error showing AcceptMultisigProposalDialog: {e}")

    def _show_join_multisig_rotation_dialog(self, row_data: dict[str, Any]):
        """
        Show the Accept Multisig Rotation dialog for a MULTISIG_ROT notification.

        Args:
            row_data: Row data dict with column values including _said for rotation proposal
        """
        proposal_said = row_data.get('_said', '')
        if not proposal_said:
            logger.error("No proposal SAID available for Join rotation action")
            return

        if not self.app or not self._parent:
            logger.error("No app or parent available to show AcceptMultisigRotationDialog")
            return

        try:
            from locksmith.ui.vault.groups.accept_rotation import AcceptMultisigRotationDialog
            dialog = AcceptMultisigRotationDialog(
                app=self.app,
                parent=self._parent,
                proposal_said=proposal_said
            )
            dialog.exec()
        except Exception as e:
            logger.exception(f"Error showing AcceptMultisigRotationDialog: {e}")

    def set_vault_name(self, vault_name: str):
        """
        Set the vault name for this page.

        Args:
            vault_name: Name of the open vault
        """
        self.vault_name = vault_name

    def on_show(self):
        """Called when page becomes visible - load notifications."""
        logger.info("NotificationsListPage shown, loading notifications")
        self._load_notifications()
