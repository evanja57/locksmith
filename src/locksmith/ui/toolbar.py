# -*- encoding: utf-8 -*-
"""
locksmith.ui.toolbar module

This module contains the toolbar component for the Locksmith application.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QToolBar, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QPushButton
from hio.base import doing
from keri import help

from locksmith.core.configing import LocksmithConfig
from locksmith.ui import colors
from locksmith.ui.toolkit.utils import create_spacer, load_scaled_pixmap
from locksmith.ui.toolkit.widgets import HoverIconButton, LocksmithDialog, LocksmithButton

logger = help.ogler.getLogger(__name__)


class LocksmithToolbar(QToolBar):
    """
    Custom toolbar for Locksmith application.
    Handles dynamic button states based on app state/page.
    """

    # Signals for toolbar actions
    settings_clicked = Signal()
    vaults_clicked = Signal()
    lock_clicked = Signal()
    home_clicked = Signal()
    notifications_clicked = Signal()

    def __init__(self, app, parent=None):
        """
        Initialize the Locksmith toolbar.

        Parameters:
            app: Application instance.
            parent: Parent widget (typically the main window).
        """
        super().__init__("Main Toolbar", parent)

        self.app = app
        self.setMovable(False)
        self.setFloatable(False)
        self.notifications_button_doer = None
        self._apply_styles()

        # Build toolbar for homepage (default)
        self._build_homepage_toolbar()

    def _apply_styles(self):
        """Apply stylesheet to toolbar."""
        self.setStyleSheet(f"""
            QToolBar {{
                background-color: {colors.TOOLBAR_DARK};
                border-bottom: 1px solid {colors.BORDER_NEUTRAL};
                padding: 4px;
                spacing: 4px;
            }}
            QToolButton {{
                background-color: transparent;
                padding: 4px 2px;
                margin: 2px;
                border-radius: 4px;
                border: none;
            }}
            QToolButton:hover {{
                background-color: {colors.BACKGROUND_NEUTRAL};
            }}
            QToolButton:pressed {{
                background-color: {colors.BACKGROUND_NEUTRAL_HOVER};
            }}
        """)

    def _build_homepage_toolbar(self):
        """Build toolbar layout for homepage."""
        self.addWidget(create_spacer(8))

        # Add clickable favicon icon (navigates to home)
        favicon_button = QPushButton()
        favicon_button.setFixedSize(36, 36)
        favicon_pixmap = load_scaled_pixmap(":/assets/custom/SymbolLogo.svg", 28, 28)
        favicon_button.setIcon(QIcon(favicon_pixmap))
        favicon_button.setIconSize(QSize(28, 28))
        favicon_button.setToolTip("Go to Home")
        favicon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        favicon_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        favicon_button.clicked.connect(self.home_clicked.emit)
        self.addWidget(favicon_button)

        self.addWidget(create_spacer(6))
        text_label = QLabel("Locksmith")
        text_label.setStyleSheet(f"color: {colors.WHITE};")
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)

        text_label.setFont(font)
        self.addWidget(text_label)

        # Add spacer to push next items to the right
        self.addWidget(create_spacer(expanding=True))

        # Notifications button (with dropdown) - initially hidden
        self.notifications_button = NotificationsButton(self.app, self)
        self.notifications_button.clicked.connect(self.notifications_clicked.emit)
        self.notifications_action = self.addWidget(self.notifications_button)
        self.notifications_action.setVisible(False)  # Hidden by default

        # Settings button with hover effect
        self.settings_button = HoverIconButton(
            icon_normal="assets/material-icons/settings.svg",
            icon_hover="assets/material-icons/settings-hover.svg",
            tooltip="Settings"
        )
        self.settings_button.clicked.connect(self.show_settings_dialog)
        self.settings_button.clicked.connect(self.settings_clicked.emit)
        self.settings_action = self.addWidget(self.settings_button)

        # Vaults button with hover effect
        self.vaults_button = HoverIconButton(
            icon_normal="assets/material-icons/vault-drawer.svg",
            icon_hover="assets/material-icons/vault-drawer-hover.svg",
            tooltip="Vaults"
        )
        self.vaults_button.clicked.connect(self.vaults_clicked.emit)
        self.vaults_action = self.addWidget(self.vaults_button)

        # Lock button (close vault) - initially hidden
        self.lock_button = HoverIconButton(
            icon_normal="assets/material-icons/lock.svg",
            icon_hover="assets/material-icons/lock-hover.svg",
            tooltip="Close Vault"
        )
        self.lock_button.clicked.connect(self.lock_clicked.emit)
        self.lock_action = self.addWidget(self.lock_button)
        self.lock_action.setVisible(False)  # Hidden by default

        self.addWidget(create_spacer(6))

    def set_vaults_active(self, active: bool):
        """
        Set the active state of the vaults button.

        Args:
            active: True to show as active, False for normal state.
        """
        if hasattr(self, 'vaults_button'):
            self.vaults_button.set_active(active)

    def update_for_config(self, config: dict):
        """
        Update toolbar buttons based on configuration from current page.

        Args:
            config (dict): Dictionary with button visibility settings:
                - show_vaults_button (bool)
                - show_lock_button (bool)
                - show_notifications_button (bool)
                - show_settings_button (bool)
        """
        # Update vaults button visibility
        if hasattr(self, 'vaults_action'):
            self.vaults_action.setVisible(config.get('show_vaults_button', True))

        # Update lock button visibility
        if hasattr(self, 'lock_action'):
            self.lock_action.setVisible(config.get('show_lock_button', False))

        # Update notifications button visibility
        if hasattr(self, 'notifications_action'):
            if config.get('show_notifications_button', False):
                self.notifications_button.activate()
                self.notifications_action.setVisible(True)
                self.notifications_button_doer = NotificationButtonDoer(self.notifications_button)
                if self.notifications_button_doer not in self.app.vault.doers:
                    self.app.vault.extend([self.notifications_button_doer])
            else:
                self.notifications_button.deactivate()
                self.notifications_action.setVisible(False)

        # Update settings button visibility
        if hasattr(self, 'settings_action'):
            self.settings_action.setVisible(config.get('show_settings_button', True))


    def show_settings_dialog(self):
        """Show the Configuration settings dialog."""
        # Get configuration instance
        config = LocksmithConfig.get_instance()

        # Create content widget with configuration information
        content_widget = self._create_settings_content(config)

        # Create button layout with OK button
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        ok_button = LocksmithButton("Ok")

        button_layout.addWidget(ok_button)

        title_content = QLabel("Configuration")
        title_content.setStyleSheet(f"font-size: 24px; color: {colors.TEXT_DARK};")

        # Create dialog
        dialog = LocksmithDialog(
            parent=self.parent(),
            title="Configuration",
            title_content=title_content,
            show_close_button=True,
            show_title_divider=False,
            content=content_widget,
            buttons=button_layout
        )

        # Connect OK button to close dialog
        ok_button.clicked.connect(dialog.accept)

        # Set fixed size for dialog
        dialog.setFixedSize(720, 650)

        # Show dialog
        dialog.open()

    def _create_settings_content(self, config: LocksmithConfig):
        """
        Create the content widget displaying configuration information.

        Args:
            config: LocksmithConfig instance with configuration data.

        Returns:
            QWidget containing formatted configuration data.
        """
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Add subtitle
        subtitle = QLabel("Provider Connection Information:")
        subtitle.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_PRIMARY};")
        layout.addWidget(subtitle)

        # Add spacing
        layout.addSpacing(20)

        # Add configuration fields
        self._add_config_field(layout, "ROOT AID", config.root_aid)
        self._add_config_field(layout, "ROOT OOBI", config.root_oobi)
        layout.addSpacing(15)
        self._add_config_field(layout, "API AID", config.api_aid)
        self._add_config_field(layout, "API OOBI", config.api_oobi)
        layout.addSpacing(15)
        self._add_config_field(layout, "Registration URL", config.unprotected_url)
        self._add_config_field(layout, "API URL", config.protected_url, False)

        # Add stretch to push content to top
        layout.addStretch()

        return content

    def _add_config_field(self, layout: QVBoxLayout, label: str, value: str, spacing_after: bool = True):
        """
        Add a labeled configuration field to the layout.

        Args:
            layout: Layout to add the field to.
            label: Label text for the field.
            value: Value to display.
        """
        # Create label
        label_widget = QLabel(label)
        label_font = QFont()
        label_font.setBold(True)
        label_widget.setFont(label_font)
        label_widget.setStyleSheet(f"font-size: 16px; color: {colors.TEXT_PRIMARY};")
        layout.addWidget(label_widget)
        layout.addSpacing(3)

        # Create value label
        value_widget = QLabel(value)
        value_widget.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_SECONDARY}; padding-left: 0px;")
        value_widget.setWordWrap(True)
        value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value_widget)

        # Add spacing after each field
        if spacing_after:
            layout.addSpacing(15)



class NotificationsButton(HoverIconButton):
    """Notifications icon button with mailbox dropdown menu."""

    def __init__(self, app, parent=None):
        """
        Initialize the NotificationsButton.

        Parameters:
            app: Application instance
            parent: Parent widget
        """
        self.app = app

        # Icon setup
        self.icon_empty_normal = ":/assets/material-icons/notifications.svg"
        self.icon_empty_hover = ":/assets/material-icons/notifications_hover.svg"
        self.icon_unread_normal = ":/assets/material-icons/notifications_blue_dot.svg"
        self.icon_unread_hover = ":/assets/material-icons/notifications_blue.svg"

        super().__init__(self.icon_empty_normal, self.icon_empty_hover, "Notifications")

    def activate(self):

        if self.app.vault:
            self.app.vault.signals.doer_event.connect(self._on_doer_event)

            message_count = 0
            for _, note in self.app.vault.notifier.noter.notes.getTopItemIter():
                if not note.read:
                    message_count += 1

            if message_count > 0:
                self.setIcon(QIcon(self.icon_unread_normal))
                self.icon_normal = self.icon_unread_normal
                self.icon_hover = self.icon_unread_hover
            else:
                self.setIcon(QIcon(self.icon_empty_normal))
                self.icon_normal = self.icon_empty_normal
                self.icon_hover = self.icon_empty_hover

    def deactivate(self):
        # self.app.vault.signals.doer_event.disconnect(self._on_doer_event)
        pass

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        # Handle key state update completion
        if doer_name == "MailboxListener":
            self.activate()

class NotificationButtonDoer(doing.Doer):
    """Doer for changing icon based on presence of unread mailbox notifications"""

    def __init__(self, button: NotificationsButton, signal_bridge=None, **kwa):
        """
        Initialize the NotificationButtonDoer.

        Args:
            signal_bridge: Optional DoerSignalBridge instance for emitting Qt signals
            button: NotificationsButton instance to monitor
        """
        super().__init__(tock=5.0, **kwa)  # Run every 5 second
        self.button = button
        self.signal_bridge = signal_bridge

    def enter(self, **kwa):
        """Called when doer starts."""
        logger.info(f"Entering NotificationButtonDoer")

    def recur(self, tyme):
        """Called every tock (5 second)."""
        self.button.activate()
        return False

    def exit(self):
        """Called when doer exits."""
        logger.info(f"Exiting NotificationButtonDoer")