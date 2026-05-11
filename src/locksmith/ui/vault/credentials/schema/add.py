# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.schema.add module

Dialog for loading credential schemas
"""
from keri import help
import re
from urllib import parse

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QFileDialog, QCheckBox

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
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

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
        self.oobi_radio.setChecked(True)

        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.oobi_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.file_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

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
        self.said_field = FloatingLabelLineEdit("SAID")
        self.said_field.setDisabled(True)
        self.said_field.setFixedWidth(340)
        layout.addWidget(self.said_field)

        layout.addSpacing(20)

        # Checkbox for credential registry creation
        self.create_registry_checkbox = QCheckBox("Use for Credential Issuance")
        self.create_registry_checkbox.setStyleSheet("""
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
        layout.addWidget(self.create_registry_checkbox)

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
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(420, 540)

        # Create button group for connection type radios (must be after super().__init__)
        self.connection_type_group = QButtonGroup(self)
        self.connection_type_group.addButton(self.oobi_radio)
        self.connection_type_group.addButton(self.file_radio)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.oobi_radio.toggled.connect(self._on_connection_type_changed)
        self.file_radio.toggled.connect(self._on_connection_type_changed)
        self.browse_button.clicked.connect(self._browse_file)
        self.load_button.clicked.connect(self._on_load)
        self.oobi_field.line_edit.textChanged.connect(self._on_oobi_changed)
        self.create_registry_checkbox.toggled.connect(self._on_registry_checkbox_toggled)

        # Populate issuer dropdown with local identifiers
        self._populate_issuer_dropdown()

        # Connect to vault signal bridge for doer events
        if self.app and hasattr(self.app, 'vault') and self.app.vault and hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            self.app.vault.signals.auth_codes_entered.connect(self._on_auth_codes_entered)
            logger.info("AddSchemaDialog: Connected to vault signal bridge")

        # State for workflow with authentication
        self.pending_load_params = None  # Stores params while waiting for auth codes


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

    def _on_registry_checkbox_toggled(self, checked):
        """
        Handle registry checkbox toggle to show/hide issuer dropdown.

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
        """Open file dialog to select a schema file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Schema File",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.file_path_field.setText(file_path)
            self._extract_said_from_file(file_path)

    def _on_oobi_changed(self, text):
        """
        Handle OOBI field text changes and auto-extract SAID.

        Args:
            text: Current OOBI text
        """
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

    def _extract_said_from_file(self, file_path):
        """
        Extract and display SAID from a schema file.

        Args:
            file_path: Path to the schema file
        """
        try:
            import json
            with open(file_path, 'r') as f:
                schema_data = json.load(f)
                # Look for SAID in common locations
                said = schema_data.get('$id') or schema_data.get('said') or schema_data.get('SAID')
                if said:
                    self.said_field.setText(said)
                else:
                    logger.warning("No SAID found in schema file")
                    self.said_field.setText("")
        except Exception as e:
            logger.error(f"Failed to extract SAID from file: {e}")
            self.show_error(f"Failed to read schema file: {str(e)}")

    def _on_load(self):
        """Handle Load Schema button click."""
        # Clear any previous errors
        self.clear_error()

        # Validate fields
        if not self._validate_fields():
            return

        # Disable load button during processing
        self.load_button.setEnabled(False)
        self.load_button.setText("Loading...")

        # Determine which workflow to use
        if self.oobi_radio.isChecked():
            self._load_oobi()
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

        self.said_field.setProperty("error", False)
        self.said_field.style().unpolish(self.said_field)
        self.said_field.style().polish(self.said_field)

        self.issuer_dropdown.setProperty("error", False)
        self.issuer_dropdown.style().unpolish(self.issuer_dropdown)
        self.issuer_dropdown.style().polish(self.issuer_dropdown)

        failed_fields = []

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

        # Validate SAID
        said = self.said_field.text().strip()
        if not said:
            failed_fields.append("SAID")
            self.said_field.setProperty("error", True)
            self.said_field.style().unpolish(self.said_field)
            self.said_field.style().polish(self.said_field)

        # Validate issuer selection if registry checkbox is checked
        if self.create_registry_checkbox.isChecked():
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
        """Initiate schema loading from OOBI."""
        oobi = self.oobi_field.text().strip()
        create_registry = self.create_registry_checkbox.isChecked()

        # Get issuer AID if registry is being created
        issuer_aid = None
        if create_registry:
            issuer_index = self.issuer_dropdown.currentIndex()
            if issuer_index > 0:
                issuer_aid = self.issuer_dropdown.itemData(issuer_index)

        logger.info(f"Loading schema from OOBI: {oobi}")
        if issuer_aid:
            logger.info(f"Will create registry with issuer: {issuer_aid}")

        try:
            # Check if issuer has witnesses and needs authentication
            if issuer_aid and create_registry:
                hab = self.app.vault.hby.habs.get(issuer_aid)
                if hab and hab.kever.wits:
                    logger.info(f"Issuer {issuer_aid} has {len(hab.kever.wits)} witnesses, launching auth dialog")

                    # Store params for later use after auth
                    self.pending_load_params = {
                        'workflow': 'oobi',
                        'oobi': oobi,
                        'create_registry': create_registry,
                        'issuer_aid': issuer_aid
                    }

                    # Launch witness authentication dialog
                    auth_dialog = WitnessAuthenticationDialog(
                        app=self.app,
                        hab=hab,
                        witness_ids=hab.kever.wits,
                        auth_only=True,
                        signals=self.app.vault.signals,
                        parent=self
                    )
                    auth_dialog.open()
                    return

            # No witnesses or no registry creation - proceed directly
            self._create_load_schema_doer(
                oobi=oobi,
                create_registry=create_registry,
                issuer_aid=issuer_aid
            )

        except Exception as e:
            logger.error(f"Failed to create LoadSchemaDoer: {e}")
            self.load_button.setEnabled(True)
            self.load_button.setText("Load Schema")
            self.show_error(f"Failed to initiate schema loading: {str(e)}")

    def _load_file(self):
        """Initiate schema loading from file."""
        file_path = self.file_path_field.text().strip()
        create_registry = self.create_registry_checkbox.isChecked()

        # Get issuer AID if registry is being created
        issuer_aid = None
        if create_registry:
            issuer_index = self.issuer_dropdown.currentIndex()
            if issuer_index > 0:
                issuer_aid = self.issuer_dropdown.itemData(issuer_index)

        logger.info(f"Loading schema from file: {file_path}")
        if issuer_aid:
            logger.info(f"Will create registry with issuer: {issuer_aid}")

        try:
            # Read the schema file
            with open(file_path, 'rb') as f:
                raw = f.read()

            # Check if issuer has witnesses and needs authentication
            if issuer_aid and create_registry:
                hab = self.app.vault.hby.habs.get(issuer_aid)
                if hab and hab.kever.wits:
                    logger.info(f"Issuer {issuer_aid} has {len(hab.kever.wits)} witnesses, launching auth dialog")

                    # Store params for later use after auth
                    self.pending_load_params = {
                        'workflow': 'file',
                        'file_path': file_path,
                        'file_content': raw,
                        'create_registry': create_registry,
                        'issuer_aid': issuer_aid
                    }

                    # Launch witness authentication dialog
                    auth_dialog = WitnessAuthenticationDialog(
                        app=self.app,
                        hab=hab,
                        witness_ids=hab.kever.wits,
                        auth_only=True,
                        signals=self.app.vault.signals,
                        parent=self
                    )
                    auth_dialog.open()
                    return

            # No witnesses or no registry creation - proceed directly
            self._create_load_schema_doer(
                file_path=file_path,
                file_content=raw,
                create_registry=create_registry,
                issuer_aid=issuer_aid
            )

        except Exception as e:
            logger.error(f"Failed to create LoadSchemaDoer: {e}")
            self.load_button.setEnabled(True)
            self.load_button.setText("Load Schema")
            self.show_error(f"Failed to initiate schema loading: {str(e)}")

    def _create_load_schema_doer(self, oobi=None, file_path=None, file_content=None,
                                  create_registry=False, issuer_aid=None, auth_codes=None):
        """
        Create and launch the LoadSchemaDoer.

        Args:
            oobi: Optional OOBI URL
            file_path: Optional file path
            file_content: Optional file content bytes
            create_registry: Whether to create a credential registry
            issuer_aid: AID of the issuer identifier
            auth_codes: Optional list of auth codes for witness authentication
        """
        try:
            # Create the LoadSchemaDoer
            doer = LoadSchemaDoer(
                app=self.app,
                oobi=oobi,
                file_path=file_path,
                file_content=file_content,
                create_registry=create_registry,
                issuer_aid=issuer_aid,
                auth_codes=auth_codes,
                signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
            )

            # Launch the doer
            self.app.vault.extend([doer])

            workflow = "OOBI" if oobi else "file"
            logger.info(f"LoadSchemaDoer launched for {workflow}" +
                       (f" with {len(auth_codes)} auth codes" if auth_codes else ""))

        except Exception as e:
            logger.error(f"Failed to create LoadSchemaDoer: {e}")
            self.load_button.setEnabled(True)
            self.load_button.setText("Load Schema")
            self.show_error(f"Failed to initiate schema loading: {str(e)}")

    def _on_auth_codes_entered(self, data: dict):
        """
        Handle auth codes entered from WitnessAuthenticationDialog.

        Args:
            data: Dictionary containing 'codes' key with list of "witness_id:passcode" strings
        """
        codes = data.get('codes', [])
        logger.info(f"Received {len(codes)} auth codes from WitnessAuthenticationDialog")

        if not self.pending_load_params:
            logger.warning("Received auth codes but no pending load operation")
            return

        params = self.pending_load_params
        self.pending_load_params = None  # Clear pending state

        # Launch LoadSchemaDoer with auth codes
        if params['workflow'] == 'oobi':
            self._create_load_schema_doer(
                oobi=params['oobi'],
                create_registry=params['create_registry'],
                issuer_aid=params['issuer_aid'],
                auth_codes=codes
            )
        elif params['workflow'] == 'file':
            self._create_load_schema_doer(
                file_path=params['file_path'],
                file_content=params['file_content'],
                create_registry=params['create_registry'],
                issuer_aid=params['issuer_aid'],
                auth_codes=codes
            )

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
        """
        Handle successful schema loading.

        Args:
            data: Success data from doer
        """
        schema_title = data.get('title', 'Unknown')
        schema_said = data.get('said', '')
        registry_name = data.get('registry_name')

        logger.info(f"Successfully loaded schema: {schema_title} ({schema_said})")
        if registry_name:
            logger.info(f"Created credential registry: {registry_name}")

        # Reset button state
        self.load_button.setEnabled(True)
        self.load_button.setText("Load Schema")

        # Close dialog
        self.close()

    def _on_failure(self, error_msg):
        """
        Handle failed schema loading.

        Args:
            error_msg: Error message to display
        """
        logger.error(f"Failed to load schema: {error_msg}")

        # Reset button state
        self.load_button.setEnabled(True)
        self.load_button.setText("Load Schema")

        # Show error
        self.show_error(error_msg)
