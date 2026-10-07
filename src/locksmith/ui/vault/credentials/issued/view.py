# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.view module

Dialog for viewing issued credential details
"""
import json
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout
)
from locksmith.ui import colors
from locksmith.core import credentialing
from locksmith.ui.vault.credentials.presentation import attribute_view, credential_name, identifier_name, date_label, status_label
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection

from locksmith.ui.toolkit.widgets import (
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.dialogs import LocksmithDialog
from locksmith.ui.toolkit.widgets.fields import (
    LocksmithLineEdit,
    LocksmithPlainTextEdit
)

logger = logging.getLogger(__name__)


class ViewIssuedCredentialDialog(LocksmithDialog):
    """Dialog for viewing issued credential details."""
    def __init__(self, icon_path, app, credential_said, parent=None, received=False):
        """
        Initialize the ViewIssuedCredentialDialog.

        Args:
            icon_path: Path to the credential icon
            app: Application instance
            credential_said: SAID of the credential to view
            parent: Parent widget (typically VaultPage)
        """
        self.app = app
        self.credential_said = credential_said
        self.received = received

        # Get the credential details from the app
        try:
            self.credential = credentialing.credential(self.app.vault, self.credential_said, received=received)

            # Get schema info
            self.schema_title = credential_name(self.credential.get("schema"))

        except Exception as e:
            logger.error(f"Error loading credential: {e}")
            raise

        # Create title content FIRST (before super().__init__)
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(icon_path)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel(f"  {self.schema_title}")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_content.addWidget(title_label)
        title_content_widget.setLayout(title_content)

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(15)

        # Create button row
        button_row = QHBoxLayout()
        self.close_button = LocksmithInvertedButton("Close")
        if hasattr(parent, 'show_credential_activity'):
            self.history_button = LocksmithInvertedButton('View exchange history')
            self.history_button.clicked.connect(
                lambda: (self.close(), parent.show_credential_activity(credential_said, received=received)))
            button_row.addWidget(self.history_button)
        button_row.addWidget(self.close_button)

        # Initialize parent dialog EARLY
        super().__init__(
            parent=parent,
            title_content=title_content_widget,
            show_close_button=True,
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        # Set initial size
        self.resize(620, 650)

        self._build_issuer_section(layout)
        self._build_recipient_section(layout)
        self._build_status_section(layout)
        self._build_issued_date_section(layout)
        attributes = self.credential['sad'].get('a', {})
        schema = self.credential.get('schema') or {}
        definition = schema.get('properties', {}).get('a', {})
        definition = definition if isinstance(definition, dict) else {}
        definition = next((item for item in definition.get('oneOf', [definition])
                           if isinstance(item, dict) and item.get('type') == 'object'), {})
        for name, value in attributes.items() if isinstance(attributes, dict) else []:
            if name in ('d', 'i'):
                continue
            prop = definition.get('properties', {}).get(name, {})
            prop = prop if isinstance(prop, dict) else {}
            layout.addWidget(attribute_view(prop.get('description', name), value, prop))
        verification = CollapsibleSection(title='Verification details')
        details = QVBoxLayout()
        auth = self.credential['status'].get('auth')
        details.addWidget(QLabel('Authentication: ' + {'anchor': 'Issuer KEL anchor',
            'signature': 'Issuer signature', 'registry': 'Registry'}.get(auth, 'Not currently verified')))
        for label, pre in (('Issuer AID', self.credential['sad']['i']),
                           ('Recipient AID', self.credential['recipient'])):
            if pre:
                row = QHBoxLayout()
                text = QLabel(f'{label}: {pre}')
                text.setTextFormat(Qt.TextFormat.PlainText)
                text.setWordWrap(True)
                row.addWidget(text)
                row.addWidget(LocksmithCopyButton(copy_content=pre))
                details.addLayout(row)
        self._build_said_section(details)
        self._build_schema_section(details)
        self._build_credential_content_section(details)
        verification.set_content_layout(details)
        layout.addWidget(verification)
        self.register_collapsible_section(verification)

        # Connect buttons
        self.close_button.clicked.connect(self.close)

    def _build_said_section(self, layout):
        """Build the SAID section with copy button."""
        said_label_row = QHBoxLayout()
        said_label_row.setSpacing(5)
        said_label = QLabel("Credential SAID")
        said_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        said_label_row.addWidget(said_label)

        self.copy_said_button = LocksmithCopyButton(copy_content=self.credential_said)
        self.copy_said_button.setFixedHeight(36)
        said_label_row.addWidget(self.copy_said_button)
        said_label_row.addStretch()
        layout.addLayout(said_label_row)

        self.said_field = LocksmithLineEdit("Credential SAID")
        self.said_field.setText(self.credential_said)
        self.said_field.setReadOnly(True)
        self.said_field.setCursorPosition(0)
        self.said_field.setMinimumWidth(420)
        layout.addWidget(self.said_field)

    def _build_schema_section(self, layout):
        """Build the schema section."""
        schema_label = QLabel("Schema")
        schema_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(schema_label)

        self.schema_field = LocksmithLineEdit("Schema")
        self.schema_field.setText(self.schema_title)
        self.schema_field.setReadOnly(True)
        self.schema_field.setCursorPosition(0)
        self.schema_field.setMinimumWidth(420)
        layout.addWidget(self.schema_field)

    def _build_issuer_section(self, layout):
        """Build the issuer section."""
        issuer_label = QLabel("Issuer")
        issuer_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(issuer_label)

        # Get issuer prefix from credential
        issuer_pre = self.credential['sad']['i']

        issuer_display = identifier_name(self.app.vault, issuer_pre)

        self.issuer_field = LocksmithLineEdit("Issuer")
        self.issuer_field.setText(issuer_display)
        self.issuer_field.setReadOnly(True)
        self.issuer_field.setCursorPosition(0)
        self.issuer_field.setMinimumWidth(420)
        layout.addWidget(self.issuer_field)

    def _build_recipient_section(self, layout):
        """Build the recipient section."""
        recipient_label = QLabel("Recipient")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(recipient_label)

        # Get recipient from credential attributes
        attributes = self.credential['sad'].get('a', {})
        recipient_pre = attributes.get('i', '') if isinstance(attributes, dict) else ''

        recipient_display = identifier_name(self.app.vault, recipient_pre)

        self.recipient_field = LocksmithLineEdit("Recipient")
        self.recipient_field.setText(recipient_display)
        self.recipient_field.setReadOnly(True)
        self.recipient_field.setCursorPosition(0)
        self.recipient_field.setMinimumWidth(420)
        layout.addWidget(self.recipient_field)

    def _build_status_section(self, layout):
        """Build the status section."""
        label = QLabel("Status")
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)

        # Determine credential status
        status = self.credential.get("status", {})
        status_text = status_label(status)

        self.status_field = LocksmithLineEdit("Status")
        self.status_field.setText(status_text)
        self.status_field.setReadOnly(True)
        self.status_field.setCursorPosition(0)
        self.status_field.setMinimumWidth(420)
        layout.addWidget(self.status_field)

    def _build_issued_date_section(self, layout):
        """Build the issued date section."""
        date_title = "Accepted" if self.received else "Created"
        label = QLabel(date_title)
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)

        self.date_field = LocksmithLineEdit(date_title)
        self.date_field.setText(date_label(self.credential['accepted_at' if self.received else 'created_at']))
        self.date_field.setReadOnly(True)
        self.date_field.setCursorPosition(0)
        self.date_field.setMinimumWidth(420)
        layout.addWidget(self.date_field)

    def _build_credential_content_section(self, layout):
        """Build the credential content section showing full JSON."""
        content_label_row = QHBoxLayout()
        content_label_row.setSpacing(5)
        content_label = QLabel("Credential Content")
        content_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        content_label_row.addWidget(content_label)

        # Add copy button for credential content
        credential_json = json.dumps(self.credential['sad'], indent=2)
        self.copy_content_button = LocksmithCopyButton(copy_content=credential_json)
        self.copy_content_button.setFixedHeight(36)
        content_label_row.addWidget(self.copy_content_button)
        content_label_row.addStretch()
        layout.addLayout(content_label_row)

        self.content_field = LocksmithPlainTextEdit()
        self.content_field.setPlainText(credential_json)
        self.content_field.setReadOnly(True)
        self.content_field.setFixedHeight(200)
        self.content_field.setMaximumWidth(480)
        # Use monospace font for JSON
        font = self.content_field.font()
        font.setFamily("Menlo, SF Mono, Monaco, Courier New, monospace")
        font.setPointSize(11)
        self.content_field.setFont(font)
        layout.addWidget(self.content_field)
