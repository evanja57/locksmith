"""Start a credential exchange from its schema or inventory."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from locksmith.core import credentialing, ipexing
from locksmith.core.habbing import list_eligible_local_identifiers
from locksmith.ui.toolkit.widgets import LocksmithButton, LocksmithDialog, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from locksmith.ui.vault.credentials.presentation import (credential_details, credential_name,
                                                        disclosed_credentials, identifier_name)
from locksmith.ui.vault.remotes.add import AddRemoteIdentifierDialog


class StartExchangeDialog(LocksmithDialog):
    """Start a credential request or offer with a compact preview."""

    submitted = Signal(str)

    def __init__(self, app, parent, action, *, schema=None, credential_said=None, received=False):
        self.app, self.vault, self.action = app, app.vault, action
        self.received = received
        self._offer_error = ''
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if action == 'Offer':
            explanation = QLabel('Shares the issuer, credential type, and terms below. '
                                 'Credential values are sent after agreement.')
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
        self.sender = FloatingLabelComboBox('Your identifier')
        for identifier in list_eligible_local_identifiers(app):
            self.sender.addItem(self._name(identifier['prefix']), identifier['prefix'])
        if self.sender.count() != 1:
            self.sender.setCurrentIndex(-1)
            layout.addWidget(self.sender)
        else:
            self.sender.hide()
        self.recipient = FloatingLabelComboBox('To')
        layout.addWidget(self.recipient)
        self.selection = FloatingLabelComboBox('Credential type' if action == 'Apply' else 'Credential')
        if action == 'Apply':
            for (said,), schemer in self.vault.hby.db.schema.getTopItemIter():
                self.selection.addItem(credential_name(schemer.sed), said)
        else:
            for view in credentialing.credentials(self.vault, received=True if received else None):
                if (view['status']['et'] in ('issued', 'authenticated') and
                        (view['held'] or view['sad']['i'] in self.vault.hby.prefixes)):
                    self.selection.addItem(credential_name(view['schema']) + ' · ' + view['sad']['d'][:8] + '…',
                                           view['sad']['d'])
        selected = schema if action == 'Apply' else credential_said
        if selected:
            self.selection.setCurrentIndex(self.selection.combo_box.findData(selected))
            self.selection.setEnabled(False)
        layout.addWidget(self.selection)
        self.preview = QWidget()
        preview_layout = QVBoxLayout(self.preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview.setVisible(action == 'Offer')
        layout.addWidget(self.preview)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        self.repair_button = LocksmithInvertedButton('Import delivery details')
        self.repair_button.clicked.connect(self._repair_route)
        layout.addWidget(self.repair_button)
        cancel = LocksmithInvertedButton('Cancel')
        self.send_button = LocksmithButton('Send application' if action == 'Apply' else 'Send offer')
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.send_button)
        super().__init__(parent, title='Apply for credential' if action == 'Apply' else 'Offer credential',
                         content=content, buttons=buttons, show_title_divider=False)
        self.fit_content(540)
        cancel.clicked.connect(self.close)
        self.send_button.clicked.connect(self._send)
        self.sender.currentIndexChanged.connect(self._update_recipients)
        self.recipient.currentIndexChanged.connect(self._check_route)
        self.selection.currentIndexChanged.connect(self._select_sender)
        self._select_sender()
        self._update_recipients()

    def _name(self, pre):
        return identifier_name(self.vault, pre)

    def _update_recipients(self, *_):
        """Keep the recipient choice when it remains valid for the sender."""
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self.send_button.setEnabled(False)
            return
        selected = self.recipient.currentData()
        peers = {contact['id'] for contact in self.vault.org.list()}
        peers.update(self.vault.hby.prefixes)
        peers.discard(self.sender.currentData())
        with QSignalBlocker(self.recipient):
            self.recipient.clear()
            self.recipient.addItem('Choose a contact', None)
            for pre in sorted(peers, key=lambda pre: (self._name(pre).casefold(), pre)):
                self.recipient.addItem(self._name(pre), pre)
            self.recipient.setCurrentIndex(max(0, self.recipient.combo_box.findData(selected)))
        self._check_route()

    def _select_sender(self, *_):
        if self.action == 'Offer' and self.selection.currentData():
            said = self.selection.currentData()
            view = credentialing.credential(self.vault, said, received=self.received)
            pre = (view['sad']['i'] if not self.received and self.vault.db.issued.get((said,))
                   else view['subject'])
            self.sender.setCurrentIndex(self.sender.combo_box.findData(pre))
        if self.action == 'Offer':
            layout = self.preview.layout()
            while layout.count():
                widget = layout.takeAt(0).widget()
                widget.setParent(None)
                widget.deleteLater()
            self._offer_error = ''
            try:
                if self.selection.currentData():
                    for node in disclosed_credentials(self.vault, self.selection.currentData(), metadata=True):
                        layout.addWidget(credential_details(self.vault, node))
            except Exception as error:
                self._offer_error = str(error)
            self.fit_content(540)
        self._check_route()

    def _check_route(self, *_):
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self.send_button.setEnabled(False)
            return
        hab = self.vault.hby.habByPre(self.sender.currentData())
        recipient = self.recipient.currentData()
        error = self._offer_error
        missing_recipient = False
        if hab is not None and recipient and recipient != hab.pre and not error:
            try:
                ipexing._require_route(hab, recipient)
            except ipexing.MissingRouteError as ex:
                error = str(ex)
                missing_recipient = True
            except Exception as ex:
                error = str(ex)
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.repair_button.setVisible(missing_recipient)
        self.send_button.setEnabled(bool(hab and recipient and recipient != hab.pre
                                         and self.selection.currentData() and not error))

    def _repair_route(self):
        self._repair_dialog = AddRemoteIdentifierDialog(self.app, self)
        self._repair_dialog.finished.connect(self._return_from_repair)
        self.hide()
        self._repair_dialog.open()

    def _return_from_repair(self, *_):
        if self.app.vault is self.vault and not getattr(self.vault, 'closed', False):
            self._update_recipients()
            self.open()

    def _send(self):
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self.error.setText('This vault is closed.')
            self.error.show()
            return
        self.send_button.setEnabled(False)
        try:
            hab = self.vault.hby.habByPre(self.sender.currentData())
            if hab is None:
                raise ValueError('Choose your identifier')
            selection = {'schema' if self.action == 'Apply' else 'credential_said': self.selection.currentData()}
            said = ipexing.start(self.vault, hab, self.recipient.currentData(), self.action, **selection)
            self.accept()
            self.submitted.emit(said)
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            self.send_button.setEnabled(True)
