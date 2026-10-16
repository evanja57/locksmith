"""A revocation changes native registry state and survives receipt retries."""
import pytest
from hio.base import doing
from keri import kering
from keri.core import Blinder, BlindState, SerderACDC, SerderKERI

from locksmith.core import credentialing
from test_credentialing import _load_schema, _issue
from test_keri_v2_compat import ipex_vaults as ipex_vaults, _deliver_ipex


def _revoke(app):
    (said,), _ = next(app.vault.db.issued.getTopItemIter())
    doer = credentialing.RevokeCredentialDoer(app, said)
    doing.Doist(doers=[doer], tock=0.03125, limit=31).do()
    assert doer.done and not doer.deeds
    return said


def test_revocation_native_state_idempotence_and_reopen(ipex_vaults):
    app = ipex_vaults('revoke')
    hab = app.hby.makeHab(name='issuer')
    schema = _load_schema(app, hab)
    said = _issue(app, schema, hab)
    original = app.vault.db.issued.get((said,))
    acdc = SerderACDC(raw=original.raw.encode())
    old_proof = Blinder(clan=BlindState, qb64=original.blinder)
    _revoke(app)
    assert credentialing.credential(app.vault, said)['status']['et'] == 'revoked'
    with pytest.raises(kering.ValidationError):
        credentialing.credential_state(app.vault, acdc, old_proof)
    head = app.vault.rgy.store.headEvent(acdc.regid)
    sn = hab.kever.sn
    _revoke(app)
    assert hab.kever.sn == sn
    assert app.vault.rgy.store.headEvent(acdc.regid).said == head.said
    app.close_vault()
    app = ipex_vaults('revoke')
    _revoke(app)
    assert credentialing.credential(app.vault, said)['status']['et'] == 'revoked'
    assert app.vault.rgy.store.headEvent(acdc.regid).said == head.said
    assert app.hby.habByName('issuer').kever.sn == sn


@pytest.mark.parametrize('close', [False, True])
def test_revocation_receipt_retry_retains_proof_and_anchor(ipex_vaults, monkeypatch, close):
    app = ipex_vaults('revoke-retry')
    witness = app.hby.makeHab(name='witness', transferable=False)
    hab = app.hby.makeHab(name='issuer', wits=[witness.pre], toad=1)
    schema = _load_schema(app, hab)
    receipts, finish = [], [True]
    def receipt(self, pre, sn=None, auths=None):
        receipts.append((sn, auths))
        try:
            while not finish[0]:
                yield self.tock
            _deliver_ipex(app.vault, witness.witness(SerderKERI(raw=hab.msgOwnEvent(sn=sn))))
        finally:
            receipts.append('closed')
    monkeypatch.setattr(credentialing.LocksmithReceiptor, 'receipt', receipt)
    said = _issue(app, schema, hab)
    finish[0] = False
    doer = credentialing.RevokeCredentialDoer(app, said, codes=[f'{witness.pre}:123456'])
    if close:
        app.vault.extend([doer])
        for _ in range(8):
            app.qtask.run()
    else:
        doing.Doist(doers=[doer], tock=0.03125, limit=31).do()
    record = app.vault.db.issued.get((said,))
    proof, update, sn = record.blinder, record.update, hab.kever.sn
    assert Blinder(clan=BlindState, qb64=proof).state == 'revoked'
    assert credentialing.credential(app.vault, said)['status']['et'] == 'pending'
    assert any(isinstance(item, tuple) and item[1].get(witness.pre, '').startswith('123456#')
               for item in receipts)
    app.close_vault()
    assert receipts[-1] == 'closed'
    assert not doer.deeds
    app = ipex_vaults('revoke-retry')
    hab, witness = app.hby.habByName('issuer'), app.hby.habByName('witness')
    finish[0] = True
    _revoke(app)
    record = app.vault.db.issued.get((said,))
    assert record.blinder == proof and record.update == update
    assert hab.kever.sn == sn
    assert credentialing.credential(app.vault, said)['status']['et'] == 'revoked'


def test_revocation_dialog_requires_click_and_ignores_another_vault(ipex_vaults, qapp):
    from locksmith.ui.vault.credentials.issued.revoke import RevokeCredentialDialog

    app = ipex_vaults('revoke-dialog')
    hab = app.hby.makeHab(name='issuer')
    schema = _load_schema(app, hab)
    said = _issue(app, schema, hab)
    dialog = RevokeCredentialDialog(app, said, 'Example credential')
    assert credentialing.credential(app.vault, said)['status']['et'] == 'issued'
    dialog.revoke_button.click()
    for _ in range(12):
        app.qtask.run()
    assert credentialing.credential(app.vault, said)['status']['et'] == 'revoked'
    assert dialog._closed
    stale = RevokeCredentialDialog(app, said, 'Example credential')
    app.close_vault()
    stale.revoke_button.click()
    assert stale._revocation_id is None
    stale.close()
