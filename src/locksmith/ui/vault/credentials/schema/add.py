# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.schema.add module

Dialog for loading credential schemas
"""
from keri import help
import json
import re
from urllib import parse

from PySide6.QtCore import QDir, QFile, QIODevice
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QFileDialog, QCheckBox

from locksmith import resources_rc  # noqa: F401 - register bundled schemas and icons
from locksmith.core.credentialing import LoadSchemaDoer
from locksmith.core.habbing import list_eligible_local_identifiers
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    FloatingLabelLineEdit,
    FloatingLabelComboBox,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton, LocksmithIconButton

logger = help.ogler.getLogger(__name__)

SCHEMA_OOBI_RE = re.compile(r'\A/oobi/(?P<said>[^/]+)/?\Z', re.IGNORECASE)


class AddSchemaDialog(LocksmithDialog):
    """Dialog for loading a credential schema."""
    def __init__(self, app, parent=None):
        """
        Initialize the AddSchemaDialog.

        Args:
            app: Application instance
            parent: Parent widget
        """
        self.app = app

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #F8F9FF;")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addSpacing(20)

        # Connection type radio buttons
        radio_layout = QHBoxLayout()
        self.oobi_radio = LocksmithRadioButton("OOBI")
        self.file_radio = LocksmithRadioButton("File")
        self.builtin_radio = LocksmithRadioButton("Built-in")
        self.oobi_radio.setChecked(True)

        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.oobi_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.file_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.builtin_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        layout.addSpacing(15)

        # Schema source controls
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

        self.builtin_dropdown = FloatingLabelComboBox("Schema")
        self.builtin_dropdown.setFixedWidth(340)
        self.builtin_dropdown.hide()
        self.input_container.addWidget(self.builtin_dropdown)
        self.input_container.addStretch()

        layout.addLayout(self.input_container)

        self.builtin_version = QLabel()
        self.builtin_version.hide()
        layout.addWidget(self.builtin_version)

        layout.addSpacing(15)
        self.said_field = FloatingLabelLineEdit("SAID")
        self.said_field.setDisabled(True)
        self.said_field.setFixedWidth(340)
        layout.addWidget(self.said_field)

        layout.addSpacing(20)

        # Checkbox for choosing a schema issuer
        self.enable_issuance_checkbox = QCheckBox("Use for Credential Issuance")
        self.enable_issuance_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                spacing: 8px;
                color: #2D2F33;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid #CCCCCC;
                border-radius: 4px;
                background-color: #F8F9FF;
            }
            QCheckBox::indicator:checked {
                background-color: #F57B03;
                border-color: #F57B03;
                color: #FFFFFF;
            }
        """)
        layout.addWidget(self.enable_issuance_checkbox)

        layout.addSpacing(15)

        # Issuer identifier dropdown (shown when checkbox is checked)
        self.issuer_label = QLabel("Issuer Identifier")
        self.issuer_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.issuer_label.hide()
        layout.addWidget(self.issuer_label)

        self.issuer_dropdown = FloatingLabelComboBox("Issuer")
        self.issuer_dropdown.setFixedWidth(340)
        self.issuer_dropdown.hide()
        layout.addWidget(self.issuer_dropdown)

        layout.addStretch()

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.load_button = LocksmithButton("Load Schema")
        button_row.addWidget(self.load_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(":/assets/material-icons/schema.svg")
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Load Credential Schema")
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

        self.setFixedSize(420, 580)
        self.file_dialog = None

        # Create button group for connection type radios (must be after super().__init__)
        self.connection_type_group = QButtonGroup(self)
        self.connection_type_group.addButton(self.oobi_radio)
        self.connection_type_group.addButton(self.file_radio)
        self.connection_type_group.addButton(self.builtin_radio)

        # Connect signals
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.oobi_radio.toggled.connect(self._on_connection_type_changed)
        self.file_radio.toggled.connect(self._on_connection_type_changed)
        self.builtin_radio.toggled.connect(self._on_connection_type_changed)
        self.builtin_dropdown.currentIndexChanged.connect(self._on_builtin_changed)
        self.browse_button.clicked.connect(self._browse_file)
        self.load_button.clicked.connect(self._on_primary_clicked)
        self.oobi_field.line_edit.textChanged.connect(self._on_oobi_changed)
        self.enable_issuance_checkbox.toggled.connect(self._on_issuance_checkbox_toggled)

        # Populate issuer dropdown with local identifiers
        self._populate_issuer_dropdown()
        self._populate_builtin_dropdown()

        # Connect to vault signal bridge for doer events
        if self.app and hasattr(self.app, 'vault') and self.app.vault and hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            self._doer_event_connected = True
            logger.info("AddSchemaDialog: Connected to vault signal bridge")
        else:
            self._doer_event_connected = False

        self.finished.connect(self._on_dialog_finished)

    def _disconnect_doer_event_signal(self):
        if not self._doer_event_connected:
            return
        try:
            self.app.vault.signals.doer_event.disconnect(self._on_doer_event)
        except RuntimeError:
            pass
        self._doer_event_connected = False

    def _on_dialog_finished(self, _result):
        self._disconnect_doer_event_signal()

    def _on_primary_clicked(self):
        self._on_load()

    def _on_cancel_clicked(self):
        self.close()


    def _set_primary_button_idle(self):
        self.cancel_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.load_button.setText("Load Schema")


    def _on_connection_type_changed(self, checked):
        """Handle connection type radio button selection changes."""
        if not checked:
            return
        self.clear_error()
        self.oobi_field.setVisible(self.oobi_radio.isChecked())
        self.file_path_field.setVisible(self.file_radio.isChecked())
        self.browse_button.setVisible(self.file_radio.isChecked())
        self.builtin_dropdown.setVisible(self.builtin_radio.isChecked())
        self.builtin_version.setVisible(self.builtin_radio.isChecked())
        self.said_field.setText("")
        if self.oobi_radio.isChecked():
            self._on_oobi_changed(self.oobi_field.text())
        elif self.file_radio.isChecked():
            self._on_file_selected(self.file_path_field.text())
        else:
            self._on_builtin_changed()

    def _populate_builtin_dropdown(self):
        """Read the bundled schema names and bytes from Qt resources."""
        self.builtin_dropdown.addItem("Select a schema...")
        directory = QDir(":/assets/schemas/sedi")
        try:
            for filename in directory.entryList(["*.json"], QDir.Filter.Files):
                source = QFile(directory.filePath(filename))
                if not source.open(QIODevice.OpenModeFlag.ReadOnly):
                    raise OSError(source.errorString())
                try:
                    raw = bytes(source.readAll())
                finally:
                    source.close()
                schema = json.loads(raw)
                self.builtin_dropdown.addItem(schema['title'], userData={
                    'raw': raw, 'said': schema['$id'], 'version': schema['version'],
                })
        except (OSError, ValueError, KeyError) as error:
            self.show_error(f"Failed to read built-in schemas: {error}")

    def _on_builtin_changed(self):
        """Show the selected schema identity without loading it into the vault."""
        if not self.builtin_radio.isChecked():
            return
        schema = self.builtin_dropdown.currentData()
        self.said_field.setText(schema['said'] if schema else "")
        self.said_field.setCursorPosition(0)
        self.builtin_version.setText(f"Draft · Version {schema['version']}" if schema else "")
        self.builtin_dropdown.setToolTip(self.builtin_dropdown.currentText() if schema else "")

    def _on_issuance_checkbox_toggled(self, checked):
        """
        Handle issuance checkbox toggle to show/hide issuer dropdown.

        Args:
            checked: Whether the checkbox is checked
        """
        if checked:
            self.issuer_label.show()
            self.issuer_dropdown.show()
        else:
            self.issuer_label.hide()
            self.issuer_dropdown.hide()

    def _populate_issuer_dropdown(self):
        """Populate the issuer dropdown with local identifiers."""
        self.issuer_dropdown.clear()
        self.issuer_dropdown.addItem("Select an issuer...")

        try:
            for identifier in list_eligible_local_identifiers(self.app):
                hab_pre = identifier["prefix"]
                hab = self.app.vault.hby.habs[hab_pre]
                # Format: "Name (prefix)"
                display_text = f"{hab.name} ({hab_pre[:15]}...)"
                self.issuer_dropdown.addItem(display_text, userData=hab_pre)

            logger.debug(f"Populated issuer dropdown with {self.issuer_dropdown.count() - 1} identifiers")
        except Exception as e:
            logger.exception(f"Error loading local identifiers: {e}")
            self.show_error(f"Failed to load issuers: {str(e)}")

    def _browse_file(self):
        """Select a schema without nesting the Qt event loop."""
        if self.file_dialog is None:
            self.file_dialog = QFileDialog(self, "Select Schema File", "",
                                           "JSON Files (*.json);;All Files (*)")
            self.file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            self.file_dialog.fileSelected.connect(self._on_file_selected)
            self.finished.connect(self.file_dialog.reject)
        self.file_dialog.open()

    def _on_oobi_changed(self, text):
        """
        Handle OOBI field text changes and auto-extract SAID.

        Args:
            text: Current OOBI text
        """
        if not self.oobi_radio.isChecked():
            return
        if not text:
            self.said_field.setText("")
            return

        # Parse OOBI URL to extract SAID
        try:
            purl = parse.urlparse(text)
            match = SCHEMA_OOBI_RE.match(purl.path)
            if match:
                said = match.group("said")
                self.said_field.setText(said)
                self.said_field.setCursorPosition(0)
            else:
                # Clear SAID if OOBI doesn't match expected format
                self.said_field.setText("")
        except Exception as e:
            logger.warning(f"Failed to parse OOBI: {e}")
            self.said_field.setText("")

    def _on_file_selected(self, file_path):
        """Show the selected path and its schema SAID."""
        if not file_path:
            return
        self.file_path_field.setText(file_path)
        if not self.file_radio.isChecked():
            return
        self.said_field.setText("")
        try:
            with open(file_path, 'r') as f:
                schema_data = json.load(f)
                # Look for SAID in common locations
                said = schema_data.get('$id') or schema_data.get('said') or schema_data.get('SAID')
                if said:
                    self.said_field.setText(said)
                else:
                    logger.warning("No SAID found in schema file")
                    self.said_field.setText("")
            return True
        except Exception as e:
            logger.error(f"Failed to extract SAID from file: {e}")
            self.show_error(f"Failed to read schema file: {str(e)}")
            return False

    def _on_load(self):
        """Handle Load Schema button click."""
        # Clear any previous errors
        self.clear_error()

        if self.file_radio.isChecked() and self.file_path_field.text().strip():
            if not self._on_file_selected(self.file_path_field.text().strip()):
                return

        # Validate fields
        if not self._validate_fields():
            return

        # Disable load button during processing
        self.load_button.setEnabled(False)
        self.load_button.setText("Loading...")

        # Determine which workflow to use
        if self.oobi_radio.isChecked():
            self._load_oobi()
        elif self.builtin_radio.isChecked():
            self._create_load_schema_doer(
                file_content=self.builtin_dropdown.currentData()['raw'],
                enable_issuance=self.enable_issuance_checkbox.isChecked(),
                issuer_aid=self.issuer_dropdown.currentData(),
            )
        else:
            self._load_file()

    def _validate_fields(self):
        """
        Validate all required fields.

        Returns:
            bool: True if all fields are valid, False otherwise
        """
        # Reset field styles
        self.oobi_field.setProperty("error", False)
        self.oobi_field.style().unpolish(self.oobi_field)
        self.oobi_field.style().polish(self.oobi_field)

        self.file_path_field.setProperty("error", False)
        self.file_path_field.style().unpolish(self.file_path_field)
        self.file_path_field.style().polish(self.file_path_field)

        self.builtin_dropdown.setProperty("error", False)
        self.builtin_dropdown.style().unpolish(self.builtin_dropdown)
        self.builtin_dropdown.style().polish(self.builtin_dropdown)

        self.said_field.setProperty("error", False)
        self.said_field.style().unpolish(self.said_field)
        self.said_field.style().polish(self.said_field)

        self.issuer_dropdown.setProperty("error", False)
        self.issuer_dropdown.style().unpolish(self.issuer_dropdown)
        self.issuer_dropdown.style().polish(self.issuer_dropdown)

        failed_fields = []

        # Validate the selected source
        if self.oobi_radio.isChecked():
            oobi = self.oobi_field.text().strip()
            if not oobi:
                failed_fields.append("OOBI")
                self.oobi_field.setProperty("error", True)
                self.oobi_field.style().unpolish(self.oobi_field)
                self.oobi_field.style().polish(self.oobi_field)
        elif self.file_radio.isChecked():
            file_path = self.file_path_field.text().strip()
            if not file_path:
                failed_fields.append("File Path")
                self.file_path_field.setProperty("error", True)
                self.file_path_field.style().unpolish(self.file_path_field)
                self.file_path_field.style().polish(self.file_path_field)
        elif self.builtin_dropdown.currentData() is None:
            failed_fields.append("Schema")
            self.builtin_dropdown.setProperty("error", True)
            self.builtin_dropdown.style().unpolish(self.builtin_dropdown)
            self.builtin_dropdown.style().polish(self.builtin_dropdown)

        # Validate SAID
        said = self.said_field.text().strip()
        if not said:
            failed_fields.append("SAID")
            self.said_field.setProperty("error", True)
            self.said_field.style().unpolish(self.said_field)
            self.said_field.style().polish(self.said_field)

        # Validate issuer selection if issuance checkbox is checked
        if self.enable_issuance_checkbox.isChecked():
            if self.issuer_dropdown.currentIndex() <= 0:
                failed_fields.append("Issuer Identifier")
                self.issuer_dropdown.setProperty("error", True)
                self.issuer_dropdown.style().unpolish(self.issuer_dropdown)
                self.issuer_dropdown.style().polish(self.issuer_dropdown)

        if failed_fields:
            field_text = "field" if len(failed_fields) == 1 else "fields"
            self.show_error(f"Missing {field_text}: {', '.join(failed_fields)}")
            return False

        return True

    def _load_oobi(self):
        """Load a schema and optionally save its local issuer selection."""
        self._create_load_schema_doer(
            oobi=self.oobi_field.text().strip(),
            enable_issuance=self.enable_issuance_checkbox.isChecked(),
            issuer_aid=self.issuer_dropdown.currentData(),
        )

    def _load_file(self):
        """Load a schema file and optionally save its local issuer selection."""
        file_path = self.file_path_field.text().strip()
        try:
            with open(file_path, 'rb') as source:
                raw = source.read()
            self._create_load_schema_doer(
                file_content=raw,
                enable_issuance=self.enable_issuance_checkbox.isChecked(),
                issuer_aid=self.issuer_dropdown.currentData(),
            )
        except OSError as error:
            self.show_error(f"Failed to read schema: {error}")
            self._set_primary_button_idle()

    def _create_load_schema_doer(self, oobi=None, file_content=None,
                                 enable_issuance=False, issuer_aid=None):
        """Schedule schema loading and save the requested issuer selection."""
        try:
            doer = LoadSchemaDoer(
                app=self.app, oobi=oobi,
                file_content=file_content, enable_issuance=enable_issuance,
                issuer_aid=issuer_aid, signal_bridge=self.app.vault.signals,
            )
            self.app.vault.extend([doer])
        except Exception as error:
            logger.exception("Failed to start schema loading")
            self._set_primary_button_idle()
            self.show_error(f"Failed to load schema: {error}")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        # Only handle LoadSchemaDoer events
        if doer_name != "LoadSchemaDoer":
            return

        logger.info(f"AddSchemaDialog received: {doer_name} - {event_type}")

        if event_type == "schema_loaded":
            self._on_success(data)
        elif event_type == "schema_load_failed":
            error_msg = data.get('error', 'Schema loading failed')
            self._on_failure(error_msg)

    def _on_success(self, data):
        """Close after the schema and issuer selection have been saved."""
        logger.info("Loaded schema %s", data.get('said', ''))
        self.close()

    def _on_failure(self, error_msg):
        """
        Handle failed schema loading.

        Args:
            error_msg: Error message to display
        """
        logger.error(f"Failed to load schema: {error_msg}")

        self._set_primary_button_idle()
        self.show_error(error_msg)
