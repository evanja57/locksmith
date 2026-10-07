from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget

from locksmith.ui.toolkit.widgets import LocksmithDialog
from locksmith.ui.vaults import open as open_module
from locksmith.ui.vaults.open import OpenVaultDialog


def test_open_vault_dialog_focuses_passcode_field_on_show(qapp, tmp_path):
    parent = QWidget()
    parent.app = SimpleNamespace()
    config = SimpleNamespace(base=str(tmp_path), salt=None)

    previous = LocksmithDialog(parent)
    previous.show()
    previous.accept()
    previous.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    previous_parent = QWidget()
    previous = LocksmithDialog(previous_parent)
    previous.show()
    previous_parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    with patch.object(open_module.otping, "has_otp_configured", return_value=False):
        dialog = OpenVaultDialog(vault_name="test-vault", parent=parent, config=config)

    try:
        dialog.show()
        qapp.processEvents()

        assert qapp.focusWidget() is dialog.passcode_field.line_edit
    finally:
        dialog.close()
        parent.close()
