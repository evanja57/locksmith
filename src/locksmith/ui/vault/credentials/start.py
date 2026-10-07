"""Start a credential exchange from its schema or inventory."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from locksmith.core import credentialing, ipexing
from locksmith.core.habbing import list_eligible_local_identifiers
from locksmith.ui.toolkit.widgets import LocksmithButton, LocksmithDialog, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, LocksmithPlainTextEdit
from locksmith.ui.vault.credentials.presentation import credential_name, identifier_name


class StartExchangeDialog(LocksmithDialog):
    """Start a whole-credential request or reference-only offer."""

    submitted = Signal(str)

    def __init__(self, app, parent, action, *, schema=None, credential_said=None):
        self.app, self.vault, self.action = app, app.vault, action
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if action == 'Offer':
            explanation = QLabel('Only a reference is shared. Details are sent later.')
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
        self.sender = FloatingLabelComboBox('Your identifier')
        for identifier in list_eligible_local_identifiers(app):
            self.sender.addItem(self._name(identifier['prefix']), identifier['prefix'])
        if self.sender.count() != 1:
            layout.addWidget(self.sender)
        else:
            self.sender.hide()
        self.recipient = FloatingLabelComboBox('To')
        self.recipient.addItem('Choose a contact', None)
        peers = {contact['id'] for contact in self.vault.org.list()}
        peers.update(self.vault.hby.prefixes)
        for pre in sorted(peers):
            self.recipient.addItem(self._name(pre), pre)
        layout.addWidget(self.recipient)
        self.selection = FloatingLabelComboBox('Credential type' if action == 'Apply' else 'Credential')
        if action == 'Apply':
            for (said,), schemer in self.vault.hby.db.schema.getTopItemIter():
                self.selection.addItem(credential_name(schemer.sed), said)
        else:
            for view in credentialing.credentials(self.vault):
                if view['status']['et'] in ('issued', 'authenticated'):
                    self.selection.addItem(credential_name(view['schema']) + ' · ' + view['sad']['d'][:8] + '…',
                                           view['sad']['d'])
        selected = schema if action == 'Apply' else credential_said
        if selected:
            self.selection.setCurrentIndex(self.selection.combo_box.findData(selected))
            self.selection.setEnabled(False)
        layout.addWidget(self.selection)
        self.message = LocksmithPlainTextEdit()
        self.message.setMaximumHeight(90)
        options = CollapsibleSection(title='Add a message')
        options_layout = QVBoxLayout()
        options_layout.addWidget(self.message)
        options.set_content_layout(options_layout)
        layout.addWidget(options)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
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
        self.register_collapsible_section(options)
        cancel.clicked.connect(self.close)
        self.send_button.clicked.connect(self._send)

    def _name(self, pre):
        return identifier_name(self.vault, pre)

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
            said = ipexing.start(self.vault, hab, self.recipient.currentData(), self.action,
                          self.message.toPlainText().strip(), **selection)
            self.accept()
            self.submitted.emit(said)
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            self.send_button.setEnabled(True)
