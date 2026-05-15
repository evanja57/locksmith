# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.settings.page module

Settings content page (displayed within VaultPage container).
"""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QButtonGroup
)
from keri import help
from keri.core import coring
from keri import kering

from locksmith.core.configing import ENABLE_TURRET_BROWSER_PLUGIN, LocksmithConfig
from locksmith.ui import colors
from locksmith.ui.styles import get_monospace_font_family
from locksmith.ui.toolkit.widgets.buttons import LocksmithButton, LocksmithIconButton, LocksmithRadioButton, LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit
from locksmith.ui.toolkit.widgets.toggle import ToggleSwitch
from locksmith.ui.vault.settings.delete_dialog import DeleteVaultDialog

logger = help.ogler.getLogger(__name__)

__version__ = "0.0.1"

# AID validation regex (44 character base64url)
AID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{44}$')


class SettingsPage(QWidget):
    """
    Settings content page.

    This is a content-only page that displays within the VaultPage container.
    The VaultPage manages the navigation menu.
    """

    vault_deleted = Signal(str)

    def __init__(self, parent=None):
        """
        Initialize the SettingsPage.

        Args:
            parent: Parent widget (VaultPage container)
        """
        super().__init__(parent)

        self.vault_page = parent
        self.app = parent.app if parent else None
        self.config: LocksmithConfig = self.app.config if self.app else LocksmithConfig.get_instance()
        assert self.config is not None, "SettingsPage requires a valid config"
        self.vault_name = None

        # Create main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Set background
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create scrollable content area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Force light background for the scroll area and its viewport 
        # (overrides system dark mode for consistency with other vault pages)
        scroll_area.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT}; border: none;")
        scroll_area.viewport().setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")

        # Content widget inside scroll area
        content_widget = QWidget()
        content_widget.setObjectName("settingsContentWidget")
        content_widget.setStyleSheet(f"#settingsContentWidget {{ background-color: {colors.BACKGROUND_CONTENT}; }}")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.setSpacing(20)

        # Add the actual settings content
        self._create_general_settings_section(content_layout)
        self._create_danger_zone_section(content_layout)
        
        # Push version to bottom
        content_layout.addStretch()
        self._create_version_section(content_layout)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        logger.info("SettingsPage initialized")

    def _create_general_settings_section(self, parent_layout: QVBoxLayout):
        """Create the General Settings section with form fields."""
        # Section header
        header_label = QLabel("Vault Settings")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(14)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {colors.TEXT_PRIMARY};")
        parent_layout.addWidget(header_label)

        # Subheader explaining these are defaults
        subheader_label = QLabel("Default settings for new vaults and identifiers")
        subheader_label.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 12px; margin-bottom: 10px;")
        parent_layout.addWidget(subheader_label)

        # Container with styled inputs
        settings_container = QFrame()
        settings_container.setObjectName("settingsContainer")
        settings_container.setStyleSheet(f"""
            #settingsContainer {{
                background-color: {colors.WHITE};
                border: 1px solid {colors.BORDER_TABLE};
                border-radius: 24px;
            }}
            /* --- Ensure child widgets inherit container background --- */
            QWidget {{ background-color: transparent; }}
            
            /* --- RADIO BUTTONS --- */
            QRadioButton {{ spacing: 8px; color: {colors.TOGGLE_TRACK_ON}; }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
                border-radius: 8px;
                border: 2px solid {colors.BLUE_ACCENT};
                background-color: transparent;
            }}
            QRadioButton::indicator:checked {{
                background-color: {colors.BLUE_ACCENT};
            }}
            /* --- TEXT INPUTS --- */
            QLineEdit {{
                border: 2px solid {colors.BORDER_TABLE};
                border-radius: 6px;
                padding: 5px;
                color: {colors.TOGGLE_TRACK_ON};
            }}
            QLineEdit:focus {{
                border: 2px solid {colors.BLUE_ACCENT};
            }}
        """)
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(25, 25, 25, 25)
        settings_layout.setSpacing(20)

        # Temporary Datastore toggle
        self._create_temp_datastore_row(settings_layout)

        # Database Directory Base
        self._create_base_dir_row(settings_layout)

        # Cryptographic Key Strength
        self._create_tier_row(settings_layout)

        # Default Key Generation (algo)
        self._create_algo_row(settings_layout)

        # Key Salt (only visible when salty is selected)
        self._create_salt_row(settings_layout)

        parent_layout.addWidget(settings_container)

        if ENABLE_TURRET_BROWSER_PLUGIN:
            self._create_browser_plugin_section(parent_layout)

    def _create_browser_plugin_section(self, parent_layout: QVBoxLayout):
        """Create the Browser Plugin Connection section."""
        # Section header
        header_label = QLabel("Browser Plugin Connection")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(14)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {colors.TEXT_PRIMARY};")
        parent_layout.addWidget(header_label)

        # Subheader
        subheader_label = QLabel("Connect this vault to the Locksmith browser plugin")
        subheader_label.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 12px; margin-bottom: 10px;")
        parent_layout.addWidget(subheader_label)

        # Container
        plugin_container = QFrame()
        plugin_container.setObjectName("pluginContainer")
        plugin_container.setStyleSheet(f"""
            #pluginContainer {{
                background-color: {colors.WHITE};
                border: 1px solid {colors.BORDER_TABLE};
                border-radius: 24px;
            }}
            QWidget {{ background-color: transparent; }}
        """)
        plugin_layout = QVBoxLayout(plugin_container)
        plugin_layout.setContentsMargins(25, 25, 25, 25)
        plugin_layout.setSpacing(20)

        # Locksmith Identifier row
        self._create_locksmith_identifier_row(plugin_layout)

        # Plugin Identifier row
        self._create_plugin_identifier_row(plugin_layout)

        parent_layout.addWidget(plugin_container)

    def _create_locksmith_identifier_row(self, parent_layout: QVBoxLayout):
        """Create the Locksmith Identifier row with generate and copy buttons."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Locksmith Identifier")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        # Read-only field for identifier
        self.locksmith_id_field = FloatingLabelLineEdit("Identifier")
        self.locksmith_id_field.setStyleSheet(f'font-family: "{get_monospace_font_family()}", monospace;')
        self.locksmith_id_field.setReadOnly(True)
        self.locksmith_id_field.setFixedWidth(435)

        row.addWidget(self.locksmith_id_field)

        # Copy button
        copy_content = self.locksmith_id_field.text() if self.locksmith_id_field.text() else ""
        self.locksmith_copy_button = LocksmithCopyButton(
            copy_content=copy_content,
            tooltip="Copy Locksmith Identifier"
        )
        row.addWidget(self.locksmith_copy_button)

        row.addStretch()
        parent_layout.addLayout(row)

    def _create_plugin_identifier_row(self, parent_layout: QVBoxLayout):
        """Create the Plugin Identifier editable row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Plugin Identifier")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        # Editable field for plugin identifier
        self.plugin_id_field = FloatingLabelLineEdit("Plugin Identifier")
        self.plugin_id_field.setFixedWidth(435)

        self.plugin_id_field.line_edit.textChanged.connect(self._on_plugin_id_changed)
        row.addWidget(self.plugin_id_field)

        row.addStretch()
        parent_layout.addLayout(row)

    def _on_plugin_id_changed(self, text: str):
        """Handle plugin identifier field change with validation."""
        if not self.app or not self.app.vault:
            return

        text = text.strip()

        # Validate AID format if not empty
        if text:
            # Basic regex validation
            if not AID_PATTERN.match(text):
                logger.warning(f"Invalid Plugin Identifier format: {text}")
                self.plugin_id_field.line_edit.setStyleSheet(f"""
                    QLineEdit {{
                        border: 2px solid {colors.DANGER};
                        border-radius: 6px;
                        padding: 12px;
                        font-size: 14px;
                        background-color: {colors.BACKGROUND_CONTENT};
                    }}
                """)
                return

            try:
                coring.Prefixer(qb64=text)
            except (kering.InvalidCodeError, ValueError) as e:
                logger.warning(f"Invalid Plugin Identifier (KERI validation): {e}")
                self.plugin_id_field.line_edit.setStyleSheet(f"""
                    QLineEdit {{
                        border: 2px solid {colors.DANGER};
                        border-radius: 6px;
                        padding: 12px;
                        font-size: 14px;
                        background-color: {colors.BACKGROUND_CONTENT};
                    }}
                """)
                return

            # Clear error styling if valid
            self.plugin_id_field.reset_style()

        # Update vault turret settings
        self.app.vault.update_plugin_identifier(text)
        logger.info(f"Plugin identifier updated: {text}")

    def _create_danger_zone_section(self, parent_layout: QVBoxLayout):
        """Create the Danger Zone section with delete vault button."""
        # Section header
        header_label = QLabel("Danger Zone")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(14)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {colors.DANGER};")  # Red color
        parent_layout.addWidget(header_label)

        # Container for danger actions
        danger_container = QFrame()
        danger_container.setObjectName("dangerContainer")
        danger_container.setStyleSheet(f"""
            #dangerContainer {{
                background-color: {colors.BACKGROUND_DANGER};
                border: 1px solid {colors.BACKGROUND_DANGER_BORDER};
                border-radius: 24px;
            }}
            QWidget {{ background-color: transparent; }}
        """)
        danger_layout = QVBoxLayout(danger_container)
        danger_layout.setContentsMargins(25, 25, 25, 25)
        danger_layout.setSpacing(20)

        # Delete Vault button
        self._create_delete_vault_row(danger_layout)

        parent_layout.addWidget(danger_container)

    def _create_temp_datastore_row(self, parent_layout: QVBoxLayout):
        """Create the temporary datastore toggle row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Temporary Datastore")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        self.temp_toggle = ToggleSwitch()
        self.temp_toggle.setChecked(self.config.temp)
        self.temp_toggle.toggled.connect(self._on_temp_changed)
        row.addWidget(self.temp_toggle)

        row.addStretch()
        parent_layout.addLayout(row)

    def _create_base_dir_row(self, parent_layout: QVBoxLayout):
        """Create the database directory base row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Database Directory Base")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        self.base_dir_field = FloatingLabelLineEdit("Directory")
        self.base_dir_field.setText(self.config.base)
        self.base_dir_field.setFixedWidth(300)
        self.base_dir_field.line_edit.textChanged.connect(self._on_base_changed)
        row.addWidget(self.base_dir_field)

        row.addStretch()
        parent_layout.addLayout(row)

    def _create_tier_row(self, parent_layout: QVBoxLayout):
        """Create the cryptographic key strength row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Cryptographic Key Strength")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        # Radio button group
        self.tier_group = QButtonGroup(self)
        tier_layout = QHBoxLayout()
        tier_layout.setSpacing(15)

        self.tier_low = LocksmithRadioButton("Low")
        self.tier_med = LocksmithRadioButton("Medium")
        self.tier_high = LocksmithRadioButton("High")

        self.tier_group.addButton(self.tier_low)
        self.tier_group.addButton(self.tier_med)
        self.tier_group.addButton(self.tier_high)

        # Set current selection
        current_tier = self.config.tier
        if current_tier == "med":
            self.tier_med.setChecked(True)
        elif current_tier == "high":
            self.tier_high.setChecked(True)
        else:
            self.tier_low.setChecked(True)

        tier_layout.addWidget(self.tier_low)
        tier_layout.addWidget(self.tier_med)
        tier_layout.addWidget(self.tier_high)

        self.tier_group.buttonClicked.connect(self._on_tier_changed)

        row.addLayout(tier_layout)
        row.addStretch()
        parent_layout.addLayout(row)

    def _create_algo_row(self, parent_layout: QVBoxLayout):
        """Create the default key generation algorithm row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Default Key Generation")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        # Radio button group
        self.algo_group = QButtonGroup(self)
        algo_layout = QHBoxLayout()
        algo_layout.setSpacing(15)

        self.algo_salty = LocksmithRadioButton("Salty")
        self.algo_randy = LocksmithRadioButton("Randy")

        self.algo_group.addButton(self.algo_salty)
        self.algo_group.addButton(self.algo_randy)

        # Set current selection
        if self.config.algo == "salty":
            self.algo_salty.setChecked(True)
        else:
            self.algo_randy.setChecked(True)

        algo_layout.addWidget(self.algo_salty)
        algo_layout.addWidget(self.algo_randy)

        self.algo_group.buttonClicked.connect(self._on_algo_changed)

        row.addLayout(algo_layout)
        row.addStretch()
        parent_layout.addLayout(row)

    def _create_salt_row(self, parent_layout: QVBoxLayout):
        """Create the key salt row with resalt button."""
        self.salt_row_widget = QWidget()
        self.salt_row_widget.setStyleSheet("background-color: transparent;")
        row = QHBoxLayout(self.salt_row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)

        label = QLabel("Key Salt")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        row.addWidget(label)

        self.salt_field = FloatingLabelLineEdit("Salt", password_mode=True)
        self.salt_field.setText(self.config.salt)
        self.salt_field.setFixedWidth(300)
        self.salt_field.line_edit.textChanged.connect(self._on_salt_changed)
        row.addWidget(self.salt_field)

        # Resalt button
        resalt_button = LocksmithIconButton(
            icon_path=":/assets/material-icons/refresh.svg",
            tooltip="Generate new salt"
        )
        resalt_button.clicked.connect(self._on_resalt)
        row.addWidget(resalt_button)

        row.addStretch()
        parent_layout.addWidget(self.salt_row_widget)

        # Show/hide based on algo selection
        self._update_salt_visibility()

    def _create_delete_vault_row(self, parent_layout: QVBoxLayout):
        """Create the delete vault button row."""
        row = QHBoxLayout()
        row.setSpacing(20)

        label = QLabel("Delete Vault")
        label.setFixedWidth(220)
        label.setStyleSheet(f"font-size: 16px; color: {colors.DANGER}; font-weight: 500;")
        row.addWidget(label)

        # Delete button with red styling
        self.delete_button = LocksmithButton("Permanently Delete")
        self.delete_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.DANGER};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {colors.DANGER_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {colors.DANGER_PRESSED};
            }}
        """)
        self.delete_button.clicked.connect(self._on_delete_vault)
        row.addWidget(self.delete_button)

        row.addStretch()
        parent_layout.addLayout(row)

    def _create_version_section(self, parent_layout: QVBoxLayout):
        """Create the version info section."""
        parent_layout.addSpacing(20)

        version_label = QLabel(f"Version: {__version__}")
        version_label.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SECONDARY};")
        parent_layout.addWidget(version_label)



    def _on_temp_changed(self, checked: bool):
        """Handle temporary datastore toggle."""
        self.config.temp = checked
        logger.info(f"Temporary datastore set to: {self.config.temp}")

    def _on_base_changed(self, text: str):
        """Handle database directory change."""
        self.config.base = text
        logger.info(f"Database base directory set to: {self.config.base}")

    def _on_tier_changed(self):
        """Handle tier selection change."""
        if self.tier_low.isChecked():
            self.config.tier = "low"
        elif self.tier_med.isChecked():
            self.config.tier = "med"
        elif self.tier_high.isChecked():
            self.config.tier = "high"
        logger.info(f"Cryptographic tier set to: {self.config.tier}")

    def _on_algo_changed(self):
        """Handle algorithm selection change."""
        if self.algo_salty.isChecked():
            self.config.algo = "salty"
        else:
            self.config.algo = "randy"
        logger.info(f"Key generation algorithm set to: {self.config.algo}")
        self._update_salt_visibility()

    def _update_salt_visibility(self):
        """Show/hide salt row based on algorithm selection."""
        if hasattr(self, 'salt_row_widget'):
            self.salt_row_widget.setVisible(self.config.algo == "salty")

    def _on_salt_changed(self, text: str):
        """Handle salt field change."""
        self.config.salt = text
        logger.info("Key salt updated")

    def _on_resalt(self):
        """Handle resalt button click."""
        new_salt = self.config.resalt()
        self.salt_field.setText(new_salt)
        logger.info("New salt generated")

    def _on_delete_vault(self):
        """Handle delete vault button click."""
        if not self.vault_name:
            logger.warning("No vault name set, cannot delete")
            return
        
        if not self.app:
            logger.warning("No app instance, cannot delete vault")
            return

        dialog = DeleteVaultDialog(
            vault_name=self.vault_name,
            app=self.app,
            parent=self.vault_page
        )
        dialog.vault_deleted.connect(self._handle_vault_deleted)
        dialog.open()

    def _handle_vault_deleted(self, vault_name: str):
        """Handle successful vault deletion and navigate to home."""
        logger.info(f"Vault '{vault_name}' deleted; navigating to home")

        # Find the main window by traversing up the parent chain
        # Widget hierarchy: SettingsPage -> VaultPage -> QStackedWidget -> central_widget -> LocksmithWindow
        widget = self.vault_page
        nav_manager = None
        while widget is not None:
            # Look for LocksmithWindow (has nav_manager attribute)
            nav_manager = getattr(widget, 'nav_manager', None)
            if nav_manager is not None:
                break
            widget = widget.parent()  # type: ignore[assignment]
        
        if nav_manager is not None:
            # Clear navigation stack and navigate to home
            nav_manager.clear_navigation_stack()
            from locksmith.ui.navigation import Pages
            nav_manager.navigate_to(Pages.HOME)
        else:
            # Fallback: just emit signal for any other handlers
            logger.warning("Could not find main window, emitting vault_deleted signal")
            self.vault_deleted.emit(vault_name)

    def set_vault_name(self, vault_name: str):
        """
        Set the vault name for this page.

        Args:
            vault_name: Name of the open vault
        """
        self.vault_name = vault_name
        logger.info(f"SettingsPage: Set vault name to {vault_name}")

        # Load existing browser plugin settings if available
        if ENABLE_TURRET_BROWSER_PLUGIN and self.app and self.app.vault and self.app.vault.pluginSettings:
            self.locksmith_id_field.setText(self.app.vault.pluginSettings.locksmith_identifier)
            self.locksmith_copy_button.set_copy_content(self.app.vault.pluginSettings.locksmith_identifier)
            plugin_id = self.app.vault.pluginSettings.plugin_identifier
            if plugin_id:
                self.plugin_id_field.setText(plugin_id)
            else:
                self.plugin_id_field.setText("")
