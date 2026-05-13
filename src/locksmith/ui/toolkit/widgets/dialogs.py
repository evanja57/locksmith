# -*- encoding: utf-8 -*-
"""
locksmith.ui.toolkit.widgets.dialogs module

This module contains reusable custom dialog widget components.
"""
from typing import cast

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QPushButton
)
from keri import help

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithButton

logger = help.ogler.getLogger(__name__)


class LocksmithDialog(QDialog):
    """
    Reusable dialog class with fade-in animation, overlay, and structured layout.

    Features:
    - Modal by default (can be disabled with show_overlay=False)
    - 8px border radius
    - Fade-in animation
    - Optional semi-transparent overlay behind dialog
    - Optional header with icon, title, and close button
    - Scrollable content area
    - Optional centered button row
    - Centralized collapsible section management

    Usage:
        # Simple dialog with content
        dialog = LocksmithDialog(parent, content=my_widget)
        dialog.open()

        # Non-modal dialog without overlay
        dialog = LocksmithDialog(parent, content=my_widget, show_overlay=False)
        dialog.open()

        # Full-featured dialog
        button_layout = QHBoxLayout()
        button_layout.addWidget(QPushButton("Cancel"))
        button_layout.addWidget(QPushButton("OK"))

        dialog = LocksmithDialog(
            parent=parent,
            title="My Dialog",
            title_icon="path/to/icon.png",
            content=my_widget,
            buttons=button_layout
        )
        dialog.open()

        # Manual content addition
        dialog = LocksmithDialog(parent)
        dialog.content_layout.addWidget(QLabel("Custom content"))
        dialog.open()

        # With collapsible sections
        dialog = LocksmithDialog(parent, content=my_widget)
        section = CollapsibleSection(title="Section 1", parent=dialog)
        section.set_content_layout(section_layout)
        dialog.register_collapsible_section(section)
    """

    # Class variable to track currently open dialog
    _current_dialog = None

    def __init__(
            self,
            parent: QWidget | None = None,
            title: str | None = None,
            title_icon: str | None = None,
            title_content: QWidget | None = None,
            show_close_button: bool = True,
            show_title_divider: bool = True,
            content: QWidget | None = None,
            buttons: QHBoxLayout | None = None,
            show_overlay: bool = False,
            margin_for_max_height: int = 40
    ):
        """
        Initialize the LocksmithDialog.

        Args:
            parent: Parent widget (typically the main window).
            title: Optional title text to display in header.
            title_icon: Optional path to icon to display before title.
            show_close_button: Whether to show X button in top right (default True).
            show_title_divider: Whether to show horizontal line below header (default True).
            content: Optional widget to display in scrollable content area.
            buttons: Optional QHBoxLayout containing buttons to display at bottom.
            show_overlay: Whether to show overlay and make dialog modal (default True).
            margin_for_max_height: Margin (in pixels) to leave when calculating max height.
        """
        super().__init__(parent)

        if show_overlay:
            self.setModal(True)
        # Remove window frame for custom styling
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)

        # Enable translucent background for border radius to work
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Create overlay if we have a parent and show_overlay is True
        self.overlay = None
        if parent and show_overlay:
            self._create_overlay(parent)

        # Create main container frame with background and border radius
        self.container = QFrame(self)
        self.container.setObjectName("dialog-container")
        self.container.setStyleSheet(f"""
            QFrame#dialog-container {{
                background-color: {colors.BACKGROUND_CONTENT};
                border-radius: 12px;
            }}
            QFrame#header-divider {{
                background-color: {colors.DIVIDER};
                max-height: 2px;
            }}
        """)

        # Create layout for dialog (holds the container)
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.addWidget(self.container)

        # Use window opacity instead of QGraphicsOpacityEffect to avoid rendering artifacts
        self._opacity = 1.0
        self.fade_animation = QPropertyAnimation(self, b"dialogOpacity")
        self.fade_animation.setDuration(300)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)

        # Build dialog structure inside the container
        self._build_dialog(title, title_icon, title_content, show_close_button, show_title_divider, content, buttons)

        # Track base height for error banner animation
        self._base_height = None
        self._dialog_resize_animation = None

        # Collapsible section management
        self._collapsible_sections = []
        self._base_content_height = None
        self._max_dialog_height = None
        self._margin_for_max_height = margin_for_max_height
        self._is_scrollable = False

    def _build_dialog(
            self,
            title: str | None,
            title_icon: str | None,
            title_content: QWidget | None,
            show_close_button: bool,
            show_title_divider: bool,
            content: QWidget | None,
            buttons: QHBoxLayout | None
    ):
        """Build the dialog structure with header, content, and buttons."""
        # Main layout (applied to container, not dialog)
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Conditionally add header section
        if title or title_icon or show_close_button:
            self._build_header(main_layout, title, title_icon, title_content, show_close_button, show_title_divider)

        # Add error banner section
        self._build_error_banner(main_layout)

        # Add success banner section
        self._build_success_banner(main_layout)

        # Add content area (scrollable)
        self._build_content_area(main_layout, content)

        # Conditionally add button section
        if buttons:
            self._build_button_section(main_layout, buttons)

    def _build_header(
            self,
            main_layout: QVBoxLayout,
            title: str | None,
            title_icon: str | None,
            title_content: QWidget | None,
            show_close_button: bool,
            show_title_divider: bool
    ):
        """Build the header section with optional icon, title, and close button."""
        # Header container
        main_layout.addSpacing(5)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(20, 20, 20, 20)
        header_layout.setSpacing(12)

        # Add icon if provided
        if title_icon:
            icon_label = QLabel()
            icon_label.setPixmap(QIcon(title_icon).pixmap(24, 24))
            header_layout.addWidget(icon_label)


        # Default to title_content if both title and title_content are provided
        if title_content:
            header_layout.addWidget(title_content)
            self.title_label = None  # No direct title label when using custom content

        # Add title if provided
        elif title:
            self.title_label = QLabel(title)
            self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
            header_layout.addWidget(self.title_label)
        else:
            self.title_label = None

        # Add stretch to push close button to the right
        header_layout.addStretch()

        # Add close button if requested
        if show_close_button:
            close_button = QPushButton()
            close_button.setIcon(QIcon(":/assets/material-icons/close.svg"))
            close_button.setFixedSize(32, 32)
            close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            close_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {colors.BACKGROUND_NEUTRAL};
                }}
                QPushButton:pressed {{
                    background-color: {colors.BACKGROUND_NEUTRAL_HOVER};
                }}
            """)
            close_button.clicked.connect(self.reject)
            header_layout.addWidget(close_button)

        main_layout.addLayout(header_layout)

        # Add divider if requested
        if show_title_divider:
            divider = QFrame()
            divider.setObjectName("header-divider")
            divider.setFrameShape(QFrame.Shape.HLine)
            main_layout.addWidget(divider)

    def _build_error_banner(self, main_layout: QVBoxLayout):
        """Build collapsible error banner."""
        self.error_banner = QFrame()
        self.error_banner.setObjectName("error-banner")
        self.error_banner.setStyleSheet(f"""
            QFrame#error-banner {{
                background-color: {colors.BACKGROUND_ERROR};
                border-left: 4px solid {colors.DANGER};
            }}
        """)
        self.error_banner.setMaximumHeight(0)  # Start hidden

        banner_layout = QHBoxLayout(self.error_banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        banner_layout.setSpacing(10)

        # Error icon
        error_icon = QLabel()
        error_pixmap = QIcon(":/assets/material-icons/error.svg").pixmap(QSize(20, 20))
        error_icon.setPixmap(error_pixmap)
        error_icon.setFixedSize(20, 20)
        banner_layout.addWidget(error_icon)

        # Error message
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {colors.DANGER}; font-size: 13px;")
        banner_layout.addWidget(self.error_label, 1)

        main_layout.addWidget(self.error_banner)

        # Animation for smooth expand/collapse
        self.error_animation = QPropertyAnimation(self.error_banner, b"maximumHeight")
        self.error_animation.setDuration(200)
        self.error_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_success_banner(self, main_layout: QVBoxLayout):
        """Build collapsible success banner."""
        self.success_banner = QFrame()
        self.success_banner.setObjectName("success-banner")
        self.success_banner.setStyleSheet(f"""
            QFrame#success-banner {{
                background-color: {colors.BACKGROUND_SUCCESS};
                border-left: 4px solid {colors.SUCCESS};
            }}
        """)
        self.success_banner.setMaximumHeight(0)  # Start hidden

        banner_layout = QHBoxLayout(self.success_banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        banner_layout.setSpacing(10)

        # Success icon
        success_icon = QLabel()
        success_pixmap = QIcon(":/assets/material-icons/check_circle.svg").pixmap(QSize(20, 20))
        success_icon.setPixmap(success_pixmap)
        success_icon.setFixedSize(20, 20)
        banner_layout.addWidget(success_icon)

        # Success message
        self.success_label = QLabel()
        self.success_label.setWordWrap(True)
        self.success_label.setStyleSheet(f"color: {colors.SUCCESS_TEXT}; font-size: 13px;")
        banner_layout.addWidget(self.success_label, 1)

        main_layout.addWidget(self.success_banner)

        # Animation for smooth expand/collapse
        self.success_animation = QPropertyAnimation(self.success_banner, b"maximumHeight")
        self.success_animation.setDuration(200)
        self.success_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_content_area(self, main_layout: QVBoxLayout, content: QWidget | None):
        """Build the scrollable content area."""
        # Create scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # Create content container widget
        content_container = QWidget()
        content_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        self.content_layout = QVBoxLayout(content_container)
        self.content_layout.setContentsMargins(20, 0, 20, 0)

        # Add provided content or leave layout exposed for manual addition
        if content:
            self.content_layout.addWidget(content)

        self.scroll_area.setWidget(content_container)
        main_layout.addWidget(self.scroll_area)

    def _build_button_section(self, main_layout: QVBoxLayout, buttons: QHBoxLayout):
        """Build the button section at the bottom."""
        # Add spacing before buttons
        main_layout.addSpacing(20)

        # Create container for centered buttons
        button_container = QHBoxLayout()
        button_container.setContentsMargins(16, 0, 16, 16)
        button_container.addStretch()

        # Add the provided button layout
        button_container.addLayout(buttons)
        for index in range(buttons.count() - 1, -1, -1):
            item = buttons.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, LocksmithButton):
                widget.setDefault(True)
                widget.setAutoDefault(True)
                break

        button_container.addStretch()
        main_layout.addLayout(button_container)
        main_layout.addSpacing(10)

    def _create_overlay(self, parent: QWidget):
        """
        Create semi-transparent overlay behind dialog.

        Args:
            parent: Parent widget to attach overlay to.
        """
        self.overlay = QFrame(parent)
        self.overlay.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 150);
            }
        """)
        self.overlay.setGeometry(parent.rect())
        self.overlay.hide()

        # Create opacity effect for fade animation
        self.overlay_opacity = QGraphicsOpacityEffect(self.overlay)
        self.overlay.setGraphicsEffect(self.overlay_opacity)

        # Create fade animation for overlay
        self.overlay_animation = QPropertyAnimation(self.overlay_opacity, b"opacity")
        self.overlay_animation.setDuration(300)
        self.overlay_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _is_nested_under_locksmith_dialog(self, ancestor: QWidget) -> bool:
        """True if this dialog's Qt parent chain includes ``ancestor`` (e.g. witness auth over issue UI)."""
        p = self.parentWidget()
        while p is not None:
            if p is ancestor:
                return True
            p = p.parentWidget()
        return False

    def showEvent(self, event):
        """Override showEvent to trigger fade-in animation."""
        cur = LocksmithDialog._current_dialog
        nested_under_current = (
            cur is not None
            and cur is not self
            and self._is_nested_under_locksmith_dialog(cur)
        )

        # Close any existing peer dialog before showing this one (but not the parent
        # of a nested dialog — e.g. Issue Credential must stay open while Witness Auth shows).
        if cur is not None and cur is not self and not nested_under_current:
            cur.close()

        if not nested_under_current:
            LocksmithDialog._current_dialog = self

        super().showEvent(event)

        # Center dialog on parent
        try:
            self.center_on_parent()
        except Exception:
            pass

        # Calculate max dialog height based on parent window
        self._max_dialog_height = self._calculate_max_dialog_height()

        # Store base height (dialog with all sections collapsed)
        if self._base_content_height is None:
            self._base_content_height = self.height()

        # Show and animate overlay
        if self.overlay:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay_animation.setStartValue(0.0)
            self.overlay_animation.setEndValue(1.0)
            self.overlay_animation.start()

        # Raise dialog above overlay
        self.raise_()

        # Start fade animation (window opacity doesn't need the timing workarounds)
        self.setWindowOpacity(0.0)
        self.fade_animation.start()

    def closeEvent(self, event):
        """Override closeEvent to clean up overlay."""
        # Clear the current dialog reference if this is it
        if LocksmithDialog._current_dialog == self:
            LocksmithDialog._current_dialog = None

        # Hide overlay
        if self.overlay:
            self.overlay.hide()

        super().closeEvent(event)

    def reject(self):
        """Override reject to ensure overlay cleanup."""
        if self.overlay:
            self.overlay.hide()
        super().reject()

    def accept(self):
        """Override accept to ensure overlay cleanup."""
        if self.overlay:
            self.overlay.hide()
        super().accept()

    @Property(int)
    def dialogHeight(self):
        """Get dialog height property for animation."""
        return self.height()

    @dialogHeight.setter
    def dialogHeight(self, value):
        """Set dialog height property for animation."""
        current_width = self.width()
        self.setFixedSize(current_width, value)
        self.center_on_parent()

    def center_on_parent(self):
        """Center the dialog on its parent widget."""
        if self.parent():
            parent = cast(QWidget, self.parent())
            parent_rect = parent.rect()
            parent_center = parent.mapToGlobal(parent_rect.center())
            self.move(
                parent_center.x() - self.width() // 2,
                parent_center.y() - self.height() // 2
            )

    @Property(float)
    def dialogOpacity(self):
        """Get dialog opacity for animation."""
        return self._opacity

    @dialogOpacity.setter
    def dialogOpacity(self, value):
        """Set dialog opacity for animation."""
        self._opacity = value
        self.setWindowOpacity(value)

    def show_error(self, message: str):
        """
        Show error banner with message and animate dialog height.

        Args:
            message: Error message to display.
        """
        # Clear any existing success banner without resizing the dialog
        # This allows show_error to handle the resize from Current -> Target
        self.clear_success(resize_dialog=False)

        # Capture base height on first error
        if self._base_height is None:
            self._base_height = self.height()

        self.error_label.setText(message)

        # Calculate the natural height the banner needs
        # Temporarily remove height constraint to measure
        self.error_banner.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
        self.error_banner.adjustSize()
        banner_height = self.error_banner.sizeHint().height()
        self.error_banner.setMaximumHeight(0)  # Reset for animation

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Animate error banner to calculated height
        self.error_animation.setStartValue(0)
        self.error_animation.setEndValue(banner_height)
        self.error_animation.start()

        # Store banner height for clear_error
        self._current_banner_height = banner_height

        # Animate dialog height
        if self._dialog_resize_animation is None:
            self._dialog_resize_animation = QPropertyAnimation(self, b"dialogHeight")
            self._dialog_resize_animation.setDuration(200)
            self._dialog_resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Re-enable scrollbars when animation finishes
            self._dialog_resize_animation.finished.connect(self._re_enable_scrollbars)

        self._dialog_resize_animation.setStartValue(self.height())
        self._dialog_resize_animation.setEndValue(self._base_height + banner_height)
        self._dialog_resize_animation.start()

    def clear_error(self, resize_dialog: bool = True):
        """
        Hide error banner and animate dialog height back.

        Args:
            resize_dialog: Whether to resize the dialog window (default True).
                           Set to False when swapping banners to let the new banner handle resizing.
        """
        if self._base_height is None:
            return

        # Get current banner height (use stored value or measure)
        banner_height = getattr(self, '_current_banner_height', self.error_banner.height())

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Animate error banner
        self.error_animation.setStartValue(banner_height)
        self.error_animation.setEndValue(0)
        self.error_animation.start()

        if resize_dialog:
            # Animate dialog height
            if self._dialog_resize_animation:
                self._dialog_resize_animation.setStartValue(self.height())
                self._dialog_resize_animation.setEndValue(self._base_height)
                self._dialog_resize_animation.start()

    def show_success(self, message: str):
        """
        Show success banner with message and animate dialog height.

        Args:
            message: Success message to display.
        """
        # Clear any existing error banner without resizing the dialog
        # This allows show_success to handle the resize from Current -> Target
        self.clear_error(resize_dialog=False)

        # Capture base height on first success
        if self._base_height is None:
            self._base_height = self.height()

        self.success_label.setText(message)

        # Calculate the natural height the banner needs
        # Temporarily remove height constraint to measure
        self.success_banner.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
        self.success_banner.adjustSize()
        banner_height = self.success_banner.sizeHint().height()
        self.success_banner.setMaximumHeight(0)  # Reset for animation

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Animate success banner to calculated height
        self.success_animation.setStartValue(0)
        self.success_animation.setEndValue(banner_height)
        self.success_animation.start()

        # Store banner height for clear_success
        self._current_success_banner_height = banner_height

        # Animate dialog height
        if self._dialog_resize_animation is None:
            self._dialog_resize_animation = QPropertyAnimation(self, b"dialogHeight")
            self._dialog_resize_animation.setDuration(200)
            self._dialog_resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Re-enable scrollbars when animation finishes
            self._dialog_resize_animation.finished.connect(self._re_enable_scrollbars)

        self._dialog_resize_animation.setStartValue(self.height())
        self._dialog_resize_animation.setEndValue(self._base_height + banner_height)
        self._dialog_resize_animation.start()

    def clear_success(self, resize_dialog: bool = True):
        """
        Hide success banner and animate dialog height back.

        Args:
            resize_dialog: Whether to resize the dialog window (default True).
                           Set to False when swapping banners to let the new banner handle resizing.
        """
        if self._base_height is None:
            return

        # Get current banner height (use stored value or measure)
        banner_height = getattr(self, '_current_success_banner_height', self.success_banner.height())

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Animate success banner
        self.success_animation.setStartValue(banner_height)
        self.success_animation.setEndValue(0)
        self.success_animation.start()

        if resize_dialog:
            # Animate dialog height
            if self._dialog_resize_animation:
                self._dialog_resize_animation.setStartValue(self.height())
                self._dialog_resize_animation.setEndValue(self._base_height)
                self._dialog_resize_animation.start()

    def adjust_for_content_expansion(self, height_delta: int):
        """
        Expand dialog height when content (like CollapsibleSection) expands.

        Args:
            height_delta: Amount of height to add to the dialog.
        """

        if self._dialog_resize_animation is None:
            self._dialog_resize_animation = QPropertyAnimation(self, b"dialogHeight")
            self._dialog_resize_animation.setDuration(300)
            self._dialog_resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Re-enable scrollbars when animation finishes
            self._dialog_resize_animation.finished.connect(self._re_enable_scrollbars)

        # Capture base height if not set
        if self._base_height is None:
            self._base_height = self.height()

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        target_height = self.height() + height_delta
        self._dialog_resize_animation.setStartValue(self.height())
        self._dialog_resize_animation.setEndValue(target_height)
        self._dialog_resize_animation.start()

    def adjust_for_content_collapse(self, height_delta: int):
        """
        Shrink dialog height when content (like CollapsibleSection) collapses.

        Args:
            height_delta: Amount of height to remove from the dialog.
        """
        if self._dialog_resize_animation is None:
            self._dialog_resize_animation = QPropertyAnimation(self, b"dialogHeight")
            self._dialog_resize_animation.setDuration(300)
            self._dialog_resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Re-enable scrollbars when animation finishes
            self._dialog_resize_animation.finished.connect(self._re_enable_scrollbars)

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        target_height = self.height() - height_delta
        self._dialog_resize_animation.setStartValue(self.height())
        self._dialog_resize_animation.setEndValue(target_height)
        self._dialog_resize_animation.start()

    def _re_enable_scrollbars(self):
        """Re-enable scrollbars after animation completes."""
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def register_collapsible_section(self, section):
        """
        Register a collapsible section with the dialog.

        Args:
            section: CollapsibleSection instance to register.
        """
        section_info = {
            'section': section,
            'content_height': section._content_height,
            'is_expanded': False
        }
        self._collapsible_sections.append(section_info)

        # Connect section toggle to our handler
        section.set_dialog_new(self)

    def on_section_toggle(self, section, is_expanded):
        """
        Handle collapsible section toggle event.

        Args:
            section: The CollapsibleSection that toggled.
            is_expanded: New expanded state.
        """
        # Update state tracking
        for item in self._collapsible_sections:
            if item['section'] == section:
                item['is_expanded'] = is_expanded
                break

        # Calculate new target height
        target_height = self._calculate_target_height()

        # Update dialog height with appropriate logic
        self._update_dialog_height(target_height)

    def _calculate_target_height(self):
        """
        Calculate the target dialog height based on expanded sections.

        Returns:
            int: Target height in pixels.
        """
        # Start with base height (all sections collapsed)
        total_height = self._base_content_height

        # Add height of all expanded sections
        for item in self._collapsible_sections:
            if item['is_expanded']:
                total_height += item['content_height']

        return total_height

    def _calculate_max_dialog_height(self):
        """
        Calculate maximum dialog height based on parent window.

        Returns:
            int: Maximum height in pixels.
        """
        # Try to find the main window (LocksmithWindow)
        widget = self.parent()
        while widget is not None:
            if widget.__class__.__name__ == 'LocksmithWindow':
                # Use window height minus margin
                return cast(QWidget, widget).height() - self._margin_for_max_height
            widget = widget.parent()

        # Fallback: use a reasonable default
        return 1000

    def _update_dialog_height(self, target_height):
        """
        Update dialog height with appropriate animation and scrolling logic.

        Args:
            target_height: Desired dialog height.
        """
        current_height = self.height()

        # Determine action based on target vs max height
        # (Calculate final_height BEFORE disabling scrollbars to allow early return)
        if target_height > self._max_dialog_height:
            # Content exceeds max height - enable scrolling and set to max
            self._is_scrollable = True
            final_height = self._max_dialog_height
        elif current_height == self._max_dialog_height and target_height < self._max_dialog_height:
            # Currently at max (scrollable), but content shrunk below max
            # Shrink dialog to fit content
            self._is_scrollable = False
            final_height = target_height
        else:
            # Normal resize without scrolling
            self._is_scrollable = False
            final_height = target_height

        # Skip animation and scrollbar toggling if no height change is needed
        if current_height == final_height:
            if self._is_scrollable:
                self._scroll_to_bottom()
            return

        # Disable scrollbars during animation
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Create or reuse animation
        if self._dialog_resize_animation is None:
            self._dialog_resize_animation = QPropertyAnimation(self, b"dialogHeight")
            self._dialog_resize_animation.setDuration(300)
            self._dialog_resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._dialog_resize_animation.finished.connect(self._on_resize_animation_finished)

        # Animate to target height
        self._dialog_resize_animation.setStartValue(current_height)
        self._dialog_resize_animation.setEndValue(final_height)
        self._dialog_resize_animation.start()

    def _on_resize_animation_finished(self):
        """Handle animation completion - re-enable scrollbars if needed."""
        if self._is_scrollable:
            # Enable vertical scrollbar
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            # Content fits - no scrollbars needed
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Horizontal scrollbar always off
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _scroll_to_bottom(self):
        """Smoothly scroll the content area to the bottom."""
        from PySide6.QtCore import QTimer
        # Use a short delay to ensure layout is updated before scrolling
        QTimer.singleShot(10, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self):
        """Execute animated scroll to bottom."""
        scrollbar = self.scroll_area.verticalScrollBar()

        if not hasattr(self, '_scroll_animation') or self._scroll_animation is None:
            self._scroll_animation = QPropertyAnimation(scrollbar, b"value")
            self._scroll_animation.setDuration(200)
            self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(scrollbar.maximum())
        self._scroll_animation.start()

    def set_title(self, title: str):
        """
        Update the dialog title text.

        Args:
            title: New title text to display.
        """
        if self.title_label:
            self.title_label.setText(title)

class LocksmithResourceDeletionDialog(LocksmithDialog):
    """
    Reusable dialog for confirming resource deletion with name validation.

    The user must type the resource name exactly to enable the Delete button,
    preventing accidental deletions.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        resource_type: str = "resource",
        resource_name: str = "",
        title_icon: str | None = None
    ):
        """
        Initialize the LocksmithResourceDeletionDialog.

        Args:
            parent: Parent widget.
            resource_type: Type of resource being deleted (e.g., "identifier", "credential").
            resource_name: Name of the resource to delete.
            title_icon: Optional path to icon to display in title.
        """
        self.resource_type = resource_type
        self.resource_name = resource_name

        # Import here to avoid circular imports
        from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit
        from locksmith.ui.toolkit.widgets import LocksmithButton, LocksmithInvertedButton

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        layout.addSpacing(10)

        # Warning message
        message = QLabel(
            f"You are attempting to delete a(n) {resource_type} with name '{resource_name}'. "
            f"Please type the name below and select Delete to confirm."
        )
        message.setWordWrap(True)
        message.setStyleSheet(f"font-size: 14px; color: {colors.DANGER_HOVER};")
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(message)

        layout.addSpacing(20)

        # Name confirmation field
        self.name_field = FloatingLabelLineEdit(f"Type '{resource_name}' to confirm")
        self.name_field.setFixedWidth(360)
        self.name_field.line_edit.textChanged.connect(self._on_name_changed)
        layout.addWidget(self.name_field)

        layout.addStretch()

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.delete_button = LocksmithButton("Delete")
        self.delete_button.setEnabled(False)  # Disabled by default
        button_row.addWidget(self.delete_button)

        # Initialize parent dialog
        super().__init__(
            parent=parent,
            title=f"Delete {resource_type.title()}",
            title_icon=title_icon,
            show_close_button=True,
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        # Set initial size
        self.setFixedSize(400, 340)

        # Connect buttons
        self.cancel_button.clicked.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)

    def _on_name_changed(self, text: str):
        """
        Handle name field changes and enable/disable delete button.

        Args:
            text: Current text in the name field.
        """
        # Enable delete button only if typed name exactly matches resource name
        matches = text.strip() == self.resource_name
        self.delete_button.setEnabled(matches)
