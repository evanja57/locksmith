# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.identifiers.accept_delegate module

Dialog for accepting delegate events from file.
"""
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFileDialog
from keri import help
from keri.core.serdering import SerderKERI
from keri.core import parsing

from locksmith.core.remoting import message_version
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    FloatingLabelLineEdit,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithIconButton

logger = help.ogler.getLogger(__name__)


class AcceptDelegateDialog(LocksmithDialog):
    """Dialog for accepting a delegate event from file."""

    def __init__(self, app, identifier_prefix: str, identifier_alias: str, parent=None):
        """
        Initialize the AcceptDelegateDialog.

        Args:
            app: Application instance
            identifier_prefix: Prefix of the delegator (selected identifier)
            identifier_alias: Alias of the delegator
            parent: Parent widget
        """
        self.app = app
        self.identifier_prefix = identifier_prefix
        self.identifier_alias = identifier_alias
        self.delegate_serder = None  # Store parsed delegate event
        self.delegate_raw = None  # Store raw event bytes

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addSpacing(20)

        # Delegator info (read-only display)
        delegator_label = QLabel("Delegator:")
        delegator_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(delegator_label)

        delegator_info = QLabel(f"{identifier_alias} ({identifier_prefix})")
        delegator_info.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SECONDARY}; margin-bottom: 10px;")
        layout.addWidget(delegator_info)

        layout.addSpacing(10)

        # File path container
        file_container = QHBoxLayout()

        # File path field
        self.file_path_field = FloatingLabelLineEdit("Delegate Event File")
        self.file_path_field.setFixedWidth(385)
        file_container.addWidget(self.file_path_field)

        # Browse button
        self.browse_button = LocksmithIconButton(
            ":/assets/material-icons/browse.svg",
            tooltip="Browse files"
        )
        self.browse_button.setFixedHeight(48)
        self.browse_button.setFixedWidth(48)
        file_container.addWidget(self.browse_button)
        file_container.addStretch()

        layout.addLayout(file_container)

        layout.addSpacing(15)

        # Delegate prefix field (auto-populated from file)
        self.delegate_prefix_field = FloatingLabelLineEdit("Delegate Prefix")
        self.delegate_prefix_field.setDisabled(True)
        self.delegate_prefix_field.setFixedWidth(425)
        layout.addWidget(self.delegate_prefix_field)

        layout.addSpacing(10)

        # Validation indicator (checkmark and text)
        validation_container = QHBoxLayout()
        validation_container.setContentsMargins(0, 0, 0, 0)

        # Checkmark icon
        self.checkmark_label = QLabel()
        check_icon = QIcon(":/assets/material-icons/green_check_circle.svg")
        self.checkmark_label.setPixmap(check_icon.pixmap(20, 20))
        self.checkmark_label.setFixedSize(20, 20)
        validation_container.addWidget(self.checkmark_label)

        validation_container.addSpacing(5)

        # Validation text
        self.validation_text = QLabel("Delegate of this identifier")
        self.validation_text.setStyleSheet(f"color: {colors.SUCCESS_INDICATOR}; font-size: 12px; font-weight: bold;")
        validation_container.addWidget(self.validation_text)

        validation_container.addStretch()

        layout.addLayout(validation_container)

        # Hide validation indicator by default
        self.checkmark_label.hide()
        self.validation_text.hide()

        layout.addStretch()

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.accept_button = LocksmithButton("Accept Delegate")
        button_row.addWidget(self.accept_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(":/assets/custom/identifiers.png")
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Accept Delegate")
        title_label.setStyleSheet("font-size: 16px;")
        title_content.addWidget(title_label)
        title_content_widget.setLayout(title_content)

        # Initialize parent dialog
        super().__init__(
            parent=parent,
            title_content=title_content_widget,
            show_close_button=True,
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(475, 500)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.browse_button.clicked.connect(self._browse_file)
        self.accept_button.clicked.connect(self._on_accept)

    def _browse_file(self):
        """Open file dialog to select a delegate event file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Delegate Event File",
            "",
            "CESR Files (*.cesr);;All Files (*)"
        )
        if file_path:
            self.file_path_field.setText(file_path)
            self._extract_delegate_from_file(file_path)

    def _extract_delegate_from_file(self, file_path):
        """
        Extract and validate delegate event from file.

        Args:
            file_path: Path to the delegate event file
        """
        try:
            # Read file
            with open(file_path, 'rb') as f:
                ims = f.read()

            # Parse delegate event
            serder = SerderKERI(raw=ims)

            # Validate 'di' field matches delegator
            delegator_in_event = serder.sad.get("di")

            if not delegator_in_event:
                self.show_error("Invalid delegate event: missing 'di' field (delegator)")
                self.delegate_serder = None
                self.delegate_raw = None
                self.checkmark_label.hide()
                self.validation_text.hide()
                return

            if delegator_in_event != self.identifier_prefix:
                self.show_error(
                    f"Delegator mismatch:\n"
                    f"Expected: {self.identifier_prefix}\n"
                    f"Found in event: {delegator_in_event}"
                )
                self.delegate_serder = None
                self.delegate_raw = None
                self.checkmark_label.hide()
                self.validation_text.hide()
                return

            self.delegate_prefix_field.setText(delegator_in_event)

            # Store valid serder and raw bytes for acceptance
            self.delegate_serder = serder
            self.delegate_raw = ims
            self.clear_error()

            # Show validation indicator
            self.checkmark_label.show()
            self.validation_text.show()

            logger.info(f"Valid delegate event: {self.identifier_prefix} for delegator {delegator_in_event}")

        except Exception as e:
            logger.error(f"Failed to parse delegate event: {e}")
            self.show_error(f"Failed to read file: {str(e)}")
            self.delegate_serder = None
            self.delegate_raw = None
            self.checkmark_label.hide()
            self.validation_text.hide()

    def _on_accept(self):
        """Handle Accept Delegate button click."""
        # Clear previous errors
        self.clear_error()

        # Validate file was selected and parsed
        if not self.delegate_serder or not self.delegate_raw:
            self.show_error("Please select a valid delegate event file")
            return

        # Disable button during processing
        self.accept_button.setEnabled(False)
        self.accept_button.setText("Accepting...")

        try:
            # Get the hab for the delegator
            hab = self.app.vault.hby.habByPre(self.identifier_prefix)
            if not hab:
                raise ValueError(f"Delegator identifier not found: {self.identifier_prefix}")

            # Parse and process the delegate event through Kevery
            kvy = self.app.vault.kvy
            parsing.Parser().parse(ims=self.delegate_raw, kvy=kvy, version=message_version(self.delegate_raw))

            # The event should now be in delegables, retrieve it
            delegate_prefix = self.delegate_serder.pre
            delegate_sn = self.delegate_serder.sn

            # Look up in delegables
            edig = None
            sn_full = None
            for (pre, sn), dig in self.app.vault.hby.db.delegables.getTopItemIter(keys=()):
                if pre == delegate_prefix and sn[-1] == delegate_sn:
                    edig = dig
                    sn_full = sn
                    break

            if not edig:
                raise ValueError("Delegate event not found in delegables after processing")

            # Confirm the delegate using habbing.confirm_delegates
            from locksmith.core import habbing
            result = habbing.confirm_delegates(
                self.app,
                hab,
                [{
                    'pre': delegate_prefix,
                    'sn': delegate_sn,
                    'edig': edig,
                    'sn_full': sn_full
                }]
            )

            if result['success']:
                logger.info(f"Successfully accepted delegate: {delegate_prefix}")
                self.accept()  # Close dialog on success
            else:
                raise ValueError(result.get('message', 'Unknown error'))

        except Exception as e:
            logger.exception(f"Error accepting delegate: {e}")
            self.show_error(f"Failed to accept delegate: {str(e)}")

            # Reset button state
            self.accept_button.setEnabled(True)
            self.accept_button.setText("Accept Delegate")
