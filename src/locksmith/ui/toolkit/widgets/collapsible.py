from typing import Callable

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QSize
from PySide6.QtWidgets import QWidget, QToolButton, QGridLayout, QSizePolicy

from locksmith.ui import colors


class CollapsibleSection(QWidget):
    def __init__(
            self,
            button: QWidget | None = None,
            on_expand_changed: Callable[[bool], None] | None = None,
            title: str = "",
            parent: QWidget | None = None
    ):
        super().__init__(parent)

        self._content_height = 0
        self._dialog = None
        self._dialog_animation = None
        self._content_animation = None  # Add this
        self._collapsed_dialog_height = None
        self._expanded_dialog_height = None
        self._is_expanded = False
        self._on_expand_changed = on_expand_changed
        self._uses_custom_button = button is not None
        self._uses_centralized_management = False  # Flag for new dialog system

        if button: 
            self.toggle_button = button
        else:
            self.toggle_button = QToolButton()
            self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
            self.toggle_button.setText(f"  {title}")
            self.toggle_button.setStyleSheet(f"""
            QToolButton {{
                border: none;
                color: {colors.TEXT_PRIMARY};
                font-size: 14px;
                background-color: transparent;
                padding-left: 10px;
                padding-top: 5px;
                padding-bottom: 5px;
            }}
            QToolButton:hover {{
                background-color: {colors.BACKGROUND_COLLAPSIBLE_HOVER};
                border-radius: 4px;
            }}
        """)
            self.toggle_button.setCheckable(True)
            self.toggle_button.setChecked(False)
            self.toggle_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.toggle_button.setFixedHeight(self.toggle_button.sizeHint().height())

        self.content_area = QWidget()
        self.content_area.setVisible(False)
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QGridLayout(self)
        layout.setVerticalSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle_button, 0, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.content_area, 1, 0)

        if not button:
            self.toggle_button.toggled.connect(self._on_toggle)

    def sizeHint(self):
        """
        Manually calculate size hint to ensure atomic updates during animations.
        Relying on QLayout.sizeHint() can be laggy during rapid state changes.
        """
        h = 0
        if self.toggle_button:
            h += self.toggle_button.sizeHint().height()
        
        if self._is_expanded and self.content_area and self.content_area.isVisible():
            # Use cached content height if available (more stable) or calculate one
            content_h = self._content_height if self._content_height > 0 else self.content_area.sizeHint().height()
            h += content_h
            
        return QSize(super().sizeHint().width(), h)

    def toggle(self) -> None:
        self._set_expanded(not self._is_expanded)
        self.updateGeometry()

    def set_dialog(self, dialog):
        self._dialog = dialog
        self._collapsed_dialog_height = dialog.height()

        if not self._uses_custom_button:
            self._dialog_animation = QPropertyAnimation(dialog, b"dialogHeight")
            self._dialog_animation.setDuration(300)
            self._dialog_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._dialog_animation.stateChanged.connect(self._on_animation_state_changed)
            self._dialog_animation.finished.connect(self._on_animation_finished)

            # Add content area animation
            self._content_animation = QPropertyAnimation(self.content_area, b"maximumHeight")
            self._content_animation.setDuration(300)
            self._content_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        dialog.destroyed.connect(self._on_dialog_destroyed)

    def set_dialog_new(self, dialog):
        """
        Set the dialog using the new centralized management approach.

        This method connects the collapsible section to a LocksmithDialogNew
        instance which handles all collapsible sections centrally.

        Args:
            dialog: LocksmithDialogNew instance to connect to.
        """
        self._dialog = dialog
        self._uses_centralized_management = True

        # Create content animation for smooth expand/collapse
        if not self._uses_custom_button:
            self._content_animation = QPropertyAnimation(self.content_area, b"maximumHeight")
            self._content_animation.setDuration(300)
            self._content_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._content_animation.finished.connect(self._on_content_animation_finished)

        dialog.destroyed.connect(self._on_dialog_destroyed)

    def _on_dialog_destroyed(self):
        """Clean up references when the dialog is destroyed."""
        self._dialog = None
        self._dialog_animation = None
        self._content_animation = None  # Add this
        self._collapsed_dialog_height = None
        self._expanded_dialog_height = None
        self._is_expanded = False        
        self.content_area.setVisible(False)

        # Reset toggle button state
        if isinstance(self.toggle_button, QToolButton):
            blocked = self.toggle_button.blockSignals(True)
            self.toggle_button.setChecked(False)
            self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
            self.toggle_button.blockSignals(blocked)
        
        if self._on_expand_changed:
            self._on_expand_changed(False)

    def set_content_layout(self, layout):
        self.content_area.setLayout(layout)
        self._content_height = layout.sizeHint().height()
        self.content_area.setMaximumHeight(self._content_height)  # Use max instead of fixed
        self.content_area.setMinimumHeight(0)  # Allow shrinking to 0

    def _update_expanded_height(self):
        if self._collapsed_dialog_height is not None:
            self._expanded_dialog_height = self._collapsed_dialog_height + self._content_height

    def _on_toggle(self, checked: bool):
        # Handle centralized management mode (LocksmithDialogNew)
        if self._uses_centralized_management:
            self._is_expanded = checked

            if self._on_expand_changed:
                self._on_expand_changed(checked)

            if isinstance(self.toggle_button, QToolButton):
                arrow = Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
                self.toggle_button.setArrowType(arrow)

            # Animate content area
            if self._content_animation:
                if checked:
                    self.content_area.setVisible(True)
                    self.content_area.setMinimumHeight(self._content_height)
                    self.content_area.setMaximumHeight(self._content_height)
                else:
                    self.content_area.setMinimumHeight(0)
                    self._content_animation.setStartValue(self._content_height)
                    self._content_animation.setEndValue(0)
                    self._content_animation.start()

            # Notify dialog to handle height coordination
            if self._dialog and hasattr(self._dialog, 'on_section_toggle'):
                self._dialog.on_section_toggle(self, checked)

            return

        # Original logic for legacy set_dialog() mode
        if self._expanded_dialog_height is None:
            self._update_expanded_height()

        if self._dialog_animation and self._dialog_animation.state() == QAbstractAnimation.State.Running:
            self._dialog_animation.stop()
            if self._content_animation:
                self._content_animation.stop()
            self._snap_to_state(not checked)

        self._is_expanded = checked

        if self._on_expand_changed:
            self._on_expand_changed(checked)

        if isinstance(self.toggle_button, QToolButton):
            arrow = Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            self.toggle_button.setArrowType(arrow)

        if self._dialog_animation:
            if checked:
                self.content_area.setVisible(True)
                self._dialog_animation.setStartValue(self._collapsed_dialog_height)
                self._dialog_animation.setEndValue(self._expanded_dialog_height)
                # Animate content from 0 to full height
                if self._content_animation:
                    self._content_animation.setStartValue(0)
                    self._content_animation.setEndValue(self._content_height)
            else:
                self._dialog_animation.setStartValue(self._expanded_dialog_height)
                self._dialog_animation.setEndValue(self._collapsed_dialog_height)
                # Animate content from full height to 0
                if self._content_animation:
                    self._content_animation.setStartValue(self._content_height)
                    self._content_animation.setEndValue(0)

            self._dialog_animation.start()
            if self._content_animation:
                self._content_animation.start()

    def _set_expanded(self, expanded: bool) -> None:
        self._is_expanded = expanded
        self.content_area.setVisible(expanded)

        if self._on_expand_changed:
            self._on_expand_changed(expanded)

        if isinstance(self.toggle_button, QToolButton):
            arrow = Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            self.toggle_button.setArrowType(arrow)

        self.updateGeometry()

    def _on_animation_state_changed(self, new_state, _old_state):
        """Disable scrollbars when animation starts running."""
        if new_state == QAbstractAnimation.State.Running:
            if self._dialog and hasattr(self._dialog, 'scroll_area'):
                self._dialog.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self._dialog.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _on_animation_finished(self):
        """Hide content after collapse animation completes and re-enable scrollbars."""
        if not self._is_expanded:
            self.content_area.setVisible(False)

        # Re-enable scrollbars
        if self._dialog and hasattr(self._dialog, 'scroll_area'):
            self._dialog.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _on_content_animation_finished(self):
        """Hide content after collapse animation completes (for centralized mode)."""
        if not self._is_expanded:
            self.content_area.setVisible(False)


    def _snap_to_state(self, expanded: bool):
        self._is_expanded = expanded
        self.content_area.setVisible(expanded)
        if self._dialog:
            target = self._expanded_dialog_height if expanded else self._collapsed_dialog_height
            if target:
                self._dialog.setFixedSize(self._dialog.width(), target)

    def update_content_height(self):
        """Recalculate content height and update dialog size if expanded."""
        if self.content_area.layout():
            self._content_height = self.content_area.layout().sizeHint().height()
            self.content_area.setFixedHeight(self._content_height)
            self._update_expanded_height()

            # If currently expanded, update the dialog height immediately
            if self._is_expanded and self._dialog and self._expanded_dialog_height:
                self._dialog.setFixedSize(self._dialog.width(), self._expanded_dialog_height)
            if self._dialog:
                self._dialog.center_on_parent()
