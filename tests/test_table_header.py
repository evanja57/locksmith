from itertools import combinations
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

import locksmith.resources_rc  # noqa: F401
from locksmith.ui.toolkit.tables.components import TableHeader
from locksmith.ui.vault.credentials.received.list import ReceivedCredentialsListPage


@pytest.mark.parametrize('width', [700, 900, 1280])
def test_received_header_keeps_title_search_and_actions_visible(qapp, width):
    window = QWidget()
    window.app = SimpleNamespace()
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    page = ReceivedCredentialsListPage(window)
    layout.addWidget(page)
    window.resize(width, 520)
    window.show()
    qapp.processEvents()

    header = page.table.header
    title = next(label for label in header.findChildren(QLabel) if label.text() == 'Received Credentials')
    import_button = next(button for button in header.findChildren(QPushButton) if button.text() == 'Import Grant…')
    controls = [title, header.search_input, import_button, header.add_button]
    rectangles = [QRect(widget.mapTo(header, QPoint()), widget.size()) for widget in controls]

    assert window.width() == width, 'The header must fit without expanding the page'
    assert title.width() >= title.sizeHint().width()
    for button in (import_button, header.add_button):
        assert button.width() >= button.minimumSizeHint().width()
    assert all(header.rect().contains(rectangle) for rectangle in rectangles)
    assert all(not first.intersects(second) for first, second in combinations(rectangles, 2))
    assert header.search_input.rect().contains(header.search_input.line_edit.geometry())


def test_received_toolbar_retains_search_actions_and_keyboard_order(qapp, monkeypatch):
    actions = []
    searches = []
    monkeypatch.setattr(ReceivedCredentialsListPage, '_on_accept_credential', lambda self: actions.append('Import'))
    window = QWidget()
    window.app = SimpleNamespace()
    window.start_credential_exchange = actions.append
    layout = QVBoxLayout(window)
    page = ReceivedCredentialsListPage(window)
    layout.addWidget(page)
    window.resize(900, 520)
    window.show()
    qapp.processEvents()
    header = page.table.header
    page.table.search_changed.connect(searches.append)
    import_button = next(button for button in header.findChildren(QPushButton) if button.text() == 'Import Grant…')

    header.search_input.line_edit.setFocus()
    QTest.keyClicks(header.search_input.line_edit, 'SEDI')
    assert searches[-1] == 'SEDI'
    QTest.keyClick(header.search_input.line_edit, Qt.Key.Key_Tab)
    assert qapp.focusWidget() is import_button
    QTest.keyClick(import_button, Qt.Key.Key_Space)
    QTest.keyClick(import_button, Qt.Key.Key_Tab)
    assert qapp.focusWidget() is header.add_button
    QTest.keyClick(header.add_button, Qt.Key.Key_Space)
    assert actions == ['Import', 'Apply']


def test_existing_single_row_header_keeps_filter_search_and_add(qapp):
    actions = []
    searches = []
    header = TableHeader(title='Identifiers', filter_func=lambda: actions.append('Filter'))
    header.add_clicked.connect(lambda: actions.append('Add'))
    header.search_changed.connect(searches.append)
    header.resize(1000, 85)
    header.show()
    qapp.processEvents()

    assert header.search_input.width() == 300
    header.filter_button.click()
    QTest.keyClicks(header.search_input.line_edit, 'Alice')
    header.add_button.click()
    assert actions == ['Filter', 'Add']
    assert searches[-1] == 'Alice'
