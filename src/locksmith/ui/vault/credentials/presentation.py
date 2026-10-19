"""Credential labels and read-only attributes shared by wallet views."""
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from keri.help import helping
from keri.core import Saider

from locksmith.core import ipexing
from locksmith.ui import colors


def credential_name(schema):
    schema = schema or {}
    return schema.get('title', 'Credential')


def attribute_label(name, schema):
    """Use the same readable field names in forms and credential reviews."""
    description = schema.get('description', 'Date' if name == 'dt' else name)
    # Timestamp annotations describe wire encoding, not part of the field label.
    return description.split(' RFC-3339')[0].split(' RFC3339')[0]


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


def rules_text(rules):
    """Keep disclosed terms readable without treating a commitment as rule text."""
    if not isinstance(rules, Mapping):
        try:
            if Saider(qb64=rules).qb64 == rules:
                return 'Rule text has not been disclosed.'
        except Exception:
            pass
        return rules
    values = {('Legal terms' if key == 'l' else key): value if key == 'l' else rules_text(value)
              for key, value in rules.items() if key not in ('d', 'u')}
    if list(values) == ['Legal terms']:
        return values['Legal terms']
    return values or 'Rule text has not been disclosed.'


def disclosed_credentials(vault, said, *, metadata=False):
    """Read the same retained nodes that the Grant builder will send."""
    _, _, _, nodes = ipexing._credential_evidence(vault, said)
    if metadata:
        return [node.sad for node in ipexing._offer_previews(nodes)]
    return list(nodes.values())


def credential_details(vault, sad, *, identity=True):
    """Show a retained credential's identity, disclosed attributes, and terms."""
    schema = sad.get('s', {})
    if isinstance(schema, str):
        schemer = vault.hby.db.schema.get((schema,))
        schema = schemer.sed if schemer else {}
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 12)
    if identity:
        layout.addWidget(attribute_view(credential_name(schema), 'Issued by ' + identifier_name(vault, sad.get('i'))))
    attrs = sad.get('a')
    if isinstance(attrs, Mapping):
        if identity:
            layout.addWidget(attribute_view('Credential subject', identifier_name(vault, attrs.get('i'))))
        definition = schema.get('properties', {}).get('a', {})
        definition = definition if isinstance(definition, Mapping) else {}
        definition = next((item for item in definition.get('oneOf', [definition])
                           if isinstance(item, Mapping) and item.get('type') == 'object'), {})
        for name, value in attrs.items():
            if name in ('d', 'i', 'u'):
                continue
            prop = definition.get('properties', {}).get(name, {})
            prop = prop if isinstance(prop, Mapping) else {}
            layout.addWidget(attribute_view(attribute_label(name, prop), value, prop))
    elif attrs is not None:
        layout.addWidget(attribute_view('Attributes', 'Withheld until the Grant.' if attrs == '' else 'Only a commitment is disclosed.'))
    if 'A' in sad:
        layout.addWidget(attribute_view('Disclosed aggregate', sad['A']))
    layout.addWidget(attribute_view('Terms', rules_text(sad['r']) if sad.get('r') else 'No rules attached.'))
    return widget


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
            child = attribute_view(attribute_label(name, prop), item, prop)
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
