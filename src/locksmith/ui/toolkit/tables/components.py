# -*- encoding: utf-8 -*-
"""
locksmith.ui.toolkit.tables.components module

Sub-components for table widgets: header, pagination, menus.
"""
from typing import List, Optional, Dict

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QLabel,
    QToolButton,
    QMenu,
)
from keri import help

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import HoverIconButton, LocksmithButton, LocksmithIconButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit

logger = help.ogler.getLogger(__name__)


class TableHeader(QWidget):
    """
    Header bar with icon, title, search field, and add button.

    Search and actions can use separate rows below the title.
    """

    search_changed = Signal(str)
    add_clicked = Signal()
    filter_clicked = Signal()

    def __init__(
        self,
        icon_path: Optional[str] = None,
        title: str = "",
        show_search: bool = True,
        show_add_button: bool = True,
        add_button_text: str = "Add",
        filter_func: Optional[callable] = None,
        parent=None,
        *,
        separate_toolbar: bool = False
    ):
        """
        Initialize the TableHeader.

        Args:
            icon_path: Optional path to icon to display at the left
            title: Page title text
            show_search: Whether to show the search bar
            show_add_button: Whether to show the add button
            add_button_text: Text for the add button
            filter_func: Optional callback function to invoke when filter button is clicked
            parent: Parent widget
            separate_toolbar: Put search and actions below the title for action-heavy pages
        """
        super().__init__(parent)

        self.show_search = show_search
        self.show_add_button = show_add_button
        self.filter_func = filter_func

        # Create main layout
        layout = QVBoxLayout(self) if separate_toolbar else QHBoxLayout(self)
        layout.setContentsMargins(10, 20, 5, 10)
        layout.setSpacing(12 if separate_toolbar else 16)
        if separate_toolbar:
            title_layout = QHBoxLayout()
            title_layout.setSpacing(16)
            layout.addLayout(title_layout)
            self.search_layout = QHBoxLayout()
            self.search_layout.setSpacing(16)
            layout.addLayout(self.search_layout)
            self.toolbar_layout = QHBoxLayout()
            self.toolbar_layout.setSpacing(16)
            layout.addLayout(self.toolbar_layout)
        else:
            title_layout = layout
            self.search_layout = layout
            self.toolbar_layout = layout

        # Icon (optional)
        if icon_path:
            icon = QIcon(icon_path)
            if not icon.isNull():
                icon_label = QLabel()
                icon_label.setPixmap(icon.pixmap(32, 32))
                icon_label.setFixedSize(32, 32)
                title_layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: 28px;
                font-weight: 600;
                color: {colors.TEXT_PRIMARY};
            }}
        """)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        # Filter button (optional)
        if filter_func is not None:
            self.filter_button = LocksmithIconButton(
                icon_path=":/assets/material-icons/tune.svg",
                tooltip="Filter results",
                icon_size=28
            )
            self.filter_button.setFixedSize(55, 55)
            self.filter_button.clicked.connect(lambda: self.filter_func())
            self.toolbar_layout.addWidget(self.filter_button)

        # Search bar
        if show_search:
            search_icon_path = ":/assets/material-icons/search.svg"
            self.search_input = FloatingLabelLineEdit(
                label_text="Search...",
                leading_icon=search_icon_path
            )
            if separate_toolbar:
                self.search_input.setMinimumWidth(160)
                self.search_input.setMaximumWidth(300)
                self.search_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            else:
                self.search_input.setFixedWidth(300)
            self.search_input.setMinimumHeight(55)

            # Add clear button when text is present
            clear_action = QAction(self)
            clear_icon_path = ":/assets/material-icons/close.svg"
            clear_action.setIcon(QIcon(clear_icon_path))
            clear_action.triggered.connect(lambda: self.search_input.setText(""))
            self.search_input.line_edit.addAction(clear_action, self.search_input.line_edit.ActionPosition.TrailingPosition)

            # Connect search signal
            self.search_input.line_edit.textChanged.connect(self.search_changed.emit)

            self.search_layout.addWidget(self.search_input)

        if separate_toolbar:
            self.toolbar_layout.addStretch()

        # Add button
        if show_add_button:
            self.add_button = LocksmithButton(add_button_text)
            self.add_button.setFixedHeight(47)
            self.add_button.clicked.connect(self.add_clicked.emit)

            self.toolbar_layout.addWidget(self.add_button)

        logger.debug(f"TableHeader initialized: title='{title}'")

    def add_action_button(self, button):
        """Insert a secondary action before the primary action in the toolbar."""
        if self.show_add_button:
            self.toolbar_layout.insertWidget(self.toolbar_layout.indexOf(self.add_button), button)
            # Move the new action into the toolbar focus chain, then put it before the primary.
            QWidget.setTabOrder(self.add_button, button)
            QWidget.setTabOrder(button, self.add_button)
        else:
            self.toolbar_layout.addWidget(button)


class PaginationControls(QWidget):
    """
    Pagination bar with item count and navigation controls.

    Layout: [X items] [---stretch---] [<<] [<] [Page X of Y] [>] [>>]
    """

    page_changed = Signal(int)  # new page number

    def __init__(self, parent=None):
        """
        Initialize the PaginationControls.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        self.current_page = 1
        self.total_pages = 1
        self.total_items = 0
        self.items_per_page = 25

        # Create main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(12)

        # Stretch to push pagination to the right
        layout.addStretch()

        # Item count label
        self.item_count_label = QLabel("0 items")
        self.item_count_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                color: {colors.TEXT_SECONDARY};
            }}
        """)
        layout.addWidget(self.item_count_label)

        # First page button
        first_page_icon_path = ":/assets/material-icons/first_page.svg"
        first_page_hover_path = ":/assets/material-icons/first_page.svg"
        self.first_page_btn = HoverIconButton(
            first_page_icon_path,
            first_page_hover_path,
            tooltip="First page"
        )
        self.first_page_btn.clicked.connect(self._on_first_page)
        layout.addWidget(self.first_page_btn)

        # Previous page button
        prev_page_icon_path = ":/assets/material-icons/chevron_left.svg"
        prev_page_hover_path = ":/assets/material-icons/chevron_left.svg"
        self.prev_page_btn = HoverIconButton(
            prev_page_icon_path,
            prev_page_hover_path,
            tooltip="Previous page"
        )
        self.prev_page_btn.clicked.connect(self._on_previous_page)
        layout.addWidget(self.prev_page_btn)

        # Page indicator
        self.page_indicator = QLabel("Page 1 of 1")
        self.page_indicator.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                color: {colors.TEXT_PRIMARY};
                padding: 0 12px;
            }}
        """)
        layout.addWidget(self.page_indicator)

        # Next page button
        next_page_icon_path = ":/assets/material-icons/chevron_right.svg"
        next_page_hover_path = ":/assets/material-icons/chevron_right.svg"
        self.next_page_btn = HoverIconButton(
            next_page_icon_path,
            next_page_hover_path,
            tooltip="Next page"
        )
        self.next_page_btn.clicked.connect(self._on_next_page)
        layout.addWidget(self.next_page_btn)

        # Last page button
        last_page_icon_path = ":/assets/material-icons/last_page.svg"
        last_page_hover_path = ":/assets/material-icons/last_page.svg"
        self.last_page_btn = HoverIconButton(
            last_page_icon_path,
            last_page_hover_path,
            tooltip="Last page"
        )
        self.last_page_btn.clicked.connect(self._on_last_page)
        layout.addWidget(self.last_page_btn)

        # Update button states
        self._update_button_states()

        logger.debug("PaginationControls initialized")

    def set_pagination(self, current_page: int, total_pages: int, total_items: int):
        """
        Update pagination information.

        Args:
            current_page: Current page number (1-indexed)
            total_pages: Total number of pages
            total_items: Total number of items across all pages
        """
        self.current_page = current_page
        self.total_pages = max(1, total_pages)  # At least 1 page
        self.total_items = total_items

        # Update labels
        self.item_count_label.setText(f"{total_items} item{'s' if total_items != 1 else ''}")
        self.page_indicator.setText(f"Page {current_page} of {self.total_pages}")

        # Update button states
        self._update_button_states()

    def _update_button_states(self):
        """Enable/disable buttons based on current page."""
        # Disable first/previous on first page
        is_first_page = self.current_page <= 1
        self.first_page_btn.setEnabled(not is_first_page)
        self.prev_page_btn.setEnabled(not is_first_page)

        # Disable next/last on last page
        is_last_page = self.current_page >= self.total_pages
        self.next_page_btn.setEnabled(not is_last_page)
        self.last_page_btn.setEnabled(not is_last_page)

    def _on_first_page(self):
        """Navigate to first page."""
        if self.current_page != 1:
            self.page_changed.emit(1)

    def _on_previous_page(self):
        """Navigate to previous page."""
        if self.current_page > 1:
            self.page_changed.emit(self.current_page - 1)

    def _on_next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages:
            self.page_changed.emit(self.current_page + 1)

    def _on_last_page(self):
        """Navigate to last page."""
        if self.current_page != self.total_pages:
            self.page_changed.emit(self.total_pages)

class SkewersMenuButton(QToolButton):
    """
    Button with three-dot (kebab) menu for row actions.

    Displays a vertical three-dot icon that opens a dropdown menu
    with customizable actions.
    """

    action_triggered = Signal(str)  # action_name

    def __init__(self, actions: List[str] = None, action_icons: Optional[Dict[str, str]] = None, parent=None):
        """
        Initialize the SkewersMenuButton.

        Args:
            actions: List of action names to display in menu
            action_icons: Optional dict mapping action names to full icon paths (e.g., {"Edit": ":/assets/custom/edit.svg"})
            parent: Parent widget
        """
        super().__init__(parent)

        self.actions_list = actions or []
        self.action_icons = action_icons or {}

        # Set icon
        icon_path = ":/assets/material-icons/more_vert.svg"
        self.setIcon(QIcon(icon_path))
        # Set icon size to ensure it's not clipped
        self.setIconSize(QSize(24, 24))

        # Set minimum size to prevent clipping
        self.setMinimumSize(32, 32)
        self.setFixedSize(32, 32)

        # Button styling
        self.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {colors.BACKGROUND_NEUTRAL};
            }}
            QToolButton:pressed {{
                background-color: {colors.BACKGROUND_NEUTRAL_HOVER};
            }}
            QToolButton::menu-indicator {{
                image: none;  /* Hide default menu arrow */
            }}
        """)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Row actions")
        self.setToolTip("Row actions")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Create menu
        self.menu = QMenu(self)
        self.setMenu(self.menu)
        self.menu.setStyleSheet(f"""
            QMenu {{
                background-color: {colors.BACKGROUND_CONTENT};
                border: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-radius: 6px;
                padding: 0px;
            }}
            QMenu::item {{
                padding: 8px 32px 8px 14px;
                border-radius: 4px;
                color: {colors.BLACK};
                min-height: 24px;
            }}
            QMenu::item:selected {{
                background-color: {colors.BACKGROUND_COLLAPSIBLE_HOVER};
            }}
            QMenu::icon {{
                padding-left: 16px;
            }}
        """)

        # Add actions to menu
        self._populate_menu()

        # Change popup mode to allow manual control
        self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)

        # Override the default menu behavior
        self.clicked.connect(self._show_menu_right_aligned)

        logger.debug(f"SkewersMenuButton initialized with actions: {self.actions_list}")

    def _show_menu_right_aligned(self):
        """Show menu aligned to the right edge of the button."""
        if self.menu:
            # Calculate position for right-aligned menu
            bottom_right = self.mapToGlobal(self.rect().bottomRight())
            menu_width = self.menu.sizeHint().width()

            # Position so menu's right edge aligns with button's right edge
            menu_pos = bottom_right
            menu_pos.setX(bottom_right.x() - menu_width)

            self.menu.popup(menu_pos)

    def _populate_menu(self):
        """Populate menu with actions and their icons."""
        for action_name in self.actions_list:
            action = QAction(action_name, self)

            # Add icon if available
            if action_name in self.action_icons:
                icon_path = self.action_icons[action_name]
                icon = QIcon(icon_path)

                # Set icon with explicit pixmap size to force rendering
                if not icon.isNull():
                    action.setIcon(icon)
                    action.setIconVisibleInMenu(True)
                else:
                    logger.warning(f"Icon could not be loaded: {icon_path}")

            action.triggered.connect(lambda checked=False, name=action_name: self._on_action_triggered(name))
            self.menu.addAction(action)

    def _on_action_triggered(self, action_name: str):
        """
        Handle menu action triggered.

        Args:
            action_name: Name of the triggered action
        """
        logger.debug(f"SkewersMenuButton action triggered: {action_name}")
        self.action_triggered.emit(action_name)

    def set_actions(self, actions: List[str], action_icons: Optional[Dict[str, str]] = None):
        """
        Update the menu actions.

        Args:
            actions: New list of action names
            action_icons: Optional dict mapping action names to full icon paths
        """
        self.actions_list = actions
        if action_icons is not None:
            self.action_icons = action_icons

        # Clear existing actions
        self.menu.clear()

        # Add new actions with icons
        self._populate_menu()
