# -*- encoding: utf-8 -*-
"""
locksmith.ui.toolkit.widgets.buttons module

This module contains reusable custom button widget components.
"""
from PySide6.QtCore import Qt, QSize, Signal, QPoint, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QColor, QPixmap, QPainter, QCursor
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QPushButton, QRadioButton, QCheckBox, QApplication, QHBoxLayout, \
    QLabel, QFrame, QGraphicsOpacityEffect, QWidget, QStyle, QStyleOptionToolButton, QStylePainter

from locksmith.ui import colors


class HoverIconButton(QToolButton):
    """
    A toolbar button that automatically swaps icons on hover.

    This widget encapsulates the logic for displaying different icons
    when the mouse hovers over the button, providing visual feedback.
    """

    def __init__(self, icon_normal: str, icon_hover: str, tooltip: str | None = None, parent=None):
        """
        Initialize the HoverIconButton.

        Args:
            icon_normal: Path to the normal state icon.
            icon_hover: Path to the hover state icon.
            tooltip: Optional tooltip text.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        # Convert to resource paths if not already
        self.icon_normal = f":/{icon_normal}" if not icon_normal.startswith(":/") else icon_normal
        self.icon_hover = f":/{icon_hover}" if not icon_hover.startswith(":/") else icon_hover
        self.is_active = False  # Track if button should stay in active/hover state

        # Set initial icon
        self.setIcon(QIcon(self.icon_normal))

        # Set tooltip if provided
        if tooltip:
            self.setToolTip(tooltip)

        # Set cursor to pointer hand
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Set transparent background to match toolbar style
        self.setStyleSheet(f"""
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

    def set_active(self, active: bool):
        """
        Set the active state of the button.

        When active, the button displays the hover icon and background
        even when the mouse is not hovering over it.

        Args:
            active: True to keep button in active/hover state, False for normal behavior.
        """
        self.is_active = active
        if active:
            self.setIcon(QIcon(self.icon_hover))
            self.setStyleSheet(f"""
                QToolButton {{
                    background-color: {colors.BACKGROUND_NEUTRAL};
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
        else:
            self.setIcon(QIcon(self.icon_normal))
            self.setStyleSheet(f"""
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

    def enterEvent(self, event):
        """Handle mouse enter event by switching to hover icon."""
        if not self.is_active:
            self.setIcon(QIcon(self.icon_hover))
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handle mouse leave event by switching back to normal icon."""
        if not self.is_active:
            self.setIcon(QIcon(self.icon_normal))
        super().leaveEvent(event)


class LocksmithButton(QPushButton):
    """
    Custom QPushButton styled with orange background and white text.
    Darker shade on hover (opposite of the original lighter hover).
    """

    def __init__(self, text: str = "", icon_path: str | None = None, parent=None):
        """
        Initialize the LocksmithButton.

        Args:
            text: Button text.
            icon_path: Optional path to icon file to display before text.
            parent: Parent widget.
        """
        # Add extra space to text if icon is present
        display_text = f"  {text}" if icon_path else text
        super().__init__(display_text, parent)

        # Set icon if provided
        if icon_path:

            # Load the icon
            original_pixmap = QPixmap(icon_path)

            # Create a white version of the icon
            white_pixmap = QPixmap(original_pixmap.size())
            white_pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(white_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawPixmap(0, 0, original_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(white_pixmap.rect(), QColor(colors.WHITE))
            painter.end()

            icon = QIcon(white_pixmap)
            self.setIcon(icon)
            self.setIconSize(QSize(20, 20))

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.PRIMARY};
                color: {colors.WHITE};
                border-radius: 6px;
                font-size: 14px;
                padding-top: 12px;
                padding-bottom: 12px;
                padding-left: 25px;
                padding-right: 25px;
                border: 1px solid {colors.PRIMARY};
            }}
            QPushButton:hover {{
                background-color: {colors.PRIMARY_HOVER};
                border: 1px solid {colors.PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {colors.PRIMARY_HOVER};
            }}
            QPushButton:disabled {{
                background-color: {colors.BACKGROUND_DISABLED};
                color: {colors.TEXT_MUTED};
                border-color: {colors.BORDER_NEUTRAL};
            }}
        """)


class LocksmithInvertedButton(QPushButton):
    """
    Custom QPushButton styled with white background, orange outline and text.
    Inverted version of OrangeButton.
    """

    def __init__(self, text: str = "", parent=None):
        """
        Initialize the InvertedOrangeButton.

        Args:
            text: Button text.
            parent: Parent widget.
        """
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.WHITE};
                color: {colors.PRIMARY};
                border: 1px solid {colors.PRIMARY};
                border-radius: 6px;
                font-size: 14px;
                padding-top: 12px;
                padding-bottom: 12px;
                padding-left: 25px;
                padding-right: 25px;
            }}
            QPushButton:hover {{
                background-color: {colors.BACKGROUND_HOVER};
                color: {colors.PRIMARY_HOVER};
                border: 1px solid {colors.PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {colors.DIVIDER};
                color: {colors.PRIMARY_PRESSED};
                border: 1px solid {colors.PRIMARY_PRESSED};
            }}
        """)


class BackButton(QPushButton):
    """
    A back navigation button with arrow icon and "Back" text.
    
    Supports both dark mode (white icon/text for dark backgrounds) and
    light mode (dark icon/text for light backgrounds).
    """

    def __init__(self, dark_mode: bool = False, parent=None):
        """
        Initialize the BackButton.

        Args:
            dark_mode: If True, use white icon/text for dark backgrounds.
                       If False, use dark icon/text for light backgrounds.
            parent: Parent widget.
        """
        super().__init__(parent)
        self.dark_mode = dark_mode
        
        self.setMinimumHeight(40)
        self.setFixedHeight(40)  # Fixed height for layout stability
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Create layout for icon + text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        
        # Arrow icon
        arrow_label = QLabel()
        icon_pixmap = self._create_colored_icon()
        if icon_pixmap and not icon_pixmap.isNull():
            arrow_label.setPixmap(icon_pixmap)
        arrow_label.setFixedSize(16, 16)
        arrow_label.setStyleSheet("background-color: transparent; border: none;")
        
        # Text label
        text_color = colors.WHITE if dark_mode else colors.TEXT_MENU
        text_label = QLabel("Back")
        text_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {text_color}; "
            "background-color: transparent; border: none;"
        )
        
        layout.addWidget(arrow_label)
        layout.addWidget(text_label)
        layout.addStretch()
        
        # Style based on dark_mode
        if dark_mode:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 0.2);
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: rgba(0, 0, 0, 0.05);
                }
                QPushButton:pressed {
                    background-color: rgba(0, 0, 0, 0.1);
                }
            """)
    
    def _create_colored_icon(self) -> QPixmap | None:
        """Create a colored version of the chevron_left icon."""
        original_pixmap = QPixmap(":/assets/material-icons/chevron_left.svg")
        
        if original_pixmap.isNull():
            return None
        
        # Scale to 16x16
        scaled = original_pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, 
                                        Qt.TransformationMode.SmoothTransformation)
        
        # For dark mode, recolor to white
        if self.dark_mode:
            colored_pixmap = QPixmap(scaled.size())
            colored_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(colored_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawPixmap(0, 0, scaled)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(colored_pixmap.rect(), QColor(colors.WHITE))
            painter.end()
            
            return colored_pixmap
        
        return scaled

    def set_hidden(self, hidden: bool):
        """
        Hide or show the button while preserving layout space.
        
        Uses opacity effect instead of setVisible() to prevent layout shift.
        
        Args:
            hidden: True to hide the button, False to show it.
        """
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        
        if hidden:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.0)
            self.setGraphicsEffect(effect)
            self.setEnabled(False)
        else:
            self.setGraphicsEffect(None)
            self.setEnabled(True)

class LocksmithRadioButton(QRadioButton):
    def __init__(self, text: str = "", parent=None):
        """
        Initialize the LocksmithRadioButton.

        Args:
            text: Button text.
            parent: Parent widget.
        """
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QRadioButton {{
                color: {colors.RADIO_BUTTON};
                spacing: 6px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {colors.RADIO_BUTTON};
                border-radius: 10px;
                background-color: {colors.WHITE};
            }}
            QRadioButton::indicator:checked {{
                background-color: qradialgradient(
                    cx:0.5, cy:0.5, radius:0.5,
                    fx:0.5, fy:0.5,
                    stop:0 {colors.RADIO_BUTTON},
                    stop:0.6 {colors.RADIO_BUTTON},
                    stop:0.7 {colors.WHITE},
                    stop:1 {colors.WHITE}
                );
                border: 2px solid {colors.BLACK};
            }}
        """)


class LocksmithCheckbox(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        """
        Initialize the LocksmithCheckbox.

        Args:
            text: Button text.
            parent: Parent widget.
        """
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QCheckBox {{
                color: {colors.RADIO_BUTTON};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {colors.RADIO_BUTTON};
                border-radius: 2px;
                background-color: {colors.WHITE};
            }}
            QCheckBox::indicator:checked {{
                background-color: {colors.RADIO_BUTTON};
                border: 2px solid {colors.RADIO_BUTTON};
                image: url(:/assets/material-icons/check.svg);
            }}
        """)

class LocksmithIconButton(QToolButton):
    """
    A compact icon-only button styled to match the Locksmith theme.

    This button displays only an icon (no text) and provides hover feedback
    with the orange brand color. Ideal for toolbars and icon-based interfaces.
    """

    def __init__(self, icon_path: str, tooltip: str, icon_size: int = 36, parent=None, border=False):
        """
        Initialize the LocksmithIconButton.

        Args:
            icon_path: Path to the icon file (supports Qt resource paths).
            tooltip: Tooltip text to display on hover (required for accessibility).
            icon_size: Size of the icon in pixels (default: 36).
            parent: Optional parent widget.
            border: Whether to show a border around the button (default: False).
        """
        super().__init__(parent)

        # Load and set the icon
        self.icon_path = icon_path
        self._icon_size = icon_size
        self._setup_icon()

        # Set tooltip (required for icon-only buttons)
        self.setToolTip(tooltip)

        # Set cursor to pointer hand
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        border_style = f"1px solid {colors.BORDER_NEUTRAL}" if border else "none"
        # Apply Locksmith-themed styling
        self.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                padding: 0px;
                margin: 0px;
                border-radius: 6px;
                border: {border_style};
            }}
            QToolButton:hover {{
                background-color: {colors.BACKGROUND_HOVER};
            }}
            QToolButton:pressed {{
                background-color: {colors.BACKGROUND_HOVER};
            }}
            QToolButton:disabled {{
                opacity: 0.5;
            }}
        """)

    def _setup_icon(self):
        """Set up the icon with proper sizing and coloring."""
        # Load the original icon
        original_pixmap = QPixmap(self.icon_path)

        if not original_pixmap.isNull():
            # Set the icon
            icon = QIcon(original_pixmap)
            self.setIcon(icon)
            self.setIconSize(QSize(self._icon_size, self._icon_size))

    def set_icon_color(self, color: str):
        """
        Change the icon color dynamically.

        Args:
            color: A color string from locksmith.ui.colors.
        """
        original_pixmap = QPixmap(self.icon_path)

        if original_pixmap.isNull():
            return

        # Create a colored version of the icon
        colored_pixmap = QPixmap(original_pixmap.size())
        colored_pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(colored_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawPixmap(0, 0, original_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), QColor(color))
        painter.end()

        icon = QIcon(colored_pixmap)
        self.setIcon(icon)

    def set_icon_size(self, size: int):
        """
        Change the icon size dynamically.

        Args:
            size: New icon size in pixels.
        """
        self._icon_size = size
        self.setIconSize(QSize(size, size))


class LocksmithCopyButton(LocksmithIconButton):
    """
    A copy button that copies content to the clipboard when clicked.

    This button automatically uses the copy icon and handles clipboard operations.
    Inherits the Locksmith styling from LocksmithIconButton.
    """

    def __init__(self, copy_content: str = "", tooltip: str = "Copy to clipboard",
                 icon_size: int = 36, parent=None, border=False):
        """
        Initialize the LocksmithCopyButton.

        Args:
            copy_content: The text content to copy to clipboard when clicked.
            tooltip: Optional tooltip text (default: "Copy to clipboard").
            icon_size: Size of the icon in pixels (default: 36).
            parent: Optional parent widget.
            border: Whether to show a border around the button (default: False).
        """
        # Initialize with the copy icon
        super().__init__(
            icon_path=":/assets/material-icons/content_copy.svg",
            tooltip=tooltip,
            icon_size=icon_size,
            parent=parent,
            border=border
        )

        self._copy_content = copy_content
        self._copy_tooltip = tooltip
        self._check_icon = QIcon(":/assets/material-icons/check_dark.svg")
        self.setAccessibleName(tooltip)
        self.setStyleSheet(self.styleSheet() + f"""
            QToolButton:hover, QToolButton:focus {{
                background-color: {colors.BACKGROUND_SELECTION};
            }}
            QToolButton:pressed {{
                background-color: {colors.BACKGROUND_HIGHLIGHT};
            }}
        """)
        self._feedback = QVariantAnimation(self)
        self._feedback.setDuration(140)
        self._feedback.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._feedback.setStartValue(0.0)
        self._feedback.setEndValue(0.0)
        self._feedback.valueChanged.connect(lambda _: self.update())
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(1500)
        self._reset_timer.timeout.connect(self._reset_copy_feedback)

        # Connect click signal to copy action
        self.clicked.connect(self._copy_to_clipboard)

    def _copy_to_clipboard(self):
        """Copy the content to the system clipboard."""
        if self._copy_content:
            clipboard = QApplication.clipboard()
            clipboard.setText(self._copy_content)
            self.setToolTip("Copied")
            self.setAccessibleDescription("Copied")
            self._animate_feedback(1.0)
            self._reset_timer.start()

    def _animate_feedback(self, value):
        self._feedback.stop()
        self._feedback.setStartValue(self._feedback.currentValue())
        self._feedback.setEndValue(value)
        self._feedback.start()

    def _reset_copy_feedback(self):
        self._reset_timer.stop()
        self.setToolTip(self._copy_tooltip)
        self.setAccessibleDescription("")
        self._animate_feedback(0.0)

    def paintEvent(self, event):
        """Crossfade the icons without moving the button or its neighbors."""
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        rect = QStyle.alignedRect(self.layoutDirection(), Qt.AlignmentFlag.AlignCenter,
                                  self.iconSize(), self.rect())
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        progress = self._feedback.currentValue()
        painter.setOpacity(1.0 - progress)
        self.icon().paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode)
        painter.setOpacity(progress)
        self._check_icon.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode)

    def set_copy_content(self, content: str):
        """
        Update the content that will be copied to clipboard.

        Args:
            content: The new text content to copy.
        """
        if content != self._copy_content:
            self._reset_copy_feedback()
        self._copy_content = content

    def get_copy_content(self) -> str:
        """
        Get the current copy content.

        Returns:
            The text content that will be copied to clipboard.
        """
        return self._copy_content


class LocksmithRadioPanel(QFrame):
    """
    A radio panel with header and subheader text that highlights when selected.

    Clicking anywhere on the panel selects the radio button.
    """

    # Signal emitted when selection state changes
    toggled = Signal(bool)

    # Colors
    BORDER_NORMAL = colors.BACKGROUND_NEUTRAL
    BORDER_SELECTED = colors.BLUE_SELECTION
    BG_SELECTED = colors.BLUE_SELECTION_BG
    TEXT_SELECTED = colors.BLUE_SELECTION
    TEXT_NORMAL = colors.RADIO_BUTTON

    def __init__(self, header: str, subheader: str, parent=None):
        """
        Initialize the LocksmithRadioPanel.

        Args:
            header: Bold header text (16px).
            subheader: Subheader text (12px).
            parent: Parent widget.
        """
        super().__init__(parent)

        self._is_checked = False

        # Set fixed dimensions
        self.setFixedWidth(465)
        self.setFixedHeight(100)

        # Set cursor to indicate clickability
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Create main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(40, 20, 40, 20)
        main_layout.setSpacing(12)

        # Create radio button (no text, we handle text separately)
        self._radio_button = QRadioButton()
        self._radio_button.toggled.connect(self._on_radio_toggled)
        self._update_radio_style()

        # Create vertical layout for header and subheader
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)

        # Header label
        self._header_label = QLabel(header)
        self._header_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {self.TEXT_NORMAL};
        """)

        # Subheader label
        self._subheader_label = QLabel(subheader)
        self._subheader_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: normal;
            color: {self.TEXT_NORMAL};
        """)

        text_layout.addStretch()
        text_layout.addWidget(self._header_label)
        text_layout.addWidget(self._subheader_label)
        text_layout.addStretch()

        # Add widgets to main layout (radio centered vertically by default in QHBoxLayout)
        main_layout.addWidget(self._radio_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        main_layout.addLayout(text_layout)
        main_layout.addStretch()

        # Apply initial frame style
        self._update_frame_style()

    def _update_frame_style(self):
        """Update the frame border and background based on selection state."""
        if self._is_checked:
            self.setStyleSheet(f"""
                LocksmithRadioPanel {{
                    border: 1px solid {self.BORDER_SELECTED};
                    background-color: {self.BG_SELECTED};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                LocksmithRadioPanel {{
                    border: 1px solid {self.BORDER_NORMAL};
                    background-color: transparent;
                }}
            """)

    def _update_radio_style(self):
        """Update the radio button style based on selection state."""
        if self._is_checked:
            self._radio_button.setStyleSheet(f"""
                QRadioButton {{
                    spacing: 6px;
                }}
                QRadioButton::indicator {{
                    width: 16px;
                    height: 16px;
                    border: 2px solid {self.BORDER_SELECTED};
                    border-radius: 10px;
                    background-color: {colors.WHITE};
                }}
                QRadioButton::indicator:checked {{
                    background-color: qradialgradient(
                        cx:0.5, cy:0.5, radius:0.5,
                        fx:0.5, fy:0.5,
                        stop:0 {self.BORDER_SELECTED},
                        stop:0.6 {self.BORDER_SELECTED},
                        stop:0.7 {colors.WHITE},
                        stop:1 {colors.WHITE}
                    );
                    border: 2px solid {self.BORDER_SELECTED};
                }}
            """)
        else:
            self._radio_button.setStyleSheet(f"""
                QRadioButton {{
                    spacing: 6px;
                }}
                QRadioButton::indicator {{
                    width: 16px;
                    height: 16px;
                    border: 2px solid {colors.RADIO_BUTTON};
                    border-radius: 10px;
                    background-color: {colors.WHITE};
                }}
                QRadioButton::indicator:checked {{
                    background-color: qradialgradient(
                        cx:0.5, cy:0.5, radius:0.5,
                        fx:0.5, fy:0.5,
                        stop:0 {colors.RADIO_BUTTON},
                        stop:0.6 {colors.RADIO_BUTTON},
                        stop:0.7 {colors.WHITE},
                        stop:1 {colors.WHITE}
                    );
                    border: 2px solid {colors.BLACK};
                }}
            """)

    def _update_text_style(self):
        """Update the header and subheader colors based on selection state."""
        color = self.TEXT_SELECTED if self._is_checked else self.TEXT_NORMAL
        self._header_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {color};
        """)
        self._subheader_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: normal;
            color: {color};
        """)

    def _on_radio_toggled(self, checked: bool):
        """Handle radio button toggle."""
        self._is_checked = checked
        self._update_frame_style()
        self._update_radio_style()
        self._update_text_style()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        """Handle mouse click anywhere on the panel."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._radio_button.setChecked(True)
        super().mousePressEvent(event)

    def setChecked(self, checked: bool):
        """Set the checked state of the radio button."""
        self._radio_button.setChecked(checked)

    def isChecked(self) -> bool:
        """Return whether the radio button is checked."""
        return self._radio_button.isChecked()

    def radioButton(self) -> QRadioButton:
        """Return the underlying radio button for group management."""
        return self._radio_button

    def setEnabled(self, enabled: bool):
        """Enable or disable the radio panel."""
        super().setEnabled(enabled)
        self._radio_button.setEnabled(enabled)

        # Update cursor
        if enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ForbiddenCursor)

        # Update opacity
        if enabled:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.8)
            self.setGraphicsEffect(effect)


class IconRightButton(QWidget):
    clicked = Signal()

    def __init__(self, text, icon=None, parent=None):
        super().__init__(parent)

        self.menu = None
        self.text = text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 5)
        layout.setSpacing(5)

        # Add text
        self.text_label = QLabel(text)
        layout.addWidget(self.text_label, stretch=0)

        # Add icon
        if icon:
            self.icon_label = QLabel()
            if isinstance(icon, QIcon):
                pixmap = icon.pixmap(28, 28)
            else:
                pixmap = icon
            self.icon_label.setPixmap(pixmap)
            layout.addWidget(self.icon_label, stretch=1)

        # Make it look and behave like a button
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            IconRightButton {{
                background-color: transparent;
                font-size: 16px;
                color: {colors.TEXT_TOOLBAR};
                border: none;
                text-align: left;
                padding-left: 10px;
                padding-top: 0px;  /* Make room for icon */
            }}
            QLabel {{
                border: none;
            }}
            IconRightButton:hover {{
                background-color: {colors.TOOLBAR_HOVER};
                border-radius: 4px;

            }}
            QLabel {{
                font-size: 16px;
                color: {colors.TEXT_TOOLBAR};
                background-color: transparent;
                border: none;
            }}
        """)

    def set_text(self, text):
        self.text_label.setText(text)
        self.text = text

    def set_menu(self, menu):
        """Set a menu to be displayed when the button is clicked"""
        self.menu = menu

    def show_menu(self):
        """Show the popup menu at the appropriate position"""
        if self.menu:
            # Calculate position below the button
            pos = self.mapToGlobal(QPoint(self.text_label.width(), self.height()))
            self.menu.exec(pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.menu:
                self.show_menu()
            else:
                self.clicked.emit()
