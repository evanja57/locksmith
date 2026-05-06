# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.issue module

Dialog for issuing credentials
"""
from PySide6.QtCore import QDateTime
from PySide6.QtGui import QIcon, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QDateTimeEdit, QCheckBox
from keri import help
from keri.core import coring

from locksmith.core.credentialing import IssueCredentialDoer
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton,
    LocksmithTextListWidget
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, FloatingLabelLineEdit
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

logger = help.ogler.getLogger(__name__)


class IssueCredentialDialog(LocksmithDialog):
    """Dialog for issuing a credential."""
    def __init__(self, app, parent = None):
        """
        Initialize the IssueCredentialDialog.

        Args:
            app: Application instance
            parent: Parent widget
        """
        self.app = app

        # Initialize storage for dynamic fields
        self._dynamic_field_widgets = {}
        self._dynamic_fields_start_index = None
        self._const_fields_values = {}
        self._edge_dropdowns = {}  # Store edge credential dropdowns
        self._auth_pending = False
        self._auth_codes_connected = False

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #F8F9FF;")
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

        self.schema_dropdown = FloatingLabelComboBox("Schema")
        self.schema_dropdown.setFixedWidth(340)
        self._populate_schema_dropdown()
        layout.addWidget(self.schema_dropdown)

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

        self.recipient_dropdown = FloatingLabelComboBox("Recipient")
        self.recipient_dropdown.setFixedWidth(400)
        self._populate_recipient_dropdown()
        layout.addWidget(self.recipient_dropdown)

        layout.addStretch()
        control_widget = QWidget()
        control_widget.setStyleSheet("background-color: #F8F9FF;")
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
        self.cancel_button.clicked.connect(self.close)
        self.local_radio.toggled.connect(self._on_recipient_type_changed)
        self.remote_radio.toggled.connect(self._on_recipient_type_changed)
        self.schema_dropdown.currentIndexChanged.connect(self._on_schema_changed)
        self.issue_button.clicked.connect(self._on_issue)

        # Connect to vault signal bridge for doer events
        if hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            logger.info("IssueCredentialDialog: Connected to vault signal bridge")

    def _disconnect_auth_codes_signal(self):
        if not self._auth_codes_connected:
            return

        try:
            self.app.vault.signals.auth_codes_entered.disconnect(self._on_auth_codes_entered)
        except RuntimeError:
            pass
        self._auth_codes_connected = False

    def closeEvent(self, event):
        self._disconnect_auth_codes_signal()
        super().closeEvent(event)

    def _populate_schema_dropdown(self):
        """Populate the schema dropdown with loaded schemas from the vault."""
        self.schema_dropdown.clear()
        self.schema_dropdown.addItem("Select a schema...")

        try:
            # Get all schemas from the database
            for (said,), schemer in self.app.vault.hby.db.schema.getTopItemIter():
                logger.info(f"Found schema {said} checking with {self.app.vault.rgy.regs}")
                if not self.app.vault.rgy.registryByName(said):
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
                # Populate with local identifiers
                hby = self.app.vault.hby
                for hab_pre, hab in hby.habs.items():
                    # Format: "Name (prefix)"
                    display_text = f"{hab.name} ({hab_pre})"
                    self.recipient_dropdown.addItem(display_text, userData=hab_pre)
            else:
                # Populate with remote identifiers
                remote_ids = self.app.vault.org.list()
                for remote_id in remote_ids:
                    alias = remote_id.get('alias', 'Unknown')
                    pre = remote_id.get('id', '')
                    # Format: "Alias (prefix)"
                    display_text = f"{alias} ({pre})"
                    self.recipient_dropdown.addItem(display_text, userData=pre)

        except Exception as e:
            logger.exception(f"Error loading recipients: {e}")
            self.show_error(f"Failed to load recipients: {str(e)}")

    def _on_recipient_type_changed(self):
        """Handle recipient type radio button selection changes."""
        # Refresh the recipient dropdown when type changes
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
            schemer = self.app.vault.hby.db.schema.get(keys=(schema_said,))
            if not schemer:
                logger.error(f"Schema {schema_said} not found")
                self.show_error(f"Schema not found: {schema_said[:20]}...")
                return []

            schema = schemer.sed
            props = schema.get('properties', {})

            # Navigate to a.oneOf array
            if 'a' not in props or 'oneOf' not in props['a']:
                logger.error("Schema missing 'a.oneOf' structure")
                self.show_error("Schema has invalid structure (missing attributes definition)")
                return []

            one_of = props['a']['oneOf']

            # Find the object type (should be second element, index 1)
            attributes_obj = None
            for item in one_of:
                if isinstance(item, dict) and item.get('type') == 'object':
                    attributes_obj = item
                    break

            if not attributes_obj:
                logger.error("No object type found in oneOf array")
                self.show_error("Schema has invalid structure (no attribute properties found)")
                return []

            # Get properties and required list
            properties = attributes_obj.get('properties', {})
            required_fields = set(attributes_obj.get('required', []))

            # Filter and build field definitions
            field_defs = []
            excluded_fields = {'d', 'i', 'dt', 'u'}

            for prop_name, prop_def in properties.items():
                if prop_name in excluded_fields:
                    continue

                field_def = {
                    'name': prop_name,
                    'description': prop_def.get('description', prop_name),
                    'type': prop_def.get('type', 'string'),
                    'format': prop_def.get('format'),
                    'required': prop_name in required_fields,
                    'const': prop_def.get('const', None)
                }
                field_defs.append(field_def)

            logger.info(f"Parsed {len(field_defs)} fields from schema {schema_said}")
            return field_defs

        except Exception as e:
            logger.exception(f"Error parsing schema fields: {e}")
            self.show_error(f"Failed to parse schema fields: {str(e)}")
            return []

    def _parse_edge_requirements(self, schema_said: str) -> list[dict]:
        """
        Parse schema edge requirements for chained credentials.

        Args:
            schema_said: SAID of the schema to parse

        Returns:
            List of edge requirement dictionaries with keys:
            - name: edge property name
            - description: edge label
            - schema_said: SAID of required credential schema
        """
        try:
            # Get schema from database using SAID
            schemer = self.app.vault.hby.db.schema.get(keys=(schema_said,))
            if not schemer:
                logger.error(f"Schema {schema_said} not found")
                # Don't show error here - _parse_schema_fields already handles this
                return []

            schema = schemer.sed
            props = schema.get('properties', {})

            # Navigate to e.oneOf array
            if 'e' not in props or 'oneOf' not in props['e']:
                logger.debug("Schema has no 'e.oneOf' structure (no edge requirements)")
                return []

            one_of = props['e']['oneOf']

            edge_requirements = []

            # Process all object types in oneOf array
            for item in one_of:
                if not isinstance(item, dict) or item.get('type') != 'object':
                    continue

                # Get properties of this edge block
                edge_properties = item.get('properties', {})

                # Iterate through properties (skip 'd')
                for prop_name, prop_def in edge_properties.items():
                    if prop_name == 'd':
                        continue

                    # This should be a nested object with an 's' property
                    if not isinstance(prop_def, dict) or prop_def.get('type') != 'object':
                        continue

                    nested_props = prop_def.get('properties', {})

                    # Look for 's' property with const constraint
                    if 's' in nested_props:
                        s_def = nested_props['s']
                        schema_const = s_def.get('const')

                        if schema_const:
                            edge_req = {
                                'name': prop_name,
                                'description': prop_def.get('description', prop_name),
                                'schema_said': schema_const
                            }
                            edge_requirements.append(edge_req)
                            logger.debug(f"Found edge requirement: {prop_name} -> schema {schema_const}")

            logger.info(f"Parsed {len(edge_requirements)} edge requirements from schema {schema_said}")
            return edge_requirements

        except Exception as e:
            logger.exception(f"Error parsing edge requirements: {e}")
            self.show_error(f"Failed to parse chained credential requirements: {str(e)}")
            return []

    def _parse_rules_from_schema(self, schema_said: str) -> dict:
        """
        Parse schema and extract rules block for credential issuance.

        Args:
            schema_said: SAID of the schema to parse

        Returns:
            Dictionary representing the rules block with const values
        """
        try:
            # Get schema from database using SAID
            schemer = self.app.vault.hby.db.schema.get(keys=(schema_said,))
            if not schemer:
                logger.error(f"Schema {schema_said} not found")
                return {}

            schema = schemer.sed
            props = schema.get('properties', {})

            # Navigate to r.oneOf array
            if 'r' not in props:
                logger.debug("Schema has no 'r' property (no rules)")
                return {}

            r_prop = props['r']

            # Check if r has oneOf
            if 'oneOf' not in r_prop:
                logger.debug("Schema 'r' property has no 'oneOf' structure")
                return {}

            one_of = r_prop['oneOf']

            # Find the object type in the oneOf array
            rules_obj = None
            for item in one_of:
                if isinstance(item, dict) and item.get('type') == 'object':
                    rules_obj = item
                    break

            if not rules_obj:
                logger.debug("No object type found in r.oneOf array")
                return {}

            # Get properties of the rules object
            rules_properties = rules_obj.get('properties', {})

            # Build the rules block (exclude 'd' property)
            rules_block = {'d': ''}
            for prop_name, prop_def in rules_properties.items():
                if prop_name == 'd':
                    continue

                # Recursively extract const values from nested structure
                extracted = self._extract_rules_block(prop_def)
                if extracted:
                    rules_block[prop_name] = extracted

            _, rules_block = coring.Saider.saidify(sad=rules_block, label='d')
            logger.info(f"Parsed rules block with {len(rules_block)} rules from schema {schema_said}")
            return rules_block

        except Exception as e:
            logger.exception(f"Error parsing rules from schema: {e}")
            self.show_error(f"Failed to parse schema rules: {str(e)}")
            return {}

    def _extract_rules_block(self, prop_def: dict) -> dict | str | None:
        """
        Recursively extract rules block structure from schema property definition.

        Traverses nested objects and extracts 'const' values.

        Args:
            prop_def: Property definition from schema

        Returns:
            Extracted rules structure (dict, string, or None)
        """
        # If this property has a const value, return it directly
        if 'const' in prop_def:
            return prop_def['const']

        # If this property is an object, recursively process its properties
        if prop_def.get('type') == 'object' and 'properties' in prop_def:
            result = {}
            for nested_name, nested_def in prop_def['properties'].items():
                extracted = self._extract_rules_block(nested_def)
                if extracted is not None:
                    result[nested_name] = extracted

            return result if result else None

        # If no const or nested properties, return None
        return None

    def _get_credentials_for_schema(self, schema_said: str) -> list[dict]:
        """
        Get all credentials (issued and received) for a specific schema.

        Args:
            schema_said: SAID of the schema to filter by

        Returns:
            List of credential info dictionaries with 'said' and 'display_name'
        """
        try:
            reger = self.app.vault.rgy.reger
            credentials = []

            # Query credentials by schema SAID
            for (_,), saider in reger.schms.getTopItemIter(keys=(schema_said,)):
                credential = reger.creds.get(keys=(saider.qb64,))

                if not credential:
                    continue

                # Get schema info for display
                schema_name = "Unknown Schema"
                try:
                    schemer = self.app.vault.hby.db.schema.get(keys=(credential.schema,))
                    if schemer:
                        schema_name = schemer.sed.get('title', 'Unknown Schema')
                except:
                    pass

                cred_said = credential.said
                display_name = f"{schema_name} ({cred_said[:15]}...)"

                credentials.append({
                    'said': cred_said,
                    'display_name': display_name
                })

            logger.debug(f"Found {len(credentials)} credentials for schema {schema_said}")
            return credentials

        except Exception as e:
            logger.exception(f"Error querying credentials for schema: {e}")
            self.show_error(f"Failed to load chained credentials: {str(e)}")
            return []

    def _create_edge_dropdown(self, edge_req: dict) -> FloatingLabelComboBox:
        """
        Create a dropdown for selecting an edge credential.

        Args:
            edge_req: Edge requirement dict with name, description, schema_said

        Returns:
            FloatingLabelComboBox: Dropdown widget populated with matching credentials
        """
        # Add asterisk to indicate required field
        label = f"{edge_req['description']} *"

        dropdown = FloatingLabelComboBox(label)
        dropdown.setFixedWidth(400)

        # Add placeholder
        dropdown.addItem("Select a credential...")

        # Get credentials for this schema
        credentials = self._get_credentials_for_schema(edge_req['schema_said'])

        # Populate dropdown
        for cred in credentials:
            dropdown.addItem(cred['display_name'], userData=cred['said'])

        return dropdown

    def _create_field_widget(self, field_def: dict) -> QWidget:
        """
        Create appropriate widget for field based on type and format.

        Args:
            field_def: Field definition dict with name, type, format, description, required

        Returns:
            QWidget: Appropriate input widget for the field type
        """
        field_type = field_def['type']
        field_format = field_def.get('format')
        label = field_def['description']

        # Add asterisk to label if required
        if field_def['required']:
            label = f"{label} *"

        # Date-time fields
        if field_type == 'string' and field_format == 'date-time':
            widget = QDateTimeEdit()
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            widget.setCalendarPopup(True)
            widget.setDateTime(QDateTime.currentDateTime())
            widget.setMinimumHeight(50)
            widget.setStyleSheet("""
                QDateTimeEdit {
                    border: 1px solid #CCCCCC;
                    border-radius: 6px;
                    padding: 12px;
                    font-size: 14px;
                    background-color: #F8F9FF;
                }
                QDateTimeEdit:focus {
                    border: 2px solid #F57B03;
                }
            """)

            # Wrap in container with label
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(4)

            label_widget = QLabel(label)
            label_widget.setStyleSheet("font-weight: bold; font-size: 12px; color: #636466;")
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
            widget.setStyleSheet("""
                QCheckBox {
                    font-size: 14px;
                    spacing: 8px;
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
                }
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
            label_widget.setStyleSheet("font-weight: bold; font-size: 12px; color: #636466;")
            container_layout.addWidget(label_widget)
            container_layout.addWidget(widget)

            # Store reference to actual input widget
            container.input_widget = widget
            return container

        # Default: string fields
        else:
            widget = FloatingLabelLineEdit(label)
            widget.setFixedWidth(400)
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
        edge_reqs = self._parse_edge_requirements(schema_said)

        if not field_defs and not edge_reqs:
            logger.warning(f"No fields or edges to generate for schema {schema_said}")
            return

        # Start adding fields to the control layout
        # First add some space
        self.control_layout.addSpacing(20)

        # Add credential attributes section if there are any fields
        if field_defs:
            # Add section header
            fields_label = QLabel("Credential Attributes")
            fields_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self.control_layout.addWidget(fields_label)

            self.control_layout.addSpacing(15)

            # Generate and add widgets
            for field_def in field_defs:
                if field_def.get('const', None) is not None:
                    self._const_fields_values[field_def['name']] = field_def['const']
                    continue

                widget = self._create_field_widget(field_def)
                self.control_layout.addWidget(widget)
                self.control_layout.addSpacing(10)

                # Store reference with field name as key
                self._dynamic_field_widgets[field_def['name']] = {
                    'widget': widget,
                    'field_def': field_def
                }

            # Add spacing after attribute fields
            self.control_layout.addSpacing(15)

        # Add chained credentials section if there are edge requirements
        if edge_reqs:
            # Add section header
            edges_label = QLabel("Chained Credentials")
            edges_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self.control_layout.addWidget(edges_label)

            self.control_layout.addSpacing(15)

            # Generate and add edge dropdowns
            for edge_req in edge_reqs:
                dropdown = self._create_edge_dropdown(edge_req)
                self.control_layout.addWidget(dropdown)

                # Store reference with edge name as key
                self._edge_dropdowns[edge_req['name']] = {
                    'dropdown': dropdown,
                    'edge_req': edge_req
                }

            # Add spacing after edge dropdowns
            self.control_layout.addSpacing(15)

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
        self._edge_dropdowns = {}
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
        field_format = field_def.get('format')

        # Date-time fields (wrapped in container)
        if field_type == 'string' and field_format == 'date-time':
            if hasattr(widget, 'input_widget'):
                # Extract from QDateTimeEdit
                dt = widget.input_widget.dateTime()
                return dt.strftime("%b %d, %Y %I:%M %p")  # ISO 8601 format
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
                return widget.text().strip()
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
            if value is not None and value != '':
                attributes[field_name] = value

        return attributes

    def _extract_edge_credentials(self) -> dict:
        """
        Extract selected edge credential SAIDs from dropdowns.

        Returns:
            dict: Edge credentials with edge names as keys and credential SAIDs as values
        """
        edges = {}

        if not hasattr(self, '_edge_dropdowns'):
            return edges

        for edge_name, edge_info in self._edge_dropdowns.items():
            dropdown = edge_info['dropdown']
            edge_req = edge_info['edge_req']

            # Get selected credential SAID from dropdown userData
            current_index = dropdown.currentIndex()
            if current_index > 0:  # Skip placeholder at index 0
                cred_said = dropdown.itemData(current_index)
                if cred_said:
                    edges[edge_name] = {'cred_said': cred_said, 'schema_said': edge_req['schema_said']}

        return edges

    def _on_issue(self):
        """Handle Issue Credential button click."""
        # Clear any previous errors
        self.clear_error()

        # Validate fields
        if not self._validate_fields():
            return

        # Disable issue button during processing
        self.issue_button.setEnabled(False)
        self.issue_button.setText("Issuing...")

        # Get selected values
        schema_index = self.schema_dropdown.currentIndex()
        schema_said = self.schema_dropdown.itemData(schema_index)

        registryName = schema_said
        registry = self.app.vault.rgy.registryByName(registryName)
        if not registry:
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue Credential")
            self.show_error(f"Registry not found for schema {schema_said}")
            return

        hab = registry.hab
        if hab.kever.wits:
            self._auth_pending = True
            self.app.vault.signals.auth_codes_entered.connect(self._on_auth_codes_entered)
            self._auth_codes_connected = True

            # Launch witness authentication dialog
            auth_dialog = WitnessAuthenticationDialog(
                app=self.app,
                hab=hab,
                witness_ids=hab.kever.wits,
                auth_only=True,
                signals=self.app.vault.signals,
                parent=self
            )
            auth_dialog.finished.connect(self._on_auth_dialog_finished)
            auth_dialog.open()
        else:
            self._complete_issuance(codes=None)

    def _on_auth_dialog_finished(self, _result):
        if not self._auth_pending:
            return

        self._auth_pending = False
        self._disconnect_auth_codes_signal()
        self.issue_button.setEnabled(True)
        self.issue_button.setText("Issue Credential")

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

                # Only validate required fields
                if not field_def['required']:
                    continue

                # Get value based on widget type
                value = self._get_field_value(widget, field_def)

                # Check if empty
                if value is None or value == '' or (isinstance(value, str) and not value.strip()):
                    failed_fields.append(field_def['description'])

                    # Set error state on widget
                    if hasattr(widget, 'setProperty'):
                        widget.setProperty("error", True)
                        widget.style().unpolish(widget)
                        widget.style().polish(widget)

        # Validate edge credential selections (all are required)
        # Checks truthiness of self._edge_dropdowns to prevent dropping into this block when self._edge_dropdowns == {}
        if hasattr(self, '_edge_dropdowns') and self._edge_dropdowns:
            chained = False
            for edge_name, edge_info in self._edge_dropdowns.items():
                dropdown = edge_info['dropdown']

                # Check if a credential is selected (index 0 is placeholder)
                if dropdown.currentIndex() > 0:
                    chained = True
                    break

            if not chained:
                failed_fields.append("At least one chained credential is required")
                for edge_name, edge_info in self._edge_dropdowns.items():
                    dropdown = edge_info['dropdown']
                    # Set error state on dropdown
                    dropdown.setProperty("error", True)
                    dropdown.style().unpolish(dropdown)
                    dropdown.style().polish(dropdown)

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
        logger.debug(f"IssueCredentialDialog received doer_event: {doer_name} - {event_type}")

        # Handle credential issuance success
        if doer_name == "IssueCredentialDoer" and event_type == "credential_issued":
            logger.info(f"Credential issued successfully: {data.get('credential_said')}")

            # Re-enable issue button
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue Credential")

            # Show success message
            schema_title = data.get('schema_title', 'Credential')
            self.show_success(f"{schema_title} issued successfully!")

            # Close the dialog after a short delay
            # (Let user see the success message)

        # Handle credential issuance failure
        elif doer_name == "IssueCredentialDoer" and event_type == "credential_issuance_failed":
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Credential issuance failed: {error_msg}")

            # Re-enable issue button
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue Credential")

            # Show error message
            self.show_error(f"Failed to issue credential: {error_msg}")

    def _on_auth_codes_entered(self, data: dict):
        """
        Handle auth codes entered from WitnessAuthenticationDialog.

        Args:
            data: Dictionary containing 'codes' key with list of "witness_id:passcode" strings
        """
        if not self._auth_pending:
            return

        self._auth_pending = False
        self._disconnect_auth_codes_signal()
        codes = data.get('codes', [])
        logger.info(f"Received {len(codes)} auth codes from WitnessAuthenticationDialog")

        self._complete_issuance(codes=codes)

    def _complete_issuance(self, codes=None):
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
        rules = self._parse_rules_from_schema(schema_said)

        logger.info(f"Issuing credential with schema {schema_said} to recipient {recipient_pre}")
        logger.info(f"Credential attributes: {attributes}")
        logger.info(f"Edge credentials: {edges}")
        logger.info(f"Rules block: {rules}")

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
                signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
            )
            self.app.vault.extend([doer])

            logger.info(f"IssueCredentialDoer started for schema {schema_said}")

        except Exception as e:
            logger.exception(f"Error creating IssueCredentialDoer: {e}")
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue Credential")
            self.show_error(f"Failed to start credential issuance: {str(e)}")
