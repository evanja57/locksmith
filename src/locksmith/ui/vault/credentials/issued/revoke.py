"""Confirm a registry revocation and collect current witness authentication."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri.core import SerderACDC

from locksmith.core.credentialing import RevokeCredentialDoer
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from locksmith.ui.vault.shared.witness_auth_mixin import WitnessAuthenticationPanel


class RevokeCredentialDialog(LocksmithDialog):
    def __init__(self, app, credential_said, credential_schema, parent=None):
        self.app, self.vault = app, app.vault
        self.credential_said = credential_said
        self._revocation_id = None
        self._closed = False
        content = QWidget()
        layout = QVBoxLayout(content)
        notice = QLabel(f'Revoke {credential_schema}? This permanently invalidates the credential. '
                        'A pending revocation can be retried with the same registry update.')
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        record = self.vault.db.issued.get((credential_said,))
        acdc = SerderACDC(raw=record.raw.encode()) if record else None
        hab = self.vault.hby.habByPre(acdc.israid) if acdc else None
        self.auth_panel = None
        if hab and hab.kever.wits:
            self.auth_panel = WitnessAuthenticationPanel(app, hab, list(hab.kever.wits))
            layout.addWidget(self.auth_panel)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = LocksmithInvertedButton('Cancel')
        self.revoke_button = LocksmithButton('Revoke credential')
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.revoke_button)
        super().__init__(parent=parent, title='Revoke credential', content=content, buttons=buttons)
        self.cancel_button.clicked.connect(self.reject)
        self.revoke_button.clicked.connect(self._revoke)
        self.vault.signals.doer_event.connect(self._on_event)
        self.finished.connect(self._finish)
        if not acdc or not acdc.regid or not hab:
            self.revoke_button.setEnabled(False)
            self.show_error('This credential has no local revocable registry')

    def _revoke(self):
        if self._closed or self.app.vault is not self.vault or self.vault.closed:
            self.show_error('This vault is closed. Open the credential in the current vault.')
            return
        codes = None
        if self.auth_panel:
            valid, codes, error = self.auth_panel.validate_authentication_codes()
            if not valid:
                self.show_error(error)
                return
        self.clear_error()
        doer = RevokeCredentialDoer(self.app, self.credential_said, codes=codes)
        self._revocation_id = doer.revocation_id
        self.revoke_button.setEnabled(False)
        self.revoke_button.setText('Revoking…')
        self.vault.extend([doer])

    def _on_event(self, name, event, data):
        if (self._closed or self.app.vault is not self.vault or self.vault.closed
                or name != 'RevokeCredentialDoer' or data.get('revocation_id') != self._revocation_id):
            return
        if event == 'credential_revoked':
            self.accept()
        elif event == 'credential_revocation_failed':
            self._revocation_id = None
            self.revoke_button.setEnabled(True)
            self.revoke_button.setText('Retry revocation')
            self.show_error(data.get('error', 'Revocation failed'))

    def _finish(self, result):
        self._closed = True
        try:
            self.vault.signals.doer_event.disconnect(self._on_event)
        except RuntimeError:
            pass
