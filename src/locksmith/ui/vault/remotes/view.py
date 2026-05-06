# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.remotes.view module

Dialog for viewing remote identifier details
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame
)
from keri import help
from keri.app import organizing
from keri.help import helping
from keri.kering import Roles
from keri.peer import exchanging

from locksmith.core import remoting
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithIconButton, LocksmithCopyButton
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.dialogs import LocksmithDialog
from locksmith.ui.toolkit.widgets.fields import (
    LocksmithLineEdit,
    LocksmithPlainTextEdit,
    FloatingLabelComboBox
)

logger = help.ogler.getLogger(__name__)


class ViewRemoteIdentifierDialog(LocksmithDialog):
    """Dialog for viewing remote identifier details."""
    def __init__(self, icon_path, app, remote_identifier_prefix, parent=None):
        """
        Initialize the ViewRemoteIdentifierDialog.

        Args:
            icon_path: Path to the remote identifier icon
            app: Application instance
            remote_identifier_prefix: Alias or AID of the remote identifier to view
            parent: Parent widget (typically VaultPage)
        """
        self.app = app
        self.org = organizing.Organizer(hby=self.app.vault.hby)

        self.remote_identifier_prefix = remote_identifier_prefix

        # Get the remote identifier details from the app
        self.remote_id = remoting.get_remote_id_details(self.app, self.remote_identifier_prefix)

        # Create title content FIRST (before super().__init__)
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(icon_path)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel(f"  {self.remote_id.get('alias', 'Unknown Alias')}")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_content.addWidget(title_label)
        title_content_widget.setLayout(title_content)

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(15)

        # Create button row
        button_row = QHBoxLayout()
        self.close_button = LocksmithInvertedButton("Close")
        button_row.addWidget(self.close_button)

        # Initialize parent dialog EARLY, before building sections that use self as parent
        super().__init__(
            parent=parent,
            title_content=title_content_widget,
            show_close_button=True,
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        # Set initial size
        self.setFixedSize(600, 940)

        # NOW build sections (after super().__init__ has been called)
        # AID Section
        self._build_aid_section(layout)

        # Refresh Key State Section
        self._build_refresh_keystate_section(layout)

        # Keystate Information Section
        self._build_keystate_info_section(layout)

        # Key Event Log Section
        self._build_kel_section(layout)

        # Key Event Log Section

        layout.addSpacing(10)

        # OOBI Section (collapsible)
        self._build_oobi_section(layout)

        # Mailboxes Section (collapsible)
        self._build_mailbox_section(layout)

        # Verification Section (Collapsible)
        self._build_verification_section(layout)

        # Roles Section (Collapsible)
        self._build_roles_section(layout)

        layout.addStretch()

        # Connect buttons
        self.close_button.clicked.connect(self.close)

    def _get_remote_identifier_details(self):
        """
        Get remote identifier details from the app.

        Returns:
            dict: Remote identifier details
        """
        # TODO: Implement actual lookup of remote identifier from app
        details = self.app.vault.org.get(self.remote_identifier_prefix)
        logger.info(f"Retrieved remote identifier details for {self.remote_identifier_prefix} \n\n {details}")
        # This is a placeholder structure based on the flet implementation
        return {
            'id': self.remote_identifier_prefix,
            'alias': details.get('alias', 'Alias Unknown'),
            'oobi': details.get('oobi', 'OOBI Unknown'),
            'sequence_number': 0,
            'keystate_updated_at': 'N/A',
            'roles': [],
            'existing_roles': []  # List of (cid, role, eid) tuples
        }

    def _build_aid_section(self, layout):
        """Build the AID section with copy button."""
        aid_label_row = QHBoxLayout()
        aid_label_row.setSpacing(5)
        aid_label = QLabel("AID")
        aid_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        aid_label_row.addWidget(aid_label)

        self.copy_aid_button = LocksmithCopyButton(copy_content=self.remote_id['id'])
        self.copy_aid_button.setFixedHeight(36)
        aid_label_row.addWidget(self.copy_aid_button)
        aid_label_row.addStretch()
        layout.addLayout(aid_label_row)

        self.aid_field = LocksmithLineEdit("AID")
        self.aid_field.setText(self.remote_id['id'])
        self.aid_field.setReadOnly(True)
        self.aid_field.setCursorPosition(0)
        self.aid_field.setMinimumWidth(360)
        layout.addWidget(self.aid_field)

    def _build_kel_section(self, layout):
        """Build the Key Event Log section with copy button."""
        kel_label_row = QHBoxLayout()
        kel_label_row.setSpacing(5)
        kel_label = QLabel("Key Event Log")
        kel_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        kel_label_row.addWidget(kel_label)

        # Copy button
        copy_kel_button = LocksmithIconButton(":/assets/material-icons/content_copy.svg", tooltip="Copy KEL")
        copy_kel_button.setFixedHeight(36)
        copy_kel_button.clicked.connect(lambda: self._copy_to_clipboard(self.remote_id.get('kel', '')))
        kel_label_row.addWidget(copy_kel_button)
        kel_label_row.addStretch()
        layout.addLayout(kel_label_row)

        # KEL value (multiline, read-only)
        self.kel_field = LocksmithPlainTextEdit()
        self.kel_field.setPlainText(self.remote_id.get('pretty_kel', ''))
        self.kel_field.setReadOnly(True)
        self.kel_field.setFixedHeight(250)
        self.kel_field.setProperty("class", "monospace")
        self.kel_field._update_styling()  # Force style refresh
        layout.addWidget(self.kel_field)

    def _build_oobi_section(self, layout):
        """Build the OOBI collapsible section."""
        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
        layout.addWidget(divider)

        # Create collapsible section
        self.oobi_section = CollapsibleSection(title="OOBI", parent=self)
        oobi_content_widget = QWidget()
        oobi_layout = QVBoxLayout(oobi_content_widget)
        oobi_layout.setContentsMargins(20, 10, 20, 10)
        oobi_layout.setSpacing(15)

        # OOBI label and copy button
        oobi_label_row = QHBoxLayout()
        oobi_label_row.setSpacing(5)
        oobi_label = QLabel("OOBI")
        oobi_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        oobi_label_row.addWidget(oobi_label)

        self.copy_oobi_button = LocksmithCopyButton(copy_content=self.remote_id.get('oobi', ''))
        self.copy_oobi_button.setFixedHeight(36)
        oobi_label_row.addWidget(self.copy_oobi_button)
        oobi_label_row.addStretch()
        oobi_layout.addLayout(oobi_label_row)

        # OOBI text field
        self.oobi_field = LocksmithPlainTextEdit()
        self.oobi_field.setPlainText(self.remote_id.get('oobi', ''))
        self.oobi_field.setReadOnly(True)
        self.oobi_field.setFixedHeight(80)
        self.oobi_field.setMaximumWidth(480)
        oobi_layout.addWidget(self.oobi_field)

        self.oobi_section.set_content_layout(oobi_layout)
        layout.addWidget(self.oobi_section)

        # Register collapsible section with dialog for centralized management
        self.register_collapsible_section(self.oobi_section)

    def _build_refresh_keystate_section(self, layout):
        """Build the refresh key state section."""
        refresh_row = QHBoxLayout()
        refresh_label = QLabel("Refresh Key State")
        refresh_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        refresh_row.addWidget(refresh_label)

        self.refresh_keystate_button = LocksmithIconButton(
            icon_path=":/assets/material-icons/refresh.svg",
            tooltip="Refresh key state",
            icon_size=24
        )
        self.refresh_keystate_button.setFixedHeight(36)
        self.refresh_keystate_button.clicked.connect(self._on_refresh_keystate)
        refresh_row.addWidget(self.refresh_keystate_button)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

    def _build_keystate_info_section(self, layout):
        """Build the keystate information section."""
        # Container frame
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {colors.BORDER};
                border-radius: 8px;
                background-color: {colors.BACKGROUND_CONTENT};
            }}
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(10)

        # Title
        info_title = QLabel("Keystate Information")
        info_title.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        info_layout.addWidget(info_title)

        # Keystate Updated At
        updated_row = QHBoxLayout()
        updated_row.addSpacing(20)
        updated_label = QLabel("Keystate Updated At:")
        updated_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        updated_row.addWidget(updated_label)

        self.keystate_updated_value = QLabel(str(self.remote_id.get('keystate_updated_at', 'N/A')))
        self.keystate_updated_value.setStyleSheet("font-size: 13px; border: none;")
        updated_row.addWidget(self.keystate_updated_value)
        updated_row.addStretch()
        info_layout.addLayout(updated_row)

        # Sequence Number
        sn_row = QHBoxLayout()
        sn_row.addSpacing(20)
        sn_label = QLabel("Sequence Number:")
        sn_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        sn_row.addWidget(sn_label)

        self.sequence_number_value = QLabel(str(self.remote_id.get('sequence_number', 0)))
        self.sequence_number_value.setStyleSheet("font-size: 13px; border: none;")
        sn_row.addWidget(self.sequence_number_value)
        sn_row.addStretch()
        info_layout.addLayout(sn_row)

        # Role (if witness)
        if 'Witness' in self.remote_id.get('roles', []):
            role_row = QHBoxLayout()
            role_label = QLabel("Role:")
            role_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
            role_row.addWidget(role_label)

            role_value = QLabel("Witness")
            role_value.setStyleSheet("font-size: 13px; border: none;")
            role_row.addWidget(role_value)
            role_row.addStretch()
            info_layout.addLayout(role_row)

        layout.addWidget(info_frame)

    def _build_verification_section(self, layout):
        """Build the verification collapsible section."""
        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
        layout.addWidget(divider)

        # Create collapsible section
        self.verification_section = CollapsibleSection(title="Verifications", parent=self)
        verification_content_widget = QWidget()
        verification_layout = QVBoxLayout(verification_content_widget)
        verification_layout.setContentsMargins(20, 10, 20, 10)
        verification_layout.setSpacing(15)

        if self.app.vault.hby.db.reps.cnt(keys=(self.remote_identifier_prefix,)) == 0:
            label = QLabel(f"<b>No challenge responses recieved from this identifier</b><br/>")
            label.setFixedWidth(500)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
            verification_layout.addWidget(label)

        for (_,), saider in self.app.vault.hby.db.reps.getItemIter(keys=(self.remote_identifier_prefix,)):
            exn, _ = exchanging.cloneMessage(self.app.vault.hby, saider.qb64)
            if not exn:
                continue

            attrib = exn.ked.get('a', {})
            date = helping.fromIso8601(exn.ked['dt'])
            words = attrib.get('words', [])

            label = QLabel(f"<b>Challenge signed on {date.strftime('%Y-%m-%d %H:%M:%S')}:</b> <p>{' '.join(words)}</p> <br/>")
            label.setFixedWidth(500)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
            verification_layout.addWidget(label)

        # Associated Identifier dropdown
        self.verification_section.set_content_layout(verification_layout)
        layout.addWidget(self.verification_section)

        # Register collapsible section with dialog for centralized management
        self.register_collapsible_section(self.verification_section)

    def _build_mailbox_section(self, layout):
        """Build the verification collapsible section."""
        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
        layout.addWidget(divider)

        # Create collapsible section
        self.mailbox_section = CollapsibleSection(title="Mailboxes", parent=self)
        mailbox_content_widget = QWidget()
        mailbox_layout = QVBoxLayout(mailbox_content_widget)
        mailbox_layout.setContentsMargins(20, 10, 20, 10)
        mailbox_layout.setSpacing(15)

        if len(self.remote_id.get('mailboxes', [])) == 0:
            label = QLabel(f"<b>No mailboxes for this identifier</b><br/>")
            label.setFixedWidth(500)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
            mailbox_layout.addWidget(label)

        for eid in self.remote_id.get('mailboxes', []):
            label = QLabel(f"<b>Mailbox: {eid}</b><br/>")
            label.setFixedWidth(500)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
            mailbox_layout.addWidget(label)

        # Associated Identifier dropdown
        self.mailbox_section.set_content_layout(mailbox_layout)
        layout.addWidget(self.mailbox_section)

        # Register collapsible section with dialog for centralized management
        self.register_collapsible_section(self.mailbox_section)


    def _build_roles_section(self, layout):
        """Build the roles collapsible section."""
        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
        layout.addWidget(divider)

        # Create collapsible section
        self.roles_section = CollapsibleSection(title="Roles", parent=self)
        roles_content_widget = QWidget()
        roles_layout = QVBoxLayout(roles_content_widget)
        roles_layout.setContentsMargins(20, 10, 20, 10)
        roles_layout.setSpacing(15)

        # Roles List (existing roles)
        self.roles_list_container = QWidget()
        self.roles_list_layout = QVBoxLayout(self.roles_list_container)
        self.roles_list_layout.setContentsMargins(0, 0, 0, 0)
        self.roles_list_layout.setSpacing(5)
        self._populate_roles_list()
        roles_layout.addWidget(self.roles_list_container)

        # Divider before new role section
        if len(self.remote_id.get('existing_roles', [])) > 0:
            roles_divider = QFrame()
            roles_divider.setFrameShape(QFrame.Shape.HLine)
            roles_divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
            roles_layout.addWidget(roles_divider)

        # Associated AID dropdown
        self.role_associated_aid_dropdown = FloatingLabelComboBox("Associated AID")
        self._populate_identifier_dropdown(self.role_associated_aid_dropdown)
        roles_layout.addWidget(self.role_associated_aid_dropdown)

        # Role selection and Set Role button
        role_button_row = QHBoxLayout()
        self.role_dropdown = FloatingLabelComboBox("Role")
        self.role_dropdown.addItems(["Gateway", "Watcher", "Mailbox", "Witness", "Controller"])
        role_button_row.addWidget(self.role_dropdown)

        self.set_role_button = LocksmithButton("Set Role")
        self.set_role_button.clicked.connect(self._on_set_role)
        role_button_row.addWidget(self.set_role_button)
        roles_layout.addLayout(role_button_row)

        self.roles_section.set_content_layout(roles_layout)
        layout.addWidget(self.roles_section)

        # Register collapsible section with dialog for centralized management
        self.register_collapsible_section(self.roles_section)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.DIVIDER};")
        layout.addWidget(divider)

    def _populate_roles_list(self):
        """Populate the roles list with existing roles."""
        # Clear existing items
        while self.roles_list_layout.count():
            child = self.roles_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add existing roles
        existing_roles = self.remote_id.get('existing_roles', [])
        for cid, role, eid in existing_roles:
            role_item = self._create_role_item(cid, role, eid)
            self.roles_list_layout.addWidget(role_item)

        # Add "No roles" message if list is empty
        if len(existing_roles) == 0:
            no_roles_label = QLabel("No roles assigned")
            no_roles_label.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-style: italic; font-size: 13px;")
            self.roles_list_layout.addWidget(no_roles_label)

    def _create_role_item(self, cid, role, eid):
        """
        Create a role list item widget.

        Args:
            cid: Controller ID
            role: Role name
            eid: Endpoint ID

        Returns:
            QWidget: Role item widget
        """
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(8)

        # Role info content widget (matches _create_item_widget from ExtensibleSelectorWidget)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 4, 8, 4)
        content_layout.setSpacing(2)

        role_label = QLabel(str(role).title())
        role_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {colors.TEXT_DARK};")
        content_layout.addWidget(role_label)

        cid_label = QLabel(cid)
        cid_label.setStyleSheet(f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: 'Menlo', 'SF Mono', monospace;")
        content_layout.addWidget(cid_label)

        item_layout.addWidget(content_widget, stretch=1)

        # Delete button
        delete_button = LocksmithIconButton(
            icon_path=":/assets/material-icons/close.svg",
            tooltip="Remove role",
            icon_size=20
        )
        delete_button.setProperty('role_data', (cid, role, eid))
        delete_button.clicked.connect(self._on_delete_role)
        item_layout.addWidget(delete_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        return item_widget

    def _populate_identifier_dropdown(self, dropdown):
        """
        Populate a dropdown with all available identifiers from hby.habs.

        Args:
            dropdown: FloatingLabelComboBox instance to populate
        """
        dropdown.clear()
        dropdown.addItem("Select an identifier...")

        # Get all identifiers from habery
        hby = self.app.vault.hby
        for hab_pre, hab in hby.habs.items():
            # Format: "Name (prefix)"
            item_text = f"{hab.name} ({hab_pre[:15]}...)"
            dropdown.addItem(item_text, userData=hab_pre)

    @staticmethod
    def _copy_to_clipboard(text):
        """Copy text to clipboard."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        logger.info(f"Copied to clipboard: {text[:50]}...")

    # Action handlers
    def _on_refresh_keystate(self):
        """Handle refresh key state button click."""
        logger.info(f"Refresh key state clicked for {self.remote_identifier_prefix}")

        # Disable button during refresh
        self.refresh_keystate_button.setEnabled(False)

        try:
            # Call business logic to refresh keystate
            doer = remoting.refresh_keystate(
                app=self.app,
                remote_id_pre=self.remote_identifier_prefix,
                oobi=self.remote_id.get('oobi')
            )

            if doer:
                # Connect to signal for completion
                if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                    self.app.vault.signals.doer_event.connect(self._on_keystate_refreshed)
                logger.info("Keystate refresh initiated")
            else:
                self.show_error("No OOBI available for this remote identifier")
                self.refresh_keystate_button.setEnabled(True)

        except Exception as e:
            logger.exception(f"Error refreshing keystate: {e}")
            self.show_error(f"Error refreshing keystate: {str(e)}")
            self.refresh_keystate_button.setEnabled(True)

    def _on_keystate_refreshed(self, doer_name, event_type, data):
        """Handle keystate refresh completion signal."""
        if doer_name != "ResolveOobiDoer":
            return

        # Re-enable button
        self.refresh_keystate_button.setEnabled(True)

        if event_type == "oobi_resolved" and data.get('success'):
            # Refresh the details
            self.remote_id = remoting.get_remote_id_details(self.app, self.remote_identifier_prefix)

            # Update UI with new keystate info
            self.sequence_number_value.setText(str(self.remote_id.get('sequence_number', 0)))
            self.keystate_updated_value.setText(str(self.remote_id.get('keystate_updated_at', 'N/A')))

            logger.info("Keystate refreshed successfully")
            self.show_success("Keystate refreshed successfully")

            # Disconnect signal
            if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                try:
                    self.app.vault.signals.doer_event.disconnect(self._on_keystate_refreshed)
                except:
                    pass

        elif event_type in ["oobi_resolution_timeout", "oobi_resolution_failed"]:
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Keystate refresh failed: {error_msg}")
            self.show_error(f"Keystate refresh failed: {error_msg}")

            # Disconnect signal
            if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                try:
                    self.app.vault.signals.doer_event.disconnect(self._on_keystate_refreshed)
                except:
                    pass

    def _on_set_role(self):
        """Handle set role button click."""
        logger.info("Set role clicked")

        # Get selected role
        role = self.role_dropdown.currentText()
        if not role or role == "Role":
            self.show_error("Please select a role")
            return

        # Map role name to Roles enum
        role_mapping = {
            "Gateway": Roles.gateway,
            "Watcher": Roles.watcher,
            "Mailbox": Roles.mailbox,
            "Witness": Roles.witness,
            "Controller": Roles.controller
        }

        if role not in role_mapping:
            self.show_error(f"Invalid role: {role}")
            return

        role_value = role_mapping[role]

        # Get selected identifier
        selected_index = self.role_associated_aid_dropdown.currentIndex()
        if selected_index <= 0:  # 0 is "Select an identifier..."
            self.show_error("Please select an associated identifier")
            return

        hab_pre = self.role_associated_aid_dropdown.itemData(selected_index)
        if not hab_pre:
            self.show_error("Invalid identifier selected")
            return

        # Disable button during operation
        self.set_role_button.setEnabled(False)

        try:
            # Create doer for setting role
            doer = remoting.SetRoleDoer(
                app=self.app,
                hab_pre=hab_pre,
                remote_id_pre=self.remote_identifier_prefix,
                role=role_value,
                signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
            )

            # Add doer to vault
            self.app.vault.extend([doer])

            # Connect to completion signal
            if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                self.app.vault.signals.doer_event.connect(self._on_role_set)

            logger.info(f"Setting role {role} with associated AID {hab_pre}")

        except Exception as e:
            logger.exception(f"Error setting role: {e}")
            self.show_error(f"Error setting role: {str(e)}")
            self.set_role_button.setEnabled(True)

    def _on_role_set(self, doer_name, event_type, data):
        """Handle role setting completion signal."""
        if doer_name != "SetRoleDoer":
            return

        # Re-enable button
        self.set_role_button.setEnabled(True)

        if event_type in ["role_set", "role_already_set"] and data.get('success'):
            # Refresh the remote ID details to get updated roles
            self.remote_id = remoting.get_remote_id_details(self.app, self.remote_identifier_prefix)

            # Refresh roles list
            self._populate_roles_list()

            role_status = "already set" if event_type == "role_already_set" else "set successfully"
            logger.info(f"Role {role_status}")
            self.show_success(f"Role {role_status}")

            # Disconnect signal
            if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                try:
                    self.app.vault.signals.doer_event.disconnect(self._on_role_set)
                except:
                    pass

        elif event_type == "set_role_failed":
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Role setting failed: {error_msg}")
            self.show_error(f"Role setting failed: {error_msg}")

            # Disconnect signal
            if hasattr(self.app.vault, 'signals') and self.app.vault.signals:
                try:
                    self.app.vault.signals.doer_event.disconnect(self._on_role_set)
                except:
                    pass

    def _on_delete_role(self):
        """Handle delete role button click."""
        button = self.sender()
        if not button:
            return

        role_data = button.property('role_data')
        if not role_data:
            return

        cid, role, eid = role_data
        logger.info(f"Delete role clicked for {role_data}")

        try:
            # Call business logic to delete role
            result = remoting.delete_role(
                app=self.app,
                cid=cid,
                role=role,
                eid=eid
            )

            if result.get('success'):
                # Refresh the remote ID details
                self.remote_id = remoting.get_remote_id_details(self.app, self.remote_identifier_prefix)

                # Refresh roles list
                self._populate_roles_list()

                logger.info(f"Role '{role}' deleted successfully")
                self.show_success(f"Role '{role}' deleted successfully")
            else:
                error_msg = result.get('message', 'Unknown error')
                logger.error(f"Role deletion failed: {error_msg}")
                self.show_error(f"Role deletion failed: {error_msg}")

        except Exception as e:
            logger.exception(f"Error deleting role: {e}")
            self.show_error(f"Error deleting role: {str(e)}")