"""Credential labels and read-only attributes shared by wallet views."""
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from keri.help import helping

from locksmith.ui import colors


def credential_name(schema):
    schema = schema or {}
    return schema.get('title', 'Credential')


def identifier_name(vault, pre):
    if not pre:
        return 'Not specified'
    hab = vault.hby.habByPre(pre)
    contact = vault.org.get(pre) or {}
    name = hab.name if hab else contact.get('alias')
    if not name:
        return pre[:10] + '…' + pre[-6:]
    peers = {h.pre for h in vault.hby.habs.values() if h.name == name}
    peers.update(c['id'] for c in vault.org.list() if c.get('alias') == name)
    return f'{name} ({pre[:8]}…)' if len(peers) > 1 else name


def date_label(stamp):
    if not stamp:
        return '—'
    try:
        return helping.fromIso8601(stamp).astimezone().strftime('%b %d, %Y %H:%M')
    except (ValueError, TypeError):
        return stamp


def status_label(status):
    return {'issued': 'Active', 'revoked': 'Revoked', 'pending': 'Pending verification',
            'authenticated': 'Authenticated'}.get(status.get('et'), 'Unknown state')


def attribute_view(label, value, schema=None):
    """Display disclosed values without editable controls or JSON syntax."""
    schema = schema if isinstance(schema, Mapping) else {}
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 8)
    title = QLabel(label)
    title.setTextFormat(Qt.TextFormat.PlainText)
    title.setStyleSheet(f'font-weight: bold; color: {colors.TEXT_SECONDARY};')
    title.setWordWrap(True)
    layout.addWidget(title)
    if isinstance(value, Mapping):
        properties = schema.get('properties', {})
        for name, item in value.items():
            prop = properties.get(name, {})
            prop = prop if isinstance(prop, Mapping) else {}
            child = attribute_view(prop.get('description', name), item, prop)
            child.layout().setContentsMargins(16, 0, 0, 8)
            layout.addWidget(child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            layout.addWidget(attribute_view(str(index + 1), item, schema.get('items', {})))
    else:
        text = ('Yes' if value else 'No') if isinstance(value, bool) else str(value if value is not None else '')
        content = QLabel(text or '—')
        content.setTextFormat(Qt.TextFormat.PlainText)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                        Qt.TextInteractionFlag.TextSelectableByKeyboard)
        content.setWordWrap(True)
        layout.addWidget(content)
    return widget
