# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.remotes.add module

Dialog for connecting remote identifiers
"""
import re
from pathlib import Path
from urllib import parse

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QFileDialog
from keri import help
from keri.core.serdering import SerderKERI

from locksmith.core.remoting import ResolveOobiDoer, ImportDoer
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    FloatingLabelLineEdit,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton, LocksmithIconButton

logger = help.ogler.getLogger(__name__)

# Regex pattern to extract AID/prefix from OOBI URL
# Matches: /oobi/{cid} or /oobi/{cid}/{role} or /oobi/{cid}/{role}/{eid}
OOBI_RE = re.compile(r'\A/oobi/(?P<cid>[^/]+)(?:/(?P<role>[^/]+)(?:/(?P<eid>[^/]+))?)?\Z', re.IGNORECASE)


class AddRemoteIdentifierDialog(LocksmithDialog):
    """Dialog for connecting a remote identifier."""
    def __init__(self, app, parent=None):
        """
        Initialize the AddRemoteIdentifierDialog.

        Args:
            app: Application instance
            parent: Parent widget
        """
        self.app = app

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addSpacing(20)

        # Connection type radio buttons
        radio_layout = QHBoxLayout()
        self.oobi_radio = LocksmithRadioButton("OOBI")
        self.file_radio = LocksmithRadioButton("File")
        self.oobi_radio.setChecked(True)

        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.oobi_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.file_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        layout.addSpacing(15)

        # Alias field
        self.alias_field = FloatingLabelLineEdit("Alias")
        self.alias_field.setFixedWidth(340)
        layout.addWidget(self.alias_field)

        layout.addSpacing(15)

        # OOBI/File path container
        self.input_container = QHBoxLayout()

        # OOBI field (shown by default)
        self.oobi_field = FloatingLabelLineEdit("OOBI")
        self.oobi_field.setFixedWidth(340)
        self.input_container.addWidget(self.oobi_field)

        # File path field and browse button (hidden by default)
        self.file_path_field = FloatingLabelLineEdit("File Path")
        self.file_path_field.setFixedWidth(283)
        self.file_path_field.hide()
        self.input_container.addWidget(self.file_path_field)

        self.browse_button = LocksmithIconButton(":/assets/material-icons/browse.svg", tooltip="Browse files")
        self.browse_button.setFixedHeight(48)
        self.browse_button.setFixedWidth(48)
        self.browse_button.hide()
        self.input_container.addWidget(self.browse_button)
        self.input_container.addStretch()

        layout.addLayout(self.input_container)

        layout.addSpacing(15)
        self.prefix_field = FloatingLabelLineEdit("Prefix")
        # self.prefix_field.setReadOnly(True)
        self.prefix_field.setDisabled(True)
        self.prefix_field.setFixedWidth(340)
        layout.addWidget(self.prefix_field)
        layout.addStretch()

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.connect_button = LocksmithButton("Connect")
        button_row.addWidget(self.connect_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(":/assets/custom/remoteIds.png")
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Connect a Remote Identifier")
        title_label.setStyleSheet("font-size: 16px;")
        title_content.addWidget(title_label)
        title_content_widget.setLayout(title_content)

        # Initialize parent dialog
        super().__init__(
            parent=parent,
            title_content=title_content_widget,
            show_close_button=True,
            content=content_widget,
            initial_focus=self.oobi_field.line_edit,
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(380, 480)
        self.file_dialog = None

        # Create button group for connection type radios (must be after super().__init__)
        self.connection_type_group = QButtonGroup(self)
        self.connection_type_group.addButton(self.oobi_radio)
        self.connection_type_group.addButton(self.file_radio)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.oobi_radio.toggled.connect(self._on_connection_type_changed)
        self.file_radio.toggled.connect(self._on_connection_type_changed)
        self.browse_button.clicked.connect(self._browse_file)
        self.connect_button.clicked.connect(self._on_connect)
        self.oobi_field.line_edit.textChanged.connect(self._on_oobi_changed)

        # Set up signal handlers for doer events
        if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
            self.app.vault.signals.doer_event.connect(self._on_doer_event)

    def _on_connection_type_changed(self):
        """Handle connection type radio button selection changes."""
        if self.oobi_radio.isChecked():
            self.oobi_field.show()
            self.file_path_field.hide()
            self.browse_button.hide()
        else:
            self.oobi_field.hide()
            self.file_path_field.show()
            self.browse_button.show()

    def _browse_file(self):
        """Select a file without nesting the Qt event loop."""
        if self.file_dialog is None:
            self.file_dialog = QFileDialog(self, "Select File", "", "All Files (*)")
            self.file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            self.file_dialog.fileSelected.connect(self._on_file_selected)
            self.finished.connect(self.file_dialog.reject)
        self.file_dialog.open()

    def _on_oobi_changed(self, text):
        """
        Handle OOBI field text changes and auto-calculate prefix.

        Args:
            text: Current OOBI text
        """
        if not text:
            self.prefix_field.clear()
            return

        # Parse OOBI URL to extract prefix
        try:
            purl = parse.urlparse(text)
            match = OOBI_RE.match(purl.path)
            if match:
                prefix = match.group("cid")
                self.prefix_field.setText(prefix)
                self.prefix_field.setCursorPosition(0)
            else:
                # Clear prefix if OOBI doesn't match expected format
                self.prefix_field.clear()
        except Exception as e:
            logger.warning(f"Failed to parse OOBI: {e}")
            self.prefix_field.clear()

    def _on_file_selected(self, file_path):
        """Show the selected path and its identifier prefix."""
        if not file_path:
            return
        alias = self.alias_field.text().strip()
        previous_name = Path(self.file_path_field.text()).stem
        if not alias or alias == previous_name:
            self.alias_field.setText(Path(file_path).stem)
        self.file_path_field.setText(file_path)
        try:
            with open(file_path, 'rb') as f:
                ims = f.read()
                serder = SerderKERI(raw=ims)
                self.prefix_field.setText(serder.pre)
        except Exception as e:
            logger.error(f"Failed to extract prefix from file: {e}")
            self.show_error(f"Failed to read file: {str(e)}")

    def _on_connect(self):
        """Handle Connect button click."""
        # Clear any previous errors
        self.clear_error()

        # Validate fields
        if not self._validate_fields():
            return

        # Disable connect button during processing
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Connecting...")

        # Determine which workflow to use
        if self.oobi_radio.isChecked():
            self._connect_oobi()
        else:
            self._connect_file()

    def _validate_fields(self):
        """
        Validate all required fields.

        Returns:
            bool: True if all fields are valid, False otherwise
        """
        alias = self.alias_field.text().strip()
        prefix = self.prefix_field.text().strip()

        # Reset field styles
        self.alias_field.setProperty("error", False)
        self.alias_field.style().unpolish(self.alias_field)
        self.alias_field.style().polish(self.alias_field)

        self.prefix_field.setProperty("error", False)
        self.prefix_field.style().unpolish(self.prefix_field)
        self.prefix_field.style().polish(self.prefix_field)

        failed_fields = []

        # Validate alias
        if not alias:
            failed_fields.append("Alias")
            self.alias_field.setProperty("error", True)
            self.alias_field.style().unpolish(self.alias_field)
            self.alias_field.style().polish(self.alias_field)

        # Validate prefix
        if not prefix:
            failed_fields.append("Prefix")
            self.prefix_field.setProperty("error", True)
            self.prefix_field.style().unpolish(self.prefix_field)
            self.prefix_field.style().polish(self.prefix_field)

        # Validate OOBI or file path
        if self.oobi_radio.isChecked():
            oobi = self.oobi_field.text().strip()
            if not oobi:
                failed_fields.append("OOBI")
                self.oobi_field.setProperty("error", True)
                self.oobi_field.style().unpolish(self.oobi_field)
                self.oobi_field.style().polish(self.oobi_field)
        else:
            file_path = self.file_path_field.text().strip()
            if not file_path:
                failed_fields.append("File Path")
                self.file_path_field.setProperty("error", True)
                self.file_path_field.style().unpolish(self.file_path_field)
                self.file_path_field.style().polish(self.file_path_field)

        if failed_fields:
            field_text = "field" if len(failed_fields) == 1 else "fields"
            self.show_error(f"Missing {field_text}: {', '.join(failed_fields)}")
            return False

        return True

    def _connect_oobi(self):
        """Initiate OOBI resolution workflow."""
        alias = self.alias_field.text().strip()
        oobi = self.oobi_field.text().strip()
        prefix = self.prefix_field.text().strip()

        logger.info(f"Resolving OOBI for alias '{alias}': {oobi}")

        # Create and start ResolveOobiDoer
        doer = ResolveOobiDoer(
            app=self.app,
            pre=prefix,
            oobi=oobi,
            alias=alias,
            signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
        )

        # Add doer to vault's doer chain
        self.app.vault.extend([doer])

    def _connect_file(self):
        """Initiate file import workflow."""
        alias = self.alias_field.text().strip()
        file_path = self.file_path_field.text().strip()

        logger.info(f"Importing remote identifier from file for alias '{alias}': {file_path}")

        # Create and start ImportDoer
        doer = ImportDoer(
            app=self.app,
            file=file_path,
            alias=alias,
            signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
        )

        # Add doer to vault's doer chain
        self.app.vault.extend([doer])

    def _on_doer_event(self, doer_name, event_type, data):
        """
        Handle doer events from signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        # Handle ResolveOobiDoer events
        if doer_name == "ResolveOobiDoer":
            if event_type == "oobi_resolved":
                self._on_success(data)
            elif event_type in ("oobi_resolution_timeout", "oobi_resolution_failed"):
                error_msg = data.get('error', 'OOBI resolution failed or timed out')
                self._on_failure(error_msg)

        # Handle ImportDoer events
        elif doer_name == "ImportDoer":
            if event_type == "remote_identifier_imported":
                self._on_success(data)
            elif event_type == "import_failed":
                error_msg = data.get('error', 'Failed to import remote identifier')
                self._on_failure(error_msg)

    def _on_success(self, data):
        """
        Handle successful remote identifier connection.

        Args:
            data: Success data from doer
        """
        alias = data.get('alias', 'Unknown')
        logger.info(f"Successfully connected remote identifier: {alias}")

        # Reset button state
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Connect")

        # Close dialog
        self.accept()

    def _on_failure(self, error_msg):
        """
        Handle failed remote identifier connection.

        Args:
            error_msg: Error message to display
        """
        logger.error(f"Failed to connect remote identifier: {error_msg}")

        # Reset button state
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Connect")

        # Show error
        self.show_error(error_msg)
