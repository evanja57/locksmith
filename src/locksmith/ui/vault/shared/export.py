# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.shared.export module

Shared utility for exporting identifiers to CESR files.
"""
from PySide6.QtWidgets import QFileDialog, QWidget
from keri import help

from locksmith.core.remoting import identifier_introduction

logger = help.ogler.getLogger(__name__)


def export_identifier_to_cesr(parent_widget: QWidget, app, identifier_alias: str) -> None:
    """
    Export an identifier to a CESR file.

    Args:
        parent_widget: Parent widget for the file dialog
        app: Application instance
        identifier_alias: The alias of the identifier to export
    """
    try:
        # Get the hab (identifier) by alias
        hab = app.vault.hby.habByName(identifier_alias)
        if not hab:
            logger.error(f"Identifier '{identifier_alias}' not found")
            return

        # Format the suggested filename: lowercase with spaces replaced by dashes
        suggested_filename = f"{identifier_alias.lower().replace(' ', '-')}.cesr"

        # Open file save dialog
        file_path, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Identifier",
            suggested_filename,
            "CESR Files (*.cesr);;All Files (*)"
        )

        # If user cancelled, file_path will be empty
        if not file_path:
            logger.info("Identifier export cancelled")
            return

        # Include the signed routes needed to send messages to this identifier.
        introduction = identifier_introduction(hab)
        with open(file_path, "wb") as f:
            f.write(introduction)

        logger.info(f"Identifier '{identifier_alias}' exported to {file_path}")

    except Exception as e:
        logger.exception(f"Error exporting identifier '{identifier_alias}': {e}")
