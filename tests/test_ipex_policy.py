"""Wallet acceptance policy on independent native exchange stores."""
from copy import deepcopy

import pytest
from keri import kering
from keri.acdc import acdcmap, ipexing as native
from keri.core import Noncer, scheming
from keri.peer import exchanging

from locksmith.core import credentialing, ipexing
from locksmith.db.basing import IssuedCredential
from locksmith.core.remoting import identifier_introduction
from test_credentialing import _issue, _load_schema
from test_keri_v2_compat import _deliver_ipex
from test_keri_v2_compat import ipex_vaults as ipex_vaults


def _introduce(source, target):
    for hab in source.hby.habs.values():
        _deliver_ipex(target.vault, identifier_introduction(hab))


def test_only_issuee_can_represent_targeted_credential(ipex_vaults):
    source, holder_app, verifier = [ipex_vaults(name) for name in ('policy-issuer', 'policy-holder', 'policy-verifier')]
    issuer = source.hby.makeHab(name='issuer')
    holder = holder_app.hby.makeHab(name='holder')
    reviewer = verifier.hby.makeHab(name='reviewer')
    schema = _load_schema(source, issuer)
    for app in (holder_app, verifier):
        app.hby.db.schema.pin((schema.said,), schema)
    for app in (source, holder_app, verifier):
        for other in (source, holder_app, verifier):
            if app is not other:
                _introduce(app, other)
    said = _issue(source, schema, holder, authentication='signature')
    grant, atc = ipexing.grant(source.vault, issuer, said, holder.pre)
    _deliver_ipex(holder_app.vault, ipexing.prepare(source.vault, issuer, grant, atc))
    ipexing.admit(holder_app.vault, holder, grant.said)
    presentation, atc = ipexing.grant(holder_app.vault, holder, said, reviewer.pre)
    stream = ipexing.prepare(holder_app.vault, holder, presentation, atc)
    _deliver_ipex(verifier.vault, stream)
    ipexing.admit(verifier.vault, reviewer, presentation.said)
    credential = ipexing.grant_credential(verifier.vault, presentation.said)
    assert ipexing.presentation_eligible(credential, holder.pre)
    assert not ipexing.presentation_eligible(credential, reviewer.pre)
    with pytest.raises(kering.ValidationError, match='issuee or original issuer'):
        ipexing.grant(verifier.vault, reviewer, said, issuer.pre)
    with pytest.raises(kering.ValidationError, match='must address'):
        ipexing.grant(source.vault, issuer, said, reviewer.pre)

    # Bypass the local composer. Authentic issuer evidence is insufficient to
    # authorize a different presenter at the receiving wallet's admission step.
    proof = credentialing.credential(verifier.vault, said)['proof']
    replay, atc = native.grant(reviewer, holder.pre, 'Replay', origin=proof,
                                modifiers={'dp': [[[schema.said, '/', []]]]}, kind=kering.Kinds.json)
    _deliver_ipex(holder_app.vault, replay.raw + atc)
    assert holder_app.vault.exc.complete(replay.said)
    with pytest.raises(kering.ValidationError, match='issuee or original issuer'):
        ipexing.admit(holder_app.vault, holder, replay.said)
    assert holder_app.vault.db.receipts.get((holder.pre, replay.said)) is None


@pytest.mark.parametrize('substitute', [None, 'rules', 'issuer'])
def test_metadata_offer_binds_rules_before_admission(ipex_vaults, substitute):
    source, target = ipex_vaults('metadata-issuer'), ipex_vaults('metadata-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    target.hby.db.schema.pin((schema.said,), schema)
    _introduce(source, target)
    _introduce(target, source)
    said = _issue(source, schema, holder, authentication='signature', rules={'d': '', 'terms': 'Agreed terms'})
    original = credentialing.credential(source.vault, said)
    metadata = acdcmap(israid=issuer.pre, uuid='', schema=schema.said, attribute='', rule=original['sad']['r'])
    offer, atc = native.offer(issuer, 'Terms', metadata, recp=holder.pre, artifacts=[],
                              modifiers={'dp': [[[schema.said, '/', []]]]}, kind=kering.Kinds.json)
    _deliver_ipex(target.vault, ipexing.prepare(source.vault, issuer, offer, atc))
    agree, atc = native.agree(holder, 'Agree', offer, kind=kering.Kinds.json)
    _deliver_ipex(source.vault, ipexing.prepare(target.vault, holder, agree, atc))
    if substitute == 'rules':
        said = _issue(source, schema, holder, authentication='signature', rules={'d': '', 'terms': 'Changed terms'})
    elif substitute == 'issuer':
        other_issuer = source.hby.makeHab(name='other-issuer')
        source.vault.db.issuers.pin((schema.said,), other_issuer.pre)
        said = _issue(source, schema, holder, authentication='signature', rules={'d': '', 'terms': 'Agreed terms'})
        _introduce(source, target)
    grant, atc = native.grant(issuer, holder.pre, 'Grant', origin=credentialing.credential(source.vault, said)['proof'],
                              agree=agree, modifiers={'dp': [[]]}, kind=kering.Kinds.json)
    previews = exchanging.loadParsedNestedSubstreams(target.hby, offer.said)
    assert previews, 'Missing retained offer preview'
    assert previews[0].serder.sad['r']['terms'] == 'Agreed terms'
    if substitute == 'rules':
        assert credentialing.credential(source.vault, said)['sad']['r']['terms'] == 'Changed terms'
    _deliver_ipex(target.vault, grant.raw + atc)
    assert target.vault.exc.complete(grant.said) is (not substitute)
    if not substitute:
        ipexing.admit(target.vault, holder, grant.said)


def test_admission_validates_linked_schema_and_nested_group_evidence(ipex_vaults):
    source, target = ipex_vaults('dag-issuer'), ipex_vaults('dag-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    target.hby.db.schema.pin((schema.said,), schema)
    invalid_schema = deepcopy(schema.sed)
    invalid_schema['required'].append('missingRequiredField')
    leaf_schema = scheming.Schemer(sed=invalid_schema)
    source.hby.db.schema.pin((leaf_schema.said,), leaf_schema)
    leaf = acdcmap(israid=issuer.pre, uuid=Noncer().qb64, schema=leaf_schema.said,
                   attribute={'d': '', 'i': holder.pre, 'LEI': 'value'})
    source.vault.db.issued.pin((leaf.said,), IssuedCredential(
        leaf.raw.decode(), stream=issuer.endorse(leaf, gvrsn=kering.Vrsn_2_0).decode()))
    said = _issue(source, schema, holder, authentication='signature', edges={
        'group': {'d': '', 'source': {'n': leaf.said, 's': leaf_schema.said}},
    })
    _introduce(source, target)
    _introduce(target, source)
    grant, atc = ipexing.grant(source.vault, issuer, said, holder.pre)
    assert grant.sad['q']['dp'][0][1][1] == '/e/group/source/_/'
    _deliver_ipex(target.vault, ipexing.prepare(source.vault, issuer, grant, atc))
    assert len(exchanging.loadParsedNestedSubstreams(target.hby, grant.said)) == 2
    with pytest.raises(kering.ValidationError, match='Load credential schema'):
        ipexing.admit(target.vault, holder, grant.said)
    target.hby.db.schema.pin((leaf_schema.said,), leaf_schema)
    with pytest.raises(kering.ValidationError):
        ipexing.admit(target.vault, holder, grant.said)
    assert target.vault.db.receipts.get((holder.pre, grant.said)) is None


def test_untargeted_issuer_delivery_does_not_confer_presentation_rights(ipex_vaults):
    app = ipex_vaults('untargeted')
    issuer, recipient = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='recipient')
    schema = _load_schema(app, issuer)
    credential = acdcmap(israid=issuer.pre, schema=schema.said, attribute={'d': '', 'claim': True})
    ipexing._require_presenter(credential, issuer.pre, recipient.pre)
    assert not ipexing.presentation_eligible(credential, recipient.pre)
    with pytest.raises(kering.ValidationError):
        ipexing._require_presenter(credential, recipient.pre, issuer.pre)


def test_wallet_metadata_offer_and_linked_grant_keep_private_digests_out(ipex_vaults):
    source, target = ipex_vaults('private-issuer'), ipex_vaults('private-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    target.hby.db.schema.pin((schema.said,), schema)
    _introduce(source, target)
    _introduce(target, source)
    leaf = _issue(source, schema, holder, authentication='signature', rules={'d': '', 'text': 'Linked terms'})
    said = _issue(source, schema, holder, authentication='signature',
                  edges={'source': {'n': leaf, 's': schema.said}}, rules={'d': '', 'text': 'Origin terms'})
    offered = ipexing.start(source.vault, issuer, holder.pre, 'Offer', credential_said=said)
    stream = exchanging.serializeMessage(source.hby, offered)
    preview, = exchanging.loadParsedNestedSubstreams(source.hby, offered)
    disclosed = source.hby.db.exns.get((offered,)).raw + preview.serder.raw
    assert said.encode() not in disclosed
    assert leaf.encode() not in disclosed
    assert b'254900OPPU84GM83MG36' not in disclosed
    assert b'Origin terms' in disclosed
    assert b'Linked terms' not in disclosed
    assert preview.serder.sad['u'] == ''
    assert preview.serder.sad['a'] == ''
    assert 'e' not in preview.serder.sad and 'rd' not in preview.serder.sad
    _deliver_ipex(target.vault, stream)
    agree = ipexing.respond(target.vault, offered, 'Agree')
    _deliver_ipex(source.vault, exchanging.serializeMessage(target.hby, agree))
    grant = ipexing.respond(source.vault, agree, 'Grant', credential_said=said)
    _deliver_ipex(target.vault, exchanging.serializeMessage(source.hby, grant))
    ipexing.admit(target.vault, holder, grant)
    assert len(exchanging.loadParsedNestedSubstreams(target.hby, grant)) == 2


@pytest.mark.parametrize('field', ['i', 's', 'rd', 'a', 'e', 'r'])
def test_metadata_populated_commitments_cannot_change(field):
    from types import SimpleNamespace
    from keri.core import Diger, SerderACDC

    first, second = (Diger(ser=value).qb64 for value in (b'first', b'second'))
    values = dict(i=first, s=first, rd=first, a=first, e={'d': '', 'source': {'n': first}},
                  r={'d': '', 'terms': 'Agreed'})
    metadata = acdcmap(israid=values['i'], uuid='', schema=values['s'], regid=values['rd'],
                       attribute=values['a'], edge=values['e'], rule=values['r'])
    changed = deepcopy(metadata.sad)
    changed['u'] = Noncer().qb64
    if field == 'e':
        changed['e'] = {'d': '', 'source': {'n': second}}
    elif field == 'r':
        changed['r'] = {'d': '', 'terms': 'Different'}
    else:
        changed[field] = second
    actual = SerderACDC(sad=changed, makify=True)
    offer = SimpleNamespace(sad={'a': {'o': [metadata.said]}})
    grant = SimpleNamespace(sad={'a': {'o': [actual.said]}})
    assert not ipexing._offer_matches(offer, [SimpleNamespace(serder=metadata)],
                                     grant, [SimpleNamespace(serder=actual)])


@pytest.mark.parametrize('revoked_node', ['origin', 'linked'])
def test_queued_grant_rechecks_native_state_before_disclosure(ipex_vaults, monkeypatch, revoked_node):
    from types import SimpleNamespace
    from hio.base import doing
    from keri.core import SerderACDC

    source, target = ipex_vaults('queued-issuer'), ipex_vaults('queued-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    _introduce(source, target)
    _introduce(target, source)
    linked = _issue(source, schema, holder)
    said = _issue(source, schema, holder, edges={'source': {'n': linked, 's': schema.said}})
    # This isolates current-proof policy. Registry HTTP acceptance and freshness
    # are tested independently; both heads here have completed that check.
    heads = {regk: head.qb64 for (regk,), head in source.vault.rgy.baser.heads.getTopItemIter()}
    source.vault.registry_evidence = SimpleNamespace(
        observer_url='http://observer.example', errors={},
        ensure=lambda regk, hab: heads[regk] == source.vault.rgy.store.head(regk).qb64,
        published=lambda regk: heads[regk] == source.vault.rgy.store.head(regk).qb64)
    grant, atc = ipexing.grant(source.vault, issuer, said, holder.pre)
    ipexing.submit(source.vault, issuer, grant, atc)
    assert source.vault.exc.complete(grant.said)
    revoke = credentialing.RevokeCredentialDoer(source, said if revoked_node == 'origin' else linked)
    doing.Doist(doers=[revoke], tock=0.03125, limit=1).do()
    record = source.vault.db.issued.get((said if revoked_node == 'origin' else linked,))
    regk = SerderACDC(raw=record.raw.encode()).regid
    heads[regk] = source.vault.rgy.store.head(regk).qb64
    assert source.vault.registry_evidence.ensure(regk, issuer)
    with pytest.raises(kering.ValidationError):
        ipexing.prepare(source.vault, issuer, grant, atc)
    def forbidden_transport(**kwa):
        pytest.fail('A revoked proof reached network delivery')
    monkeypatch.setattr(ipexing.forwarding, 'StreamPoster', forbidden_transport)
    sender = ipexing.SendIpexDoer(source.vault, grant.said)
    doing.Doist(doers=[sender], tock=0.03125, limit=1).do()
    outbox = source.vault.db.outbox.get((grant.said,))
    assert outbox.status == 'blocked'
    assert outbox.attempts == 0
    assert not sender.deeds
