# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.received.accept_grant module

Dialog for accepting and admitting credentials from IPEX grant messages.
"""
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFileDialog
)
from keri import help, kering
from keri.peer import exchanging

from locksmith.core import credentialing, ipexing
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.vault.credentials.presentation import credential_details, credential_name, identifier_name, date_label
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class AcceptGrantDialog(LocksmithDialog):
    """Dialog for accepting credentials from IPEX grant messages.

    Displays the grant message details, optional message from grantor,
    and credential attributes parsed from the schema in read-only format.
    """

    def __init__(
        self,
        app: "LocksmithApplication",
        parent: "VaultPage",
        grant_said: str,
        save: bool = True
    ):
        """
        Initialize the AcceptGrantDialog.

        Args:
            app: Application instance
            parent: Parent widget (VaultPage)
            grant_said: SAID of the grant exn message to process
        """
        self.app = app
        self.vault = app.vault
        self._pending_said = None
        self._listening = False
        self.parent_widget = parent
        self.grant_said = grant_said

        self.save = save

        # Load grant message data
        try:
            self._load_grant_message()
        except Exception as e:
            logger.exception(f"Failed to load grant message: {e}")
            # Create a minimal UI to show error
            self.grant_error = str(e)
            self._build_error_ui()
            return

        # Build the dialog UI
        self._build_ui()

        # Initialize parent dialog
        super().__init__(
            parent=self.parent_widget,
            title="Review credential",
            title_icon=":/assets/material-icons/in-badge.svg",
            content=self.content,
            buttons=self.button_row,
            show_overlay=False,
            show_title_divider=False
        )

        self.fit_content(560)
        for section in (self.credential_details, self.verification):
            self.register_collapsible_section(section)
        self.credential_details.toggle_button.setChecked(True)
        self.content.layout().invalidate()
        self.content.layout().activate()
        self.fit_content(560)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.admit_button.clicked.connect(self._on_admit)
        self.finished.connect(self._disconnect)


    def _load_grant_message(self):
        """Load a verified native grant and its disclosed credential."""
        exn = self.vault.hby.db.exns.get(keys=(self.grant_said,))
        if exn is None or exn.pvrsn.major != 2 or exn.route != '/ipex/grant':
            raise ValueError("A verified ACDC V2 grant is required")
        reply = self.vault.hby.db.erpy.get((self.grant_said,))
        if reply:
            saved = self.vault.hby.db.exns.get((reply.qb64,))
            if saved is None or saved.route != '/ipex/admit':
                raise ValueError('This exchange was declined or closed. Start a new exchange to accept the credential.')
        credential = ipexing.grant_credential(self.vault, self.grant_said)
        self.sender = exn.sad['i']
        self.recipient = exn.sad['ri']
        self.timestamp = exn.sad.get('dt', '')
        self.requires_anchor = (exn.sad['a'].get('ax', [False])[0]
                                and self.vault.hby.db.erpy.get((self.grant_said,)) is None)
        self.acdc_ked = credential.sad
        self.credential_said = credential.said
        self.issuer = credential.sad['i']
        schema = credential.schema
        self.schema_said = schema['$id'] if isinstance(schema, dict) else schema
        if isinstance(schema, dict):
            self.schema = schema
        else:
            schemer = self.vault.hby.db.schema.get(keys=(schema,))
            self.schema = schemer.sed if schemer is not None else {}
        self.subject = credential.iseaid
        nest = next(item for item in exchanging.loadParsedNestedSubstreams(self.vault.hby, self.grant_said)
                    if item.serder.said == self.credential_said)
        try:
            self.authentication = credentialing.authentication(self.vault, nest)['auth']
        except (kering.ValidationError, kering.MissingChainError):
            # Retained history and a committed Admit remain usable for recovery.
            # First acceptance is checked by the backend when the user acts.
            self.authentication = 'unverified'

    def _build_error_ui(self):
        """Build error UI when grant loading fails"""
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        error_label = QLabel(f"Failed to load grant message:\n\n{self.grant_error}")
        error_label.setStyleSheet(f"color: {colors.DANGER}; font-size: 14px;")
        error_label.setWordWrap(True)
        layout.addWidget(error_label)

        layout.addStretch()

        # Close button
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = LocksmithButton("Close")
        button_row.addWidget(close_button)

        # Initialize parent dialog
        super().__init__(
            parent=self.parent_widget,
            title="Accept Credential Grant",
            title_icon=":/assets/material-icons/in-badge.svg",
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(500, 300)
        close_button.clicked.connect(self.close)

    def _build_ui(self):
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)

        title = QLabel(credential_name(self.schema))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)
        sender = identifier_name(self.vault, self.sender)
        participants = f'From {sender}'
        if self.sender != self.issuer:
            participants += f' · Issued by {identifier_name(self.vault, self.issuer)}'
        subject = identifier_name(self.vault, self.subject)
        participants += f'\nCredential subject: {subject}\nReceived by {identifier_name(self.vault, self.recipient)}'
        names = QLabel(participants)
        names.setTextFormat(Qt.TextFormat.PlainText)
        names.setWordWrap(True)
        names.setStyleSheet(f'color: {colors.TEXT_SECONDARY};')
        layout.addWidget(names)
        notice = QLabel('Review the values below before adding this credential.\n' + (
                        'Adding it exports a receipt. No acknowledgment is sent.' if self.save else
                        f'Adding it confirms receipt to {sender}.'))
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        hab = self.vault.hby.habByPre(self.recipient)
        self._anchor_error = ipexing.anchor_error(hab) if self.requires_anchor else None
        self.anchor_notice = QLabel(self._anchor_error or (
            'This rotates your keys and adds a permanent commitment to your key event log.'
            if hab.kever.estOnly else 'This adds a permanent commitment to your key event log.'))
        self.anchor_notice.setWordWrap(True)
        self.anchor_notice.setStyleSheet(f'color: {colors.WARNING_TEXT};')
        self.anchor_notice.setVisible(self.requires_anchor)
        layout.addWidget(self.anchor_notice)
        if not self.schema or self.authentication == 'unverified':
            warning = QLabel('Load the schema before adding this credential.' if not self.schema else
                             'Verification is incomplete.')
            warning.setStyleSheet(f'color: {colors.WARNING_TEXT};')
            layout.addWidget(warning)

        self.credential_details = CollapsibleSection(title='Review credential data and terms')
        attributes = QVBoxLayout()
        self._create_credential_fields_section(attributes)
        self.credential_details.set_content_layout(attributes)
        layout.addWidget(self.credential_details)
        self._create_credential_details_section(layout)

        self.delivery_notice = QLabel('Delivery retries automatically. Follow progress in Activity.')
        self.delivery_notice.setWordWrap(True)
        self.delivery_notice.setStyleSheet(f'color: {colors.TEXT_SECONDARY}; font-size: 13px;')
        self.delivery_notice.hide()
        layout.addWidget(self.delivery_notice)
        layout.addStretch()

        self.button_row = QHBoxLayout()
        self.button_row.setSpacing(8)
        self.cancel_button = LocksmithInvertedButton('Close')
        self.button_row.addWidget(self.cancel_button)
        self.decline_button = LocksmithInvertedButton('Decline')
        self.decline_button.setVisible(self._can_decline())
        self.cancel_button.setVisible(not self._can_decline())
        self.decline_button.clicked.connect(self._on_decline)
        self.button_row.addWidget(self.decline_button)
        self.button_row.addStretch()
        self.admit_button = LocksmithButton('Add and export receipt' if self.save else 'Add credential')
        self.admit_button.setEnabled(not self._anchor_error)
        self.button_row.addWidget(self.admit_button)

    def _can_decline(self):
        grant = self.vault.hby.db.exns.get((self.grant_said,))
        return (not self.save and self.vault.db.receipts.get((self.recipient, self.grant_said)) is None
                and 'Spurn' in ipexing.responses(self.vault, grant))

    def _on_decline(self):
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self.show_error('This vault is closed')
            return
        try:
            if not self._can_decline():
                raise ValueError('This exchange has changed. Return to Activity to review it.')
            ipexing.respond(self.vault, self.grant_said, 'Spurn')
            self.accept()
        except Exception as error:
            self.show_error(str(error))

    def _create_credential_details_section(self, layout: QVBoxLayout):
        """Keep protocol evidence available without crowding the decision."""
        authentication = {'registry': 'Registry', 'anchor': 'Issuer KEL anchor',
                          'signature': 'Issuer signature', 'unverified': 'Not currently verified'}[self.authentication]
        self.verification = CollapsibleSection(title='Verification details')
        details = QVBoxLayout()
        details.addWidget(QLabel(f'Grant · {date_label(self.timestamp)}'))
        details.addWidget(QLabel(f'Authentication: {authentication}'))
        for label, value in (('Sender AID', self.sender), ('Issuer AID', self.issuer),
                             ('Credential ID', self.acdc_ked['d'])):
            row = QHBoxLayout()
            text = QLabel(f'{label}: {value}')
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            row.addWidget(text)
            row.addWidget(LocksmithCopyButton(copy_content=value))
            details.addLayout(row)
        self.verification.set_content_layout(details)
        layout.addWidget(self.verification)

    def _create_credential_fields_section(self, layout: QVBoxLayout):
        """Show the actual origin and linked nodes received in this Grant."""
        for nest in exchanging.loadParsedNestedSubstreams(self.vault.hby, self.grant_said):
            layout.addWidget(credential_details(self.vault, nest.serder.sad))

    def _on_admit(self):
        """Handle Admit button click"""
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self.show_error("This vault is closed")
            return
        # Disable button during processing
        self.admit_button.setEnabled(False)
        self.clear_error()
        self.admit_button.setText("Processing...")
        self.decline_button.setEnabled(False)

        logger.info(f"Admitting credential {self.credential_said}")

        if self.save:
            # Accept and export the acknowledgment when ready.
            self._save_admit_sync()
        else:
            # Send the acknowledgment after acceptance
            self._send_admit_async()

    def _save_admit_sync(self):
        """Accept the credential and save its signed acknowledgment."""
        try:
            hab = self.vault.hby.habByPre(self.recipient)
            serder, attachment = ipexing.admit(self.vault, hab, self.grant_said)
            receipt = self.vault.db.receipts.get((hab.pre, self.grant_said))
            if receipt.status != 'accepted':
                self._pending_said = serder.said
                if not self._listening:
                    self.vault.signals.doer_event.connect(self._on_doer_event)
                    self._listening = True
                self.delivery_notice.setText('Waiting for witness receipts before accepting and exporting.')
                self.delivery_notice.show()
                self.admit_button.setText('Waiting for witnesses...')
                return
            self._disconnect()
            stream = ipexing.prepare(self.vault, hab, serder, attachment)
            self.vault.signals.emit_doer_event("Ipex", "accepted", {'said': serder.said})
            self._save_admit_to_file(serder.said, stream)
        except Exception as error:
            logger.exception("Failed to accept credential")
            self.show_error(f"Failed to accept credential: {error}")
            self._reset_button()

    def _send_admit_async(self):
        """Accept the credential and submit its acknowledgment for delivery."""
        try:
            if self._pending_said:
                ipexing.retry(self.vault, self._pending_said)
            else:
                hab = self.vault.hby.habByPre(self.recipient)
                serder, _ = ipexing.admit(self.vault, hab, self.grant_said, send=True)
                self._pending_said = serder.said
                if self.vault.db.receipts.get((hab.pre, self.grant_said)).status == 'accepted':
                    self.vault.signals.emit_doer_event("Ipex", "accepted", {'said': serder.said})
                self.vault.signals.doer_event.connect(self._on_doer_event)
                self._listening = True
            self.cancel_button.setText("Close")
            self.cancel_button.show()
            self.decline_button.hide()
            self.delivery_notice.setText(
                "Delivery retries automatically. Follow progress in Activity.")
            self.delivery_notice.show()
            self.admit_button.setText("Sending acknowledgment...")
            record = self.vault.db.outbox.get((self._pending_said,))
            if record.status == 'submitted':
                self._on_doer_event('Ipex', 'transport_submitted', {'said': self._pending_said})
            elif record.status == 'blocked':
                self._on_doer_event('Ipex', 'send_failed',
                                    {'said': self._pending_said, 'error': record.error})
        except Exception as error:
            logger.exception("Failed to submit credential acknowledgment")
            self.show_error(f"Failed to submit acknowledgment: {error}")
            self._reset_button()
            receipt = self.vault.db.receipts.get((self.recipient, self.grant_said))
            if receipt is not None and receipt.send:
                self.cancel_button.setText("Close")
                self.cancel_button.show()
                self.decline_button.hide()
                self.delivery_notice.show()
                reply = self.vault.hby.db.erpy.get((self.grant_said,))
                queued = self.vault.db.outbox.get((reply.qb64,)) if reply else None
                if queued is None:
                    self.delivery_notice.setText(
                        "Acceptance preparation is saved. See Credentials → Activity for its status.")

    def _disconnect(self):
        if self._listening:
            self.vault.signals.doer_event.disconnect(self._on_doer_event)
            self._listening = False

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """Show the transport result without inferring the grantor's receipt."""
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self._disconnect()
            return
        if not self._listening:
            return
        if doer_name != "Ipex" or data.get('said') != self._pending_said:
            return
        if self.save and event_type == 'accepted':
            self._disconnect()
            stream = exchanging.serializeMessage(self.vault.hby, self._pending_said)
            self._save_admit_to_file(self._pending_said, stream)
            return
        if event_type == 'awaiting_witnesses':
            self.delivery_notice.setText('Waiting for witness receipts before accepting.')
            self.delivery_notice.show()
            self.admit_button.setText('Waiting for witnesses...')
            return
        if event_type not in ("transport_submitted", "send_failed", "preparation_failed"):
            return
        if event_type == "transport_submitted":
            self._disconnect()
            self.delivery_notice.setText("Acknowledgment submitted. This does not confirm the grantor's receipt.")
            self.admit_button.setEnabled(False)
            self.show_success("Credential accepted. Acknowledgment submitted for delivery.")
            QTimer.singleShot(2000, self.accept)
        else:
            receipt = self.vault.db.receipts.get((self.recipient, self.grant_said))
            outcome = ('Credential accepted, but acknowledgment delivery failed'
                       if receipt.status == 'accepted' else 'Acceptance preparation failed')
            self.show_error(f"{outcome}: {data.get('error', 'Unknown error')}")
            self._reset_button()
            record = self.vault.db.outbox.get((self._pending_said,))
            if record is not None and record.status == 'blocked':
                self.admit_button.setEnabled(True)
                self.delivery_notice.setText("Check delivery details in Credentials → Activity.")

    def _save_admit_to_file(self, admit_said: str, admit_message: bytes):
        """
        Save admit message to file.

        Args:
            admit_said: SAID of the admit message
            admit_message: Serialized admit message bytes
        """
        # Open save dialog
        default_filename = f"admit-{admit_said}.cesr"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Admit Message",
            default_filename,
            "CESR Files (*.cesr);;All Files (*)"
        )

        if file_path:
            try:
                # Write to file
                with open(file_path, 'wb') as f:
                    f.write(admit_message)

                logger.info(f"Admit message saved successfully to {file_path}")

                # Show success and close
                self.show_success(f"Admit message saved to {file_path}")

                # Close dialog after short delay to show success message
                QTimer.singleShot(1500, self.accept)

            except Exception as e:
                logger.exception(f"Failed to save admit message: {e}")
                self.show_error(f"Credential added, but receipt export failed: {str(e)}")
                self._reset_button()
        else:
            # User cancelled save dialog
            self.delivery_notice.setText('Credential added; receipt not exported. You can export it later.')
            self.delivery_notice.show()
            self._reset_button()

    def _reset_button(self):
        """Reset admit button to enabled state."""
        self.admit_button.setEnabled(True)
        self.decline_button.setEnabled(self._can_decline())
        receipt = self.vault.db.receipts.get((self.recipient, self.grant_said))
        self.admit_button.setText("Export receipt" if self.save and receipt and receipt.status == 'accepted' else
                                 "Retry acceptance" if self.save and self._pending_said else
                                 "Retry sending" if self._pending_said else
                                 "Add and export receipt" if self.save else "Add credential")
