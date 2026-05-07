# -*- encoding: utf-8 -*-
"""
locksmith.ui.vaults.create module

Dialog for creating new vaults
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup
from keri import help
from keri.core import signing

from locksmith.core import habbing
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    FloatingLabelLineEdit,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton, LocksmithCheckbox
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, LocksmithLineEdit
from locksmith.ui.vault.shared.delegation_mixin import DelegationMixin

logger = help.ogler.getLogger(__name__)


class CreateIdentifierDialog(DelegationMixin, LocksmithDialog):
    """Dialog for initializing a new vault."""

    identifier_created = Signal(str, str)
    identifier_creation_failed = Signal(str)

    def __init__(self, icon_path, app, parent=None, config=None):
        """
        Initialize the CreateVaultDialog.

        Args:
            parent: Parent widget (typically main window)
            config: LocksmithConfig instance
        """
        self.config = config
        self.app = app

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addSpacing(10)

        self.name_field = FloatingLabelLineEdit("Alias")
        self.name_field.setFixedWidth(360)
        layout.addWidget(self.name_field)
        layout.addSpacing(15)

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.create_button = LocksmithButton("Create")
        button_row.addWidget(self.create_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(icon_path)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Add a Local Identifier")
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

        # Set initial size (will expand when error is shown or collapsible sections expand)
        self.setFixedSize(420, 320)

        # Connect buttons
        self.cancel_button.clicked.connect(self.close)
        self.create_button.clicked.connect(self.create_identifier)

        # Add collapsible advanced configuration section
        self.advanced_config = CollapsibleSection(title="Advanced Configuration", parent=self)
        advanced_config_widget = QWidget()
        advanced_config_layout = QVBoxLayout(advanced_config_widget)
        advanced_config_layout.addSpacing(20)

        # Key type label and radio buttons
        key_type_label = QLabel("Key Type")
        key_type_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        advanced_config_layout.addWidget(key_type_label)

        advanced_config_layout.addSpacing(15)

        self.key_chain_radio = LocksmithRadioButton("Key Chain     ")
        self.random_key_radio = LocksmithRadioButton("Random Key    ")
        # Set one as default
        self.key_chain_radio.setChecked(True)

        # Create button group for key type radios
        self.key_type_button_group = QButtonGroup(self)
        self.key_type_button_group.addButton(self.key_chain_radio)
        self.key_type_button_group.addButton(self.random_key_radio)

        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(10)
        radio_layout.addWidget(self.key_chain_radio)
        radio_layout.addWidget(self.random_key_radio)
        radio_layout.addStretch()
        advanced_config_layout.addLayout(radio_layout)

        # Generate random salt by default
        default_salt = signing.Salter().qb64[2:23]
        self.key_salt_field = FloatingLabelLineEdit("Key Salt", password_mode=True)
        self.key_salt_field.setText(default_salt)
        advanced_config_layout.addWidget(self.key_salt_field)

        # Connect radio buttons to handler
        self.key_chain_radio.toggled.connect(self._on_key_type_radio_changed)
        self.random_key_radio.toggled.connect(self._on_key_type_radio_changed)

        advanced_config_layout.addSpacing(15)

        #Number of keys and threshold label and fields
        keys_and_thresholds_label = QLabel("Number of Keys / Thresholds")
        keys_and_thresholds_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        advanced_config_layout.addWidget(keys_and_thresholds_label)

        advanced_config_layout.addSpacing(15)

        signing_keys_and_thresholds_layout = QHBoxLayout()
        self.num_signing_keys_field = FloatingLabelLineEdit("Signing Keys")
        self.num_signing_keys_field.setText("1")
        self.signing_threshold_field = FloatingLabelLineEdit("Signing Threshold")
        self.signing_threshold_field.setText("1")

        signing_keys_and_thresholds_layout.addWidget(self.num_signing_keys_field)
        signing_keys_and_thresholds_layout.addWidget(self.signing_threshold_field)

        advanced_config_layout.addLayout(signing_keys_and_thresholds_layout)


        rotation_keys_and_thresholds_layout = QHBoxLayout()
        self.num_rotation_keys_field = FloatingLabelLineEdit("Rotation Keys")
        self.num_rotation_keys_field.setText("1")
        self.rotation_threshold_field = FloatingLabelLineEdit("Rotation Threshold")
        self.rotation_threshold_field.setText("1")

        rotation_keys_and_thresholds_layout.addWidget(self.num_rotation_keys_field)
        rotation_keys_and_thresholds_layout.addWidget(self.rotation_threshold_field)
        advanced_config_layout.addLayout(rotation_keys_and_thresholds_layout)

        checkbox_layout = QHBoxLayout()
        self.establishment_only_checkbox = LocksmithCheckbox("Establishment Only")
        self.do_not_delegate_checkbox = LocksmithCheckbox("Do Not Delegate")
        checkbox_layout.addWidget(self.establishment_only_checkbox)
        checkbox_layout.addWidget(self.do_not_delegate_checkbox)
        advanced_config_layout.addLayout(checkbox_layout)

        advanced_config_layout.addSpacing(20)

        delegation_label = QLabel("Delegation")
        delegation_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        advanced_config_layout.addWidget(delegation_label)

        advanced_config_layout.addSpacing(15)

        delegation_radio_layout = QHBoxLayout()
        self.no_delegation_radio = LocksmithRadioButton("None")
        self.local_delegation_radio = LocksmithRadioButton("Local")
        self.remote_delegation_radio = LocksmithRadioButton("Remote")

        # Create button group for delegation radios
        self.delegation_button_group = QButtonGroup(self)
        self.delegation_button_group.addButton(self.no_delegation_radio)
        self.delegation_button_group.addButton(self.local_delegation_radio)
        self.delegation_button_group.addButton(self.remote_delegation_radio)

        self.no_delegation_radio.setChecked(True)

        delegation_radio_layout.addWidget(self.no_delegation_radio)
        delegation_radio_layout.addSpacing(10)
        delegation_radio_layout.addWidget(self.local_delegation_radio)
        delegation_radio_layout.addSpacing(10)
        delegation_radio_layout.addWidget(self.remote_delegation_radio)
        delegation_radio_layout.addStretch()
        advanced_config_layout.addLayout(delegation_radio_layout)
        advanced_config_layout.addSpacing(15)

        self.delegator_dropdown = FloatingLabelComboBox("Delegator")
        self.delegator_dropdown.setFixedWidth(360)
        self.delegator_dropdown.addItem("None")
        advanced_config_layout.addWidget(self.delegator_dropdown)
        self.delegator_dropdown.hide()

        self.delegate_proxy_dropdown = FloatingLabelComboBox("Delegate Proxy")
        self.delegate_proxy_dropdown.setFixedWidth(360)
        self.delegate_proxy_dropdown.addItem("None")
        advanced_config_layout.addWidget(self.delegate_proxy_dropdown)
        self.delegate_proxy_dropdown.hide()

        # Connect delegation radio buttons to handler
        self.no_delegation_radio.toggled.connect(self._on_delegation_radio_changed)
        self.local_delegation_radio.toggled.connect(self._on_delegation_radio_changed)
        self.remote_delegation_radio.toggled.connect(self._on_delegation_radio_changed)

        advanced_config_layout.addSpacing(10)

        toad_layout = QHBoxLayout()
        toad_label = QLabel("Threshold of Acceptable Duplicity:  ")
        toad_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        toad_layout.addWidget(toad_label)
        self.toad_field = LocksmithLineEdit()
        self.toad_field.setText("0")
        self.toad_field.setFixedWidth(50)
        self.toad_field.setAlignment(Qt.AlignmentFlag.AlignCenter)

        toad_layout.addWidget(self.toad_field)
        toad_layout.addStretch()

        advanced_config_layout.addLayout(toad_layout)

        self.advanced_config.set_content_layout(advanced_config_layout)
        layout.addWidget(self.advanced_config)
        layout.addSpacing(10)

        # Link collapsible section to dialog for synchronized resize animations
        self.advanced_config.set_dialog(self)
        layout.addStretch() # Always add stretch after collapsible sections

        # Connect to vault signal bridge if available
        if self.app and hasattr(self.app, 'vault') and self.app.vault and hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            logger.info("CreateIdentifierDialog: Connected to vault signal bridge")

    def create_identifier(self):
        """Create a new identifier using the form values."""
        logger.info("Creating new identifier...")

        # Get alias
        alias = self.name_field.text().strip()
        if not alias:
            logger.error("Alias is required")
            # TODO: Show error message to user
            return

        # Determine key type
        if self.key_chain_radio.isChecked():
            key_type = 'salty'
        elif self.random_key_radio.isChecked():
            key_type = 'randy'
        else:
            key_type = 'salty'

        # Build parameters
        params = {
            'icount': self.num_signing_keys_field.text() or '1',
            'isith': self.signing_threshold_field.text() or '1',
            'ncount': self.num_rotation_keys_field.text() or '1',
            'nsith': self.rotation_threshold_field.text() or '1',
            'toad': self.toad_field.text() or '0',
            'wits': [],  # Will add witness support later
            'estOnly': self.establishment_only_checkbox.isChecked(),
            'DnD': self.do_not_delegate_checkbox.isChecked(),
        }

        # Add salt for key chain type
        if key_type == 'salty':
            params['salt'] = self.key_salt_field.text()

        # Determine delegation type
        if self.no_delegation_radio.isChecked():
            params['delegation_type'] = 'none'
        elif self.local_delegation_radio.isChecked():
            params['delegation_type'] = 'local'
            # Get delegator if selected
            delegator = self.delegator_dropdown.currentText()
            if delegator and delegator != "None":
                params['delpre'] = delegator.split('|')[0].strip() if '|' in delegator else delegator
        elif self.remote_delegation_radio.isChecked():
            params['delegation_type'] = 'remote'
            # Get delegator and proxy if selected
            delegator = self.delegator_dropdown.currentText()
            if delegator and delegator != "None":
                params['delpre'] = delegator.split('|')[0].strip() if '|' in delegator else delegator
            proxy = self.delegate_proxy_dropdown.currentText()
            if proxy and proxy != "None":
                params['proxy_alias'] = proxy.split('|')[0].strip() if '|' in proxy else proxy

        # Call the identifier creation function
        result = habbing.create_identifier(
            app=self.app,
            alias=alias,
            key_type=key_type,
            **params
        )

        # Handle result
        if result['success']:
            logger.info(f"Identifier creation initiated: {result['message']}")
            # Keep dialog open if async operation, it will close when InceptDoer signals completion
            if not result.get('async'):
                self.identifier_created.emit(alias, result.get('pre', ''))
                # Synchronous creation succeeded, close dialog
                self.close()
        else:
            logger.error(f"Identifier creation failed: {result['message']}")
            self.identifier_creation_failed.emit(result['message'])
            # TODO: Show error message to user

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        # Only handle identifier creation doer events
        if doer_name != "InceptDoer":
            return

        logger.info(f"CreateIdentifierDialog received doer_event: {doer_name} - {event_type} - {data}")

        # Handle identifier creation completion
        if event_type == "identifier_created":
            logger.info(f"Identifier created successfully: {data.get('alias')} ({data.get('pre')})")
            self.identifier_created.emit(data.get('alias', ''), data.get('pre', ''))
            self.close()
        elif event_type == "identifier_creation_failed":
            logger.error(f"Identifier creation failed: {data.get('error')}")
            self.identifier_creation_failed.emit(data.get('error', ''))
            self.show_error(f"Identifier creation failed: {data.get('error')}")
            # Keep dialog open so user can try again

    def _on_key_type_radio_changed(self):
        """Handle key type radio button selection changes."""
        if self.key_chain_radio.isChecked():
            self.key_salt_field.show()
            self.num_signing_keys_field.show()
            self.num_rotation_keys_field.show()
        elif self.random_key_radio.isChecked():
            self.key_salt_field.hide()
            self.num_signing_keys_field.show()
            self.num_rotation_keys_field.show()

        # Update collapsible section height to reflect content changes
        self.advanced_config.update_content_height()
