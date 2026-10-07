# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.grant module

Dialog for granting (sending or saving) issued credentials.
"""
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QButtonGroup, QFileDialog
)
from keri import help

from locksmith.core import credentialing, ipexing
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton, LocksmithIconButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, FloatingLabelLineEdit
from locksmith.ui.vault.credentials.presentation import attribute_view, identifier_name
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class GrantCredentialDialog(LocksmithDialog):
    """Dialog for granting (sending or saving) an issued credential.

    Two modes:
    - Send: Share credential with a remote identifier via IPEX
    - Save: Export credential to CESR file
    """

    def __init__(
        self,
        app: "LocksmithApplication",
        parent: "VaultPage",
        credential_said: str,
        credential_schema: str,
        credential_issuer: str
    ):
        """
        Initialize the GrantCredentialDialog.

        Args:
            app: Application instance
            parent: Parent widget (VaultPage)
            credential_said: SAID of the credential to grant
            credential_schema: Schema name/title for display
            credential_issuer: Issuer/Recipient identifier for display
        """
        self.app = app
        self.vault = app.vault
        self._pending_said = None
        self._listening = False
        self.parent_widget = parent
        self.credential_said = credential_said
        self.credential_schema = credential_schema
        self.credential_issuer = credential_issuer

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)
        title = QLabel(credential_schema)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)
        issuer = QLabel(f'Issued by {identifier_name(self.vault, credential_issuer)}')
        issuer.setTextFormat(Qt.TextFormat.PlainText)
        issuer.setStyleSheet(f'color: {colors.TEXT_SECONDARY};')
        layout.addWidget(issuer)
        self.recipient_dropdown = FloatingLabelComboBox(label_text='To')
        self._populate_recipients()
        layout.addWidget(self.recipient_dropdown)
        self.sharing_notice = QLabel('This shares the whole credential with the recipient.')
        self.sharing_notice.setWordWrap(True)
        layout.addWidget(self.sharing_notice)

        review = CollapsibleSection(title='Review credential details')
        review_layout = QVBoxLayout()
        view = credentialing.credential(self.vault, credential_said)
        attrs = view['sad'].get('a', {})
        if isinstance(attrs, dict):
            for key, value in attrs.items():
                if key not in ('d', 'i'):
                    review_layout.addWidget(attribute_view(key, value))
        review.set_content_layout(review_layout)
        layout.addWidget(review)

        self.options = CollapsibleSection(title='More options')
        options_layout = QVBoxLayout()
        self.message_field = FloatingLabelLineEdit(label_text='Message (optional)')
        options_layout.addWidget(self.message_field)
        radio_layout = QHBoxLayout()
        self.send_radio = LocksmithRadioButton('Send')
        self.send_radio.setChecked(True)
        self.save_radio = LocksmithRadioButton('Export to file')
        radio_layout.addWidget(self.send_radio)
        radio_layout.addWidget(self.save_radio)
        radio_layout.addStretch()
        options_layout.addLayout(radio_layout)
        file_row = QHBoxLayout()
        self.file_name_field = FloatingLabelLineEdit(label_text='File name')
        self.file_name_field.setText(self._generate_default_filename())
        self.file_name_field.hide()
        file_row.addWidget(self.file_name_field)
        self.browse_button = LocksmithIconButton(':/assets/material-icons/browse.svg', tooltip='Browse files')
        self.browse_button.setFixedSize(48, 48)
        self.browse_button.hide()
        file_row.addWidget(self.browse_button)
        options_layout.addLayout(file_row)
        self.options.set_content_layout(options_layout)
        layout.addWidget(self.options)
        self.delivery_notice = QLabel('Delivery retries automatically. Follow progress in Activity.')
        self.delivery_notice.setWordWrap(True)
        self.delivery_notice.setStyleSheet(f'color: {colors.TEXT_SECONDARY}; font-size: 13px;')
        self.delivery_notice.hide()
        layout.addWidget(self.delivery_notice)
        layout.addStretch()
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.cancel_button = LocksmithInvertedButton('Cancel')
        button_row.addWidget(self.cancel_button)
        button_row.addStretch()
        self.action_button = LocksmithButton('Send credential')
        button_row.addWidget(self.action_button)
        super().__init__(parent=parent, title='Send credential',
                         title_icon=':/assets/material-icons/share.svg',
                         content=content_widget, buttons=button_row, show_overlay=False,
                         show_title_divider=False)
        self.fit_content(560)
        self.register_collapsible_section(review)
        self.register_collapsible_section(self.options)
        self.grant_type_group = QButtonGroup(self)
        self.grant_type_group.addButton(self.send_radio)
        self.grant_type_group.addButton(self.save_radio)
        self.cancel_button.clicked.connect(self.close)
        self.send_radio.toggled.connect(self._on_grant_type_changed)
        self.save_radio.toggled.connect(self._on_grant_type_changed)
        self.browse_button.clicked.connect(self._browse_file)
        self.action_button.clicked.connect(self._on_grant)
        self.finished.connect(self._disconnect)

    def _populate_recipients(self):
        """Populate recipient dropdown from vault organizer (remote identifiers)."""
        self.recipient_dropdown.clear()

        if not self.vault:
            return

        try:
            org = self.vault.org
            remote_ids = org.list()
            recipient = credentialing.credential(self.vault, self.credential_said)['recipient']

            default_index = -1
            current_index = 0

            for remote_id in remote_ids:
                pre = remote_id.get('id', '')
                display_text = identifier_name(self.vault, pre)

                # Store full prefix as userData
                self.recipient_dropdown.addItem(display_text, userData=pre)

                # Check if this is the credential's recipient (default selection)
                if pre == recipient:
                    default_index = current_index

                current_index += 1

            # Set default selection to credential's recipient if found
            if default_index >= 0:
                self.recipient_dropdown.setCurrentIndex(default_index)
            elif self.recipient_dropdown.count() > 0:
                self.recipient_dropdown.setCurrentIndex(0)

            if self.recipient_dropdown.count() == 0:
                # No remote identifiers available
                self.recipient_dropdown.addItem("No remote identifiers available")
                self.recipient_dropdown.setCurrentIndex(0)
                self.recipient_dropdown.setEnabled(False)

        except Exception as e:
            logger.exception(f"Error loading recipients: {e}")
            self.recipient_dropdown.addItem("Error loading recipients")
            self.recipient_dropdown.setEnabled(False)
            self.show_error(f"Failed to load recipients: {str(e)}")

    def _generate_default_filename(self) -> str:
        """
        Generate a default filename for credential export.

        Format: {schema-name}-{short-said}.cesr
        Example: driver-license-EAbCD123.cesr
        """
        # Sanitize schema name
        schema_safe = self.credential_schema.lower()
        schema_safe = schema_safe.replace(' ', '-')
        schema_safe = ''.join(c for c in schema_safe if c.isalnum() or c == '-')

        # Get short SAID (first 8 characters)
        short_said = self.credential_said[:8] if len(self.credential_said) > 8 else self.credential_said

        return f"{schema_safe}-{short_said}.cesr"

    def _on_grant_type_changed(self):
        """Handle grant type radio button changes."""
        if self.send_radio.isChecked():
            # Show Send mode UI
            self.file_name_field.hide()
            self.browse_button.hide()
            self.action_button.setText("Send credential")
            self.sharing_notice.setText("This shares the whole credential with the recipient.")
        else:
            # Show Save mode UI
            self.file_name_field.show()
            self.browse_button.show()
            self.action_button.setText("Export credential")
            self.sharing_notice.setText("Exports the credential for this recipient. Nothing is sent.")
        self.options.update_content_height()

    def _browse_file(self):
        """Open file save dialog to select output path."""
        # Get current filename as default
        default_filename = self.file_name_field.text().strip() or "credential.cesr"

        # Ensure .cesr extension
        if not default_filename.endswith('.cesr'):
            default_filename += '.cesr'

        # Open save dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Credential",
            default_filename,
            "CESR Files (*.cesr);;All Files (*)"
        )

        if file_path:
            # Update filename field with selected path
            self.file_name_field.setText(file_path)

    def _validate_fields(self) -> bool:
        """
        Validate all required fields based on current mode.

        Returns:
            bool: True if validation passes, False otherwise
        """
        # Clear any previous errors
        self.clear_error()

        failed_fields = []

        if not self.send_radio.isChecked():
            # Validate Save mode: File name must be provided
            file_name = self.file_name_field.text().strip()
            if not file_name:
                failed_fields.append("File Name")
                self.file_name_field.setProperty("error", True)
                self.file_name_field.style().unpolish(self.file_name_field)
                self.file_name_field.style().polish(self.file_name_field)

        if failed_fields:
            field_text = "field" if len(failed_fields) == 1 else "fields"
            self.show_error(f"Please fill in required {field_text}: {', '.join(failed_fields)}")
            return False

        return True

    def _on_grant(self):
        """Create a grant after the user selects its recipient and delivery mode."""
        self.clear_error()
        if not self._validate_fields():
            return
        self.action_button.setEnabled(False)
        self.action_button.setText("Processing...")
        try:
            if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
                raise ValueError("This vault is closed")
            if self._pending_said:
                ipexing.retry(self.vault, self._pending_said)
                self.action_button.setText("Sending...")
                return
            hab = self.vault.hby.habByPre(self.credential_issuer)
            if hab is None:
                raise ValueError("The credential issuer is not a local identifier")
            serder, attachment = ipexing.grant(
                self.vault, hab, self.credential_said,
                self.recipient_dropdown.currentData(), self.message_field.text(),
            )
            if self.send_radio.isChecked():
                self._send_grant(hab, serder, attachment)
            else:
                stream = ipexing.prepare(self.vault, hab, serder, attachment)
                self._save_grant(stream)
        except Exception as error:
            logger.exception("Failed to create credential grant")
            self.show_error(f"Failed to create grant: {error}")
            self._reset_button()

    def _send_grant(self, hab, serder, attachment):
        """Submit the signed grant through the vault's transport."""
        self._pending_said = ipexing.submit(self.vault, hab, serder, attachment)
        self.cancel_button.setText("Close")
        self.delivery_notice.show()
        self.vault.signals.doer_event.connect(self._on_doer_event)
        self._listening = True
        # A retry sends this same grant, including its recipient and message.
        for field in (self.recipient_dropdown, self.message_field, self.send_radio, self.save_radio):
            field.setEnabled(False)
        self.action_button.setText("Sending...")

    def _disconnect(self):
        if self._listening:
            self.vault.signals.doer_event.disconnect(self._on_doer_event)
            self._listening = False

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """Show the transport result for this grant."""
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self._disconnect()
            return
        if not self._listening:
            return
        if doer_name != "Ipex" or data.get('said') != self._pending_said:
            return
        if event_type not in ("transport_submitted", "send_failed"):
            return
        if event_type == "transport_submitted":
            self._disconnect()
            self.delivery_notice.setText("Submitted for delivery. Peer acceptance is separate.")
            self.action_button.setEnabled(False)
            self.show_success("Grant submitted for delivery")
            QTimer.singleShot(2000, self.accept)
        else:
            self.show_error(f"Failed to send: {data.get('error', 'Unknown error')}")
            self._reset_button()
            record = self.vault.db.outbox.get((self._pending_said,))
            if record.status == 'blocked':
                self.action_button.setEnabled(False)
                self.delivery_notice.setText("Delivery stopped. See Credentials → Activity for details.")

    def _save_grant(self, grant: bytes):
        """Save credential to file in CESR format."""
        file_path = self.file_name_field.text().strip()

        # Ensure .cesr extension
        if not file_path.endswith('.cesr'):
            file_path += '.cesr'

        try:
            logger.info(f"Saving credential {self.credential_said} to {file_path}")

            # Write to file
            with open(file_path, 'wb') as f:
                f.write(grant)

            logger.info(f"Grant message saved successfully to {file_path}")

            # Show success and close
            self.show_success(f"Grant message saved to {file_path}")

            # Close dialog after short delay to show success message
            QTimer.singleShot(1500, self.accept)

        except Exception as e:
            logger.exception(f"Failed to save credential: {e}")
            self.show_error(f"Failed to save credential: {str(e)}")
            self._reset_button()

    def _reset_button(self):
        """Reset action button to enabled state."""
        self.action_button.setEnabled(True)
        button_text = "Retry sending" if self._pending_said else ("Send credential" if self.send_radio.isChecked() else "Export credential")
        self.action_button.setText(button_text)
