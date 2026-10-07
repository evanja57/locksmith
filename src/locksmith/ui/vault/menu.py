# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.nav_menu module

Navigation menu for vault operations (left sidebar when vault is open).
"""
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, Qt, QPropertyAnimation, QEasingCurve, SignalInstance
from PySide6.QtGui import QIcon, QEnterEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel, QFrame
from keri import help

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import BackButton

if TYPE_CHECKING:
    pass

logger = help.ogler.getLogger(__name__)


class MenuButton(QPushButton):
    """
    A menu button that can display an icon with an optional label.
    """

    def __init__(self, icon: QIcon, label: str = "", parent=None, is_lock_button: bool = False):
        """
        Initialize a menu button.

        Args:
            icon: The icon to display
            label: Optional text label to display next to icon
            parent: Parent widget
            is_lock_button: Whether this is the lock button (has special styling)
        """
        super().__init__(parent)
        self.icon_obj = icon
        self.label_text = label
        self.is_active = False
        self.is_lock_btn = is_lock_button
        self.is_account_btn = False  # Track if this is the account button

        # Set minimum height for the button
        self.setMinimumHeight(60)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().Policy.Fixed)

        # Create layout
        self.layout = QHBoxLayout(self)
        if is_lock_button:
            self.layout.setContentsMargins(10, 6, 18, 6)
        else:
            self.layout.setContentsMargins(18, 18, 18, 18)
        self.layout.setSpacing(18)

        # For lock button, wrap icon in a container with border
        if is_lock_button:
            # Create a container widget for the icon with border
            self.icon_container = QWidget()
            self.icon_container.setFixedSize(48, 48)  # Container size
            container_layout = QHBoxLayout(self.icon_container)
            container_layout.setContentsMargins(0, 0, 0, 0)

            # Icon label
            self.icon_label = QLabel()
            self.icon_label.setStyleSheet("background-color: transparent; border: none;")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = icon.pixmap(32, 32)
            if not pixmap.isNull():
                self.icon_label.setPixmap(pixmap)
            self.icon_label.setFixedSize(32, 32)
            self.icon_label.setScaledContents(False)
            self.icon_label.setFrameShape(QFrame.Shape.NoFrame)

            container_layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

            # Add container to button layout - no alignment flags to keep it left
            self.layout.addWidget(self.icon_container)
            self.layout.addStretch()  # Push icon to the left

            # Update container style
            self._update_icon_container_style()
        else:
            # Regular icon without border
            self.icon_label = QLabel()
            self.icon_label.setStyleSheet("background-color: transparent; border: none;")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = icon.pixmap(32, 32)
            if not pixmap.isNull():
                self.icon_label.setPixmap(pixmap)
            self.icon_label.setFixedSize(32, 32)
            self.icon_label.setScaledContents(False)
            self.icon_label.setFrameShape(QFrame.Shape.NoFrame)
            self.layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Text label (only add if label text is provided)
        if label:
            self.text_label = QLabel(label)
            self.text_label.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_MENU}; background-color: transparent; border: none; margin-top: 5px")
            self.text_label.setFrameShape(QFrame.Shape.NoFrame)
            self.layout.addWidget(self.text_label, alignment=Qt.AlignmentFlag.AlignVCenter)
            if not is_lock_button:
                self.layout.addStretch()
        else:
            self.text_label = None

        # Update initial style
        self._update_style()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_attention(self, needed: bool):
        """Place an action indicator immediately after the button label."""
        if not hasattr(self, 'attention_dot'):
            group = QWidget()
            group.setStyleSheet('background: transparent;')
            group.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row = QHBoxLayout(group)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            self.layout.replaceWidget(self.text_label, group)
            self.text_label.setStyleSheet(self.text_label.styleSheet().replace('margin-top: 5px', 'margin-top: 0px'))
            row.addWidget(self.text_label)
            self.attention_dot = QLabel()
            self.attention_dot.setFixedSize(8, 8)
            self.attention_dot.setStyleSheet(
                f'background: {colors.BLUE_ACCENT}; border: none; border-radius: 4px;')
            self.attention_dot.setAccessibleName('Needs attention')
            row.addWidget(self.attention_dot)
            self._label_group = group
        self.attention_dot.setVisible(needed)

    def set_active(self, active: bool):
        """Set the active/focused state of the button."""
        self.is_active = active
        self._update_style()
        if self.is_lock_btn:
            self._update_icon_container_style()

    def _update_icon_container_style(self):
        """Update the icon container style for lock button."""
        if not self.is_lock_btn:
            return

        if self.is_active:
            self.icon_container.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(0, 0, 0, 0.05);
                    border: 1px solid {colors.BORDER_NEUTRAL};
                    border-radius: 8px;
                }}
            """)
        else:
            self.icon_container.setStyleSheet(f"""
                QWidget {{
                    background-color: transparent;
                    border: 1px solid {colors.BORDER_NEUTRAL};
                    border-radius: 8px;
                }}
            """)

    def _update_style(self):
        """Update the button style based on its state."""
        if self.is_lock_btn:
            # Lock button - transparent background, no hover effect on main button
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                }
            """)
        else:
            if self.is_active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(0, 0, 0, 0.05);
                        border: none;
                        text-align: left;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: rgba(0, 0, 0, 0.05);
                    }
                    QPushButton:pressed {
                        background-color: rgba(0, 0, 0, 0.1);
                    }
                """)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        text-align: left;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: rgba(0, 0, 0, 0.05);
                    }
                    QPushButton:pressed {
                        background-color: rgba(0, 0, 0, 0.1);
                    }
                """)

    def mousePressEvent(self, event):
        """Handle mouse press event - apply hover effect to icon container for lock button."""
        if self.is_lock_btn:
            # Change icon container background on press
            if self.is_active:
                self.icon_container.setStyleSheet(f"""
                    QWidget {{
                        background-color: rgba(0, 0, 0, 0.1);
                        border: 1px solid {colors.BORDER_DARK};
                        border-radius: 8px;
                    }}
                """)
            else:
                self.icon_container.setStyleSheet(f"""
                    QWidget {{
                        background-color: rgba(0, 0, 0, 0.1);
                        border: 1px solid {colors.BORDER_DARK};
                        border-radius: 8px;
                    }}
                """)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release event - restore normal state for lock button."""
        super().mouseReleaseEvent(event)
        if self.is_lock_btn:
            self._update_icon_container_style()

    def enterEvent(self, event):
        """Handle mouse enter event - apply hover effect to icon container for lock button."""
        if self.is_lock_btn:
            if self.is_active:
                self.icon_container.setStyleSheet(f"""
                    QWidget {{
                        background-color: rgba(0, 0, 0, 0.05);
                        border: 1px solid {colors.BORDER_NEUTRAL};
                        border-radius: 8px;
                    }}
                """)
            else:
                self.icon_container.setStyleSheet(f"""
                    QWidget {{
                        background-color: rgba(0, 0, 0, 0.05);
                        border: 1px solid {colors.BORDER_NEUTRAL};
                        border-radius: 8px;
                    }}
                """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handle mouse leave event - restore normal state for lock button."""
        if self.is_lock_btn:
            self._update_icon_container_style()
        super().leaveEvent(event)

    def set_label_visible(self, visible: bool):
        """Show or hide the text label."""
        if self.text_label:
            self.text_label.setVisible(visible)
        if hasattr(self, '_label_group'):
            self._label_group.setVisible(visible)


class MenuDivider(QFrame):
    """A horizontal divider line for the menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Plain)  # Changed from Sunken to Plain
        self.setStyleSheet(f"background-color: {colors.BACKGROUND_NEUTRAL}; border: none;")
        self.setFixedHeight(1)


class MenuSpacer(QWidget):
    """A spacer widget for the menu."""

    def __init__(self, height: int = 8, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)


class VaultNavMenu(QFrame):
    """
    Navigation menu for vault operations.

    Displays on the left side when a vault is open, providing navigation
    to different vault sections (identifiers, credentials, contacts, etc.).

    Supports collapsible mode where the menu shows only icons when collapsed
    and expands on hover or when locked open.
    """

    # Signals for navigation
    identifiers_clicked = Signal()
    remote_identifiers_clicked = Signal()
    group_identifiers_clicked = Signal()
    credentials_clicked = Signal()
    settings_clicked = Signal()
    account_clicked = Signal()

    # Credentials menu signals
    issued_credentials_clicked = Signal()
    received_credentials_clicked = Signal()
    activity_clicked = Signal()
    schema_clicked = Signal()
    back_to_vault_from_credentials_clicked = Signal()  # When Back button is clicked from credentials menu

    back_to_vault_clicked = Signal()  # When Back button is clicked
    # Plugin menu signal — emits plugin_id when a plugin entry button is clicked
    plugin_section_clicked = Signal(str)

    def __init__(self, parent=None, collapsible: bool = True):
        """
        Initialize the VaultNavMenu.

        Args:
            parent: Parent widget
            collapsible: Whether the menu should be collapsible (default: True)
        """
        super().__init__(parent)

        self.collapsible = collapsible
        self.is_locked_open = False
        self.is_expanded = False
        self.active_nav_button = None  # Track the currently active navigation button

        # Credentials menu state
        self._in_credentials_menu = False
        self._was_locked_before_credentials = False
        self.credentials_items = []  # Credentials menu widgets
        self.credentials_nav_buttons = []  # Credentials navigation buttons

        # Plugin menu state
        self._plugin_menus: dict[str, list[QWidget]] = {}
        self._plugin_nav_buttons: dict[str, list[MenuButton]] = {}
        self._active_plugin_id: str | None = None
        self._was_locked_before_plugin = False

        # Dimensions
        self.collapsed_width = 95
        self.expanded_width = 280

        # Set initial width
        initial_width = self.collapsed_width if collapsible else self.expanded_width
        self.setFixedWidth(initial_width)

        # Set frame properties for border
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            VaultNavMenu {{
                background-color: {colors.BACKGROUND_CONTENT};
                border: none;
                border-right: 1px solid {colors.BACKGROUND_NEUTRAL};
            }}
        """)

        # Create layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 24, 12, 24)
        self.layout.setSpacing(6)

        # Store menu items for show/hide label operations
        self.menu_items = []
        self.nav_buttons = []  # Store navigation buttons separately

        # Lock/unlock button (only visible in collapsible mode)
        if self.collapsible:
            self.lock_button = MenuButton(
                self._create_lock_icon(),
                is_lock_button=True
            )
            self.lock_button.clicked.connect(self._on_lock_button_clicked)
            self.layout.addWidget(self.lock_button)
            self.menu_items.append(self.lock_button)

            # Add spacing after lock button (track it so it gets hidden on menu switch)
            self.lock_button_spacer = MenuSpacer(10)
            self.layout.addWidget(self.lock_button_spacer)
            self.menu_items.append(self.lock_button_spacer)

        # Menu items
        self._add_menu_items()

        # Credentials menu items (hidden initially)
        self._create_credentials_menu_items()

        # Track where plugin entry buttons should be inserted (before the stretch)
        self._plugin_insert_index = self.layout.count()

        self.layout.addStretch()

        # Set initial label visibility
        if self.collapsible:
            self._set_labels_visible(False)

        # Animation for width changes - need to animate both min and max for fixed width
        self.min_width_animation = QPropertyAnimation(self, b"minimumWidth")
        self.min_width_animation.setDuration(200)
        self.min_width_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.max_width_animation = QPropertyAnimation(self, b"maximumWidth")
        self.max_width_animation.setDuration(200)
        self.max_width_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        logger.info(f"VaultNavMenu initialized (collapsible={collapsible})")


    def _create_lock_icon(self) -> QIcon:
        """Create a lock/unlock icon."""
        icon_path = ":/assets/material-icons/menu.svg"
        icon = QIcon(icon_path)
        if icon.isNull():
            logger.warning(f"Failed to load lock icon from {icon_path}")
        return icon

    def _create_icon(self, icon_name: str) -> QIcon:
        """
        Create an icon by name.

        Args:
            icon_name: Name/path of the icon

        Returns:
            QIcon object
        """
        # Map icon names to file paths
        icon_paths = {
            "identifiers": ":/assets/custom/identifiers.png",
            "remote_identifiers": ":/assets/custom/remoteIds.png",
            "group_identifiers": ":/assets/material-icons/group.svg",
            "credentials": ":/assets/material-icons/badge.svg",
            "settings": ":/assets/custom/settings.png",
            # Credentials menu icons
            "credentials_issued": ":/assets/material-icons/out-badge.svg",
            "credential_activity": ":/assets/material-icons/swap_horiz.svg",
            "credentials_received": ":/assets/material-icons/in-badge.svg",
            "credentials_schema": ":/assets/material-icons/schema.svg",
            "chevron_left": ":/assets/material-icons/chevron_left.svg",
        }

        icon_path = icon_paths.get(icon_name, "")
        if not icon_path:
            logger.warning(f"Unknown icon name: {icon_name}")
            return QIcon()

        icon = QIcon(icon_path)
        if icon.isNull():
            logger.warning(f"Failed to load icon from {icon_path}")
        return icon

    def _add_menu_items(self):
        """Add the navigation menu items."""
        # Identifiers
        identifiers_btn = MenuButton(
            self._create_icon("identifiers"),
            "Identifiers"
        )
        identifiers_btn.clicked.connect(lambda: self._on_nav_button_clicked(identifiers_btn, self.identifiers_clicked))
        self.layout.addWidget(identifiers_btn)
        self.menu_items.append(identifiers_btn)
        self.nav_buttons.append(identifiers_btn)

        # Remote Identifiers
        remote_identifiers_btn = MenuButton(
            self._create_icon("remote_identifiers"),
            "Remote Identifiers"
        )
        remote_identifiers_btn.clicked.connect(lambda: self._on_nav_button_clicked(remote_identifiers_btn, self.remote_identifiers_clicked))
        self.layout.addWidget(remote_identifiers_btn)
        self.menu_items.append(remote_identifiers_btn)
        self.nav_buttons.append(remote_identifiers_btn)

        # Group Identifiers
        group_identifiers_btn = MenuButton(
            self._create_icon("group_identifiers"),
            "Group Identifiers"
        )
        group_identifiers_btn.clicked.connect(lambda: self._on_nav_button_clicked(group_identifiers_btn, self.group_identifiers_clicked))
        self.layout.addWidget(group_identifiers_btn)
        self.menu_items.append(group_identifiers_btn)
        self.nav_buttons.append(group_identifiers_btn)

        # Credentials (account-style button that opens submenu)
        credentials_btn = MenuButton(
            self._create_icon("credentials"),
            "Credentials"
        )
        credentials_btn.is_account_btn = True  # Mark as account button
        credentials_btn.clicked.connect(lambda: self._on_credentials_button_clicked(credentials_btn))
        self.layout.addWidget(credentials_btn)
        self.menu_items.append(credentials_btn)

        # Settings
        settings_btn = MenuButton(
            self._create_icon("settings"),
            "Settings"
        )
        settings_btn.clicked.connect(lambda: self._on_nav_button_clicked(settings_btn, self.settings_clicked))
        self.layout.addWidget(settings_btn)
        self.menu_items.append(settings_btn)
        self.nav_buttons.append(settings_btn)


    def _on_nav_button_clicked(self, button: MenuButton, signal: SignalInstance):
        """Handle navigation button click."""
        # Deactivate all navigation buttons
        for btn in self.nav_buttons:
            btn.set_active(False)

        # Activate the clicked button
        button.set_active(True)
        self.active_nav_button = button

        # Emit the corresponding signal
        signal.emit()

    def _on_credentials_button_clicked(self, button: MenuButton):
        """Handle credentials button click - switch to credentials menu."""
        # Deactivate all navigation buttons
        for btn in self.nav_buttons:
            btn.set_active(False)

        # Reset active nav button tracking
        self.active_nav_button = None

        # Do NOT activate the credentials button itself
        button.set_active(False)

        # Switch to credentials menu
        self.switch_to_credentials_menu()

        # Emit the credentials signal (for VaultPage to handle)
        self.credentials_clicked.emit()

    def _on_lock_button_clicked(self):
        """Handle lock button click with toggle behavior."""
        # Toggle the lock button's active state
        self.lock_button.set_active(not self.lock_button.is_active)

        # Call the existing toggle lock logic
        self._toggle_lock()

    def _toggle_lock(self):
        """Toggle the locked open state."""
        self.is_locked_open = not self.is_locked_open

        if self.is_locked_open:
            # Lock open
            self._expand()
            logger.debug("Menu locked open")
        else:
            # Unlock - collapse if not hovering
            logger.debug("Menu unlocked")
            if not self.is_expanded:
                self._collapse()

        # Update lock button appearance if needed
        logger.debug(f"Lock state: {'locked' if self.is_locked_open else 'unlocked'}")

    def _expand(self):
        """Expand the menu to show labels."""
        if not self.collapsible or self.is_expanded:
            return

        self.is_expanded = True
        self._set_labels_visible(True)
        self._animate_width(self.expanded_width)
        logger.debug("Menu expanded")

    def _collapse(self):
        """Collapse the menu to show only icons."""
        if not self.collapsible or not self.is_expanded or self.is_locked_open:
            return

        self.is_expanded = False
        self._set_labels_visible(False)
        self._animate_width(self.collapsed_width)
        logger.debug("Menu collapsed")

    def _animate_width(self, target_width: int):
        """Animate the width change."""
        self.min_width_animation.stop()
        self.max_width_animation.stop()

        current_width = self.width()

        self.min_width_animation.setStartValue(current_width)
        self.min_width_animation.setEndValue(target_width)

        self.max_width_animation.setStartValue(current_width)
        self.max_width_animation.setEndValue(target_width)

        self.min_width_animation.start()
        self.max_width_animation.start()

    def _set_labels_visible(self, visible: bool):
        """Show or hide all menu item labels."""
        for item in self.menu_items:
            if isinstance(item, MenuButton):
                item.set_label_visible(visible)

    def enterEvent(self, event: QEnterEvent):
        """Handle mouse enter event."""
        if self.collapsible and not self.is_locked_open:
            self._expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handle mouse leave event."""
        if self.collapsible and not self.is_locked_open:
            self._collapse()
        super().leaveEvent(event)

    def set_vault_name(self, vault_name: str):
        """
        Set the current vault name (for display purposes).

        Args:
            vault_name (str): Name of the open vault
        """
        logger.info(f"VaultNavMenu: Set vault name to {vault_name}")
        self.vault_name = vault_name

    # -------------------------------------------------------------------------
    # Credentials Menu Methods
    # -------------------------------------------------------------------------

    def _create_credentials_menu_items(self):
        """Create credentials submenu items (hidden initially)."""
        # Back button
        self.credentials_back_button = self._create_credentials_back_button()
        self.layout.addWidget(self.credentials_back_button)
        self.credentials_items.append(self.credentials_back_button)
        self.credentials_back_button.setVisible(False)

        # Spacer after back button
        back_spacer = MenuSpacer(15)
        self.layout.addWidget(back_spacer)
        self.credentials_items.append(back_spacer)
        back_spacer.setVisible(False)

        # Issued Credentials
        issued_credentials_btn = MenuButton(
            self._create_icon("credentials_issued"),
            "Issued Credentials"
        )
        issued_credentials_btn.clicked.connect(
            lambda: self._on_credentials_nav_clicked(issued_credentials_btn, self.issued_credentials_clicked)
        )
        self.layout.addWidget(issued_credentials_btn)
        self.credentials_items.append(issued_credentials_btn)
        self.credentials_nav_buttons.append(issued_credentials_btn)
        issued_credentials_btn.setVisible(False)

        # Received Credentials
        received_credentials_btn = MenuButton(
            self._create_icon("credentials_received"),
            "Received Credentials"
        )
        received_credentials_btn.clicked.connect(
            lambda: self._on_credentials_nav_clicked(received_credentials_btn, self.received_credentials_clicked)
        )
        self.layout.addWidget(received_credentials_btn)
        self.credentials_items.append(received_credentials_btn)
        self.credentials_nav_buttons.append(received_credentials_btn)
        received_credentials_btn.setVisible(False)

        activity_btn = MenuButton(self._create_icon("credential_activity"), "Activity")
        activity_btn.clicked.connect(
            lambda: self._on_credentials_nav_clicked(activity_btn, self.activity_clicked)
        )
        self.layout.addWidget(activity_btn)
        self.credentials_items.append(activity_btn)
        self.credentials_nav_buttons.append(activity_btn)
        activity_btn.setVisible(False)
        activity_btn.set_attention(False)
        self.activity_button = activity_btn

        # Schema
        schema_btn = MenuButton(
            self._create_icon("credentials_schema"),
            "Schema"
        )
        schema_btn.clicked.connect(
            lambda: self._on_credentials_nav_clicked(schema_btn, self.schema_clicked)
        )
        self.layout.addWidget(schema_btn)
        self.credentials_items.append(schema_btn)
        self.credentials_nav_buttons.append(schema_btn)
        schema_btn.setVisible(False)

        logger.info("Credentials menu items created (hidden)")

    def _create_credentials_back_button(self) -> QPushButton:
        """Create the back button for credentials menu."""
        back_button = BackButton(dark_mode=False)
        back_button.clicked.connect(self.switch_to_vault_menu_from_credentials)
        return back_button

    def _on_credentials_nav_clicked(self, button: MenuButton, signal: SignalInstance):
        """Handle credentials navigation button click."""
        # Deactivate all credentials navigation buttons
        for btn in self.credentials_nav_buttons:
            btn.set_active(False)
        button.set_active(True)
        signal.emit()

    def switch_to_credentials_menu(self):
        """Switch from vault menu to credentials submenu."""
        if self._in_credentials_menu:
            return

        logger.info("Switching to credentials menu")

        # Store lock state
        self._was_locked_before_credentials = self.is_locked_open

        # Hide vault menu items
        for item in self.menu_items:
            item.setVisible(False)

        # Show credentials menu items
        for item in self.credentials_items:
            item.setVisible(True)

        # Set labels visible for credentials items
        for item in self.credentials_items:
            if isinstance(item, MenuButton):
                item.set_label_visible(True)

        # Update state
        self._in_credentials_menu = True

        # Force menu expanded and locked (credentials menu is always expanded)
        if not self.is_expanded:
            self.is_expanded = True
            self._animate_width(self.expanded_width)
        self.is_locked_open = True

        # Select the first navigation button (Issued Credentials)
        if self.credentials_nav_buttons:
            self.credentials_nav_buttons[0].set_active(True)

        # Emit signal to navigate to default credentials view
        self.issued_credentials_clicked.emit()

        logger.info("Switched to credentials menu")

    def switch_to_vault_menu_from_credentials(self):
        """Switch from credentials submenu back to vault menu."""
        if not self._in_credentials_menu:
            return

        logger.info("Switching back to vault menu from credentials")

        # Hide credentials menu items
        for item in self.credentials_items:
            item.setVisible(False)

        # Deactivate credentials nav buttons
        for btn in self.credentials_nav_buttons:
            btn.set_active(False)

        # Show vault menu items
        for item in self.menu_items:
            item.setVisible(True)

        # Update state
        self._in_credentials_menu = False

        # Restore lock state
        self.is_locked_open = self._was_locked_before_credentials
        if self.collapsible:
            self.lock_button.set_active(self.is_locked_open)

        # Update label visibility based on current state
        if self.collapsible and not self.is_locked_open:
            self._set_labels_visible(False)
            self._animate_width(self.collapsed_width)
            self.is_expanded = False
        else:
            self._set_labels_visible(True)

        # Always navigate to first vault menu item
        if self.nav_buttons:
            self.nav_buttons[0].set_active(True)
            self.active_nav_button = self.nav_buttons[0]

        self.identifiers_clicked.emit()

        logger.info("Switched back to vault menu from credentials")

    # -------------------------------------------------------------------------
    # Plugin Menu Methods
    # -------------------------------------------------------------------------

    def register_plugin_section(self, plugin_id: str, entry_button: MenuButton, submenu_items: list[QWidget]):
        """
        Register a plugin section in the navigation menu.

        Adds a spacer, divider, and entry button to the main vault menu layout
        (before the stretch). Submenu items are added to the layout (hidden)
        and stored for later activation via push_plugin_menu().

        Args:
            plugin_id: Unique identifier for the plugin
            entry_button: The MenuButton to show in the main vault menu
            submenu_items: List of widgets to show when the plugin menu is active
        """
        entry_button.is_account_btn = True

        # Insert spacer, divider, and entry button before the stretch
        spacer = MenuSpacer(30)
        self.layout.insertWidget(self._plugin_insert_index, spacer)
        self._plugin_insert_index += 1
        self.menu_items.append(spacer)

        divider = MenuDivider()
        self.layout.insertWidget(self._plugin_insert_index, divider)
        self._plugin_insert_index += 1
        self.menu_items.append(divider)

        # Connect entry button click to plugin handler (capture plugin_id in closure)
        pid = plugin_id
        entry_button.clicked.connect(lambda: self._on_plugin_button_clicked(pid))

        self.layout.insertWidget(self._plugin_insert_index, entry_button)
        self._plugin_insert_index += 1
        self.menu_items.append(entry_button)

        # Sync label visibility to current menu state (registration happens after __init__)
        entry_button.set_label_visible(self.is_expanded or not self.collapsible)

        # Insert submenu items BEFORE the stretch (right after the entry button),
        # then connect any BackButton instances to pop_to_vault_menu.
        nav_buttons = []
        submenu_insert = self._plugin_insert_index
        for item in submenu_items:
            self.layout.insertWidget(submenu_insert, item)
            submenu_insert += 1
            self._plugin_insert_index += 1
            item.setVisible(False)
            if isinstance(item, BackButton):
                item.clicked.connect(self.pop_to_vault_menu)
            if isinstance(item, MenuButton):
                nav_buttons.append(item)

        self._plugin_menus[plugin_id] = submenu_items
        self._plugin_nav_buttons[plugin_id] = nav_buttons

        logger.info(f"Plugin section registered: {plugin_id} ({len(submenu_items)} submenu items)")

    def _on_plugin_button_clicked(self, plugin_id: str):
        """Handle plugin entry button click - switch to plugin menu."""
        # Deactivate all vault navigation buttons
        for btn in self.nav_buttons:
            btn.set_active(False)

        # Reset active nav button tracking
        self.active_nav_button = None

        # Emit signal so VaultPage (or plugin) can react
        self.plugin_section_clicked.emit(plugin_id)

    def push_plugin_menu(self, plugin_id: str):
        """
        Switch from vault menu to a plugin's submenu.

        Hides all vault menu items, shows the plugin's submenu items,
        forces menu expanded and locked, and selects the first nav button.

        Args:
            plugin_id: The plugin whose submenu to show
        """
        if self._active_plugin_id is not None:
            return  # Already in a plugin menu

        if plugin_id not in self._plugin_menus:
            logger.warning(f"push_plugin_menu: unknown plugin_id '{plugin_id}'")
            return

        logger.info(f"Switching to plugin menu: {plugin_id}")

        # Store lock state
        self._was_locked_before_plugin = self.is_locked_open

        # Hide vault menu items
        for item in self.menu_items:
            item.setVisible(False)

        # Show plugin submenu items
        for item in self._plugin_menus[plugin_id]:
            item.setVisible(True)

        # Set labels visible on MenuButton items
        for item in self._plugin_menus[plugin_id]:
            if isinstance(item, MenuButton):
                item.set_label_visible(True)

        # Update state
        self._active_plugin_id = plugin_id

        # Force menu expanded and locked (plugin menu is always expanded)
        if not self.is_expanded:
            self.is_expanded = True
            self._animate_width(self.expanded_width)
        self.is_locked_open = True

        logger.info(f"Switched to plugin menu: {plugin_id}")

    def pop_to_vault_menu(self):
        """
        Return from any plugin or credentials submenu to the main vault menu.

        Handles both credentials submenu and plugin submenus. Restores
        lock state and previous active button.
        """
        # If in credentials menu, delegate — it handles navigation and returns
        if self._in_credentials_menu:
            self.switch_to_vault_menu_from_credentials()
            return

        # If in a plugin menu, switch back
        if self._active_plugin_id is not None:
            plugin_id = self._active_plugin_id

            logger.info(f"Switching back to vault menu from plugin: {plugin_id}")

            # Hide plugin submenu items
            for item in self._plugin_menus.get(plugin_id, []):
                item.setVisible(False)

            # Deactivate plugin nav buttons
            for btn in self._plugin_nav_buttons.get(plugin_id, []):
                btn.set_active(False)

            # Show vault menu items
            for item in self.menu_items:
                item.setVisible(True)

            # Clear active plugin
            self._active_plugin_id = None

            # Restore lock state
            self.is_locked_open = self._was_locked_before_plugin
            if self.collapsible:
                self.lock_button.set_active(self.is_locked_open)

            # Update label visibility based on current state
            if self.collapsible and not self.is_locked_open:
                self._set_labels_visible(False)
                self._animate_width(self.collapsed_width)
                self.is_expanded = False
            else:
                self._set_labels_visible(True)

            logger.info("Switched back to vault menu")

        # Reset state
        self._was_locked_before_credentials = False
        self._was_locked_before_plugin = False

        # Always navigate to first vault menu item
        for btn in self.nav_buttons:
            btn.set_active(False)
        if self.nav_buttons:
            self.nav_buttons[0].set_active(True)
            self.active_nav_button = self.nav_buttons[0]

        self.identifiers_clicked.emit()

        logger.info("Menu reset to vault state")
