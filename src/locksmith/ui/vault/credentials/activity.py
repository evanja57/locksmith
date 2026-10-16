"""Credential exchanges, decisions, and retained delivery state for one vault."""
import json
from datetime import datetime
from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QScrollArea, QStackedWidget, QTabBar, QTextEdit,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from keri.help import helping
from keri import kering
from keri.core import SerderACDC
from keri.peer import exchanging

from locksmith.core import credentialing, ipexing
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.toolkit.tables.components import SkewersMenuButton
from locksmith.ui.toolkit.widgets import LocksmithButton, LocksmithDialog, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from locksmith.ui.vault.credentials.received.accept_grant import AcceptGrantDialog
from locksmith.ui.vault.credentials.issued.issue import IssueCredentialDialog
from locksmith.ui.vault.credentials.issued.view import ViewIssuedCredentialDialog
from locksmith.ui.vault.credentials.presentation import (
    attribute_view, credential_name, identifier_name, rules_text,
    credential_details, disclosed_credentials,
)
from locksmith.ui.vault.shared.base_list_page import BaseListPage
from locksmith.ui.vault.remotes.add import AddRemoteIdentifierDialog


def action_dot(parent=None):
    dot = QLabel(parent)
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(f'background: {colors.BLUE_ACCENT}; border: none; border-radius: 4px;')
    dot.setAccessibleName('Needs attention')
    dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return dot


class ActivityTable(PaginatedTableWidget):
    def _display_empty_state(self):
        super()._display_empty_state()
        self.table.hide()

    def _create_empty_state(self):
        label = QLabel('No credential exchanges yet.')
        label.setStyleSheet(f'color: {colors.TEXT_SECONDARY}; padding: 12px 0;')
        label.setFixedHeight(48)
        return label

    def _display_data(self, data):
        super()._display_data(data)
        action_column = self.columns.index('Actions')
        self.table.horizontalHeader().setSectionResizeMode(action_column, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(action_column, 260 if any(row['_actions'] for row in data) else 70)
        for index, row in enumerate(data):
            status = self.table.item(index, self.columns.index('Status'))
            outcome = ('Accepted' if row['Status'] == 'Admit' else 'Declined') if row['_finished'] else row['_outcome']
            status.setText('Expired\n' + outcome if row.get('expired') else outcome)
            status.setToolTip(row['_outcome'])
            if row['_actions']:
                actions, icons = self.row_actions_callback(row)
                cell = QWidget()
                layout = QHBoxLayout(cell)
                layout.setContentsMargins(8, 0, 8, 0)
                button = LocksmithInvertedButton(row['_review'])
                button.clicked.connect(lambda checked=False, r=row: self.row_action_triggered.emit(r, 'Review'))
                layout.addWidget(button)
                menu = SkewersMenuButton(actions=actions, action_icons=icons)
                menu.action_triggered.connect(lambda action, r=row: self.row_action_triggered.emit(r, action))
                layout.addWidget(menu)
                self.table.setCellWidget(index, action_column, cell)
            if row['_finished']:
                status.setForeground(QColor(colors.SUCCESS_TEXT if row['Status'] == 'Admit' else colors.TEXT_SECONDARY))
            if not row['_attention']:
                continue
            item = self.table.item(index, 0)
            item.setText('')
            item.setData(Qt.ItemDataRole.UserRole, row['Credential'])
            item.setData(Qt.ItemDataRole.AccessibleTextRole, row['Credential'] + ', needs attention')
            cell = QWidget()
            cell.setStyleSheet('background: transparent;')
            cell.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(5, 0, 5, 0)
            layout.setSpacing(8)
            name = QLabel(row['Credential'])
            name.setTextFormat(Qt.TextFormat.PlainText)
            name.setStyleSheet('font-weight: bold; letter-spacing: 0px;')
            layout.addWidget(name)
            layout.addWidget(action_dot())
            layout.addStretch()
            self.table.setCellWidget(index, 0, cell)


class ActivityTabs(QTabBar):
    """Keep each indicator eight pixels after its tab text."""

    def __init__(self):
        super().__init__()
        self.setExpanding(False)
        self.setDrawBase(False)
        self.dots = []
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(40)
        for title in ('Outgoing', 'Incoming'):
            index = self.addTab(title)
            slot = QWidget()
            slot.setFixedSize(16, 16)
            dot = action_dot(slot)
            dot.move(4, 4)
            self.setTabButton(index, QTabBar.ButtonPosition.RightSide, slot)
            self.dots.append(dot)


class CredentialActivityPage(BaseListPage):
    attention_changed = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.app = parent.app
        self.wallet_page = parent
        self.vault = None
        self._selected = None
        self._response_dialog = None
        self._rows = []
        self._credential_filter = None
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.tables, self.tabs, self.dots = [], [], []
        self.history_tables, self.history_headings, self.active_headings = [], [], []
        self._history_expanded = [None, None]
        self.scope_labels, self.clear_buttons = [], []
        for direction, counterparty in enumerate(('To', 'From')):
            table = ActivityTable(
                columns=['Credential', counterparty, 'Status', 'Updated', 'Actions'],
                column_widths={'Credential': 240, counterparty: 160, 'Updated': 180, 'Actions': 70},
                title='Credential Activity', icon_path=':/assets/material-icons/swap_horiz.svg',
                items_per_page=10, add_button_text='Refresh', row_actions=['View'],
                row_actions_callback=self._get_row_actions, parent=self)
            tabs = ActivityTabs()
            tabs.setStyleSheet(f'''QTabBar {{ background: transparent; }}
                QTabBar::tab {{ padding: 10px 16px; margin-right: 8px; font-size: 14px;
                    background: transparent; border: none; border-bottom: 2px solid transparent;
                    color: {colors.TEXT_SECONDARY}; }}
                QTabBar::tab:selected {{ border-bottom-color: {colors.PRIMARY}; color: {colors.TEXT_PRIMARY}; }}
                QTabBar::tab:hover {{ background: {colors.BACKGROUND_SELECTION}; }}''')
            tabs.setCurrentIndex(direction)
            tabs.currentChanged.connect(self._set_direction)
            table.header.layout().setContentsMargins(0, 0, 0, 16)
            table.header.add_button.setStyleSheet(f'''QPushButton {{ background: transparent;
                color: {colors.TEXT_PRIMARY}; border: 1px solid {colors.BORDER}; border-radius: 6px;
                padding: 8px 16px; }} QPushButton:hover {{ background: {colors.BACKGROUND_SELECTION}; }}''')
            table.layout().insertWidget(1, tabs, alignment=Qt.AlignmentFlag.AlignLeft)
            scope = QHBoxLayout()
            scope_label = QLabel()
            scope_label.setTextFormat(Qt.TextFormat.PlainText)
            clear = LocksmithInvertedButton('Show all exchanges')
            clear.clicked.connect(self._clear_credential_filter)
            scope.addWidget(scope_label)
            scope.addStretch()
            scope.addWidget(clear)
            table.layout().insertLayout(2, scope)
            heading = QLabel('In progress')
            heading.setStyleSheet('font-weight: bold; padding: 24px 0 8px;')
            table.layout().insertWidget(3, heading)
            history = ActivityTable(columns=table.columns, column_widths=table.column_widths,
                title='Exchange history', items_per_page=10, show_add_button=False,
                row_actions=['View'], row_actions_callback=self._get_row_actions, parent=self)
            history.header.hide()
            history.layout().setContentsMargins(0, 0, 0, 0)
            history_heading = QToolButton()
            history_heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            history_heading.setCheckable(True)
            history_heading.setStyleSheet(f'''QToolButton {{ font-weight: bold; padding: 16px 0 8px;
                border: none; background: transparent; color: {colors.TEXT_PRIMARY}; }}''')
            history_heading.toggled.connect(lambda expanded, i=direction: self._toggle_history(i, expanded))
            table.layout().insertWidget(table.layout().count() - 1, history_heading)
            table.layout().insertWidget(table.layout().count() - 1, history)
            table.search_changed.connect(history._on_search_changed)
            table.search_changed.connect(lambda _, i=direction: self._update_sections(i))
            for view in (table, history):
                view.table.verticalHeader().setDefaultSectionSize(66)
                view.row_clicked.connect(self._on_row_clicked)
                view.row_action_triggered.connect(self._on_row_action)
            table.add_clicked.connect(self.refresh)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setPalette(palette)
            scroll.viewport().setPalette(palette)
            table.setPalette(palette)
            scroll.setWidget(table)
            self.stack.addWidget(scroll)
            self.tables.append(table)
            self.history_tables.append(history)
            self.history_headings.append(history_heading)
            self.active_headings.append(heading)
            self.scope_labels.append(scope_label)
            self.clear_buttons.append(clear)
            self.tabs.append(tabs)
            self.dots.append(tabs.dots)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 12, 0, 0)
        body.setSpacing(16)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Exchange details')
        protocol = self.protocol = CollapsibleSection(title='Exchange details')
        protocol_layout = QVBoxLayout()
        protocol_layout.addWidget(self.details)
        protocol.set_content_layout(protocol_layout)
        body.addWidget(protocol)
        self.response_buttons = QHBoxLayout()
        self.messages_field = FloatingLabelComboBox(label_text='Message to send')
        self.messages = self.messages_field.combo_box
        self.messages.setAccessibleName('Message to send')
        body.addWidget(self.messages_field)
        self.retry_button = LocksmithButton('Retry sending')
        self.retry_button.clicked.connect(self._retry_selected)
        self.messages.currentIndexChanged.connect(self._update_retry)
        body.addWidget(self.retry_button)
        close = LocksmithInvertedButton('Close')
        self.view_credential_button = LocksmithInvertedButton('View credential')
        self.view_credential_button.clicked.connect(self._view_credential)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.view_credential_button)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addLayout(self.response_buttons)
        self._detail_dialog = LocksmithDialog(self, title='Credential exchange',
                                             content=content, buttons=buttons)
        self._detail_dialog.resize(560, 280)
        self.details.setMinimumHeight(230)
        protocol.update_content_height()
        self._detail_dialog.register_collapsible_section(protocol)
        close.clicked.connect(self._detail_dialog.close)
        self._show_details(None)

    @property
    def table(self):
        return self.tables[self.stack.currentIndex()]

    def _set_direction(self, index):
        self.stack.setCurrentIndex(index)
        for tabs in self.tabs:
            tabs.blockSignals(True)
            tabs.setCurrentIndex(index)
            tabs.blockSignals(False)

    def _clear_credential_filter(self):
        self._credential_filter = None
        self.refresh()

    def _update_sections(self, index):
        table, history = self.tables[index], self.history_tables[index]
        self.active_headings[index].setText(f'In progress ({table.total_items})')
        self.active_headings[index].setVisible(bool(table.total_items))
        heading = self.history_headings[index]
        expanded = self._history_expanded[index]
        if expanded is None:
            expanded = not table.total_items or bool(table.current_search or self._credential_filter)
        heading.setText(f'History ({history.total_items})')
        heading.setVisible(bool(history.total_items))
        heading.blockSignals(True)
        heading.setChecked(expanded)
        heading.blockSignals(False)
        heading.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        history.setVisible(bool(history.total_items) and expanded)
        table.empty_state.setText('No matching exchanges.' if table.current_search else
                                  'No exchanges for this credential.' if self._credential_filter else
                                  'No credential exchanges yet.')
        table.empty_state.setVisible(not table.total_items and not history.total_items)

    def _toggle_history(self, index, expanded):
        self._history_expanded[index] = expanded
        self._update_sections(index)

    def _view_credential(self):
        row = next((row for row in self._rows if row['_key'] == self._selected), None)
        if not row or not row['_inventory_said'] or not self._current_vault():
            return
        self._detail_dialog.close()
        self._credential_dialog = ViewIssuedCredentialDialog(
            icon_path=':/assets/material-icons/out-badge.svg', app=self.app,
            credential_said=row['_inventory_said'], parent=self.wallet_page,
            received=row['_inventory_received'])
        self._credential_dialog.open()

    def set_vault_name(self, vault_name):
        self._detail_dialog.close()
        if self._response_dialog is not None:
            self._response_dialog.close()
        if self.vault is not None:
            self.vault.signals.doer_event.disconnect(self._on_doer_event)
        self.vault = self.app.vault
        self._selected = None
        self._credential_filter = None
        self._rows = []
        self._history_expanded = [None, None]
        for table in self.tables + self.history_tables:
            table.current_page = 1
        if self.vault is not None:
            self.vault.signals.doer_event.connect(self._on_doer_event)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self.vault is not self.app.vault:
            self.set_vault_name('')
        else:
            self.refresh()

    def _on_doer_event(self, doer_name, event_type, data):
        if doer_name == 'Ipex':
            self.refresh()

    def _current_vault(self):
        return (self.vault is not None and self.vault is self.app.vault
                and not getattr(self.vault, 'closed', False) and self.vault.db.opened)

    def _name(self, pre):
        return identifier_name(self.vault, pre)

    def _credential(self, chain):
        for exn in reversed(chain):
            origins = exn.sad['a'].get('o', [])
            if not origins:
                continue
            for nest in exchanging.loadParsedNestedSubstreams(self.vault.hby, exn.said):
                if nest.serder.said != origins[0]:
                    continue
                schema = nest.serder.schema
                if isinstance(schema, Mapping):
                    return credential_name(schema), nest.serder.sad
                schemer = self.vault.hby.db.schema.get((schema,))
                return credential_name(schemer.sed) if schemer else origins[0], nest.serder.sad
        for exn in reversed(chain):
            schema = ipexing.request_schema(exn)
            schemer = self.vault.hby.db.schema.get((schema,)) if schema else None
            if schemer:
                return credential_name(schemer.sed), None
        return 'Credential request', None

    def refresh(self, *_):
        rows = [[], []]
        if self._current_vault():
            for exchange in ipexing.exchanges(self.vault):
                chain = exchange['messages']
                tip = chain[-1] if chain else None
                title, credential = self._credential(chain) if chain else ('Saved exchange', None)
                stamp = tip.sad['dt'] if tip else ''
                try:
                    date = helping.fromIso8601(stamp).astimezone()
                    updated, sort_date = date.strftime('%b %d, %Y %H:%M'), date.timestamp()
                except (ValueError, TypeError):
                    updated, sort_date = stamp or '—', 0
                for index, role in enumerate(('sender', 'recipient')):
                    pre = exchange[role]
                    if pre not in self.vault.hby.prefixes and not (index == 0 and not pre and not chain):
                        continue
                    actions = exchange['actions'] if tip and tip.sad['ri'] == pre else []
                    interrupted = [(keys, receipt) for keys, receipt in exchange['receipts']
                                   if keys[0] == pre and receipt.status != 'accepted']
                    if interrupted:
                        actions = ['Resume acceptance']
                    submission = exchange['submissions'].get(tip.said) if tip else None
                    blocked = bool(tip and tip.pre == pre and submission and submission.status in ('blocked', 'failed'))
                    finished = bool(tip and tip.route in ('/ipex/admit', '/ipex/spurn')
                                    and not interrupted and not exchange['problem']
                                    and (tip.pre != pre or submission and submission.status == 'submitted'))
                    origins = {said for exn in chain for said in exn.sad['a'].get('o', [])}
                    # A holder can send a credential from Received inventory.
                    received_first = bool(index) or (credential is not None and credential['i'] != pre)
                    inventory_said, inventory_received = next(
                        ((said, received) for received in (received_first, not received_first) for said in origins
                         if (self.vault.db.accepted if received else self.vault.db.issued).get((said,))),
                        (None, False))
                    row = dict(exchange, Credential=title, To=self._name(exchange['recipient']),
                               From=self._name(exchange['sender']), Status=tip.route.rsplit('/', 1)[-1].title() if tip else 'Unavailable',
                               Updated=updated, Updated_tooltip='Signed date of the latest IPEX stage: ' + stamp,
                               _credential=credential, _key=(exchange['root'], index), _vault=self.vault,
                               _actions=actions, _attention=bool(actions or blocked or exchange['problem']),
                               _interrupted=interrupted, _finished=finished, _origins=origins,
                               _inventory_said=inventory_said, _inventory_received=inventory_received,
                               _updated=sort_date)
                    row['_review'] = ('Resume acceptance' if interrupted else
                                      {'Apply': 'Review application', 'Offer': 'Review offer',
                                       'Agree': 'Send credential', 'Grant': 'Review credential'}.get(row['Status'], 'Review'))
                    row['_outcome'] = self._outcome(row)
                    if exchange.get('expired'):
                        row['Status'] = 'Expired'
                    rows[index].append(row)
        self._rows = rows[0] + rows[1]
        for index, table in enumerate(self.tables):
            ordered = sorted(rows[index], key=lambda row: row['_updated'], reverse=True)
            visible = [row for row in ordered if not self._credential_filter or self._credential_filter in row['_origins']]
            history = [row for row in visible if row['_finished']]
            active = [row for row in visible if not row['_finished']]
            table.set_static_data(active, reset_page=False)
            self.history_tables[index].set_static_data(history, reset_page=False)
            self._update_sections(index)
            self.scope_labels[index].setText('Exchanges for this credential' if self._credential_filter else '')
            self.scope_labels[index].setVisible(bool(self._credential_filter))
            self.clear_buttons[index].setVisible(bool(self._credential_filter))
        attention = [any(row['_attention'] for row in direction) for direction in rows]
        for dots in self.dots:
            for index, dot in enumerate(dots):
                dot.setVisible(attention[index])
        self.attention_changed.emit(any(attention))
        self._show_details(next((row for row in self._rows if row['_key'] == self._selected), None))

    def _outcome(self, row):
        if row.get('expired'):
            return 'Start a new application or offer.'
        if not row['messages']:
            return row['problem']
        tip = row['messages'][-1]
        local = tip.pre == row['sender' if row['_key'][1] == 0 else 'recipient']
        record = row['submissions'].get(tip.said)
        if row['_interrupted']:
            if any(receipt.status == 'preparing' for _, receipt in row['receipts']):
                return 'Waiting for witness receipts before accepting.'
            return 'Acceptance needs to be resumed.'
        if record and local and record.status != 'submitted':
            label = {'pending': 'Queued', 'sending': 'Sending', 'failed': 'Send failed',
                     'blocked': 'Sending blocked'}.get(record.status, record.status)
            if record.status == 'blocked' and record.missing_route:
                label = 'Delivery details needed'
            if record.status == 'failed' and record.attempts <= len(ipexing.SendIpexDoer.RetryDelays):
                label = 'Retrying at ' + datetime.fromtimestamp(record.retry_at).strftime('%H:%M:%S')
            return ('Accepted; acknowledgment: ' if tip.route == '/ipex/admit' else '') + label
        if tip.route == '/ipex/admit':
            if not local:
                return 'Accepted by recipient.'
            return ('Accepted; acknowledgment submitted.' if record else
                    'Accepted; acknowledgment saved. Choose Send acknowledgment to notify the sender.')
        if tip.route == '/ipex/spurn':
            return 'Declined by you.' if local else f'Declined by {self._name(tip.pre)}.'
        if local and not record:
            return 'Saved locally. Sending has not been authorized.'
        return 'Awaiting your decision.' if row['_actions'] else f'Waiting for {self._name(tip.sad["ri"])}.'

    def _get_row_actions(self, row):
        action = 'Review' if row['_actions'] else 'View exchange'
        actions = [action]
        if row['_inventory_said']:
            actions.append('View credential')
        return actions, {action: ':/assets/material-icons/view.svg',
                         'View credential': ':/assets/material-icons/in-badge.svg'}

    def _show_details(self, row):
        self._selected = row['_key'] if row else None
        while self.response_buttons.count():
            self.response_buttons.takeAt(0).widget().deleteLater()
        selected_message = self.messages.currentData()
        self.messages.blockSignals(True)
        self.messages.clear()
        if row:
            peer = f"To {row['To']}" if row['_key'][1] == 0 else f"From {row['From']}"
            self.summary.setText(f"{row['Credential']}\n{peer}\n{row['problem'] or self._outcome(row)}")
            lines = [row['Credential'], f"From: {row['From']}\nTo: {row['To']}", row['problem']]
            for exn in row['messages']:
                record = row['submissions'].get(exn.said)
                local = exn.pre == row['sender' if row['_key'][1] == 0 else 'recipient']
                delivery = record.status if record else ('Saved locally' if local else 'Received')
                stage = exn.route.rsplit('/', 1)[-1].title()
                lines.append(f"{stage} · {self._name(exn.pre)} · {delivery}\n{exn.sad['a'].get('m', '')}\n"
                             f"Message ID: {exn.said}\nSigned date: {exn.sad['dt']}")
                if record:
                    lines.append(f'Attempts: {record.attempts}\nError: {record.error or "None"}')
                    if exn is row['messages'][-1] and record.status == 'blocked':
                        self.summary.setText(self.summary.text() + '\nSending stopped: ' + record.error)
                if (local and not row.get('expired') and exn is row['messages'][-1]
                        and (record is None or record.status in ('pending', 'failed', 'blocked'))):
                    self.messages.addItem(f'{stage} · {delivery}', exn.said)
            if not row['messages']:
                for said, record in row['submissions'].items():
                    lines.append(f'Message ID: {said}\n{record.status}\n{record.error}')
            for keys, receipt in row['receipts']:
                lines.append(f'Acceptance: {receipt.status}\n{receipt.error}')
                if receipt.status != 'accepted':
                    self.summary.setText(self.summary.text() + '\nAcceptance incomplete. ' + receipt.error)
                if not receipt.send:
                    lines.append('Acknowledgment saved locally. Sending has not been authorized.')
            if row['_credential']:
                lines.append('Credential attributes:\n' + json.dumps(row['_credential'].get('a', {}), indent=2))
            for action in row['_actions']:
                button = LocksmithButton(action)
                button.clicked.connect(lambda checked=False, r=row, a=action: self._on_row_action(r, a))
                self.response_buttons.addWidget(button)
            if any(record.status == 'blocked' and record.missing_route
                   for record in row['submissions'].values()):
                repair = LocksmithInvertedButton('Import delivery details')
                repair.clicked.connect(self._repair_route)
                self.response_buttons.addWidget(repair)
            self.details.setPlainText('\n\n'.join(line for line in lines if line))
        else:
            self.summary.setText('Select an exchange to see its details.')
            self.details.setPlainText('Select an exchange to see its details.')
        index = self.messages.findData(selected_message)
        if index >= 0:
            self.messages.setCurrentIndex(index)
        self.messages.blockSignals(False)
        self.messages_field.setVisible(self.messages.count() > 1)
        self.retry_button.setVisible(self.messages.count() > 0)
        self.view_credential_button.setVisible(bool(row and row['_inventory_said']))
        self._update_retry()

    def _repair_route(self):
        self._repair_dialog = AddRemoteIdentifierDialog(self.app, self)
        self._repair_dialog.finished.connect(lambda _, vault=self.vault: self._return_from_repair(vault))
        self._detail_dialog.hide()
        self._repair_dialog.open()

    def _return_from_repair(self, vault):
        if self._current_vault() and self.vault is vault:
            self.refresh()
            self._detail_dialog.open()
            self._detail_dialog.fit_content(580)

    def _update_retry(self):
        said = self.messages.currentData()
        record = self.vault.db.outbox.get((said,)) if said and self._current_vault() else None
        exn = self.vault.hby.db.exns.get((said,)) if said and self._current_vault() else None
        self.retry_button.setText('Retry sending' if record else 'Send acknowledgment'
                                  if exn and exn.route == '/ipex/admit' else 'Send saved message')
        incomplete = any(receipt.status != 'accepted' and receipt.admit == said
                         for row in self._rows if row['_key'] == self._selected
                         for _, receipt in row['receipts'])
        self.retry_button.setEnabled(bool(said and self._current_vault() and not incomplete
                                          and (record is None or record.status in ('pending', 'failed', 'blocked'))))

    def _retry_selected(self):
        said = self.messages.currentData()
        if not self._current_vault() or not said:
            return
        try:
            record = self.vault.db.outbox.get((said,))
            if record and record.status in ('pending', 'failed', 'blocked'):
                ipexing.retry(self.vault, said)
            elif record is None:
                exn = self.vault.hby.db.exns.get((said,))
                hab = self.vault.hby.habByPre(exn.pre)
                if exn.route == '/ipex/admit':
                    ipexing.admit(self.vault, hab, exn.sad['p'], send=True)
                    if self.vault.db.receipts.get((hab.pre, exn.sad['p'])).status == 'accepted':
                        self.vault.signals.emit_doer_event('Ipex', 'accepted', {'said': said})
                else:
                    stream = exchanging.serializeMessage(self.vault.hby, said)
                    ipexing.submit(self.vault, hab, exn, stream[exn.size:])
            self.refresh()
        except Exception as error:
            self.summary.setText(f'Could not send the saved message: {error}')

    def _on_row_action(self, row, action):
        if row['_vault'] is not self.vault or not self._current_vault():
            return
        self._selected = row['_key']
        self.refresh()
        row = next((item for item in self._rows if item['_key'] == self._selected), None)
        if row is None:
            return
        # Reading clears notifications, not the exchange's outstanding decision.
        saids = {exn.said for exn in row['messages']}
        notifier = self.vault.notifier
        unread = [rid for (_, rid), note in notifier.noter.notes.getTopItemIter()
                  if not note.read and note.attrs.get('d') in saids]
        for rid in unread:
            notifier.mar(rid)
        if unread:
            self.vault.signals.emit_doer_event('MailboxListener', 'mark_as_read', {})
        if action == 'View credential':
            self._view_credential()
            return
        default_response = action in ('View', 'View exchange', 'Review') and row['Status'] == 'Apply'
        if action in ('View', 'View exchange', 'Review'):
            if not row['_actions']:
                self._detail_dialog.open()
                self._detail_dialog.fit_content(580)
                return
            action = row['_actions'][0]
        if action not in row['_actions']:
            return
        self._detail_dialog.close()
        if action in ('Admit', 'Resume acceptance'):
            said = row['_interrupted'][0][0][1] if row['_interrupted'] else row['messages'][-1].said
            self._response_dialog = AcceptGrantDialog(self.app, self, said, save=False)
        else:
            self._response_dialog = ExchangeResponseDialog(self, row, None if default_response else action)
        self._response_dialog.finished.connect(self.refresh)
        self._response_dialog.open()

    def show_exchange(self, said, *, received=None, open_dialog=True):
        self._credential_filter = None
        self.refresh()
        if self._current_vault() and (self.vault.db.issued.get((said,)) or self.vault.db.accepted.get((said,))):
            self._credential_filter = said
            self._set_direction(int(received) if received is not None else
                                0 if self.vault.db.issued.get((said,)) else 1)
            self._history_expanded[self.stack.currentIndex()] = True
            self.refresh()
            return
        for row in self._rows:
            if received is not None and row['_key'][1] != int(received):
                continue
            if said == row['root'] or any(exn.said == said or said in exn.sad['a'].get('o', []) for exn in row['messages']):
                self._set_direction(row['_key'][1])
                if open_dialog:
                    self._on_row_action(row, 'View')
                return


class ExchangeResponseDialog(LocksmithDialog):
    """Review the current exchange and choose its next response."""

    Labels = {'Offer': 'Send offer', 'Grant': 'Send credential',
              'Agree': 'Agree and request', 'Spurn': 'Decline'}
    Help = {'Offer': 'Sends the issuer, credential type, and terms now. Credential values are sent after agreement.',
            'Grant': 'Sends the credential values now. The recipient can review them before adding the credential.',
            'Agree': 'Credential values are not shared yet. Agree to request them, then review them before adding the credential.',
            'Spurn': 'This ends the exchange.'}

    def __init__(self, page, row, action):
        self._default_response = action is None
        action = action or row['_actions'][0]
        self.page, self.vault, self.row, self.action = page, page.vault, row, action
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        tip = row['messages'][-1]
        summary = QLabel(row['Credential'])
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setStyleSheet('font-size: 18px; font-weight: 600;')
        summary.setWordWrap(True)
        layout.addWidget(summary)
        peer = QLabel(f"From {page._name(tip.pre)}")
        peer.setTextFormat(Qt.TextFormat.PlainText)
        peer.setStyleSheet(f'color: {colors.TEXT_SECONDARY};')
        layout.addWidget(peer)
        self.response = FloatingLabelComboBox('Response')
        for verb in row['_actions']:
            if verb in self.Labels:
                self.response.addItem(self.Labels[verb], verb)
        self.response.setCurrentIndex(self.response.combo_box.findData(action))
        self.response.setVisible(self.response.count() > 2)
        layout.addWidget(self.response)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.offer_review = QWidget()
        QVBoxLayout(self.offer_review).setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.offer_review)
        self.anchor_notice = QLabel()
        self.anchor_notice.setWordWrap(True)
        self.anchor_notice.setStyleSheet(f'color: {colors.WARNING_TEXT};')
        layout.addWidget(self.anchor_notice)
        self.credential_field = FloatingLabelComboBox(label_text='Credential to disclose')
        self.credential = self.credential_field.combo_box
        self.credential.setAccessibleName('Credential to disclose')
        layout.addWidget(self.credential_field)
        self.create_button = LocksmithInvertedButton('Create another credential…')
        self.create_button.clicked.connect(self._create_credential)
        self.preview = QWidget()
        QVBoxLayout(self.preview).setContentsMargins(0, 0, 0, 0)
        self.preview.setAccessibleName('Credential details')
        self.credential_details = CollapsibleSection(title='Review credential details')
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.preview)
        preview_layout.addWidget(self.create_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.credential_details.set_content_layout(preview_layout)
        layout.addWidget(self.credential_details)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f'color: {colors.DANGER};')
        self.error.hide()
        layout.addWidget(self.error)
        history = CollapsibleSection(title='Exchange details')
        history_layout = QVBoxLayout()
        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(page.details.toPlainText())
        history_layout.addWidget(details)
        history.set_content_layout(history_layout)
        layout.addWidget(history)
        self.send_button = LocksmithButton(self.Labels[action])
        cancel = LocksmithInvertedButton('Close')
        cancel.setVisible(self.response.count() != 2)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        buttons.addWidget(cancel)
        decline = self.decline_button = LocksmithInvertedButton('Decline')
        decline.setVisible(self.response.count() == 2 and 'Spurn' in row['_actions'] and action != 'Spurn')
        decline.clicked.connect(self._decline)
        buttons.addWidget(decline)
        buttons.addWidget(self.send_button)
        title = {'Apply': 'Review application', 'Offer': 'Review offer', 'Agree': 'Send credential'}.get(
            row['Status'], 'Credential exchange')
        super().__init__(page, title=title, content=content, buttons=buttons,
                         show_title_divider=False)
        self.register_collapsible_section(history)
        self.register_collapsible_section(self.credential_details)
        cancel.clicked.connect(self.close)
        self.send_button.clicked.connect(self._send)
        self.credential_field.currentIndexChanged.connect(self._credential_changed)
        self.response.currentIndexChanged.connect(self._select_response)
        self.response.combo_box.activated.connect(self._keep_response_choice)
        self._select_response()
        self._choose_default_response()

    def _keep_response_choice(self, *_):
        self._default_response = False

    def _credential_changed(self, *_):
        self._choose_default_response()
        self._preview()

    def _choose_default_response(self):
        """Prefer direct delivery of an issuer's exact response to its applicant."""
        tip = self.row['messages'][-1]
        if not self._default_response or tip.route != '/ipex/apply':
            return
        action = 'Offer'
        said = self.credential.currentData()
        sad = self._credentials.get(said, {})
        attrs = sad.get('a')
        if (said and not sad.get('r') and self.vault.db.issued.get((said,)) and sad.get('i') == tip.sad['ri']
                and isinstance(attrs, Mapping) and attrs.get('i') == tip.pre
                and ipexing.request_schema(tip) and 'Grant' in self.row['_actions']):
            try:
                _, artifacts, plan = ipexing._credential_evidence(self.vault, said)
                requested = tip.sad['q']['dp']
                plan[0][0][2] = requested[0][0][2]
                if plan == requested and not artifacts:
                    action = 'Grant'
            except Exception:
                pass  # The disclosure preview reports unavailable evidence.
        self.response.setCurrentIndex(self.response.combo_box.findData(action))

    def _decline(self):
        self.response.setCurrentIndex(self.response.combo_box.findData('Spurn'))
        self._send()

    def _select_response(self, *_):
        self.action = self.response.currentData()
        self.send_button.setText(self.Labels[self.action])
        self.explanation.setText(self.Help[self.action])
        self.error.clear()
        self.error.hide()
        disclose = self.action in ('Offer', 'Grant')
        self.credential_field.setVisible(disclose)
        tip = self.row['messages'][-1]
        anchored = self.action in ('Agree', 'Grant') and tip.sad['a'].get('ax', [False])[0]
        hab = self.vault.hby.habByPre(tip.sad['ri'])
        self._anchor_error = ipexing.anchor_error(hab) if anchored else None
        self.anchor_notice.setText(self._anchor_error or (
            'This rotates your keys and adds a permanent commitment to your key event log.'
            if hab.kever.estOnly else 'This adds a permanent commitment to your key event log.'))
        self.anchor_notice.setVisible(anchored)
        request = self.vault.hby.db.exns.get((tip.sad['p'],)) if tip.route == '/ipex/agree' else tip
        requested = ipexing.request_schema(request)
        self._can_create = disclose and tip.route == '/ipex/apply' and requested is not None
        self._credentials = {}
        selected = self.credential.currentData()
        self.credential_field.blockSignals(True)
        self.credential.clear()
        if disclose:
            for view in credentialing.credentials(self.vault):
                if view['status']['et'] not in ('issued', 'authenticated'):
                    continue
                try:
                    ipexing._require_presenter(SerderACDC(sad=view['sad']), tip.sad['ri'], tip.pre)
                except kering.ValidationError:
                    continue
                if requested and view['schema'].get('$id') != requested:
                    continue
                said = view['sad']['d']
                self._credentials[said] = view['sad']
                self.credential.addItem(f"{credential_name(view['schema'])} · {self.page._name(view['recipient'])} · {said[:8]}…", said)
            offered = next((exn.sad['a']['o'][0] for exn in reversed(self.row['messages']) if exn.sad['a'].get('o')), None)
            offer = next((exn for exn in reversed(self.row['messages']) if exn.route == '/ipex/offer'), None)
            previews = exchanging.loadParsedNestedSubstreams(self.vault.hby, offer.said) if offer else []
            if previews and previews[0].serder.sad.get('u') == '':
                offered = None  # A metadata SAID is not an inventory credential identifier.
            if offered or selected:
                self.credential.setCurrentIndex(self.credential.findData(offered or selected))
            else:
                matches = [said for said, sad in self._credentials.items()
                           if (SerderACDC(sad=sad).iseaid == tip.pre or
                               SerderACDC(sad=sad).iseaid == tip.sad['ri'])]
                self.credential.setCurrentIndex(self.credential.findData(matches[0]) if len(matches) == 1 else -1)
            self.credential.setEnabled(not (offered and self.action == 'Grant'))
            self.credential_field.setVisible(not (offered and self.action == 'Grant'))
        self.credential_field.blockSignals(False)
        if self._can_create and not self._credentials:
            self.credential_field.hide()
        self.create_button.setVisible(self._can_create and bool(self._credentials))
        self._preview()

    def _create_credential(self):
        if not self.page._current_vault() or self.page.vault is not self.vault:
            self.error.setText('This vault is closed.')
            self.error.show()
            return
        tip = self.row['messages'][-1]
        if ipexing.expiry_error(self.vault, tip):
            self._preview()
            return
        schema = ipexing.request_schema(tip)
        if self.vault.db.issuers.get((schema,)) != tip.sad['ri']:
            self.error.setText('Enable issuance for this schema with the identifier that received the request first.')
            self.error.show()
            return
        self._issue_dialog = IssueCredentialDialog(self.page.app, self.page, request_said=tip.said)
        self._issue_dialog.credential_created.connect(self._use_created_credential)
        self._issue_dialog.finished.connect(self._return_from_issuance)
        self.hide()
        self._issue_dialog.open()

    def _use_created_credential(self, said):
        self._select_response()
        self.credential.setCurrentIndex(self.credential.findData(said))
        self._choose_default_response()

    def _return_from_issuance(self, *_):
        if self.page._current_vault() and self.page.vault is self.vault:
            self.open()
            self.fit_content(580)

    def _preview(self, *_):
        expired = ipexing.expiry_error(self.vault, self.row['messages'][-1])
        disclose = self.action in ('Offer', 'Grant')
        self._needs_creation = self._can_create and self.credential.currentIndex() < 0
        self.send_button.setText('Create credential' if self._needs_creation else self.Labels[self.action])
        self.explanation.setText(
            'Create a credential for this application, then review and send it.'
            if self._needs_creation else self.Help[self.action])
        disclosure_error = self._show_credential(self._credentials.get(self.credential.currentData()) if disclose else None)
        offer_error = self._show_offer()
        self.credential_details.setVisible(disclose and (
            self.preview.layout().count() > 0 or self._can_create and bool(self._credentials)))
        self.credential_details.update_content_height()
        self.send_button.setEnabled(not expired and not offer_error and not disclosure_error and not self._anchor_error and (
            self._needs_creation or not disclose or self.credential.currentIndex() >= 0))
        self.create_button.setEnabled(not expired)
        self.decline_button.setEnabled(not expired)
        self.response.setEnabled(not expired)
        if expired:
            self.error.setText(expired)
        elif offer_error:
            self.error.setText(offer_error)
        elif disclosure_error:
            self.error.setText(disclosure_error)
        elif disclose and self.credential.currentIndex() < 0 and not self._needs_creation:
            self.error.setText('No authenticated credential is available for this request.')
        else:
            self.error.clear()
        self.error.setVisible(bool(self.error.text()))
        self.fit_content(580)

    def _show_offer(self):
        layout = self.offer_review.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        self.offer_review.setVisible(self.action == 'Agree')
        if self.action != 'Agree':
            return
        offer = self.row['messages'][-1]
        previews = exchanging.loadParsedNestedSubstreams(self.vault.hby, offer.said)
        if not previews:
            layout.addWidget(attribute_view('Offer details',
                'This offer contains a reference only. Its issuer and rules have not been disclosed.'))
            return
        for index, nest in enumerate(previews):
            sad = nest.serder.sad
            if index:
                schema = sad['s']
                schemer = self.vault.hby.db.schema.get((schema,)) if isinstance(schema, str) else None
                name = credential_name(schemer.sed if schemer else schema if isinstance(schema, Mapping) else {})
                layout.addWidget(attribute_view('Linked credential', name))
            layout.addWidget(attribute_view('Declared issuer', self.page._name(sad.get('i'))))
            layout.addWidget(attribute_view('Terms', rules_text(sad['r']) if sad.get('r') else 'No rules attached.'))
        note = QLabel('Agreeing signs a response to this offer. The credential is checked when it arrives; '
                      'adding it to your wallet is a separate step. Linked credential values and terms '
                      'are shown before you accept the Grant.')
        note.setWordWrap(True)
        note.setStyleSheet(f'color: {colors.TEXT_SECONDARY};')
        layout.addWidget(note)

    def _show_credential(self, sad):
        layout = self.preview.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        if not sad:
            return
        try:
            nodes = disclosed_credentials(self.vault, sad['d'])
        except Exception as error:
            self.credential_details.toggle_button.setText('  Credential options')
            return f'Cannot prepare disclosure: {error}'
        self.credential_details.toggle_button.setText('  Review data and terms to share')
        if len(nodes) > 1:
            count = len(nodes) - 1
            timing = ('Only credential types and link paths are shared now. Their values and terms arrive with the Grant.'
                      if self.action == 'Offer' else 'Their disclosed data and terms are shared with this message.')
            self.explanation.setText(self.explanation.text() +
                f' This includes {count} linked {"credential" if count == 1 else "credentials"}. {timing}')
        for node in nodes:
            layout.addWidget(credential_details(self.vault, node))

    def _send(self):
        if self.page.app.vault is not self.vault or not self.page._current_vault():
            self.error.setText('This vault is closed.')
            self.error.show()
            return
        if ipexing.expiry_error(self.vault, self.row['messages'][-1]):
            self._preview()
            self.page.refresh()
            return
        if self._needs_creation:
            self._create_credential()
            return
        self.send_button.setEnabled(False)
        try:
            ipexing.respond(self.vault, self.row['messages'][-1].said, self.action,
                            credential_said=self.credential.currentData())
            self.accept()
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            self.page.refresh()
            self.send_button.setEnabled(bool(ipexing.responses(self.vault, self.row['messages'][-1])))
            self.fit_content(580)
