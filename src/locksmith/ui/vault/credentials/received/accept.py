# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.received.accept module

Dialog for accepting/admitting credentials from IPEX grant messages.
"""
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QFileDialog
)
from keri import help
from keri.core import serdering

from keri import kering
from locksmith.ui import colors
from locksmith.ui.vault.credentials.received.accept_grant import AcceptGrantDialog
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithIconButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class AcceptCredentialDialog(LocksmithDialog):
    """Dialog for accepting credentials from IPEX grant message files.

    Allows users to select an IPEX grant message file (.cesr) from their
    local machine and admit the credential.
    """

    def __init__(
        self,
        app: "LocksmithApplication",
        parent: "VaultPage"
    ):
        """
        Initialize the AcceptCredentialDialog.

        Args:
            app: Application instance
            parent: Parent widget (VaultPage)
        """
        self.app = app
        self.parent_widget = parent

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Instructions section
        instructions_label = QLabel("Import Grant")
        instructions_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(instructions_label)

        description = QLabel(
            "Select an IPEX grant message file (.cesr) from your local machine "
            "to admit the credential into your vault."
        )
        description.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 13px;")
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addSpacing(10)

        # File selection section
        file_label = QLabel("Grant Message File")
        file_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(file_label)

        # File path field and browse button
        file_row = QHBoxLayout()
        file_row.setSpacing(8)

        self.file_path_field = FloatingLabelLineEdit(label_text="File Path")
        self.file_path_field.setFixedWidth(340)
        file_row.addWidget(self.file_path_field)

        self.browse_button = LocksmithIconButton(":/assets/material-icons/browse.svg", tooltip="Browse files")
        self.browse_button.setFixedHeight(48)
        self.browse_button.setFixedWidth(48)
        file_row.addWidget(self.browse_button)

        file_row.addStretch()
        layout.addLayout(file_row)

        layout.addStretch()

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)

        button_row.addSpacing(10)

        self.load_button = LocksmithButton("Load")
        button_row.addWidget(self.load_button)

        # Initialize parent dialog
        super().__init__(
            parent=parent,
            title="Import Grant",
            title_icon=":/assets/material-icons/in-badge.svg",
            content=content_widget,
            initial_focus=self.browse_button,
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(480, 425)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.browse_button.clicked.connect(self._browse_file)
        self.load_button.clicked.connect(self._on_load)

    def _browse_file(self):
        """Open file dialog to select grant message file."""
        # Get current file path as default (if any)
        current_path = self.file_path_field.text().strip()

        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Grant Message File",
            current_path if current_path else "",
            "CESR Files (*.cesr);;All Files (*)"
        )

        if file_path:
            # Update file path field with selected path
            self.file_path_field.setText(file_path)
            logger.info(f"Selected file: {file_path}")

    def _validate_file_path(self) -> bool:
        """
        Validate that a file path has been provided.

        Returns:
            bool: True if validation passes, False otherwise
        """
        # Clear any previous errors
        self.clear_error()

        file_path = self.file_path_field.text().strip()

        if not file_path:
            self.file_path_field.setProperty("error", True)
            self.file_path_field.style().unpolish(self.file_path_field)
            self.file_path_field.style().polish(self.file_path_field)
            self.show_error("Please select a file to load")
            return False

        return True

    def _on_load(self):
        """Handle Load button click."""
        # Clear previous errors
        self.clear_error()

        # Validate file path
        if not self._validate_file_path():
            return

        # Disable button during processing
        self.load_button.setEnabled(False)
        self.load_button.setText("Loading...")

        file_path = self.file_path_field.text().strip()
        self._admit_credential(file_path)

    def _admit_credential(self, file_path: str):
        """
        Parse CESR file and extract grant message SAID.

        Args:
            file_path: Path to the .cesr grant message file
        """
        try:

            logger.info(f"Loading grant message from file: {file_path}")

            # Read CESR file in binary mode
            with open(file_path, 'rb') as f:
                ims = f.read()

            grant_serder = serdering.SerderKERI(raw=bytes(ims))
            if (grant_serder.pvrsn.major != 2
                    or grant_serder.ked.get('r') != '/ipex/grant'):
                raise ValueError("Expected an ACDC V2 IPEX grant")
            recp = grant_serder.ked['ri']
            grant_said = grant_serder.said
            if self.app.vault.hby.habByPre(recp) is None:
                raise ValueError(f"No local identifier found for recipient: {recp}")
            try:
                # File imports have no preceding KEL replay to warm the sender state.
                self.app.vault.hby.db.kevers[grant_serder.pre]
            except KeyError:
                pass
            self.app.vault.mbx.parser.parse(
                ims=bytearray(ims), version=kering.Vrsn_2_0, local=False,
            )
            if not self.app.vault.exc.complete(grant_said):
                self.show_error("Grant verification is pending or failed. Required issuer or registry evidence may be missing.")
                self._reset_button()
                return

            logger.info(f"Found grant message SAID: {grant_said}")

            # Close this dialog
            self.accept()

            # Open AcceptGrantDialog with the grant SAID
            # The AcceptGrantDialog will handle the actual admit process
            grant_dialog = AcceptGrantDialog(
                app=self.app,
                parent=self.parent_widget,
                grant_said=grant_said
            )
            grant_dialog.open()

        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            self.show_error(f"File not found: {file_path}")
            self._reset_button()
        except ValueError as e:
            logger.error(f"Invalid grant file: {e}")
            self.show_error(f"Invalid grant message file: {str(e)}")
            self._reset_button()
        except Exception as e:
            logger.exception(f"Error loading grant message: {e}")
            self.show_error(f"Failed to load grant message: {str(e)}")
            self._reset_button()

    def _reset_button(self):
        """Reset load button to enabled state."""
        self.load_button.setEnabled(True)
        self.load_button.setText("Load")
