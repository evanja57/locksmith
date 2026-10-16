# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.issue module

Dialog for issuing credentials
"""

import json
from datetime import date, datetime, timezone

from PySide6.QtCore import Qt, QDateTime, Signal
from PySide6.QtGui import QIcon, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QDateTimeEdit, QCheckBox
from keri import help, kering
from keri.core import coring, scheming

from locksmith.ui import colors
from locksmith.core import credentialing, ipexing
from locksmith.core.credentialing import IssueCredentialDoer
from locksmith.core.habbing import list_eligible_local_identifiers
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton,
    LocksmithTextListWidget
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, FloatingLabelLineEdit
from locksmith.ui.vault.credentials.issued.grant import GrantCredentialDialog
from locksmith.ui.vault.credentials.presentation import attribute_label, attribute_view, credential_name, identifier_name
from locksmith.ui.vault.shared.witness_auth_mixin import (
    WitnessAuthenticationPanel,
    witness_auth_dialog_height
)

logger = help.ogler.getLogger(__name__)


class IssueCredentialDialog(LocksmithDialog):
    """Dialog for issuing a credential."""
    credential_created = Signal(str)

    def __init__(self, app, parent=None, *, request_said=None):
        """
        Initialize the IssueCredentialDialog.

        Args:
            app: Application instance
            parent: Parent widget
        """
        self.app = app
        self.vault = app.vault
        self.request_said = request_said
        self._issuance_id = None
        self._schema_supported = False

        # Initialize storage for dynamic fields
        self._dynamic_field_widgets = {}
        self._dynamic_fields_start_index = None
        self._const_fields_values = {}
        self._edge_dropdowns = {}  # Store edge credential dropdowns
        self._auth_panel = None
        self._workflow_mode = "issue"

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        self._issue_content_widget = content_widget
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Store reference to content layout for dynamic field insertion
        self.content_layout = layout

        layout.addSpacing(20)

        # Schema Selection
        schema_label = QLabel("Select Schema")
        schema_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(schema_label)

        self.schema_dropdown = FloatingLabelComboBox("Schema *")
        self.schema_dropdown.setFixedWidth(340)
        self._populate_schema_dropdown()
        layout.addWidget(self.schema_dropdown)

        self.authentication_dropdown = FloatingLabelComboBox("Issuer authentication")
        self.authentication_dropdown.addItem("Registry", userData='registry')
        self.authentication_dropdown.addItem("Issuer KEL anchor", userData='anchor')
        self.authentication_dropdown.addItem("Issuer signature", userData='signature')
        layout.addWidget(self.authentication_dropdown)
        self.authentication_help = QLabel()
        self.authentication_help.setWordWrap(True)
        layout.addWidget(self.authentication_help)
        self.authentication_dropdown.currentIndexChanged.connect(self._update_authentication_help)
        self._update_authentication_help()

        layout.addSpacing(15)

        # Recipient type radio buttons
        recipient_label = QLabel("Recipient Type")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(recipient_label)

        radio_layout = QHBoxLayout()
        self.local_radio = LocksmithRadioButton("Local Identifier")
        self.remote_radio = LocksmithRadioButton("Remote Identifier")
        self.remote_radio.setChecked(True)

        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.remote_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.local_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        layout.addSpacing(15)

        # Recipient identifier dropdown
        recipient_id_label = QLabel("Recipient Identifier")
        recipient_id_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(recipient_id_label)

        self.recipient_dropdown = FloatingLabelComboBox("Recipient *")
        self.recipient_dropdown.setFixedWidth(400)
        self._populate_recipient_dropdown()
        layout.addWidget(self.recipient_dropdown)

        layout.addStretch()
        control_widget = QWidget()
        control_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        self.control_layout = QVBoxLayout(control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(12)

        layout.addWidget(control_widget)

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.issue_button = LocksmithButton("Issue Credential")
        button_row.addWidget(self.issue_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(":/assets/material-icons/out-badge.svg")
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Issue Credential")
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

        self.setFixedSize(500, 720)

        # Create button group for recipient type radios (must be after super().__init__)
        self.recipient_type_group = QButtonGroup(self)
        self.recipient_type_group.addButton(self.local_radio)
        self.recipient_type_group.addButton(self.remote_radio)

        # Connect signals
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.local_radio.toggled.connect(self._on_recipient_type_changed)
        self.remote_radio.toggled.connect(self._on_recipient_type_changed)
        self.schema_dropdown.currentIndexChanged.connect(self._on_schema_changed)
        self.issue_button.clicked.connect(self._on_primary_clicked)

        # Connect to vault signal bridge for doer events
        if hasattr(self.vault, 'signals'):
            self.vault.signals.doer_event.connect(self._on_doer_event)
            self._doer_event_connected = True
            logger.info("IssueCredentialDialog: Connected to vault signal bridge")
        else:
            self._doer_event_connected = False

        self.finished.connect(self._on_dialog_finished)
        if request_said:
            request = self.vault.hby.db.exns.get((request_said,))
            schema = ipexing.request_schema(request)
            self.schema_dropdown.setCurrentIndex(self.schema_dropdown.combo_box.findData(schema))
            self.schema_dropdown.setEnabled(False)
            self.local_radio.setChecked(request.pre in self.vault.hby.prefixes)
            self.remote_radio.setChecked(request.pre not in self.vault.hby.prefixes)
            if self.recipient_dropdown.combo_box.findData(request.pre) < 0:
                self.recipient_dropdown.addItem(identifier_name(self.vault, request.pre), request.pre)
            self.recipient_dropdown.setCurrentIndex(self.recipient_dropdown.combo_box.findData(request.pre))
            self.recipient_dropdown.setEnabled(False)
            self.local_radio.setEnabled(False)
            self.remote_radio.setEnabled(False)

    def _disconnect_doer_event_signal(self):
        if not getattr(self, '_doer_event_connected', False):
            return
        try:
            self.vault.signals.doer_event.disconnect(self._on_doer_event)
        except RuntimeError:
            pass
        self._doer_event_connected = False

    def _on_dialog_finished(self, _result):
        self._disconnect_doer_event_signal()

    def _on_primary_clicked(self):
        if not self._current_vault():
            return
        if self._workflow_mode == 'issued':
            view = credentialing.credential(self.vault, self._issued_said)
            self._grant_dialog = GrantCredentialDialog(self.app, self.parentWidget(), self._issued_said,
                credential_name(view['schema']), view['sad']['i'])
            self.close()
            self._grant_dialog.open()
        elif self._workflow_mode == "auth":
            self._submit_auth_step()
        else:
            self._on_issue()

    def _on_cancel_clicked(self):
        if self._workflow_mode == "auth":
            self._show_issue_step()
        else:
            self.close()

    def _show_auth_step(self, hab):
        self.clear_error(resize_dialog=False)
        if self._dialog_resize_animation is not None:
            self._dialog_resize_animation.stop()
        self._base_height = None

        if self._auth_panel is not None:
            self._auth_panel.setParent(None)
            self._auth_panel.deleteLater()

        self._issue_content_widget.hide()
        self._auth_panel = WitnessAuthenticationPanel(
            app=self.app,
            hab=hab,
            witness_ids=list(hab.kever.wits),
            parent=self
        )
        self.content_layout.addWidget(self._auth_panel)

        self._workflow_mode = "auth"
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cancel_button.setText("Back")
        self.cancel_button.setEnabled(True)
        self.issue_button.setText("Authenticate")
        self.issue_button.setEnabled(True)
        self.setFixedSize(700, self._auth_step_height())
        self._re_enable_scrollbars()
        self.center_on_parent()

    def _auth_step_height(self) -> int:
        if self._auth_panel is None:
            return 440

        return witness_auth_dialog_height(
            self._auth_panel.individual_witnesses,
            self._auth_panel.batch_groups
        )

    def _show_issue_step(self):
        self.clear_error(resize_dialog=False)
        if self._dialog_resize_animation is not None:
            self._dialog_resize_animation.stop()
        self._base_height = None

        if self._auth_panel is not None:
            self.content_layout.removeWidget(self._auth_panel)
            self._auth_panel.setParent(None)
            self._auth_panel.deleteLater()
            self._auth_panel = None

        self._issue_content_widget.show()
        self._workflow_mode = "issue"
        self.cancel_button.setText("Cancel")
        self.cancel_button.setEnabled(True)
        self.issue_button.setText("Issue Credential")
        self.issue_button.setEnabled(True)
        self.setFixedSize(500, 720)
        self._re_enable_scrollbars()
        self.center_on_parent()

    def _set_primary_button_idle(self):
        self.cancel_button.setEnabled(True)
        self.issue_button.setEnabled(True)
        if self._workflow_mode == "auth":
            self.issue_button.setText("Authenticate")
        else:
            self.issue_button.setText("Issue Credential")

    def _submit_auth_step(self):
        if not self._current_vault():
            return
        if self._auth_panel is None:
            self._show_issue_step()
            return

        self.clear_error()
        valid, codes, error_message = self._auth_panel.validate_authentication_codes()
        if not valid:
            self.show_error(error_message)
            return

        self.issue_button.setEnabled(False)
        self.issue_button.setText("Issuing...")
        self.cancel_button.setEnabled(False)
        self._complete_issuance(codes=codes)

    def _current_vault(self):
        if self.app.vault is self.vault and not getattr(self.vault, 'closed', False):
            return True
        self.show_error("This vault is closed")
        return False

    def _update_authentication_help(self, _index=None):
        self.authentication_help.setText({
            'registry': 'A registry records credential status, including revocation.',
            'anchor': 'A KEL anchor remains verifiable after issuer key rotation.',
            'signature': 'For a transferable issuer, this signature requires the current signing keys.',
        }[self.authentication_dropdown.currentData()])

    def _populate_schema_dropdown(self):
        """Populate the schema dropdown with loaded schemas from the vault."""
        self.schema_dropdown.clear()
        self.schema_dropdown.addItem("Select a schema...")

        try:
            # Get all schemas from the database
            for (said,), schemer in self.vault.hby.db.schema.getTopItemIter():
                issuer_pre = self.vault.db.issuers.get(keys=(said,))
                if not issuer_pre or self.vault.hby.habByPre(issuer_pre) is None:
                    continue

                sed = schemer.sed
                schema_title = sed.get('title', 'Untitled')
                schema_version = sed.get('version', '')

                # Format: "Title v1.0.0 (SAID...)"
                display_text = f"{schema_title}"
                if schema_version:
                    display_text += f" v{schema_version}"

                # Store the full SAID as user data
                self.schema_dropdown.addItem(display_text, userData=said)

        except Exception as e:
            logger.exception(f"Error loading schemas: {e}")
            self.show_error(f"Failed to load schemas: {str(e)}")

    def _populate_recipient_dropdown(self):
        """Populate the recipient dropdown based on the selected recipient type."""
        self.recipient_dropdown.clear()
        self.recipient_dropdown.addItem("Select a recipient...")

        try:
            if self.local_radio.isChecked():
                for identifier in list_eligible_local_identifiers(self.app):
                    display_text = identifier_name(self.vault, identifier['prefix'])
                    self.recipient_dropdown.addItem(display_text, userData=identifier['prefix'])
            else:
                # Populate with remote identifiers
                remote_ids = self.vault.org.list()
                for remote_id in remote_ids:
                    pre = remote_id.get('id', '')
                    display_text = identifier_name(self.vault, pre)
                    self.recipient_dropdown.addItem(display_text, userData=pre)

        except Exception as e:
            logger.exception(f"Error loading recipients: {e}")
            self.show_error(f"Failed to load recipients: {str(e)}")

    def _on_recipient_type_changed(self):
        """Handle recipient type radio button selection changes."""
        # Refresh the recipient dropdown when type changes
        if self._current_vault():
            self._populate_recipient_dropdown()

    def _parse_schema_fields(self, schema_said: str) -> list[dict]:
        """
        Parse schema and extract field definitions for dynamic form generation.

        Args:
            schema_said: SAID of the schema to parse

        Returns:
            List of field definition dictionaries with keys:
            - name: property name
            - description: field label
            - type: JSON schema type (string, number, integer, boolean)
            - format: JSON schema format (date-time, ISO 17442, etc.)
            - required: boolean indicating if field is required
        """
        try:
            # Get schema from database using SAID
            schemer = self.vault.hby.db.schema.get(keys=(schema_said,))
            if not schemer:
                logger.error(f"Schema {schema_said} not found")
                self.show_error(f"Schema not found: {schema_said[:20]}...")
                return []

            schema = schemer.sed
            props = schema.get('properties', {})

            definitions = credentialing.attribute_schemas(schema)
            self._aggregate = 'A' in props and 'a' not in props
            self._schema_supported = True
            field_defs = []
            if self._aggregate:
                for index, definition in enumerate(definitions):
                    field = self._field_definition(str(index), definition, True)
                    field['section'] = 'A'
                    field_defs.append(field)
            else:
                definition = definitions[0]
                for name, prop in definition.get('properties', {}).items():
                    if name not in ('d', 'i'):
                        field_defs.append(self._field_definition(
                            name, prop, name in definition.get('required', [])))

            logger.info(f"Parsed {len(field_defs)} fields from schema {schema_said}")
            return field_defs

        except Exception as e:
            logger.exception(f"Error parsing schema fields: {e}")
            self.show_error(f"Failed to parse schema fields: {str(e)}")
            return []

    @staticmethod
    def _field_definition(name, prop, required):
        detail = credentialing.schema_detail(prop) or credentialing.schema_detail(prop, 'array') or prop
        definition = dict(name=name, description=attribute_label(name, detail),
                          type=detail.get('type', 'string'), format=detail.get('format'),
                          required=required, const=detail.get('const'),
                          minLength=detail.get('minLength', 0), schema=detail)
        # Older schemas describe timestamps without a JSON Schema format.
        description = detail.get('description', '')
        if definition['type'] == 'string' and not definition['format']:
            if 'RFC-3339' in description or 'ISO-8601' in description:
                definition.update(input_format='date' if 'MBZ' in description else 'datetime',
                                  hint=('Use YYYY-MM-DD.' if 'MBZ' in description
                                        else 'Use YYYY-MM-DD HH:MM in UTC.'))
            elif name == 'dt':
                definition['format'] = 'date-time'
        return definition

    def _parse_rules_from_schema(self, schema_said):
        if self._rules_widget is None:
            return None
        return self._get_field_value(*self._rules_widget)

    @staticmethod
    def _requires_input(field_def: dict) -> bool:
        """Mark inputs whose empty value would fail the credential schema."""
        if not field_def['required'] or field_def['type'] in ('object', 'boolean') or field_def['name'] == 'u':
            return False
        if field_def['type'] not in ('string', 'array'):
            return True
        empty = '' if field_def['type'] == 'string' else []
        try:
            scheming.JSONSchema().verify_json(schema=field_def['schema'], raw=json.dumps(empty).encode())
        except kering.ValidationError:
            return True
        return False

    def _create_field_widget(self, field_def: dict) -> QWidget:
        """
        Create appropriate widget for field based on type and format.

        Args:
            field_def: Field definition dict with name, type, format, description, required

        Returns:
            QWidget: Appropriate input widget for the field type
        """
        field_type = field_def['type']
        field_format = field_def.get('input_format', field_def.get('format'))
        label = field_def['description']

        needs_input = self._requires_input(field_def)
        if needs_input:
            label = f"{label} *"

        if field_type == 'object':
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            heading = QLabel(label)
            heading.setWordWrap(True)
            layout.addWidget(heading)
            definition = field_def.get('schema', {})
            container.fields = {}
            container.include = None
            if not field_def['required']:
                container.include = QCheckBox('Include ' + field_def['description'])
                layout.addWidget(container.include)
            container.generated = {}
            for name, prop in definition.get('properties', {}).items():
                if name == 'i' and field_def.get('section') == 'A':
                    container.generated[name] = self.recipient_dropdown.currentData()
                    self.recipient_dropdown.currentIndexChanged.connect(
                        lambda *_, container=container: container.generated.update(
                            i=self.recipient_dropdown.currentData()))
                    layout.addWidget(QLabel('Subject: selected recipient'))
                    continue
                if name in ('d', 'u'):
                    container.generated[name] = prop.get('const', '' if name == 'd' else coring.Noncer().qb64)
                    continue
                child = self._field_definition(name, prop, name in definition.get('required', []))
                child['section'] = field_def.get('section')
                if child['section'] == 'e' and name == 'n':
                    widget = FloatingLabelComboBox(child['description'])
                    widget.addItem('Choose a credential', '')
                    schema_pin = definition.get('properties', {}).get('s', {}).get('const')
                    for view in credentialing.credentials(self.vault):
                        schema = view['sad']['s']
                        schema = schema if isinstance(schema, str) else schema['$id']
                        if view['status']['et'] in ('issued', 'authenticated') and (not schema_pin or schema_pin == schema):
                            widget.addItem(credential_name(view['schema']) + ' · ' + view['sad']['d'][:8], view['sad']['d'])
                else:
                    widget = (attribute_view(child['description'], prop['const'], prop) if 'const' in prop
                              else self._create_field_widget(child))
                container.fields[name] = (widget, child)
                layout.addWidget(widget)
                if container.include is not None and 'const' not in prop:
                    widget.setEnabled(False)
                    container.include.toggled.connect(widget.setEnabled)
            if field_def.get('section') == 'e' and 'n' in container.fields and 's' in container.fields:
                selector = container.fields['n'][0]
                schema_widget, schema_field = container.fields['s']
                if 'const' not in schema_field['schema']:
                    schema_widget.setEnabled(False)
                    def selected(*_):
                        said = selector.currentData()
                        if said:
                            schema = credentialing.credential(self.vault, said)['sad']['s']
                            schema_widget.setText(schema if isinstance(schema, str) else schema['$id'])
                        else:
                            schema_widget.setText('')
                    selector.currentIndexChanged.connect(selected)
            return container

        if field_def['schema'].get('enum'):
            widget = FloatingLabelComboBox(label)
            for value in field_def['schema']['enum']:
                widget.addItem(str(value), value)
            return widget

        # Date-time fields
        if field_type == 'string' and field_format == 'date-time':
            widget = QDateTimeEdit()
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            widget.setCalendarPopup(True)
            widget.setDateTime(QDateTime.currentDateTime())
            widget.setMinimumHeight(50)
            widget.setStyleSheet(f"""
                QDateTimeEdit {{
                    border: 1px solid {colors.BORDER_NEUTRAL};
                    border-radius: 6px;
                    padding: 12px;
                    font-size: 14px;
                    background-color: {colors.BACKGROUND_CONTENT};
                }}
                QDateTimeEdit:focus {{
                    border: 2px solid {colors.PRIMARY};
                }}
            """)

            # Wrap in container with label
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(4)

            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {colors.TEXT_SECONDARY};")
            container_layout.addWidget(label_widget)
            container_layout.addWidget(widget)

            # Store reference to actual input widget
            container.input_widget = widget
            return container

        # Number fields
        elif field_type in ('number', 'integer'):
            widget = FloatingLabelLineEdit(label)
            widget.setFixedWidth(400)

            # Add validator for numbers
            if field_type == 'integer':
                widget.line_edit.setValidator(QIntValidator())
            else:
                widget.line_edit.setValidator(QDoubleValidator())

            return widget

        # Boolean fields
        elif field_type == 'boolean':
            widget = QCheckBox(label)
            widget.setStyleSheet(f"""
                QCheckBox {{
                    font-size: 14px;
                    spacing: 8px;
                }}
                QCheckBox::indicator {{
                    width: 20px;
                    height: 20px;
                    border: 2px solid {colors.BORDER_NEUTRAL};
                    border-radius: 4px;
                    background-color: {colors.BACKGROUND_CONTENT};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {colors.PRIMARY};
                    border-color: {colors.PRIMARY};
                }}
            """)
            return widget

        # Array fields
        elif field_type == 'array':
            # Remove asterisk from label if present, LocksmithTextListWidget handles its own label
            label_text = label.replace(' *', '') if label.endswith(' *') else label

            widget = LocksmithTextListWidget(label=label_text, max_height=120)
            widget.setFixedWidth(400)

            # Add a container with label for consistency
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(4)

            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {colors.TEXT_SECONDARY};")
            container_layout.addWidget(label_widget)
            container_layout.addWidget(widget)

            # Store reference to actual input widget
            container.input_widget = widget
            return container

        # Default: string fields
        else:
            widget = FloatingLabelLineEdit(label)
            widget.setFixedWidth(400)
            suffix = ' *' if needs_input else ''
            metrics = widget.label.fontMetrics()
            visible_label = metrics.elidedText(field_def['description'], Qt.TextElideMode.ElideRight,
                                               widget.width() - 32 - metrics.horizontalAdvance(suffix))
            widget.setPlaceholderText(visible_label + suffix)
            widget.setToolTip(label)
            widget.line_edit.setAccessibleName(label)
            return widget

    def _generate_dynamic_fields(self, schema_said: str):
        """
        Generate dynamic form fields based on selected schema.

        Args:
            schema_said: SAID of the schema to generate fields for
        """
        # Clear previous dynamic fields
        self._clear_dynamic_fields()

        # Reset stored widgets
        self._dynamic_field_widgets = {}
        self._edge_dropdowns = {}

        # Parse schema to get field definitions
        field_defs = self._parse_schema_fields(schema_said)

        # Parse edge requirements
        edge_reqs = []
        self._edge_widget = self._rules_widget = None


        # Start adding fields to the control layout
        # First add some space
        self.control_layout.addSpacing(20)

        # Add credential attributes section if there are any fields
        if field_defs:
            # Add section header
            fields_label = QLabel("Credential Attributes")
            fields_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self.control_layout.addWidget(fields_label)
            field_help = QLabel('Fields marked * need a value. All other text fields may be left blank.')
            field_help.setWordWrap(True)
            field_help.setFixedWidth(400)
            self.control_layout.addWidget(field_help)

            self.control_layout.addSpacing(15)

            # Generate and add widgets
            for field_def in field_defs:
                if field_def.get('const', None) is not None:
                    self._const_fields_values[field_def['name']] = field_def['const']
                    continue

                widget = self._create_field_widget(field_def)
                self.control_layout.addWidget(widget)
                if hint := field_def.get('hint'):
                    help_label = QLabel(hint)
                    help_label.setWordWrap(True)
                    help_label.setFixedWidth(400)
                    help_label.setStyleSheet(f'font-size: 12px; color: {colors.TEXT_SECONDARY};')
                    self.control_layout.addWidget(help_label)
                    widget.setToolTip(hint)
                    widget.line_edit.setAccessibleDescription(hint)
                self.control_layout.addSpacing(10)

                # Store reference with field name as key
                self._dynamic_field_widgets[field_def['name']] = {
                    'widget': widget,
                    'field_def': field_def
                }

            def needs_value(widget, definition):
                if 'const' in definition['schema']:
                    return False
                if definition['type'] == 'object':
                    return any(needs_value(child, field) for child, field in widget.fields.values())
                return self._requires_input(definition)

            if not any(needs_value(info['widget'], info['field_def'])
                       for info in self._dynamic_field_widgets.values()):
                field_help.setText('All text fields below may be left blank.')

            # Add spacing after attribute fields
            self.control_layout.addSpacing(15)

        schema = self.vault.hby.db.schema.get((schema_said,)).sed
        for name, label in (('e', 'Credential links'), ('r', 'Rules')):
            prop = schema.get('properties', {}).get(name)
            if prop is None or credentialing.schema_detail(prop) is None:
                continue
            definition = self._field_definition(name, prop, name in schema.get('required', []))
            definition['description'] = label
            definition['section'] = name
            widget = self._create_field_widget(definition)
            self.control_layout.addWidget(widget)
            if name == 'e':
                self._edge_widget = (widget, definition)
            else:
                self._rules_widget = (widget, definition)

        logger.info(f"Generated {len(self._dynamic_field_widgets)} dynamic fields and {len(self._edge_dropdowns)} edge dropdowns for schema {schema_said}")

    def _clear_dynamic_fields(self):
        """Clear all dynamically generated field widgets."""

        # Remove all widgets from dynamic fields section
        # Count backwards to avoid index shifting
        items_to_remove = []
        for i in range(self.control_layout.count()):
            item = self.control_layout.itemAt(i)
            if item and item.widget():
                # Stop at the stretch item (no widget)
                items_to_remove.append(item.widget())

        # Remove collected widgets
        for widget in items_to_remove:
            self.control_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

        for i in reversed(range(self.control_layout.count())):
            item = self.control_layout.itemAt(i)
            if item.spacerItem():
                self.control_layout.takeAt(i)

        # Reset storage
        self._dynamic_field_widgets = {}
        self._const_fields_values = {}
        self._edge_dropdowns = {}
        self._edge_widget = self._rules_widget = None
        self.control_layout.setSpacing(0)

        logger.debug("Cleared dynamic fields and edge dropdowns")

    def _on_schema_changed(self, index: int):
        """
        Handle schema dropdown selection changes.

        Args:
            index: Selected index in dropdown
        """
        # Clear any previous errors
        self.clear_error()
        if not self._current_vault():
            return
        self._schema_supported = False

        # Skip if invalid selection
        if index <= 0:
            logger.info("No schema selected, clearing dynamic fields")
            self._clear_dynamic_fields()
            return

        # Get selected schema SAID
        schema_said = self.schema_dropdown.itemData(index)
        logger.info(f"Selected schema {schema_said}")

        if not schema_said:
            logger.warning("No SAID found for selected schema")
            return

        schemer = self.vault.hby.db.schema.get(keys=(schema_said,))
        properties = schemer.sed.get('properties', {})
        requires_registry = 'rd' in schemer.sed.get('required', [])
        permits_registry = 'rd' in properties or schemer.sed.get('additionalProperties', True)
        issuer = self.vault.hby.habByPre(self.vault.db.issuers.get(keys=(schema_said,)))
        modes = self.authentication_dropdown.combo_box
        for index in range(modes.count()):
            mode = modes.itemData(index)
            enabled = permits_registry if mode == 'registry' else not requires_registry
            if mode == 'anchor':
                enabled = enabled and issuer is not None and issuer.kever.prefixer.transferable
            modes.model().item(index).setEnabled(enabled)
        if not modes.model().item(modes.currentIndex()).isEnabled():
            preferred = ('registry' if requires_registry else
                         'anchor' if modes.model().item(modes.findData('anchor')).isEnabled() else 'signature')
            modes.setCurrentIndex(modes.findData(preferred))

        # Generate fields for this schema
        self._generate_dynamic_fields(schema_said)

    @staticmethod
    def _get_field_value(widget: QWidget, field_def: dict):
        """
        Extract value from a field widget based on its type.

        Args:
            widget: The widget to extract value from
            field_def: Field definition with type information

        Returns:
            Extracted value (str, int, float, bool, or None)
        """
        field_type = field_def['type']
        field_format = field_def.get('input_format', field_def.get('format'))

        if isinstance(widget, FloatingLabelComboBox):
            return widget.currentData()

        if field_type == 'object':
            if widget.include is not None and not widget.include.isChecked():
                return None
            result = dict(widget.generated)
            for name, (child, definition) in widget.fields.items():
                value = (definition['schema']['const'] if 'const' in definition['schema']
                         else IssueCredentialDialog._get_field_value(child, definition))
                if value is not None and (value != '' or definition['required']):
                    result[name] = value
                if definition['required'] and value is None:
                    raise ValueError(f"{definition['description']} is required")
                if (isinstance(value, str) and (value or definition['required'])
                        and len(value) < definition.get('minLength', 0)):
                    raise ValueError(f"{definition['description']} needs at least {definition['minLength']} characters")
            return result

        # Date-time fields (wrapped in container)
        if field_type == 'string' and field_format == 'date-time':
            if hasattr(widget, 'input_widget'):
                # Extract from QDateTimeEdit
                dt = widget.input_widget.dateTime()
                return dt.toUTC().toString(Qt.DateFormat.ISODateWithMs)
            return None

        # Array fields (wrapped in container)
        elif field_type == 'array':
            if hasattr(widget, 'input_widget'):
                # Extract from LocksmithTextListWidget
                return widget.input_widget.get_items()
            return []

        # Boolean fields
        elif field_type == 'boolean':
            if isinstance(widget, QCheckBox):
                return widget.isChecked()
            return False

        # Number fields
        elif field_type in ('number', 'integer'):
            text = None
            if hasattr(widget, 'text'):
                text = widget.text().strip()
            if not text:
                return None
            try:
                return int(text) if field_type == 'integer' else float(text)
            except ValueError:
                return None

        # String fields (FloatingLabelLineEdit)
        else:
            if hasattr(widget, 'text'):
                value = widget.text().strip()
                if value and field_def.get('input_format') == 'date':
                    try:
                        parsed = date.fromisoformat(value)
                        if parsed.isoformat() != value:
                            raise ValueError
                    except ValueError:
                        raise ValueError('Enter a valid date in YYYY-MM-DD format.') from None
                    # SEDI uses a date-time with the time set to zero (MBZ).
                    return f'{value}T00:00:00.000000+00:00'
                if value and field_def.get('input_format') == 'datetime':
                    try:
                        parsed = datetime.strptime(value, '%Y-%m-%d %H:%M')
                        if parsed.isoformat(sep=' ', timespec='minutes') != value:
                            raise ValueError
                    except ValueError:
                        raise ValueError('Enter a valid date and time in YYYY-MM-DD HH:MM format (UTC).') from None
                    return parsed.replace(tzinfo=timezone.utc).isoformat(timespec='microseconds')
                return value
            return None

    def _extract_credential_attributes(self) -> dict:
        """
        Extract values from dynamic field widgets to build credential attributes.

        Returns:
            dict: Credential attributes with field names as keys
        """
        attributes = {}

        for field_name, value in self._const_fields_values.items():
            attributes[field_name] = value

        if not hasattr(self, '_dynamic_field_widgets'):
            return attributes

        for field_name, field_info in self._dynamic_field_widgets.items():
            widget = field_info['widget']
            field_def = field_info['field_def']

            value = self._get_field_value(widget, field_def)

            # Only include non-empty values
            if value is not None and (value != '' or (field_def['required'] and field_name != 'u')):
                attributes[field_name] = value

        if self._aggregate:
            blocks = []
            definitions = credentialing.attribute_schemas(
                self.vault.hby.db.schema.get((self.schema_dropdown.currentData(),)).sed)
            for index, definition in enumerate(definitions):
                block = attributes[str(index)]
                blocks.append(block)
            return blocks
        return attributes

    def _extract_edge_credentials(self):
        if self._edge_widget is None:
            return None
        return self._get_field_value(*self._edge_widget)

    def _on_issue(self):
        """Handle Issue Credential button click."""
        # Clear any previous errors
        self.clear_error()
        if not self._current_vault():
            return

        # Validate fields
        if not self._validate_fields():
            return

        # Get selected values
        schema_index = self.schema_dropdown.currentIndex()
        schema_said = self.schema_dropdown.itemData(schema_index)

        issuer_pre = self.vault.db.issuers.get(keys=(schema_said,))
        hab = self.vault.hby.habByPre(issuer_pre) if issuer_pre else None
        if hab is None:
            self.show_error("Select a local issuer for this schema first")
            return

        if hab.kever.wits and self.authentication_dropdown.currentData() != 'signature':
            self._show_auth_step(hab)
            return

        self.issue_button.setEnabled(False)
        self.issue_button.setText("Issuing...")
        self.cancel_button.setEnabled(False)
        self._complete_issuance(codes=None)

    def _validate_fields(self):
        """
        Validate all required fields.

        Returns:
            bool: True if all fields are valid, False otherwise
        """
        # Reset field styles
        self.schema_dropdown.setProperty("error", False)
        self.schema_dropdown.style().unpolish(self.schema_dropdown)
        self.schema_dropdown.style().polish(self.schema_dropdown)

        self.recipient_dropdown.setProperty("error", False)
        self.recipient_dropdown.style().unpolish(self.recipient_dropdown)
        self.recipient_dropdown.style().polish(self.recipient_dropdown)

        failed_fields = []
        if not self._schema_supported:
            self.show_error("This schema has no supported expanded attribute definition")
            return False

        # Validate schema selection
        if self.schema_dropdown.currentIndex() <= 0:
            failed_fields.append("Schema")
            self.schema_dropdown.setProperty("error", True)
            self.schema_dropdown.style().unpolish(self.schema_dropdown)
            self.schema_dropdown.style().polish(self.schema_dropdown)

        # Validate recipient selection
        if self.recipient_dropdown.currentIndex() <= 0:
            failed_fields.append("Recipient")
            self.recipient_dropdown.setProperty("error", True)
            self.recipient_dropdown.style().unpolish(self.recipient_dropdown)
            self.recipient_dropdown.style().polish(self.recipient_dropdown)

        # Validate dynamic fields
        if hasattr(self, '_dynamic_field_widgets'):
            for field_name, field_info in self._dynamic_field_widgets.items():
                field_def = field_info['field_def']
                widget = field_info['widget']

                # Get value based on widget type
                try:
                    value = self._get_field_value(widget, field_def)
                except (ValueError, TypeError) as error:
                    self.show_error(f"{field_def['description']}: {error}")
                    self.scroll_area.ensureWidgetVisible(widget)
                    return False

                # Check if empty
                invalid = field_def['required'] and value is None
                if isinstance(value, str) and (value or field_def['required']):
                    invalid |= len(value) < field_def['minLength']
                if field_name == 'u' and value == '':
                    invalid = False  # The issuer generates a nonce when none is supplied.
                elif value is not None and (value != '' or field_def['required']):
                    try:
                        scheming.JSONSchema().verify_json(schema=field_def['schema'], raw=json.dumps(value).encode())
                    except kering.ValidationError as error:
                        detail = str(error).splitlines()[0].removeprefix('Credential validation exception: ')
                        self.show_error(f"{field_def['description']}: {detail}")
                        self.scroll_area.ensureWidgetVisible(widget)
                        return False
                if invalid:
                    failed_fields.append(field_def['description'])

                    # Set error state on widget
                    if hasattr(widget, 'setProperty'):
                        widget.setProperty("error", True)
                        widget.style().unpolish(widget)
                        widget.style().polish(widget)

        for section in (self._edge_widget, self._rules_widget):
            if section is None:
                continue
            widget, definition = section
            try:
                value = self._get_field_value(widget, definition)
                if value is not None:
                    scheming.JSONSchema().verify_json(schema=definition['schema'], raw=json.dumps(value).encode())
            except (ValueError, TypeError, kering.ValidationError) as error:
                self.show_error(f"{definition['description']}: {error}")
                return False

        if failed_fields:
            field_text = "field" if len(failed_fields) == 1 else "fields"
            self.show_error(f"Please fill in required {field_text}: {', '.join(failed_fields)}")
            return False

        return True

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        if self.app.vault is not self.vault or getattr(self.vault, 'closed', False):
            self._disconnect_doer_event_signal()
            return
        if (doer_name != 'IssueCredentialDoer' or self._issuance_id is None
                or data.get('issuance_id') != self._issuance_id):
            return
        logger.debug(f"IssueCredentialDialog received doer_event: {doer_name} - {event_type}")

        # Handle credential issuance success
        if event_type == "credential_issued":
            self._issuance_id = None
            logger.info(f"Credential issued successfully: {data.get('credential_said')}")
            self._issued_said = data['credential_said']
            if self.request_said:
                self.credential_created.emit(self._issued_said)
                self.accept()
                return
            self._workflow_mode = 'issued'
            self.schema_dropdown.setEnabled(False)
            self.authentication_dropdown.setEnabled(False)
            self.local_radio.setEnabled(False)
            self.remote_radio.setEnabled(False)
            self.recipient_dropdown.setEnabled(False)
            self.control_layout.parentWidget().setEnabled(False)
            self.issue_button.setText('Grant…')
            self.issue_button.setEnabled(True)
            self.cancel_button.setText('Close')
            self.cancel_button.setEnabled(True)
            self.show_success('Credential created. Choose Grant to send it, or close to send it later.')

        # Handle credential issuance failure
        elif event_type == "credential_issuance_failed":
            self._issuance_id = None
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Credential issuance failed: {error_msg}")

            self._set_primary_button_idle()
            self.show_error(f"Failed to issue credential: {error_msg}")

    def _complete_issuance(self, codes=None):
        if not self._current_vault():
            return
        if self.request_said:
            request = self.vault.hby.db.exns.get((self.request_said,))
            if ('Offer' not in ipexing.responses(self.vault, request)
                    or self.vault.db.issuers.get((ipexing.request_schema(request),)) != request.sad['ri']):
                self._set_primary_button_idle()
                self.show_error(ipexing.expiry_error(self.vault, request)
                                or 'This request has changed. Return to Activity to review it.')
                return
        # Get selected values
        schema_index = self.schema_dropdown.currentIndex()
        schema_said = self.schema_dropdown.itemData(schema_index)

        recipient_index = self.recipient_dropdown.currentIndex()
        recipient_pre = self.recipient_dropdown.itemData(recipient_index)

        # Extract dynamic field values
        attributes = self._extract_credential_attributes()

        # Extract edge credential SAIDs
        edges = self._extract_edge_credentials()

        # Parse rules from schema
        rules = self._parse_rules_from_schema(schema_said) or None

        logger.info(f"Issuing credential with schema {schema_said} to recipient {recipient_pre}")

        try:
            # Create and start IssueCredentialDoer
            doer = IssueCredentialDoer(
                app=self.app,
                schema_said=schema_said,
                recipient_pre=recipient_pre,
                attributes=attributes,
                edges=edges,
                rules=rules,
                codes=codes,
                authentication=self.authentication_dropdown.currentData(),
                signal_bridge=self.vault.signals if hasattr(self.vault, 'signals') else None
            )
            self._issuance_id = doer.issuance_id
            self.vault.extend([doer])

            logger.info(f"IssueCredentialDoer started for schema {schema_said}")

        except Exception as e:
            logger.exception(f"Error creating IssueCredentialDoer: {e}")
            self._set_primary_button_idle()
            self.show_error(f"Failed to start credential issuance: {str(e)}")
