from contextlib import ExitStack
from pathlib import Path
import json
import sys
from types import MethodType, SimpleNamespace
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QCheckBox, QFileDialog, QLabel, QWidget
from hio.base import doing
from keri import kering
from keri.acdc import Registrar, Regery, acdcmap, ipexing as native_ipexing
from keri.app import habbing, notifying, organizing
from keri.core import Noncer, messagize, parsing, scheming, SerderACDC, SerderKERI
from keri.peer import exchanging

from locksmith.core import ipexing
from locksmith.core.credentialing import IssueCredentialDoer
from locksmith.core.signals import DoerSignalBridge
from locksmith.db.basing import GrantReceipt, IpexSubmission, IssuedCredential, LocksmithBaser
from locksmith.ui.vault.credentials.activity import CredentialActivityPage
from locksmith.ui.vault.credentials.issued.grant import GrantCredentialDialog
from locksmith.ui.vault.credentials.issued.issue import IssueCredentialDialog
from locksmith.ui.vault.credentials.issued.list import IssuedCredentialsListPage
from locksmith.ui.vault.credentials.issued.view import ViewIssuedCredentialDialog
from locksmith.ui.vault.credentials.received.accept import AcceptCredentialDialog
from locksmith.ui.vault.credentials.received.accept_grant import AcceptGrantDialog
from locksmith.ui.vault.credentials.received.delete import DeleteReceivedCredentialDialog
from locksmith.ui.vault.credentials.received.list import ReceivedCredentialsListPage
from locksmith.ui.vault.credentials.schema.add import AddSchemaDialog
from locksmith.ui.vault.credentials.schema.list import SchemaListPage
from locksmith.ui.vault.notifications.list import NotificationsListPage
from locksmith.ui.vault.page import VaultPage
from locksmith.ui.vault.remotes.add import AddRemoteIdentifierDialog
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit


def test_table_row_actions_support_keyboard_navigation(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from locksmith.ui.toolkit.tables import PaginatedTableWidget

    table = PaginatedTableWidget(columns=['Credential', 'Actions'], row_actions=['Grant'])
    row = {'Credential': 'SEDI IAR'}
    table.set_static_data([row])
    selected = []
    table.row_action_triggered.connect(lambda data, action: selected.append((data, action)))
    table.show()
    table.table.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(table.table, Qt.Key.Key_Tab)
        button = qapp.focusWidget()
        assert button.accessibleName() == 'Row actions'
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert button.menu.isVisible()
        QTest.keyClick(button.menu, Qt.Key.Key_Down)
        QTest.keyClick(button.menu, Qt.Key.Key_Return)
        assert selected == [(row, 'Grant')]
    finally:
        table.close()


def test_dialog_refits_wrapped_text_after_scrolling(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QStyleFactory
    from locksmith.ui.toolkit.widgets.dialogs import LocksmithDialog

    line = 'A line that fits the full viewport.'
    text = '\n'.join([line] * 3)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet('font-size: 16px;')
    dialog = LocksmithDialog(content=label, show_close_button=False, show_title_divider=False)
    style = QStyleFactory.create('Windows')
    style.setParent(dialog)
    dialog.scroll_area.setStyle(style)
    dialog.scroll_area.verticalScrollBar().setStyle(style)
    label.ensurePolished()
    margins = dialog.content_layout.contentsMargins()
    width = label.fontMetrics().horizontalAdvance(line) + margins.left() + margins.right() + 1
    long_text = '\n'.join([text] * 100)
    dialog.open()
    label.setText(long_text)
    dialog.setFixedSize(width, label.fontMetrics().height())
    qapp.processEvents()
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0

    # Each line fits at full width but wraps when the old scrollbar consumes space.
    label.setText(text)
    dialog.fit_content(width)
    qapp.processEvents()
    assert dialog.scroll_area.verticalScrollBar().maximum() == 0
    assert dialog.scroll_area.viewport().width() == dialog.scroll_area.maximumViewportSize().width()

    label.setText(long_text)
    dialog.fit_content(width)
    qapp.processEvents()
    assert dialog.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    dialog.close()


@pytest.fixture
def wallet(qapp, mailbox_routes):
    with ExitStack() as contexts:
        def create(name):
            hby = contexts.enter_context(habbing.openHby(name=name, temp=True, version=kering.Vrsn_2_0))
            mailbox_routes(hby)
            rgy = Regery(hby=hby, name=name, temp=True)
            contexts.callback(rgy.close)
            db = LocksmithBaser(name=name, temp=True)
            contexts.callback(db.close)
            notifier = notifying.Notifier(hby=hby, noter=notifying.Noter(name=name, temp=True))
            contexts.callback(notifier.noter.close)
            signals = DoerSignalBridge()
            exc = exchanging.Exchanger(hby=hby, handlers=[])
            hby.kvy.exc = exc
            for verb in ('apply', 'offer', 'agree', 'grant', 'admit', 'spurn'):
                exc.addHandler(ipexing.IpexHandler(f'/ipex/{verb}', hby, notifier, rgy, signals=signals))
            queued = []
            vault = SimpleNamespace(hby=hby, rgy=rgy, db=db, org=organizing.Organizer(hby=hby),
                                    exc=exc, signals=signals, notifier=notifier, extend=queued.extend, doers=queued, kvy=hby.kvy)
            vault.mbx = SimpleNamespace(parser=parsing.Parser(kvy=hby.kvy, exc=exc, version=kering.Vrsn_2_0))
            app = SimpleNamespace(hby=hby, vault=vault, queued=queued)
            return app
        yield create
        for widget in list(qapp.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        qapp.processEvents()


def schema(require_issuee=True, *, composed=False):
    fields = {key: {'type': 'string'} for key in ('v', 't', 'd', 'i', 'rd', 's')}
    fields['a'] = {'type': 'object', 'properties': {
        'd': {'type': 'string'}, 'i': {'type': 'string'}, 'dt': {'type': 'string'},
        'nickname': {'type': 'string', 'description': 'Nickname'},
    }, 'required': ['d', 'i', 'dt', 'nickname'], 'additionalProperties': False}
    if not require_issuee:
        fields['a']['required'].remove('i')
    required = list(fields)
    if composed:
        fields['u'] = {'type': 'string'}
        fields['a'] = {'oneOf': [{'type': 'string'}, fields['a']]}
    return scheming.Schemer(sed={
        '$id': '', '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'version': '1.0.0',
        'title': 'Native Credential', 'type': 'object', 'properties': fields,
        'required': required, 'additionalProperties': False,
    })


def issue(app, hab, recipient, authentication='registry', rules=None):
    schemer = schema(require_issuee=recipient is not None, composed=True)
    if authentication != 'registry':
        sad = schemer.sed
        sad['$id'] = ''
        sad['properties'].pop('rd')
        sad['required'].remove('rd')
        schemer = scheming.Schemer(sed=sad)
    if rules is not None:
        sad = schemer.sed
        sad['$id'] = ''
        sad['properties']['r'] = {'type': ['object', 'string']}
        schemer = scheming.Schemer(sed=sad)
    app.hby.db.schema.pin(keys=(schemer.said,), val=schemer)
    app.vault.db.issuers.pin(keys=(schemer.said,), val=hab.pre)
    if authentication != 'registry':
        before = {said for (said,), _ in app.vault.db.issued.getTopItemIter()}
        doer = IssueCredentialDoer(app, schemer.said, recipient, {'nickname': 'Alice'},
                                  authentication=authentication, rules=rules)
        doing.Doist(doers=[doer], limit=1.0, tock=0.03125).do()
        record, = [record for (said,), record in app.vault.db.issued.getTopItemIter() if said not in before]
        acdc = SerderACDC(raw=record.raw.encode())
        return acdc, record.stream.encode(), schemer
    registrar = Registrar(rgy=app.vault.rgy)
    reg = registrar.makeRegistry(name=f'credential-{len(app.vault.rgy.regs)}', prefix=hab.pre)
    def anchor(event):
        hab.interact(data=[{'i': reg.regk, 's': event.sad['n'], 'd': event.said}], gvrsn=kering.Vrsn_2_0)
        assert reg.anchorMsg(event.said)
    anchor(app.vault.rgy.store.event(reg.regk))
    acdc = acdcmap(israid=hab.pre, regid=reg.regk, schema=schemer.said,
                   attribute={'d': '', 'dt': '2026-09-09T00:00:00Z', 'nickname': 'Alice'}, iseaid=recipient,
                   rule=rules)
    schemer.verify(raw=acdc.raw)
    blinder, update = registrar.issue(reg, acdc)
    anchor(update)
    app.vault.db.issued.pin(keys=(acdc.said,), val=IssuedCredential(acdc.raw.decode(), blinder.qb64, update.said))
    proof = messagize(serder=acdc, bonds=[blinder.data], framed=False, gvrsn=kering.Vrsn_2_0)
    return acdc, proof, schemer


@pytest.mark.parametrize('kind', ['contact', 'schema'])
def test_file_selection_returns_before_choice_and_closes_with_owner(wallet, tmp_path, kind):
    app = wallet(f'{kind}-picker')
    if kind == 'contact':
        hab = app.hby.makeHab(name='contact')
        source = tmp_path / 'contact.cesr'
        source.write_bytes(hab.msgOwnInception())
        dialog = AddRemoteIdentifierDialog(app)
        field, expected = dialog.prefix_field, hab.pre
    else:
        schemer = schema()
        source = tmp_path / 'schema.json'
        source.write_bytes(schemer.raw)
        dialog = AddSchemaDialog(app)
        field, expected = dialog.said_field, schemer.said
    dialog.file_radio.setChecked(True)
    dialog.show()

    # Close a blocking picker so a regression fails instead of hanging the suite.
    timed_out = []
    def cancel_blocking_picker():
        timed_out.append(True)
        for picker in dialog.findChildren(QFileDialog):
            picker.reject()
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(cancel_blocking_picker)
    watchdog.start(1000)
    try:
        dialog.browse_button.click()
    finally:
        watchdog.stop()
    assert not timed_out, 'Browse waited for a file choice before returning'
    picker, = dialog.findChildren(QFileDialog)
    assert picker.isVisible()
    picker.selectFile(str(source))
    picker.accept()
    assert Path(dialog.file_path_field.text()) == source
    assert field.text() == expected

    dialog.browse_button.click()
    picker.reject()
    assert Path(dialog.file_path_field.text()) == source
    assert field.text() == expected
    dialog.browse_button.click()
    assert picker.isVisible()
    dialog.close()
    assert not picker.isVisible()
    assert field.text() == expected
    assert app.queued == []


def test_schema_selection_does_not_create_registry_or_request_witness_auth(wallet, tmp_path):
    app = wallet('schema-ui')
    hab = app.hby.makeHab(name='issuer')
    schemer = schema()
    source = tmp_path / 'native.json'
    source.write_bytes(schemer.raw)
    dialog = AddSchemaDialog(app=app)
    dialog.file_radio.setChecked(True)
    dialog.file_path_field.setText(str(source))
    assert not dialog.said_field.text()
    dialog.enable_issuance_checkbox.setChecked(True)
    dialog.issuer_dropdown.setCurrentIndex(1)
    dialog._on_load()
    assert len(app.queued) == 1
    assert dialog.load_button.text() == 'Loading...'
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    assert app.vault.db.issuers.get(keys=(schemer.said,)) == hab.pre
    assert app.vault.rgy.regs == {}
    assert app.hby.db.schema.get(keys=(schemer.said,)).said == schemer.said


@pytest.mark.parametrize('nonces', [False, True])
@pytest.mark.parametrize('attribute_union', [False, True])
def test_issue_form_uses_selected_issuer_and_attribute_schema(wallet, qapp, nonces, attribute_union):
    app = wallet('issue-ui')
    issuer = app.hby.makeHab(name='issuer')
    recipient = app.hby.makeHab(name='recipient')
    sad = schema().sed
    sad['$id'] = ''
    if nonces:
        sad['properties']['u'] = {'type': 'string'}
        sad['required'].append('u')
        sad['properties']['a']['properties']['u'] = {'type': 'string'}
        sad['properties']['a']['required'].append('u')
    if attribute_union:
        sad['properties']['a'] = {'oneOf': [{'type': 'string'}, sad['properties']['a']]}
    schemer = scheming.Schemer(sed=sad)
    app.hby.db.schema.pin(keys=(schemer.said,), val=schemer)
    app.vault.db.issuers.pin(keys=(schemer.said,), val=issuer.pre)
    dialog = IssueCredentialDialog(app=app)
    assert dialog.schema_dropdown.count() == 2
    dialog.schema_dropdown.setCurrentIndex(1)
    assert app.queued == []
    assert app.vault.rgy.regs == {}
    dialog.local_radio.setChecked(True)
    recipient_index = next(index for index in range(dialog.recipient_dropdown.count())
                           if dialog.recipient_dropdown.itemData(index) == recipient.pre)
    dialog.recipient_dropdown.setCurrentIndex(recipient_index)
    dialog._dynamic_field_widgets['nickname']['widget'].setText('Alice')
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    dialog._on_issue()
    assert len(app.queued) == 1
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    assert events[-1][0] == 'credential_issued', events
    ((_,), record), = app.vault.db.issued.getTopItemIter()
    acdc = SerderACDC(raw=record.raw.encode())
    assert acdc.pvrsn == kering.Vrsn_2_0
    assert acdc.sad['i'] == issuer.pre
    assert acdc.iseaid == recipient.pre
    assert schemer.verify(raw=acdc.raw)

    if nonces:
        assert Noncer(qb64=acdc.sad['u']).qb64 == acdc.sad['u']
        assert Noncer(qb64=acdc.sad['a']['u']).qb64 == acdc.sad['a']['u']
        assert acdc.sad['u'] != acdc.sad['a']['u']
    else:
        assert 'u' not in acdc.sad
        assert 'u' not in acdc.sad['a']

    details = ViewIssuedCredentialDialog('', app, acdc.said)
    details.show()
    qapp.processEvents()
    labels = {label.text() for label in details.findChildren(QLabel) if label.isVisibleTo(details)}
    assert acdc.sad['a']['nickname'] in labels
    if nonces:
        assert acdc.sad['a']['u'] not in labels
    assert json.loads(details.content_field.toPlainText()) == acdc.sad



@pytest.mark.parametrize('filename', ['age'])
def test_issue_form_issues_aggregate_blocks_with_selected_subject(wallet, qapp, filename):
    from pathlib import Path
    from locksmith.core import credentialing

    app = wallet('aggregate-issue')
    issuer, recipient = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='recipient')
    source_acdc, _, _ = issue(app, issuer, issuer.pre)
    source = source_acdc.said
    schemer = scheming.Schemer(raw=(Path(__file__).parents[1] /
                                   f'assets/schemas/sedi/{filename}.json').read_bytes())
    app.hby.db.schema.pin((schemer.said,), schemer)
    app.vault.db.issuers.pin((schemer.said,), issuer.pre)
    dialog = IssueCredentialDialog(app)
    dialog.schema_dropdown.setCurrentIndex(dialog.schema_dropdown.combo_box.findData(schemer.said))
    dialog.local_radio.setChecked(True)
    dialog.recipient_dropdown.setCurrentIndex(dialog.recipient_dropdown.combo_box.findData(recipient.pre))
    assert dialog._aggregate
    subject = dialog._dynamic_field_widgets['0']['widget']
    assert 'i' not in subject.fields
    assert subject.generated['i'] == recipient.pre
    claims = {'over18': True, 'over21': False}
    for info in dialog._dynamic_field_widgets.values():
        for name, (widget, _) in info['widget'].fields.items():
            if name in claims:
                widget.setChecked(claims[name])
    edges, _ = dialog._edge_widget
    core = edges.fields['coreIdentity'][0]
    selector = core.fields['n'][0]
    selector.setCurrentIndex(selector.combo_box.findData(source))
    core.fields['o'][0].input_widget.set_items(['I2I'])
    errors = []
    dialog.show_error = errors.append
    assert dialog._validate_fields(), errors
    blocks = dialog._extract_credential_attributes()
    assert blocks[0]['i'] == recipient.pre
    for name, value in claims.items():
        assert next(block for block in blocks if name in block)[name] is value
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    dialog._on_issue()
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    assert events[-1][0] == 'credential_issued', events
    view = credentialing.credential(app.vault, events[-1][1]['credential_said'])
    acdc = SerderACDC(raw=view['proof'])
    assert acdc.iseaid == recipient.pre
    assert schemer.verify(raw=acdc.raw)
    assert len(acdc.sad['A']) == len(blocks) + 1
    assert len({block['u'] for block in acdc.sad['A'][1:]}) == len(blocks)
    assert acdc.sad['e']['coreIdentity']['n'] == source
    assert acdc.sad['r']['l'] == ''
    assert view['status']['et'] == 'issued'

    def assert_claims(view):
        for name, value in claims.items():
            labels = [label for label in view.findChildren(QLabel)
                      if label.text() == name and label.isVisibleTo(view)]
            assert len(labels) == 1, f'Expected one visible {name} field'
            texts = {label.text() for label in labels[0].parentWidget().findChildren(QLabel)
                     if label.isVisibleTo(view)}
            assert texts == {name, 'Yes' if value else 'No'}, f'Wrong value displayed for {name}'

    details = ViewIssuedCredentialDialog('', app, acdc.said)
    details.show()
    qapp.processEvents()
    assert details.recipient_field.text() == recipient.name
    assert_claims(details)

    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, recipient.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    review = AcceptGrantDialog(app, QWidget(), grant.said)
    review.show()
    qapp.processEvents()
    labels = {label.text() for label in review.findChildren(QLabel) if label.isVisibleTo(review)}
    assert any(f'Credential subject: {recipient.name}' in label for label in labels)
    assert_claims(review)
    ipexing.admit(app.vault, recipient, grant.said)
    received = ViewIssuedCredentialDialog('', app, acdc.said, received=True)
    received.show()
    qapp.processEvents()
    assert received.recipient_field.text() == recipient.name
    assert_claims(received)
    assert credentialing.credential(app.vault, acdc.said, received=True)['held']


def test_issuance_respects_schema_constants_and_selected_subject(wallet):
    from locksmith.core import credentialing

    app = wallet('constant-issue')
    issuer, recipient = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='recipient')
    sad = schema().sed
    sad['$id'] = ''
    sad['properties']['a']['properties']['dt']['const'] = '2026-01-01T00:00:00Z'
    sad['properties']['a']['properties']['i']['const'] = recipient.pre
    schemer = scheming.Schemer(sed=sad)
    app.hby.db.schema.pin((schemer.said,), schemer)
    app.vault.db.issuers.pin((schemer.said,), issuer.pre)
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((event, data)))
    for target in (recipient, issuer):
        doer = IssueCredentialDoer(app, schemer.said, target.pre, {'nickname': 'Demo'})
        doing.Doist(doers=[doer], limit=1.0, tock=0.03125).do()
    assert [event for event, _ in events] == ['credential_issued', 'credential_issuance_failed']
    view, = credentialing.credentials(app.vault, received=False)
    assert view['sad']['a']['dt'] == '2026-01-01T00:00:00Z'
    assert view['sad']['a']['i'] == recipient.pre
    assert 'selected recipient' in events[-1][1]['error'] or 'constant' in events[-1][1]['error']


def test_issue_form_preserves_structured_attributes_and_schema_nonce(wallet, monkeypatch):
    app = wallet('structured-issue')
    issuer, recipient = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='recipient')
    sad = schema().sed
    sad['$id'] = ''
    sad['properties'].pop('rd')
    sad['required'].remove('rd')
    attributes = sad['properties']['a']
    attributes['properties'].pop('dt')
    attributes['required'].remove('dt')
    attributes['properties'].update({
        'suffix': {'type': 'string'},
        'birthDate': {'type': 'string', 'description': 'Date of birth RFC-3339/ISO-8601 time MBZ'},
        'facialImageProof': {'type': 'string', 'description': 'Image typed media block SAID'},
        'proofingDatetime': {'type': 'string', 'description': 'Proofing session datetime RFC-3339/ISO-8601'},
        'residence': {'type': 'object', 'properties': {
            'city': {'type': 'string', 'minLength': 1, 'pattern': '^Provo$'}},
                      'required': ['city'], 'additionalProperties': False},
        'attestation': {'type': 'object', 'properties': {
            'approved': {'type': 'boolean', 'const': True},
            'region': {'type': 'string', 'const': 'Utah'}}, 'required': ['approved', 'region']},
    })
    attributes['required'].extend(['suffix', 'residence', 'birthDate', 'facialImageProof', 'proofingDatetime'])
    nonce = Noncer().qb64
    sad['properties']['u'] = {'type': 'string', 'const': nonce}
    sad['properties']['r'] = {'oneOf': [{'type': 'string'}, {'type': 'object',
        'properties': {'d': {'type': 'string'}, 'l': {'type': 'string'}}, 'required': ['d', 'l']}]}
    schemer = scheming.Schemer(sed=sad)
    app.hby.db.schema.pin(keys=(schemer.said,), val=schemer)
    app.vault.db.issuers.pin(keys=(schemer.said,), val=issuer.pre)
    dialog = IssueCredentialDialog(app)
    dialog.schema_dropdown.setCurrentIndex(1)
    modes = dialog.authentication_dropdown.combo_box
    assert not modes.model().item(modes.findData('registry')).isEnabled()
    assert modes.currentData() == 'anchor'
    modes.setCurrentIndex(modes.findData('signature'))
    dialog.local_radio.setChecked(True)
    dialog.recipient_dropdown.setCurrentIndex(dialog.recipient_dropdown.combo_box.findData(recipient.pre))
    dialog._dynamic_field_widgets['nickname']['widget'].setText('Alice')
    editor = dialog._dynamic_field_widgets['residence']['widget'].fields['city'][0]
    assert dialog._dynamic_field_widgets['nickname']['widget'].label.text() == 'Nickname'
    assert dialog._dynamic_field_widgets['suffix']['widget'].label.text() == 'suffix'
    assert dialog._dynamic_field_widgets['residence']['widget'].layout().itemAt(0).widget().text() == 'residence'
    assert editor.label.text() == 'city *'
    birth_date = dialog._dynamic_field_widgets['birthDate']['widget']
    assert birth_date.label.text() == 'Date of birth'
    proofing_time = dialog._dynamic_field_widgets['proofingDatetime']['widget']
    image_proof = dialog._dynamic_field_widgets['facialImageProof']['widget']
    assert image_proof.toolTip() == 'Image typed media block SAID'
    assert image_proof.line_edit.accessibleName() == 'Image typed media block SAID'
    fixed = dialog._dynamic_field_widgets['attestation']['widget']
    fixed.include.setChecked(True)
    assert [label.text() for label in fixed.fields['approved'][0].findChildren(QLabel)] == ['approved', 'Yes']
    assert [label.text() for label in fixed.fields['region'][0].findChildren(QLabel)] == ['region', 'Utah']
    assert not fixed.fields['approved'][0].findChildren(QCheckBox)
    assert not fixed.fields['region'][0].findChildren(FloatingLabelLineEdit)
    errors = []
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    auth_requests = []
    monkeypatch.setattr(dialog, '_show_auth_step', lambda hab: auth_requests.append(hab.pre))
    modes.setCurrentIndex(modes.findData('anchor'))
    issuer.kever.wits.append('unused-witness')
    editor.setText('')
    dialog._on_issue()
    assert errors and app.queued == [] and auth_requests == []
    editor.setText('Other city')
    dialog._on_issue()
    assert 'does not match' in errors[-1]
    assert app.queued == [] and auth_requests == []
    editor.setText('Provo')
    assert dialog._validate_fields()  # Empty DOB and image reference remain schema-valid.
    assert dialog._extract_credential_attributes()['birthDate'] == ''
    assert dialog._extract_credential_attributes()['proofingDatetime'] == ''
    for invalid in ('2001-02-29', '2000-13-01', '20000229', '02/29/2000'):
        birth_date.setText(invalid)
        dialog._on_issue()
        assert errors[-1] == 'Date of birth: Enter a valid date in YYYY-MM-DD format.'
        assert app.queued == [] and auth_requests == []
    birth_date.setText('2000-02-29')
    for invalid in ('2026-02-29 14:30', '2026-10-13 24:00', '2026-10-13', '2026-1-3 4:30'):
        proofing_time.setText(invalid)
        dialog._on_issue()
        assert errors[-1] == ('Proofing session datetime: '
                              'Enter a valid date and time in YYYY-MM-DD HH:MM format (UTC).')
        assert app.queued == [] and auth_requests == []
    proofing_time.setText('2026-10-13 14:30')
    dialog._on_issue()
    assert auth_requests == [issuer.pre] and app.queued == []
    # Signature issuance needs no new KEL event, even when the issuer has witnesses.
    modes.setCurrentIndex(modes.findData('signature'))
    dialog._on_issue()
    issuer.kever.wits.clear()
    assert len(app.queued) == 1
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    ((_,), record), = app.vault.db.issued.getTopItemIter()
    acdc = SerderACDC(raw=record.raw.encode())
    assert acdc.sad['u'] == nonce
    assert acdc.sad['a']['suffix'] == ''
    assert acdc.sad['a']['birthDate'] == '2000-02-29T00:00:00.000000+00:00'
    assert acdc.sad['a']['facialImageProof'] == ''
    assert acdc.sad['a']['proofingDatetime'] == '2026-10-13T14:30:00.000000+00:00'
    assert acdc.sad['a']['residence'] == {'city': 'Provo'}
    assert acdc.sad['a']['attestation'] == {'approved': True, 'region': 'Utah'}
    assert 'dt' not in acdc.sad['a'] and 'rd' not in acdc.sad and 'r' not in acdc.sad
    assert app.vault.rgy.regs == {}
    assert schemer.verify(raw=acdc.raw)

    from locksmith.ui.vault.credentials.presentation import credential_details
    for view in (credential_details(app.vault, acdc.sad),
                 ViewIssuedCredentialDialog('', app, acdc.said)):
        labels = {label.text() for label in view.findChildren(QLabel)}
        assert {'Date of birth', 'Image typed media block SAID', 'Proofing session datetime'} <= labels
        assert not any('RFC-3339' in label for label in labels)
        assert acdc.sad['a']['birthDate'] in labels  # Values stay exact; only labels change.


@pytest.mark.parametrize('witness_count,batch', [(1, False), (4, False), (4, True), (8, False)])
def test_issue_auth_sizing_survives_errors_and_back(wallet, witness_count, batch):
    app = wallet('issue-auth-sizing')
    issuer = app.hby.makeHab(name='issuer')
    witnesses = [app.hby.makeHab(name=f'witness-{i}').pre for i in range(witness_count)]
    issuer.kever.wits.extend(witnesses)
    if batch:
        app.plugin_manager = SimpleNamespace(
            get_witness_batches=lambda vault, pre: SimpleNamespace(batches=[witnesses]))
    dialog = IssueCredentialDialog(app)
    dialog._issue_content_widget.setMinimumHeight(1000)
    dialog.open()
    form_height = dialog.height()
    dialog.show_error('Enter a valid date.')
    QTest.qWait(350)
    dialog._show_auth_step(issuer)
    auth_height = dialog.height()
    assert auth_height < form_height
    QTest.qWait(350)
    assert dialog.height() == auth_height
    assert dialog.scroll_area.verticalScrollBar().isVisible() == (witness_count > 4)
    dialog.show_error('Enter the witness code.')
    QTest.qWait(350)
    dialog._show_issue_step()
    QTest.qWait(350)
    assert dialog.height() == form_height
    assert dialog._issue_content_widget.isVisible()
    assert dialog.scroll_area.verticalScrollBar().isVisible()
    assert not app.queued


def test_issue_form_resets_constants_and_rejects_stale_context(wallet, monkeypatch):
    app = wallet('issue-guard')
    issuer = app.hby.makeHab(name='issuer')
    constant = schema().sed
    constant['$id'] = ''
    constant['properties']['a']['properties']['fixed'] = {'type': 'string', 'const': 'first'}
    first, second = scheming.Schemer(sed=constant), schema()
    for schemer in (first, second):
        app.hby.db.schema.pin(keys=(schemer.said,), val=schemer)
        app.vault.db.issuers.pin(keys=(schemer.said,), val=issuer.pre)
    dialog = IssueCredentialDialog(app)
    picker = dialog.schema_dropdown.combo_box
    picker.setCurrentIndex(picker.findData(first.said))
    assert dialog._extract_credential_attributes()['fixed'] == 'first'
    picker.setCurrentIndex(picker.findData(second.said))
    assert 'fixed' not in dialog._extract_credential_attributes()

    holder = app.hby.makeHab(name='holder')
    request = ipexing.start(app.vault, holder, issuer.pre, 'Apply', schema=second.said)
    parent = QWidget()
    dialog = IssueCredentialDialog(app, parent, request_said=request)
    dialog._dynamic_field_widgets['nickname']['widget'].setText('New credential')
    errors = []
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    original = app.vault
    original.closed = True
    dialog.issue_button.click()
    assert errors and app.queued == []
    original.closed = False
    app.vault = wallet('replacement').vault
    dialog.issue_button.click()
    assert len(errors) == 2 and app.queued == []
    app.vault = original
    ipexing.respond(original, request, 'Spurn')
    dialog.issue_button.click()
    assert len(errors) == 3 and app.queued == []
    assert list(original.db.issued.getTopItemIter()) == []

    # A closed dialog's issuance can finish after another request has started.
    dialogs = []
    for name in ('Earlier', 'Current'):
        request = ipexing.start(original, holder, issuer.pre, 'Apply', schema=second.said)
        pending = IssueCredentialDialog(app, parent, request_said=request)
        pending._dynamic_field_widgets['nickname']['widget'].setText(name)
        pending.issue_button.click()
        dialogs.append(pending)
        if name == 'Earlier':
            pending.close()
    created = []
    dialogs[1].credential_created.connect(created.append)
    earlier, current = app.queued
    doing.Doist(doers=[earlier], limit=1.0, tock=0.03125).do()
    assert created == []
    assert not dialogs[1].issue_button.isEnabled()
    doing.Doist(doers=[current], limit=1.0, tock=0.03125).do()
    said, = created
    record = original.db.issued.get((said,))
    assert SerderACDC(raw=record.raw.encode()).sad['a']['nickname'] == 'Current'


def test_grant_transport_events_do_not_imply_remote_receipt(wallet, monkeypatch):
    app = wallet('grant-ui')
    issuer = app.hby.makeHab(name='issuer')
    recipient = app.hby.makeHab(name='recipient')
    acdc, _, schemer = issue(app, issuer, recipient.pre)
    app.vault.org.update(recipient.pre, {'alias': 'Recipient'})
    other = app.hby.makeHab(name='other')
    contacts = [{'id': other.pre, 'alias': 'Other'}, {'id': recipient.pre, 'alias': 'Recipient'}]
    monkeypatch.setattr(app.vault.org, 'list', lambda: contacts)
    parent = QWidget()
    dialog = GrantCredentialDialog(app=app, parent=parent, credential_said=acdc.said,
                                   credential_schema=schemer.sed['title'], credential_issuer=issuer.pre)
    assert dialog.recipient_dropdown.currentData() == recipient.pre
    success, errors = [], []
    monkeypatch.setattr(dialog, 'show_success', success.append)
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    dialog._on_grant()
    assert app.queued == []  # The vault already owns its worker.
    ((said,), record), = app.vault.db.outbox.getTopItemIter()
    assert record.status == 'pending'
    retained = exchanging.serializeMessage(app.hby, said)
    app.vault.signals.emit_doer_event('Ipex', 'transport_submitted', {'said': 'unrelated'})
    assert not success and not errors
    assert dialog.action_button.text() == 'Sending...'
    assert dialog.cancel_button.text() == 'Close'
    assert 'retries automatically' in dialog.delivery_notice.text()
    app.vault.signals.emit_doer_event('Ipex', 'send_failed', {'said': said, 'error': 'No endpoint'})
    assert errors == ['Failed to send: No endpoint']
    assert dialog.action_button.isEnabled()
    assert dialog.action_button.text() == 'Retry sending'
    dialog._on_grant()
    assert exchanging.serializeMessage(app.hby, said) == retained
    assert [keys for keys, _ in app.vault.db.outbox.getTopItemIter()] == [(said,)]
    assert not dialog.recipient_dropdown.isEnabled()
    # A late result from this vault cannot update a dialog after a vault switch.
    old_vault = app.vault
    app.vault = wallet('other-vault').vault
    old_vault.signals.emit_doer_event('Ipex', 'transport_submitted', {'said': said})
    assert not success


def test_pending_import_does_not_open_acceptance_or_add_wallet_credential(wallet, tmp_path, monkeypatch):
    sender, receiver = wallet('import-source'), wallet('import-target')
    issuer = sender.hby.makeHab(name='issuer')
    holder = receiver.hby.makeHab(name='holder')
    acdc, proof, _ = issue(sender, issuer, holder.pre)
    receiver.vault.mbx.parser.parse(ims=bytearray(issuer.replay(gvrsn=kering.Vrsn_2_0)), local=False)
    exn, atc = native_ipexing.grant(issuer, holder.pre, 'Grant', proof)
    source = tmp_path / 'grant.cesr'
    source.write_bytes(exn.raw + atc)
    dialog = AcceptCredentialDialog(app=receiver, parent=QWidget())
    errors = []
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    monkeypatch.setattr(AcceptGrantDialog, 'open', lambda self: pytest.fail('Pending grant opened acceptance'))
    dialog.file_path_field.setText(str(source))
    dialog._on_load()
    assert not receiver.vault.exc.complete(exn.said)
    assert receiver.vault.db.accepted.get(keys=(acdc.said,)) is None
    assert errors and 'pending' in errors[0].lower()
    assert dialog.load_button.isEnabled()


@pytest.mark.parametrize('cancel_export', [False, True])
def test_grant_notification_and_file_acceptance_use_verified_native_evidence(
        wallet, tmp_path, monkeypatch, cancel_export):
    app = wallet('accept-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, schemer = issue(app, issuer, holder.pre)
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre, 'Native grant')
    ipexing.prepare(app.vault, issuer, grant, atc)
    parent = QWidget()
    parent.app = app
    notifications = NotificationsListPage(parent=parent)
    kind, message = notifications._format_ipex_message(grant, grant.route, 'Native grant')
    assert kind == 'GRANT'
    assert schemer.sed['title'] in message
    assert 'View Activity' in notifications._get_row_actions({'Type': kind})[0]
    received = ReceivedCredentialsListPage(parent=parent)
    received.set_vault_name(app.hby.name)
    dialog = AcceptGrantDialog(app=app, parent=parent, grant_said=grant.said, save=True)
    assert dialog.credential_said == acdc.said
    assert dialog.recipient == holder.pre
    assert any(label.text() == schemer.sed['title'] for label in dialog.findChildren(QLabel))
    assert app.vault.db.accepted.get(keys=(acdc.said,)) is None
    target = tmp_path / 'admit.cesr'
    monkeypatch.setattr('locksmith.ui.vault.credentials.received.accept_grant.QFileDialog.getSaveFileName',
                        lambda *a, **k: ('' if cancel_export else str(target), 'CESR'))
    dialog._on_admit()
    record = app.vault.db.accepted.get(keys=(acdc.said,))
    assert record.grant == grant.said
    assert record.accepted_at
    if cancel_export:
        assert not target.exists()
        assert 'Credential added; receipt not exported' in dialog.delivery_notice.text()
        assert dialog.admit_button.text() == 'Export receipt'
        monkeypatch.setattr('locksmith.ui.vault.credentials.received.accept_grant.QFileDialog.getSaveFileName',
                            lambda *a, **k: (str(target), 'CESR'))
        dialog._on_admit()
        assert SerderKERI(raw=target.read_bytes()).said == record.admit
    else:
        assert SerderKERI(raw=target.read_bytes()).route == '/ipex/admit'
    assert [row['SAID'] for row in received.table._static_data] == [acdc.said]
    assert app.queued == []
    assert list(app.vault.db.outbox.getTopItemIter()) == []
    assert not app.vault.db.receipts.get((holder.pre, grant.said)).send


def test_disclosure_review_shows_linked_data_and_blocks_private_offers(wallet):
    from test_credentialing import _load_schema, _issue
    from locksmith.core import credentialing

    app = wallet('linked-disclosure-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    schemer = _load_schema(app, issuer)
    terms = {'d': '', 'l': 'Use only for the requested verification.'}
    source = _issue(app, schemer, holder, attributes={'LEI': '254900OPPU84GM83MG36'},
                    authentication='anchor', rules=terms)
    origin = _issue(app, schemer, holder, attributes={'LEI': '5493001KJTIIGC8Y1R12'},
                    authentication='anchor', edges={'source': {'n': source, 's': schemer.said}})
    grant, atc = ipexing.grant(app.vault, issuer, origin, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    nodes = exchanging.loadParsedNestedSubstreams(app.hby, grant.said)
    expected = {nest.serder.sad['a']['LEI'] for nest in nodes} | {terms['l']}
    assert len(nodes) == 2
    parent = QWidget()
    parent.app = app
    direct = GrantCredentialDialog(app, parent, origin, schemer.sed['title'], issuer.pre)
    incoming = AcceptGrantDialog(app, parent, grant.said, save=False)
    for dialog in (direct, incoming):
        assert expected <= {label.text() for label in dialog.findChildren(QLabel)}
    from locksmith.ui.vault.credentials.start import StartExchangeDialog
    start = StartExchangeDialog(app, parent, 'Offer', credential_said=origin)
    start.recipient.setCurrentIndex(start.recipient.combo_box.findData(holder.pre))
    assert start.sender.currentData() == issuer.pre
    assert start.recipient.currentData() == holder.pre
    assert 'Offers for linked credentials' in start.error.text()
    assert not start.send_button.isEnabled()
    assert not start.preview.findChildren(QLabel)
    outbox = list(app.vault.db.outbox.getTopItemIter())
    start.send_button.click()
    assert list(app.vault.db.outbox.getTopItemIter()) == outbox

    request = ipexing.start(app.vault, holder, issuer.pre, 'Apply', schema=schemer.said)
    page = CredentialActivityPage(parent)
    page.set_vault_name('linked-disclosure-ui')
    row = next(row for row in page._rows if row['root'] == request and row['_actions'])
    page._on_row_action(row, 'Review')
    dialog = page._response_dialog
    dialog.credential.setCurrentIndex(dialog.credential.findData(origin))
    assert 'Offers for linked credentials' in dialog.error_label.text()
    assert not dialog.send_button.isEnabled()
    assert not dialog.preview.findChildren(QLabel)
    outbox = list(app.vault.db.outbox.getTopItemIter())
    dialog.send_button.click()
    assert app.hby.db.erpy.get((request,)) is None
    assert list(app.vault.db.outbox.getTopItemIter()) == outbox
    assert credentialing.delete_credential(app.vault, source)
    dialog._preview()
    assert 'Cannot prepare disclosure' in dialog.error_label.text()
    assert QSignalSpy(dialog._dialog_resize_animation.finished).wait(1500)
    assert dialog.error_banner.height() > 0
    assert dialog.scroll_area.verticalScrollBar().maximum() == 0
    assert not dialog.send_button.isEnabled()
    assert not dialog.credential_details.isHidden()
    assert not dialog.create_button.isHidden()
    dialog._max_dialog_height = dialog.height() - dialog.error_banner.height()
    dialog.show_error(dialog.error_label.text())
    assert QSignalSpy(dialog._dialog_resize_animation.finished).wait(1500)
    assert dialog.height() == dialog._max_dialog_height
    assert dialog.scroll_area.verticalScrollBar().isVisible()
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    dialog.show_error(dialog.error_label.text())
    assert QSignalSpy(dialog.error_animation.finished).wait(1500)
    assert dialog.height() == dialog._max_dialog_height
    assert dialog.scroll_area.verticalScrollBar().isVisible()
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    dialog.response.setCurrentIndex(dialog.response.combo_box.findData('Spurn'))
    assert dialog.error_banner.height() == 0
    assert dialog.error_label.text() == ''
    assert dialog.send_button.isEnabled()
    assert dialog.scroll_area.verticalScrollBar().maximum() == 0


def test_admit_dialog_retries_same_acknowledgment_and_disconnects_on_close(wallet, monkeypatch):
    app = wallet('admit-delivery-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, _ = issue(app, issuer, holder.pre, authentication='signature')
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    dialog = AcceptGrantDialog(app=app, parent=QWidget(), grant_said=grant.said, save=False)
    success, errors = [], []
    monkeypatch.setattr(dialog, 'show_success', success.append)
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    dialog.show()
    dialog._on_admit()
    ((said,), record), = app.vault.db.outbox.getTopItemIter()
    assert record.status == 'pending'
    assert dialog.cancel_button.text() == 'Close'
    assert 'retries automatically' in dialog.delivery_notice.text()
    retained = exchanging.serializeMessage(app.hby, said)
    record.status, record.attempts = 'failed', 4
    app.vault.db.outbox.pin((said,), record)
    app.vault.signals.emit_doer_event('Ipex', 'send_failed', {'said': said, 'error': 'No endpoint'})
    assert errors and dialog.admit_button.text() == 'Retry sending'
    assert not dialog.decline_button.isEnabled()
    dialog._on_admit()
    record = app.vault.db.outbox.get((said,))
    assert record.status == 'pending' and record.attempts == 4
    assert exchanging.serializeMessage(app.hby, said) == retained
    assert [keys for keys, _ in app.vault.db.outbox.getTopItemIter()] == [(said,)]
    dialog.close()
    app.vault.signals.emit_doer_event('Ipex', 'transport_submitted', {'said': said})
    assert not success
    # Closing a dialog does not withdraw previously saved delivery permission.
    assert app.vault.db.receipts.get((holder.pre, grant.said)).send
    assert app.vault.db.accepted.get((acdc.said,)).admit == said
    issuer.rotate()
    reopened = AcceptGrantDialog(app=app, parent=QWidget(), grant_said=grant.said, save=False)
    assert not hasattr(reopened, 'grant_error')
    assert reopened.authentication == 'unverified'
    reopened._on_admit()
    assert exchanging.serializeMessage(app.hby, said) == retained
    assert app.vault.db.accepted.get((acdc.said,)).admit == said

    for status in ('submitted', 'blocked'):
        record.status, record.error = status, 'Delivery stopped'
        app.vault.db.outbox.pin((said,), record)
        dialog = AcceptGrantDialog(app, QWidget(), grant.said, save=False)
        success, errors = [], []
        monkeypatch.setattr(dialog, 'show_success', success.append)
        monkeypatch.setattr(dialog, 'show_error', errors.append)
        dialog._on_admit()
        assert bool(success) == (status == 'submitted')
        assert bool(errors) == (status != 'submitted')
        assert dialog.admit_button.isEnabled() == (status == 'blocked')
        assert app.vault.db.outbox.get((said,)).status == status
        dialog.close()


def test_activity_retry_saved_message_after_dialog_close_and_clear_on_vault_switch(wallet):
    app = wallet('saved-delivery-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, schemer = issue(app, issuer, holder.pre)
    app.vault.org.update(holder.pre, {'alias': 'Holder'})
    parent = QWidget()
    parent.app = app
    dialog = GrantCredentialDialog(app, parent, acdc.said, schemer.sed['title'], issuer.pre)
    dialog.show()
    dialog.action_button.click()
    ((said,), record), = app.vault.db.outbox.getTopItemIter()
    retained = exchanging.serializeMessage(app.hby, said)
    record.status, record.error, record.retry_at = 'failed', 'No endpoint', 9999999999.0
    app.vault.db.outbox.pin((said,), record)
    dialog.cancel_button.click()
    assert not dialog.isVisible()

    page = CredentialActivityPage(parent)
    page.set_vault_name('saved-delivery-ui')
    row, = page.table._static_data
    assert row['Status'] == 'Grant'
    page.table.row_clicked.emit(row)
    page.protocol.toggle_button.click()
    assert page.details.isVisible()
    assert 'No endpoint' in page.details.toPlainText()
    assert page.retry_button.isEnabled()
    page.retry_button.click()
    record = app.vault.db.outbox.get((said,))
    assert record.status == 'pending' and record.retry_at == 0
    assert exchanging.serializeMessage(app.hby, said) == retained
    assert [keys for keys, _ in app.vault.db.outbox.getTopItemIter()] == [(said,)]
    assert page.table._static_data[0]['Status'] == 'Grant'
    assert 'pending' in page.details.toPlainText()

    for status in ('sending', 'submitted', 'blocked'):
        record.status = status
        app.vault.db.outbox.pin((said,), record)
        app.vault.signals.emit_doer_event('Ipex', status, {'said': said})
        assert page.table._static_data[0]['Status'] == 'Grant'
        assert status in page.details.toPlainText()
        assert page.table._static_data[0]['_attention'] == (status == 'blocked')
        assert page.retry_button.isEnabled() == (status == 'blocked')

    for missing_route in (True, False):
        record.missing_route = missing_route
        record.error = ('Import its introduction first.' if missing_route else
                        'Network delivery was not authorized')
        app.vault.db.outbox.pin((said,), record)
        page.refresh()
        buttons = [page.response_buttons.itemAt(index).widget().text()
                   for index in range(page.response_buttons.count())]
        assert ('Import delivery details' in buttons) == missing_route
        assert ('Delivery details needed' in page.summary.text()) == missing_route

    app.vault.db.receipts.put((holder.pre, said), GrantReceipt(
        credential=acdc.said, status='interrupted', error='Acceptance preparation interrupted'))
    page.table.add_clicked.emit()
    page._set_direction(1)
    receipt_row, = page.table._static_data
    page.table.row_clicked.emit(receipt_row)
    assert receipt_row['Status'] == 'Grant'
    assert receipt_row['_actions'] == ['Resume acceptance']
    assert 'Acceptance preparation interrupted' in page.details.toPlainText()
    assert not page.retry_button.isEnabled()

    old_vault = app.vault
    page._repair_route()
    app.vault = wallet('other-delivery-vault').vault
    page.set_vault_name('other-delivery-vault')
    page._repair_dialog.reject()
    assert page._detail_dialog.isHidden()
    assert page.table._static_data == []
    assert said not in page.details.toPlainText()
    page.table.row_action_triggered.emit(row, 'Retry sending')
    old_vault.signals.emit_doer_event('Ipex', 'send_failed', {'said': said})
    assert page.table._static_data == []
    assert old_vault.db.outbox.get((said,)).status == 'blocked'


@pytest.mark.parametrize('store', ['accepted', 'outbox'])
def test_admit_dialog_explains_saved_delivery_after_interrupted_acceptance(wallet, monkeypatch, store):
    app = wallet('interrupted-admit-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, _ = issue(app, issuer, holder.pre)
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    dialog = AcceptGrantDialog(app, QWidget(), grant.said, save=False)
    monkeypatch.setattr(dialog, 'show_error', lambda message: None)
    with monkeypatch.context() as patch:
        def fail_write(*args, **kwa):
            raise OSError('Temporary write failure')
        patch.setattr(getattr(app.vault.db, store), 'put', fail_write)
        dialog._on_admit()
    said = app.hby.db.erpy.get((grant.said,)).qb64
    retained = exchanging.serializeMessage(app.hby, said)
    assert app.vault.db.receipts.get((holder.pre, grant.said)).send
    assert dialog.cancel_button.text() == 'Close'
    assert not dialog.delivery_notice.isHidden()
    if store == 'outbox':
        assert list(app.vault.db.outbox.getTopItemIter()) == []
        assert 'Acceptance preparation is saved' in dialog.delivery_notice.text()
    else:
        assert 'retries automatically' in dialog.delivery_notice.text()
    dialog._on_admit()
    assert 'retries automatically' in dialog.delivery_notice.text()
    assert app.vault.db.accepted.get((acdc.said,)).admit == said
    assert exchanging.serializeMessage(app.hby, said) == retained
    assert [keys for keys, _ in app.vault.db.outbox.getTopItemIter()] == [(said,)]


def test_activity_keep_current_page_during_background_updates(wallet):
    app = wallet('delivery-pages-ui')
    # Retained submissions remain visible even if their native message is missing.
    for index in range(12):
        app.vault.db.outbox.put((f'missing-{index:02}',), IpexSubmission(status='submitted'))
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('delivery-pages-ui')
    page.table.pagination.page_changed.emit(2)
    selected = page.table._current_page_data[0]
    page.table.row_clicked.emit(selected)
    app.vault.signals.emit_doer_event('Ipex', 'sending', {'said': 'another-message'})
    assert page.table.current_page == 2
    assert selected['root'] in page.details.toPlainText()
    for index in range(10):
        app.vault.db.outbox.rem((f'missing-{index:02}',))
    page.table.add_clicked.emit()
    assert page.table.current_page == 1
    assert len(page.table._current_page_data) == 2


@pytest.mark.parametrize('received', [False, True])
def test_inventory_keeps_page_during_updates_and_clamps_after_removal(qapp, monkeypatch, received):
    from locksmith.core import credentialing

    vault = SimpleNamespace(hby=SimpleNamespace(habByPre=lambda pre: None),
                            org=SimpleNamespace(get=lambda pre: None), signals=DoerSignalBridge())
    titles = ['Other credential'] + [f'Demo {index}' for index in range(5)]
    credentials = [{'sad': {'d': f'credential-{index}', 'i': 'issuer'},
                    'schema': {'title': title}, 'status': {'et': 'authenticated'},
                    'sender': 'issuer', 'recipient': 'holder', 'held': True,
                    'accepted_at': '2026-10-15T12:00:00Z', 'created_at': '2026-10-15T12:00:00Z'}
                   for index, title in enumerate(titles)]
    monkeypatch.setattr(credentialing, 'credentials', lambda *args, **kwargs: credentials)
    parent = QWidget()
    parent.app = SimpleNamespace(vault=vault)
    page = ReceivedCredentialsListPage(parent) if received else IssuedCredentialsListPage(parent)
    page.table.items_per_page = 2
    page.set_vault_name('inventory-pages-ui')
    parent.show()
    page.show()
    qapp.processEvents()
    search = page.table.header.search_input
    search.setText('Demo')
    page.table.pagination.last_page_btn.click()

    def shown_credentials():
        table = page.table.table
        if not table.isVisibleTo(page):
            return []
        return [table.item(row, 0).text() for row in range(table.rowCount())]

    assert shown_credentials() == ['Demo 4']
    event = ('Ipex', 'transport_submitted') if received else ('RevokeCredentialDoer', 'credential_revoked')
    vault.signals.emit_doer_event(*event, {})
    assert shown_credentials() == ['Demo 4']
    assert search.text() == 'Demo'
    del credentials[4:]
    vault.signals.emit_doer_event(*event, {})
    assert shown_credentials() == ['Demo 2']
    credentials.clear()
    vault.signals.emit_doer_event(*event, {})
    assert shown_credentials() == []
    assert page.table.empty_state.isVisibleTo(page)
    assert not page.table.pagination.isVisibleTo(page)


@pytest.mark.parametrize('save', [False, True])
def test_missing_schema_grant_can_be_reviewed_but_cannot_be_accepted(wallet, monkeypatch, save):
    app = wallet('schema-missing-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, schemer = issue(app, issuer, holder.pre)
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    app.hby.db.schema.rem(keys=(schemer.said,))
    parent = QWidget()
    dialog = AcceptGrantDialog(app=app, parent=parent, grant_said=grant.said, save=save)
    assert dialog.credential_said == acdc.said
    assert any(label.text() == 'Alice' for label in dialog.findChildren(QLabel))
    errors = []
    monkeypatch.setattr(dialog, 'show_error', errors.append)
    dialog._on_admit()
    assert app.vault.db.accepted.get(keys=(acdc.said,)) is None
    assert errors and 'schema' in errors[0].lower()
    assert dialog.admit_button.isEnabled()
    if not save:
        assert dialog.decline_button.isEnabled()
        dialog.decline_button.click()
        reply = app.hby.db.exns.get((app.hby.db.erpy.get((grant.said,)).qb64,))
        assert reply.route == '/ipex/spurn'
        assert app.vault.db.receipts.get((holder.pre, grant.said)) is None


def test_wallet_tables_distinguish_issuee_and_grant_recipient(wallet, monkeypatch):
    from locksmith.core.remoting import identifier_introduction

    app = wallet('optional-issuee-ui')
    subject_app = wallet('subject-presentation-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    subject = subject_app.hby.makeHab(name='subject')
    app.vault.mbx.parser.parse(ims=bytearray(identifier_introduction(subject)))
    app.vault.org.replace(subject.pre, {'alias': subject.name})
    credentials = []
    for issuee, authentication in ((holder.pre, 'registry'), (None, 'anchor'), (subject.pre, 'signature')):
        acdc, _, schemer = issue(app, issuer, issuee, authentication=authentication)
        if issuee == subject.pre:
            delivery, atc = ipexing.grant(app.vault, issuer, acdc.said, subject.pre)
            ipexing.prepare(app.vault, issuer, delivery, atc)
            subject_app.hby.db.schema.pin((schemer.said,), schemer)
            for hab in (issuer, holder):
                subject_app.vault.mbx.parser.parse(ims=bytearray(identifier_introduction(hab)))
            subject_app.vault.mbx.parser.parse(ims=bytearray(delivery.raw + atc))
            ipexing.admit(subject_app.vault, subject, delivery.said)
            grant, atc = ipexing.grant(subject_app.vault, subject, acdc.said, holder.pre)
            ipexing.prepare(subject_app.vault, subject, grant, atc)
            app.vault.mbx.parser.parse(ims=bytearray(grant.raw + atc))
        else:
            grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
            ipexing.prepare(app.vault, issuer, grant, atc)
        ipexing.admit(app.vault, holder, grant.said)
        credentials.append(acdc)
    addressed, unaddressed, transferred = credentials
    assert 'i' not in unaddressed.sad['a']
    assert transferred.sad['a']['i'] == subject.pre
    assert len(list(app.vault.db.accepted.getTopItemIter())) == 3
    parent = QWidget()
    parent.app = app
    received = ReceivedCredentialsListPage(parent=parent)
    received.set_vault_name(app.hby.name)
    issued = IssuedCredentialsListPage(parent=parent)
    issued.set_vault_name(app.hby.name)
    received_rows = {row['SAID']: row for row in received.table._static_data}
    issued_rows = {row['SAID']: row for row in issued.table._static_data}
    expected = {acdc.said for acdc in credentials}
    assert set(received_rows) == {addressed.said}
    assert all('Offer' in row['_actions'] for row in received_rows.values())
    received.inventory.setCurrentIndex(1)
    verified_rows = {row['SAID']: row for row in received.table._static_data}
    assert set(verified_rows) == {unaddressed.said, transferred.said}
    assert all(row['_actions'] == ['View', 'View exchange history', 'Delete']
               for row in verified_rows.values())
    received_rows.update(verified_rows)
    assert set(received_rows) == set(issued_rows) == expected
    assert received_rows[addressed.said]['From'] == issuer.name
    assert received_rows[transferred.said]['From'] == subject.name
    assert issued_rows[addressed.said]['Recipient'] == holder.name
    assert issued_rows[unaddressed.said]['Recipient'] == 'Not specified'
    assert issued_rows[transferred.said]['Recipient'] == subject.name
    details = ViewIssuedCredentialDialog(icon_path='', app=app,
                                         credential_said=unaddressed.said, parent=parent)
    assert details.recipient_field.text() == 'Not specified'
    assert details.status_field.text() == 'Authenticated'
    for rows in (received_rows, issued_rows):
        assert rows[addressed.said]['Status'] == 'Active'
        assert rows[unaddressed.said]['Status'] == rows[transferred.said]['Status'] == 'Authenticated'
    viewed = []
    monkeypatch.setattr(ViewIssuedCredentialDialog, 'open', lambda self: viewed.append(self))
    received._on_row_clicked(received_rows[transferred.said])
    assert viewed[0].credential['recipient'] == holder.pre
    labels = [label.text() for label in viewed[0].findChildren(QLabel)]
    assert 'Credential subject' in labels and 'Received by' in labels
    assert f'Credential subject AID: {subject.pre}' in labels
    assert f'Received by AID: {holder.pre}' in labels
    receipt = app.vault.db.accepted.get((transferred.said,))
    review = AcceptGrantDialog(app, parent, receipt.grant, save=False)
    assert any('Credential subject: subject\nReceived by holder' in label.text()
               for label in review.findChildren(QLabel))
    accepted = app.vault.db.accepted.get(keys=(unaddressed.said,))
    deletion = DeleteReceivedCredentialDialog(schema_name='Native Credential', said=unaddressed.said,
                                             icon_path='', app=app, parent=parent)
    deletion._delete_credential()
    assert app.vault.db.accepted.get(keys=(unaddressed.said,)) is None
    assert app.vault.db.issued.get(keys=(unaddressed.said,)) is not None
    assert app.vault.exc.complete(accepted.grant)
    assert app.vault.exc.complete(accepted.admit)
    assert {row['SAID'] for row in received.table._static_data} == {transferred.said}
    received.inventory.setCurrentIndex(0)
    assert {row['SAID'] for row in received.table._static_data} == {addressed.said}
    issued._load_issued_credentials_data()
    assert {row['SAID'] for row in issued.table._static_data} == expected


@pytest.mark.parametrize('rules', [None, {'d': '', 'l': 'Use only for this verification.'}])
def test_application_defaults_to_direct_delivery_without_terms(wallet, qapp, monkeypatch, rules):
    app = wallet('direct-application-ui')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, _ = issue(app, issuer, holder.pre, authentication='anchor', rules=rules)
    other = app.hby.makeHab(name='other subject')
    other_acdc, _, _ = issue(app, issuer, other.pre, authentication='anchor', rules=rules)
    request = ipexing.start(app.vault, holder, issuer.pre, 'Apply', schema=acdc.schema)
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('direct-application-ui')
    page._on_row_action(page.tables[0]._static_data[0], 'Review')
    response = page._response_dialog
    assert response.credential.currentData() == acdc.said
    assert response.action == ('Offer' if rules else 'Grant')
    assert app.hby.db.erpy.get((request,)) is None  # Default selection does not send.
    if rules:
        return
    assert response.credential.findData(other_acdc.said) == -1
    assert response.action == 'Grant'
    response.response.setCurrentIndex(response.response.combo_box.findData('Offer'))
    response.response.combo_box.activated.emit(response.response.combo_box.currentIndex())
    response.credential.setCurrentIndex(-1)
    response.credential.setCurrentIndex(response.credential.findData(acdc.said))
    assert response.action == 'Offer'  # Keep an explicit choice across credential changes.
    response.response.setCurrentIndex(response.response.combo_box.findData('Grant'))
    response.send_button.click()
    row, = page.tables[1]._static_data
    assert [exn.route for exn in row['messages']] == ['/ipex/apply', '/ipex/grant']
    assert row['_review'] == 'Review credential'
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda kind, error, traceback: errors.append(error))
    page._on_row_action(row, 'Review')
    review = page._response_dialog
    qapp.processEvents()
    assert not errors  # Qt reports slot exceptions through the hook instead of raising.
    assert review.credential_details.toggle_button.isChecked()
    assert review.credential_details.content_area.isVisible()
    assert any(label.text() == 'Alice' and label.isVisible()
               for label in review.credential_details.findChildren(QLabel))
    assert app.vault.db.accepted.get((acdc.said,)) is None
    review.admit_button.click()
    assert app.vault.db.accepted.get((acdc.said,)).grant == row['messages'][-1].said
    assert [exn.route for exn in page.tables[1]._static_data[0]['messages']] == [
        '/ipex/apply', '/ipex/grant', '/ipex/admit']


def test_activity_drives_native_negotiation_and_keeps_direction(wallet, tmp_path, monkeypatch):
    app = wallet('activity-negotiation')
    # Exchange bodies must not inherit the identifier's KEL serialization.
    issuer = app.hby.makeHab(name='issuer', kind=kering.Kinds.cesr)
    holder = app.hby.makeHab(name='holder', kind=kering.Kinds.cesr)
    other_subject = app.hby.makeHab(name='other subject')
    acdc, _, _ = issue(app, issuer, other_subject.pre, authentication='anchor')
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    parent.start_credential_exchange = MethodType(VaultPage.start_credential_exchange, parent)
    parent.show_credential_activity = page.show_exchange
    page.set_vault_name('activity-negotiation')
    attention = []
    page.attention_changed.connect(attention.append)
    received_page = ReceivedCredentialsListPage(parent)
    received_page.table.header.add_button.click()
    composer = parent._credential_exchange_dialog
    composer.sender.setCurrentIndex(composer.sender.combo_box.findData(holder.pre))
    composer.recipient.setCurrentIndex(composer.recipient.combo_box.findData(issuer.pre))
    composer.send_button.click()
    request, = [exn for _, exn in app.hby.db.exns.getTopItemIter() if exn.route == '/ipex/apply']
    assert composer.isHidden()
    assert page.stack.currentIndex() == 1
    assert page._detail_dialog.isHidden() and page._response_dialog is None
    assert ipexing.request_schema(request) == acdc.schema
    issued, = page.tables[0]._static_data
    received, = page.tables[1]._static_data
    assert issued['To'] == 'holder' and received['From'] == 'issuer'
    assert issued['Status'] == 'Apply' and issued['_attention']
    assert not received['_attention']
    # Details remain available when explicitly opened from Activity or a notification.
    page.show_exchange(request.said, received=True)
    assert page._detail_dialog.isVisible()
    page._detail_dialog.close()
    page._on_row_action(issued, 'View')
    assert attention[-1]  # Reading is not a decision.
    # Create the requested credential without starting a new exchange or sending it.
    response = page._response_dialog
    assert response.action == 'Offer'
    # An explicit Offer choice remains in place when creation returns.
    response.response.combo_box.activated.emit(response.response.combo_box.currentIndex())
    assert response.credential.currentIndex() == -1
    assert response.send_button.text() == 'Create credential' and response.send_button.isEnabled()
    assert response.create_button.text() == 'Create another credential…'
    assert [response.response.itemData(i) for i in range(response.response.count())] == ['Offer', 'Grant', 'Spurn']
    assert not response.create_button.isVisible()
    response.send_button.click()
    creation = response._issue_dialog
    assert creation.schema_dropdown.currentData() == acdc.schema
    assert creation.recipient_dropdown.currentData() == holder.pre
    creation._dynamic_field_widgets['nickname']['widget'].setText('Requested credential')
    creation.issue_button.click()
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    selected_said = response.credential.currentData()
    assert response.send_button.text() == 'Send offer' and response.send_button.isEnabled()
    assert selected_said != acdc.said
    assert app.vault.db.issued.get((selected_said,)) is not None
    assert list(app.hby.db.erpy.getTopItemIter()) == []
    assert len(ipexing.exchanges(app.vault)) == 1
    page._response_dialog.send_button.click()
    offer = app.hby.db.exns.get((app.hby.db.erpy.get((request.said,)).qb64,))
    assert offer.route == '/ipex/offer'
    preview, = exchanging.loadParsedNestedSubstreams(app.hby, offer.said)
    assert preview.serder.said != selected_said
    assert preview.serder.sad['u'] == '' and preview.serder.sad['a'] == ''
    assert selected_said.encode() not in exchanging.serializeMessage(app.hby, offer.said)
    assert b'Requested credential' not in exchanging.serializeMessage(app.hby, offer.said)
    assert not page.tables[0]._static_data[0]['_attention']
    received, = page.tables[1]._static_data
    assert received['Status'] == 'Offer' and received['_actions'] == ['Agree', 'Spurn']
    page._on_row_action(received, 'View')
    page._response_dialog.send_button.click()
    issued, = page.tables[0]._static_data
    assert issued['Status'] == 'Agree' and issued['_actions'] == ['Grant', 'Spurn']
    page._on_row_action(issued, 'View')
    assert page._response_dialog.credential.currentData() == selected_said
    page._response_dialog.send_button.click()
    received, = page.tables[1]._static_data
    assert received['Status'] == 'Grant' and received['_actions'] == ['Admit']
    grant = received['messages'][-1]
    with pytest.raises(ValueError, match='changed'):
        ipexing.respond(app.vault, offer.said, 'Agree')
    with pytest.raises(ValueError, match='changed'):
        ipexing.respond(app.vault, grant.said, 'Spurn')
    page._on_row_action(received, 'View')
    page._response_dialog.admit_button.click()
    received, = page.tables[1]._static_data
    assert received['Status'] == 'Admit' and not received['_attention']
    assert len(received['messages']) == 5
    assert all(exn.kind == kering.Kinds.json for exn in received['messages'])
    assert received['From'] == 'issuer' and page.history_tables[0]._static_data[0]['To'] == 'holder'
    assert not attention[-1]
    assert app.vault.db.accepted.get((selected_said,)).grant == grant.said
    admit = received['messages'][-1]
    record = app.vault.db.outbox.get((admit.said,))
    record.status = 'submitted'
    app.vault.db.outbox.pin((admit.said,), record)
    app.vault.signals.emit_doer_event('Ipex', 'transport_submitted', {'said': admit.said})
    assert not page.tables[1]._static_data
    assert len(page.history_tables[1]._static_data) == 1
    history = page.history_tables[1]
    assert not history.isHidden()
    assert page.active_headings[1].isHidden()
    assert history.table.item(0, history.columns.index('Status')).text() == 'Accepted'
    heading = page.history_headings[1]
    assert heading.isChecked()
    heading.click()
    assert history.isHidden()
    page.refresh()
    assert history.isHidden() and not heading.isChecked()
    heading.click()
    assert not history.isHidden()
    completed, = history._static_data
    assert page._get_row_actions(completed)[0] == ['View exchange', 'View credential']
    page._on_row_action(completed, 'View credential')
    assert page._credential_dialog.credential_said == selected_said
    page._credential_dialog.close()
    page._response_dialog.close()
    # A second exchange for the same credential has its own row and decision.
    second, atc = ipexing.grant(app.vault, issuer, selected_said, holder.pre)
    ipexing.prepare(app.vault, issuer, second, atc)
    assert len(page.tables[1]._static_data) == 1
    assert len(page.history_tables[1]._static_data) == 1
    assert attention[-1]
    row = next(row for row in page.tables[1]._static_data if row['root'] == second.said)
    assert row['_actions'] == ['Admit', 'Spurn']
    page._on_row_action(row, 'View')
    page._response_dialog.decline_button.click()
    assert not attention[-1]
    assert app.vault.db.accepted.get((selected_said,)).grant == grant.said
    declined, = page.tables[1]._static_data
    assert declined['Status'] == 'Spurn'  # Still queued for delivery.
    spurn = declined['messages'][-1]
    record = app.vault.db.outbox.get((spurn.said,))
    record.status = 'submitted'
    app.vault.db.outbox.pin((spurn.said,), record)
    page.refresh()
    assert not page.tables[1]._static_data
    assert {row['Status'] for row in page.history_tables[1]._static_data} == {'Admit', 'Spurn'}
    declined_index, declined = next((index, row) for index, row in enumerate(history._current_page_data)
                                   if row['Status'] == 'Spurn')
    assert history.table.item(declined_index, history.columns.index('Status')).text() == 'Declined'
    assert declined['_outcome'] == 'Declined by you.'
    page._on_row_action(declined, 'View exchange')
    assert 'Declined by you.' in page.summary.text()
    page._detail_dialog.close()
    page.set_vault_name('activity-negotiation')
    assert not history.isHidden()  # With no active work, history starts expanded.
    page.tables[1]._on_search_changed('declined')
    assert history.total_items == 1
    assert page.tables[1].empty_state.isHidden()
    page.tables[1]._on_search_changed('no-such-exchange')
    assert history.isHidden() and page.history_headings[1].isHidden()
    assert page.tables[1].empty_state.text() == 'No matching exchanges.'
    page.tables[1]._on_search_changed('')
    assert history.total_items == 2 and not history.isHidden()
    with pytest.raises(kering.ValidationError, match='terminal reply'):
        ipexing.admit(app.vault, holder, second.said)
    target = tmp_path / 'declined.cesr'
    target.write_bytes(exchanging.serializeMessage(app.hby, second.said))
    reopened = []
    with monkeypatch.context() as patch:
        patch.setattr(AcceptGrantDialog, 'open', lambda dialog: reopened.append(dialog))
        importer = AcceptCredentialDialog(app, parent)
        importer._admit_credential(str(target))
    assert 'declined' in reopened[0].grant_error
    assert not hasattr(reopened[0], 'admit_button')
    assert app.hby.db.erpy.get((second.said,)).qb64 == spurn.said
    assert app.vault.db.receipts.get((holder.pre, second.said)) is None
    page.refresh()
    assert not page.tables[1]._static_data
    assert {row['Status'] for row in page.history_tables[1]._static_data} == {'Admit', 'Spurn'}
    # Credential history includes all its exchanges, not an arbitrary first match.
    third, atc = ipexing.grant(app.vault, issuer, acdc.said, other_subject.pre)
    ipexing.prepare(app.vault, issuer, third, atc)
    page.show_exchange(selected_said)
    page._set_direction(1)
    assert not page.tables[1]._static_data
    assert len(page.history_tables[1]._static_data) == 2
    assert not page.history_tables[1].isHidden()  # Explicit credential-history navigation opens it.
    page.clear_buttons[1].click()
    assert page.tables[1]._static_data[0]['root'] == third.said
    assert len(list(app.vault.db.accepted.getTopItemIter())) == 1


def test_witnessed_acceptance_waits_to_export_receipt_without_sending(wallet, monkeypatch):
    from keri.core import eventing

    app = wallet('witnessed-export')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, proof, _ = issue(app, issuer, holder.pre, authentication='signature')
    grant, atc = native_ipexing.grant(issuer, holder.pre, '', proof, ax=[True])
    ipexing.prepare(app.vault, issuer, grant, atc)
    witness = app.hby.makeHab(name='witness', transferable=False)
    holder.rotate(adds=[witness.pre], toad=1)
    dialog = AcceptGrantDialog(app, QWidget(), grant.said, save=True)
    exported = []
    monkeypatch.setattr(dialog, '_save_admit_to_file', lambda said, stream: exported.append((said, stream)))
    before = holder.kever.sn
    dialog._on_admit()
    consent = app.vault.db.receipts.get((holder.pre, grant.said))
    assert consent.status == 'preparing' and not consent.send
    assert holder.kever.sn == before + 1
    assert not exported and app.vault.db.accepted.get((acdc.said,)) is None
    assert 'Waiting for witnesses' in dialog.admit_button.text()
    assert list(app.vault.db.outbox.getTopItemIter()) == []

    def stalled_receipt(self, pre, sn=None, auths=None):
        while True:
            yield self.tock

    with monkeypatch.context() as patch:
        patch.setattr(ipexing.LocksmithReceiptor, 'receipt', stalled_receipt)
        interrupted = ipexing.SendIpexDoer(app.vault, consent.admit)
        doing.Doist(doers=[interrupted], tock=0.03125, limit=31.0).do()
    assert interrupted.done and not interrupted.deeds
    assert app.vault.db.receipts.get((holder.pre, grant.said)).status == 'interrupted'
    assert not exported and app.vault.db.accepted.get((acdc.said,)) is None
    assert dialog.admit_button.text() == 'Retry acceptance'
    dialog._on_admit()
    assert app.vault.db.receipts.get((holder.pre, grant.said)).admit == consent.admit
    assert holder.kever.sn == before + 1
    assert list(app.vault.db.outbox.getTopItemIter()) == []
    anchor = SerderKERI(raw=holder.msgOwnEvent(sn=before + 1))
    # Match Vault's inbound parser; the fixture's protected local Kevery skips
    # receipts whose witness and controller both belong to this Habery.
    receipts = parsing.Parser(kvy=eventing.Kevery(db=app.hby.db, lax=True, local=False),
                              version=kering.Vrsn_2_0)
    receipts.parse(ims=bytearray(witness.witness(
        anchor, version=kering.Vrsn_2_0, gvrsn=kering.Vrsn_2_0)))
    assert len(app.hby.db.wigs.get((holder.pre, anchor.said))) == 1
    doer = ipexing.SendIpexDoer(app.vault, consent.admit)
    doing.Doist(doers=[doer], tock=0.03125, limit=1.0).do()
    assert doer.done and not doer.deeds
    assert app.vault.db.accepted.get((acdc.said,)).admit == consent.admit
    assert exported == [(consent.admit, exchanging.serializeMessage(app.hby, consent.admit))]
    assert not dialog._listening
    assert list(app.vault.db.outbox.getTopItemIter()) == []
    assert not app.vault.db.receipts.get((holder.pre, grant.said)).send
    assert holder.kever.sn == before + 1
    dialog.close()


def test_anchored_exchange_shows_commitment_before_creating_kel_event(wallet, monkeypatch):
    app = wallet('anchor-consent')
    issuer = app.hby.makeHab(name='issuer')
    holder = app.hby.makeHab(name='holder', estOnly=True)
    acdc, proof, _ = issue(app, issuer, holder.pre, authentication='anchor')
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('anchor-consent')
    offer, atc = native_ipexing.offer(issuer, '', proof, recp=holder.pre, ax=[True],
                                     modifiers={'dp': [[[acdc.schema, '/', []]]]})
    ipexing.prepare(app.vault, issuer, offer, atc)
    page.refresh()

    for action, hab in (('Agree', holder), ('Grant', issuer), ('Admit', holder)):
        row = next(row for row in page._rows if action in row['_actions'])
        prior = row['messages'][-1]
        sn = hab.kever.sn
        with monkeypatch.context() as patch:
            patch.setattr(hab.kever, 'wits', [issuer.pre if hab is holder else holder.pre])
            page._on_row_action(row, action)
            dialog = page._response_dialog
            button = dialog.admit_button if action == 'Admit' else dialog.send_button
            assert not dialog.anchor_notice.isHidden()
            assert 'permanent commitment' in dialog.anchor_notice.text()
            assert button.isEnabled()
            assert hab.kever.sn == sn
            assert app.hby.db.erpy.get((prior.said,)) is None
            assert list(app.vault.db.receipts.getTopItemIter()) == []
            dialog.close()

        page._on_row_action(row, action)
        dialog = page._response_dialog
        button = dialog.admit_button if action == 'Admit' else dialog.send_button
        assert not dialog.anchor_notice.isHidden()
        assert 'permanent commitment' in dialog.anchor_notice.text()
        assert ('rotates your keys' in dialog.anchor_notice.text()) == hab.kever.estOnly
        assert hab.kever.sn == sn  # Opening the review does not anchor.
        button.click()
        assert hab.kever.sn == sn + 1
        assert app.hby.db.erpy.get((prior.said,)) is not None
        dialog.close()
        page.refresh()

    # An already prepared acknowledgment is recovered without anchoring again.
    with monkeypatch.context() as patch:
        patch.setattr(holder.kever, 'wits', [issuer.pre])
        sn = holder.kever.sn
        saved, _ = ipexing.admit(app.vault, holder, prior.said, send=True)
        assert holder.kever.sn == sn
        app.vault.db.receipts.rem((holder.pre, prior.said))
        app.vault.db.accepted.rem((acdc.said,))
        recovered, _ = ipexing.admit(app.vault, holder, prior.said, send=True)
        assert recovered.said == saved.said and holder.kever.sn == sn


@pytest.mark.parametrize('preview', [False, True])
def test_grant_matches_requested_schema_and_previewed_origin(wallet, preview):
    app = wallet('schema-fulfillment')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    first, first_proof, expected = issue(app, issuer, holder.pre, authentication='anchor')
    second, second_proof, _ = issue(app, issuer, holder.pre, authentication='anchor')
    other_schema = schema()
    app.hby.db.schema.pin((other_schema.said,), other_schema)

    for requested in (other_schema.said, expected.said):
        request, atc = native_ipexing.apply(holder, issuer.pre, '',
                                           modifiers={'dp': [[[requested, '/', []]]]})
        ipexing.prepare(app.vault, holder, request, atc)
        offer, atc = native_ipexing.offer(issuer, '',
            ipexing._offer_preview(first.sad) if preview else first_proof,
            artifacts=[] if preview else None, apply=request)
        ipexing.prepare(app.vault, issuer, offer, atc)
        agree, atc = native_ipexing.agree(holder, '', offer)
        ipexing.prepare(app.vault, holder, agree, atc)
        grant, atc = native_ipexing.grant(issuer, holder.pre, '', second_proof, agree=agree)
        assert (offer.sad['a']['o'] == [first.said]) is not preview
        assert grant.sad['a']['o'] == [second.said]
        malformed = grant.sad
        malformed['a'] = 'invalid'
        assert not app.vault.exc.routes['/ipex/grant'].verify(SerderKERI(sad=malformed, makify=True))
        if requested != expected.said or not preview:
            with pytest.raises(kering.ValidationError, match='protocol verification'):
                ipexing.prepare(app.vault, issuer, grant, atc)
            assert not app.vault.exc.complete(grant.said)
            assert app.hby.db.exns.get((grant.said,)) is None
            with pytest.raises(kering.ValidationError):
                ipexing.admit(app.vault, holder, grant.said, send=True)
            assert app.vault.db.accepted.get((second.said,)) is None
            assert app.vault.db.receipts.get((holder.pre, grant.said)) is None
            assert app.hby.db.erpy.get((grant.said,)) is None
            if requested == expected.said:
                grant, atc = native_ipexing.grant(issuer, holder.pre, '', first_proof, agree=agree)
                ipexing.prepare(app.vault, issuer, grant, atc)
                assert app.vault.exc.complete(grant.said)
        else:
            ipexing.prepare(app.vault, issuer, grant, atc)
            assert app.vault.exc.complete(grant.said)
            admit, _ = ipexing.admit(app.vault, holder, grant.said, send=True)
            assert app.vault.db.accepted.get((second.said,)).admit == admit.said


@pytest.mark.parametrize('metadata', [False, True])
def test_offer_review_accepts_reference_and_metadata(wallet, metadata):
    app = wallet('offer-review-variants')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, proof, _ = issue(app, issuer, holder.pre, authentication='anchor')
    origin = acdcmap(israid=issuer.pre, uuid='', schema=acdc.schema,
                     attribute=ipexing._offer_preview(acdc.sad).sad['a']) if metadata else proof
    offer, atc = native_ipexing.offer(issuer, '', origin, recp=holder.pre,
                                    artifacts=[] if metadata else None,
                                    modifiers={'dp': [[[acdc.schema, '/', []]]]})
    ipexing.prepare(app.vault, issuer, offer, atc)
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('offer-review-variants')
    page._on_row_action(page.tables[1]._static_data[0], 'Agree')
    review = page._response_dialog
    assert review.send_button.isEnabled()
    if metadata:
        assert review.error_banner.height() == 0
    else:
        assert any('rules have not been disclosed' in label.text()
                   for label in review.offer_review.findChildren(QLabel))
    assert review.decline_button.isEnabled()


def test_schema_application_keeps_selected_schema_and_rejects_vault_switch(wallet, monkeypatch):
    app, other = wallet('schema-apply'), wallet('schema-apply-other')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    alternate = app.hby.makeHab(name='alternate sender')
    acdc, _, _ = issue(app, issuer, holder.pre, authentication='anchor')
    parent = QWidget()
    parent.app = app
    parent.start_credential_exchange = MethodType(VaultPage.start_credential_exchange, parent)
    opened = []
    parent.show_credential_activity = opened.append
    page = SchemaListPage(parent)
    page._on_row_action({'SAID': acdc.schema}, 'Apply for credential')
    composer = parent._credential_exchange_dialog
    assert composer.selection.currentData() == acdc.schema
    assert not composer.selection.isEnabled()
    composer.sender.setCurrentIndex(composer.sender.combo_box.findData(holder.pre))
    assert composer.recipient.combo_box.findData(holder.pre) == -1
    composer.recipient.setCurrentIndex(composer.recipient.combo_box.findData(issuer.pre))
    composer.sender.setCurrentIndex(composer.sender.combo_box.findData(alternate.pre))
    assert composer.recipient.currentData() == issuer.pre
    assert composer.recipient.combo_box.findData(holder.pre) >= 0
    composer.sender.setCurrentIndex(composer.sender.combo_box.findData(issuer.pre))
    assert composer.recipient.currentData() is None
    assert composer.recipient.combo_box.findData(issuer.pre) == -1
    assert not composer.send_button.isEnabled()
    composer.sender.setCurrentIndex(composer.sender.combo_box.findData(holder.pre))
    composer.recipient.setCurrentIndex(composer.recipient.combo_box.findData(issuer.pre))
    assert composer.send_button.isEnabled()
    with monkeypatch.context() as patch:
        def missing_peer(*args, **kwargs):
            raise ipexing.MissingRouteError('Import the recipient introduction')
        patch.setattr(ipexing, '_require_route', missing_peer)
        composer._check_route()
        assert composer.repair_button.isVisible() and not composer.send_button.isEnabled()
        composer.repair_button.click()
        assert composer.isHidden() and composer._repair_dialog.isVisible()
        composer._repair_dialog.reject()
        assert composer.isVisible()
        assert composer.selection.currentData() == acdc.schema
        assert composer.recipient.currentData() == issuer.pre
        def missing_local(*args, **kwargs):
            raise kering.ConfigurationError('This identifier cannot receive replies. Configure a receiving mailbox.')
        patch.setattr(ipexing, '_require_route', missing_local)
        composer._check_route()
        assert composer.repair_button.isHidden() and not composer.send_button.isEnabled()
        assert 'cannot receive replies' in composer.error.text()
    composer._check_route()
    app.vault = other.vault
    composer.send_button.click()
    assert 'closed' in composer.error.text()
    assert composer.isVisible()
    assert opened == []
    assert not list(other.vault.db.outbox.getTopItemIter())


@pytest.mark.parametrize('stale', ['answered', 'expired', 'pruned'])
def test_activity_receives_verified_remote_request_and_clears_stale_response(wallet, monkeypatch, stale):
    from datetime import timedelta
    from keri.core import kraming
    from keri.help import helping
    from locksmith.core.remoting import identifier_introduction
    app, remote = wallet('activity-local'), wallet('activity-remote')
    issuer = app.hby.makeHab(name='issuer')
    holder = remote.hby.makeHab(name='holder')
    app.hby.cf.put({'kram': {'enabled': True, 'caches': {
        '~': (10000, 300000, 3600000, 86400000, 300000, 3600000, 86400000)}}})
    kramer = app.vault.kvy.kramer = kraming.Kramer(db=app.hby.db, cf=app.hby.cf)
    # Import the public key history and delivery details, then the signed request.
    app.vault.mbx.parser.parse(ims=bytearray(identifier_introduction(holder)), version=kering.Vrsn_2_0)
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('activity-local')
    schemer = schema(composed=True)
    app.hby.db.schema.pin((schemer.said,), schemer)
    app.vault.db.issuers.pin((schemer.said,), issuer.pre)
    request, atc = native_ipexing.apply(holder, issuer.pre, 'Need a credential',
                                      modifiers={'dp': [[[schemer.said, '/', []]]]})
    app.vault.mbx.parser.parse(ims=bytearray(request.raw + atc), version=kering.Vrsn_2_0)
    row, = page.tables[0]._static_data
    assert row['Status'] == 'Apply' and row['_attention']
    assert not page.tables[1]._static_data
    page._on_row_action(row, 'View')
    response = page._response_dialog
    assert response.send_button.text() == 'Create credential' and response.send_button.isEnabled()
    assert response.credential_field.isHidden() and response.create_button.isHidden()
    assert response.error_banner.height() == 0
    response.send_button.click()
    creation = response._issue_dialog
    assert creation.schema_dropdown.currentData() == schemer.said
    assert creation.recipient_dropdown.currentData() == holder.pre
    assert not list(app.vault.db.issued.getTopItemIter())
    assert not list(app.vault.db.outbox.getTopItemIter())
    creation.cancel_button.click()
    assert response.isVisible() and response.send_button.isEnabled()
    initial_height = response.height()
    response.send_button.click()
    creation = response._issue_dialog
    creation._dynamic_field_widgets['nickname']['widget'].setText('Demo')
    creation.issue_button.click()
    doing.Doist(doers=app.queued, limit=1.0, tock=0.03125).do()
    QTest.qWait(350)
    assert response.isVisible() and response.send_button.text() == 'Send credential'
    assert response.height() > initial_height
    assert response.scroll_area.verticalScrollBar().maximum() == 0
    collapsed_height = response.height()
    assert not response.create_button.isVisible()
    response.credential_details.toggle_button.click()
    QTest.qWait(350)
    assert response.height() > collapsed_height and response.create_button.isVisible()
    response.credential_details.toggle_button.click()
    QTest.qWait(350)
    assert response.height() == collapsed_height
    assert response.scroll_area.verticalScrollBar().maximum() == 0
    response.close()
    page._on_row_action(row, 'Offer')
    old_dialog = page._response_dialog
    if stale == 'answered':
        # A valid reply arrives through another local action while review is open.
        ipexing.respond(app.vault, request.said, 'Spurn', 'Already answered')
        old_dialog.send_button.click()
        assert 'changed' in old_dialog.error_label.text()
        assert QSignalSpy(old_dialog._dialog_resize_animation.finished).wait(1500)
        assert old_dialog.error_banner.height() > 0
        assert old_dialog.scroll_area.verticalScrollBar().maximum() == 0
    else:
        deadline = helping.fromIso8601(request.stamp) + timedelta(milliseconds=app.hby.db.kramCTYP.get('~').xl)
        monkeypatch.setattr(helping, 'nowUTC', lambda: deadline)
        assert ipexing.expiry_error(app.vault, request) is None
        assert 'Offer' in ipexing.responses(app.vault, request)
        now = deadline + timedelta(milliseconds=1)
        monkeypatch.setattr(helping, 'nowUTC', lambda: now)
        if stale == 'pruned':
            kramer._pruneExchanges(now.timestamp() * 1000)
            assert not list(app.hby.db.kramTMSC.getTopItemIter())
            assert app.hby.db.kramXDT.get((request.sad['x'],)) is None
        old_dialog.send_button.click()
        assert 'application has expired' in old_dialog.error_label.text()
        assert 'Ask the holder' in old_dialog.error_label.text()
        assert QSignalSpy(old_dialog._dialog_resize_animation.finished).wait(1500)
        assert old_dialog.error_banner.height() > 0
        expired_height = old_dialog.height()
        old_dialog.credential_details.toggle_button.click()
        assert QSignalSpy(old_dialog._dialog_resize_animation.finished).wait(1500)
        assert old_dialog.height() > expired_height
        old_dialog.credential_details.toggle_button.click()
        assert QSignalSpy(old_dialog.credential_details._content_animation.finished).wait(1500)
        assert old_dialog.height() == expired_height
        old_dialog._send()
        old_dialog._send()
        assert QSignalSpy(old_dialog._dialog_resize_animation.finished).wait(1500)
        assert old_dialog.height() == expired_height
        assert old_dialog.error_banner.height() > 0
        assert not old_dialog.send_button.isEnabled()
        assert not old_dialog.create_button.isEnabled()
        assert old_dialog.scroll_area.verticalScrollBar().maximum() == 0
        assert ipexing.responses(app.vault, request) == []
        expired_row, = page.tables[0]._static_data
        assert expired_row['Status'] == 'Expired' and expired_row['_actions'] == []
        page._on_row_action(expired_row, 'View')
        assert 'Ask the holder' in page.summary.text()
        assert page.response_buttons.count() == 0 and page.retry_button.isHidden()
        assert page._detail_dialog.scroll_area.verticalScrollBar().maximum() == 0
        assert not list(app.vault.db.outbox.getTopItemIter())
        ((credential_said,), credential), = app.vault.db.issued.getTopItemIter()
        before = issuer.kever.sn
        with pytest.raises(kering.ValidationError, match='application has expired'):
            ipexing.respond(app.vault, request.said, 'Offer', credential_said=credential_said)
        offer, atc = native_ipexing.offer(issuer, '', credential.stream.encode(), apply=request)
        with pytest.raises(kering.ValidationError, match='application has expired'):
            ipexing.prepare(app.vault, issuer, offer, atc)
        assert issuer.kever.sn == before
        assert app.hby.db.erpy.get((request.said,)) is None
        fresh, atc = native_ipexing.apply(holder, issuer.pre, '', modifiers=request.sad['q'])
        app.vault.mbx.parser.parse(ims=bytearray(fresh.raw + atc), version=kering.Vrsn_2_0)
        sent = ipexing.respond(app.vault, fresh.said, 'Offer', credential_said=credential_said)
        assert app.vault.exc.complete(sent)
        assert len(list(app.vault.db.issued.getTopItemIter())) == 1
    assert len(list(app.vault.db.outbox.getTopItemIter())) == 1
    app.vault = remote.vault
    page.set_vault_name('activity-remote')
    old_dialog.send_button.click()
    assert not list(remote.vault.db.outbox.getTopItemIter())


def test_activity_sends_saved_admit_with_consent_and_original_bytes(wallet):
    app = wallet('activity-saved-admit')
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, _ = issue(app, issuer, holder.pre)
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    admit, _ = ipexing.admit(app.vault, holder, grant.said, send=False)
    original = exchanging.serializeMessage(app.hby, admit.said)
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('activity-saved-admit')
    row, = page.tables[1]._static_data
    page._on_row_action(row, 'View')
    page.messages.setCurrentIndex(page.messages.findData(admit.said))
    assert page.retry_button.text() == 'Send acknowledgment'
    assert not row['_attention']
    assert not list(app.vault.db.outbox.getTopItemIter())
    page.retry_button.click()
    assert app.vault.db.receipts.get((holder.pre, grant.said)).send
    assert app.vault.db.outbox.get((admit.said,)).status == 'pending'
    assert exchanging.serializeMessage(app.hby, admit.said) == original


@pytest.mark.parametrize('rules', [None, {'d': '', 'l': 'Use only for this test <not markup>.'}])
def test_offer_first_uses_metadata_and_hides_completed_delivery_controls(wallet, qapp, rules):
    app = wallet('offer-first-ui')
    app.hby.makeHab(name='aaa-unrelated')
    issuer = app.hby.makeHab(name='issuer', kind=kering.Kinds.cesr)
    holder = app.hby.makeHab(name='holder', kind=kering.Kinds.cesr)
    acdc, _, _ = issue(app, issuer, holder.pre, authentication='anchor', rules=rules)
    other, _, _ = issue(app, issuer, holder.pre, authentication='anchor', rules=rules)
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    parent.start_credential_exchange = MethodType(VaultPage.start_credential_exchange, parent)
    parent.show_credential_activity = page.show_exchange
    page.set_vault_name('offer-first-ui')
    inventory = IssuedCredentialsListPage(parent)
    inventory._on_row_action({'SAID': acdc.said}, 'Offer')
    composer = parent._credential_exchange_dialog
    assert composer.sender.currentData() == issuer.pre
    assert composer.recipient.combo_box.findData(issuer.pre) == -1
    composer.recipient.setCurrentIndex(composer.recipient.combo_box.findData(holder.pre))
    assert composer.selection.currentData() == acdc.said
    assert not composer.selection.isEnabled()
    composer.send_button.click()
    offer, = [exn for _, exn in app.hby.db.exns.getTopItemIter() if exn.route == '/ipex/offer']
    assert offer.pre == issuer.pre
    assert composer.isHidden()
    assert page.stack.currentIndex() == 0
    assert page._detail_dialog.isHidden() and page._response_dialog is None
    preview, = exchanging.loadParsedNestedSubstreams(app.hby, offer.said)
    assert offer.sad['a']['o'] == [preview.serder.said]
    assert preview.serder.said != acdc.said
    assert preview.serder.sad['u'] == '' and preview.serder.sad['a'] == ''
    assert acdc.said.encode() not in exchanging.serializeMessage(app.hby, offer.said)
    page._on_row_action(page.tables[1]._static_data[0], 'Agree')
    review = page._response_dialog
    assert review.send_button.text() == 'Agree and request'
    assert review.offer_review.isVisible()
    labels = [label.text() for label in review.offer_review.findChildren(QLabel)]
    assert 'issuer' in labels
    assert (rules['l'] if rules else 'No rules attached.') in labels
    assert 'Alice' not in labels
    page._response_dialog.send_button.click()
    row, = page.tables[0]._static_data
    page._on_row_action(row, 'Grant')
    review = page._response_dialog
    assert review.credential.isEnabled()
    assert {review.credential.itemData(i) for i in range(review.credential.count())} == {acdc.said, other.said}
    review.credential.setCurrentIndex(review.credential.findData(acdc.said))
    assert not review.preview.isVisible()
    review.credential_details.toggle_button.setChecked(True)  # Accessible activation changes the checked state.
    qapp.processEvents()
    assert review.preview.isVisible()
    assert any(label.text() == 'Alice' for label in review.preview.findChildren(QLabel))
    page._response_dialog.send_button.click()
    page._on_row_action(page.tables[1]._static_data[0], 'Admit')
    page._response_dialog.admit_button.click()
    row, = page.tables[1]._static_data
    admit = row['messages'][-1]
    record = app.vault.db.outbox.get((admit.said,))
    for status in ('failed', 'blocked'):
        record.status = status
        app.vault.db.outbox.pin((admit.said,), record)
        page.refresh()
        assert page.tables[1]._static_data[0]['_attention']
        assert not page.history_tables[1]._static_data
    record.status = 'submitted'
    app.vault.db.outbox.pin((admit.said,), record)
    page._response_dialog.close()
    page._on_row_action(row, 'View')
    qapp.processEvents()
    assert page.messages.count() == 0
    assert not page.retry_button.isVisible()
    assert 'acknowledgment submitted' in page.summary.text()
    assert len(page._rows) == 2  # Both local roles, one exchange.
    assert not page.tables[1]._static_data
    row, = page.history_tables[1]._static_data
    assert row['Status'] == 'Admit'
    page.view_credential_button.click()
    detail = page._credential_dialog
    assert detail.credential_said == acdc.said and detail.received
    if rules:
        assert any(label.text() == rules['l'] and label.isVisibleTo(detail)
                   for label in detail.findChildren(QLabel))
    detail.history_button.click()
    assert page._credential_filter == acdc.said
    assert not page.history_tables[page.stack.currentIndex()].isHidden()
    assert page.history_tables[page.stack.currentIndex()]._static_data[0]['root'] == offer.said
    # An outgoing presentation links to the holder's Received inventory.
    verifier = app.hby.makeHab(name='verifier')
    received = ReceivedCredentialsListPage(parent)
    received._on_row_action({'SAID': acdc.said}, 'Offer')
    composer = parent._credential_exchange_dialog
    composer.recipient.setCurrentIndex(composer.recipient.combo_box.findData(verifier.pre))
    composer.send_button.click()
    presented_offer, = [exn for _, exn in app.hby.db.exns.getTopItemIter()
                       if exn.route == '/ipex/offer' and exn.said != offer.said]
    assert presented_offer.pre == holder.pre
    assert presented_offer.sad['ri'] == verifier.pre
    presentation_preview, = exchanging.loadParsedNestedSubstreams(app.hby, presented_offer.said)
    assert presented_offer.sad['a']['o'] == [presentation_preview.serder.said]
    assert presentation_preview.serder.sad['u'] == ''
    assert acdc.said.encode() not in exchanging.serializeMessage(app.hby, presented_offer.said)
    assert app.vault.db.issued.get((acdc.said,)) is not None
    assert app.vault.db.accepted.get((acdc.said,)) is not None
    presentation, atc = ipexing.grant(app.vault, holder, acdc.said, verifier.pre)
    ipexing.prepare(app.vault, holder, presentation, atc)
    row = next(row for row in page.tables[0]._static_data if row['root'] == presentation.said)
    page._on_row_action(row, 'View')
    page.view_credential_button.click()
    assert page._credential_dialog.received
    assert page._credential_dialog.credential_said == acdc.said


def test_notifications_do_not_replay_history_and_exchange_read_keeps_decision(wallet):
    from locksmith.core.vaulting import NotificationToastDoer

    app = wallet('toast-ui')
    notifier = app.vault.notifier
    notifier.add({'r': '/test', 'message': 'Older'})
    notifier.add({'r': '/test', 'message': 'Newer'})
    doer = NotificationToastDoer(app.vault)
    doer._remember_notifications()
    events = []
    app.vault.signals.doer_event.connect(lambda name, event, data: events.append((name, event, data)))
    notes = list(notifier.noter.notes.getTopItemIter())
    notifier.mar(notes[-1][0][1])
    doer.recur(0)
    assert events == []
    notifier.add({'r': '/test', 'message': 'New arrival'})
    doer.recur(1)
    assert len(events) == 1
    assert events[0][2]['message'] == 'New arrival'
    assert events[0][2]['pending_count'] == 2
    doer.recur(2)
    assert len(events) == 1
    issuer, holder = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='holder')
    acdc, _, _ = issue(app, issuer, holder.pre, authentication='anchor')
    request = ipexing.start(app.vault, holder, issuer.pre, 'Apply', schema=acdc.schema)
    offer = ipexing.respond(app.vault, request, 'Offer', credential_said=acdc.said)
    agree = ipexing.respond(app.vault, offer, 'Agree')
    for stage, said, sender in [('Apply', request, 'holder'), ('Offer', offer, 'issuer'), ('Agree', agree, 'holder')]:
        notifier.add({'r': '/exn/ipex/' + stage.lower(), 'd': said})
        doer.recur(3)
        assert events[-1][2]['message'] == f'{stage} from {sender}: Native Credential'
    grant, atc = ipexing.grant(app.vault, issuer, acdc.said, holder.pre)
    ipexing.prepare(app.vault, issuer, grant, atc)
    notifier.add({'r': '/exn/ipex/grant', 'd': grant.said})
    parent = QWidget()
    parent.app = app
    page = CredentialActivityPage(parent)
    page.set_vault_name('toast-ui')
    row = next(row for row in page.tables[1]._static_data if row['root'] == grant.said)
    page._on_row_action(row, 'View')
    assert all(note.read for _, note in list(notifier.noter.notes.getTopItemIter())
               if note.attrs.get('d') == grant.said)
    assert row['_attention']
    assert events[-1][:2] == ('MailboxListener', 'mark_as_read')
