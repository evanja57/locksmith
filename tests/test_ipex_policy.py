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
from test_keri_v2_compat import _deliver_ipex, _retry_ipex
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


def test_legacy_linked_offer_can_be_declined_after_reopen(ipex_vaults):
    source, target = ipex_vaults('legacy-issuer'), ipex_vaults('legacy-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    target.hby.db.schema.pin((schema.said,), schema)
    _introduce(source, target)
    _introduce(target, source)
    leaf = _issue(source, schema, holder, authentication='signature')
    said = _issue(source, schema, holder, authentication='signature',
                  edges={'source': {'n': leaf, 's': schema.said}})
    _, _, plan, _ = ipexing._credential_evidence(source.vault, said)
    # Older wallets replaced real child references with metadata references.
    child = acdcmap(israid=issuer.pre, uuid='', schema=schema.said, attribute='')
    root = acdcmap(israid=issuer.pre, uuid='', schema=schema.said, attribute='',
                   edge={'d': '', 'source': {'n': child.said, 's': schema.said}})
    offer, atc = native.offer(issuer, '', root, recp=holder.pre, artifacts=[child],
                              modifiers={'dp': plan}, kind=kering.Kinds.json)
    _deliver_ipex(target.vault, ipexing.prepare(source.vault, issuer, offer, atc))
    agree = ipexing.respond(target.vault, offer.said, 'Agree')
    _deliver_ipex(source.vault, exchanging.serializeMessage(target.hby, agree))
    source.close_vault()
    target.close_vault()
    source, target = ipex_vaults('legacy-issuer'), ipex_vaults('legacy-holder')
    issuer, holder = source.hby.habByName('issuer'), target.hby.habByName('holder')
    _introduce(source, target)

    outbox = list(source.vault.db.outbox.getTopItemIter())
    with pytest.raises(kering.ValidationError, match='protocol verification'):
        ipexing.respond(source.vault, agree, 'Grant', credential_said=said)
    assert list(source.vault.db.outbox.getTopItemIter()) == outbox
    assert source.hby.db.erpy.get((agree,)) is None

    view, artifacts, _, _ = ipexing._credential_evidence(source.vault, said)
    grant, atc = native.grant(issuer, holder.pre, '', view['proof'], artifacts=artifacts,
                              agree=source.hby.db.exns.get((agree,)),
                              modifiers={'dp': [[]]}, kind=kering.Kinds.json)
    _deliver_ipex(target.vault, grant.raw + atc)
    assert not target.vault.exc.complete(grant.said)
    assert target.vault.db.receipts.get((holder.pre, grant.said)) is None
    assert target.vault.db.accepted.get((said,)) is None
    assert target.hby.db.erpy.get((agree,)) is None

    spurn = ipexing.respond(source.vault, agree, 'Spurn')
    _deliver_ipex(target.vault, exchanging.serializeMessage(source.hby, spurn))
    for app in (source, target):
        exchange, = ipexing.exchanges(app.vault)
        assert exchange['messages'][-1].said == spurn
        assert exchange['actions'] == []


@pytest.mark.parametrize('invalid', [False, True])
def test_admission_validates_linked_schema_and_nested_group_evidence(ipex_vaults, invalid):
    source, target = ipex_vaults('dag-issuer'), ipex_vaults('dag-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schema = _load_schema(source, issuer)
    target.hby.db.schema.pin((schema.said,), schema)
    invalid_schema = deepcopy(schema.sed)
    if invalid:
        invalid_schema['required'].append('missingRequiredField')
    else:
        invalid_schema['title'] = 'Linked credential'
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
    if invalid:
        with pytest.raises(kering.ValidationError, match='protocol verification'):
            ipexing.prepare(source.vault, issuer, grant, atc)
        # Exercise intake independently of the outgoing composer's rejection.
        stream = grant.raw + atc
    else:
        stream = ipexing.prepare(source.vault, issuer, grant, atc)
    _deliver_ipex(target.vault, stream)
    assert not target.vault.exc.complete(grant.said)
    assert target.hby.db.emse.get((grant.said, leaf_schema.said)) is not None
    with pytest.raises(kering.ValidationError):
        ipexing.admit(target.vault, holder, grant.said)
    assert target.vault.db.receipts.get((holder.pre, grant.said)) is None
    assert target.vault.db.accepted.get((said,)) is None
    target.hby.db.schema.pin((leaf_schema.said,), leaf_schema)
    _retry_ipex(target.vault)
    assert target.vault.exc.complete(grant.said) is (not invalid)
    if invalid:
        with pytest.raises(kering.ValidationError):
            ipexing.admit(target.vault, holder, grant.said)
        assert target.vault.db.receipts.get((holder.pre, grant.said)) is None
        assert target.vault.db.accepted.get((said,)) is None
    else:
        assert len(exchanging.loadParsedNestedSubstreams(target.hby, grant.said)) == 2
        assert target.vault.db.accepted.get((said,)) is None
        ipexing.admit(target.vault, holder, grant.said)
        assert target.vault.db.accepted.get((said,)) is not None


def test_untargeted_issuer_delivery_does_not_confer_presentation_rights(ipex_vaults):
    app = ipex_vaults('untargeted')
    issuer, recipient = app.hby.makeHab(name='issuer'), app.hby.makeHab(name='recipient')
    schema = _load_schema(app, issuer)
    credential = acdcmap(israid=issuer.pre, schema=schema.said, attribute={'d': '', 'claim': True})
    ipexing._require_presenter(credential, issuer.pre, recipient.pre)
    assert not ipexing.presentation_eligible(credential, recipient.pre)
    with pytest.raises(kering.ValidationError):
        ipexing._require_presenter(credential, recipient.pre, issuer.pre)


@pytest.mark.parametrize('profile', ['organizational-unit', 'issuing-agent'])
def test_bundled_sedi_metadata_negotiation_withholds_registry_and_attributes(ipex_vaults, profile):
    from pathlib import Path
    from keri.core import Compactor, Saider

    source, target = ipex_vaults('sedi-unit-issuer'), ipex_vaults('sedi-unit-holder')
    issuer, holder = source.hby.makeHab(name='issuer'), target.hby.makeHab(name='holder')
    schemas = {name: scheming.Schemer(raw=(Path(__file__).parents[1] /
                                         f'assets/schemas/sedi/{name}.json').read_bytes())
               for name in ('organizational-unit', 'issuing-agent')}
    for schema in schemas.values():
        for app in (source, target):
            app.hby.db.schema.pin((schema.said,), schema)
        source.vault.db.issuers.pin((schema.said,), issuer.pre)
    _introduce(target, source)
    unit = _issue(source, schemas['organizational-unit'],
                  issuer if profile == 'issuing-agent' else holder,
                  attributes={'issuedDate': '2026-10-19T00:00:00Z', 'unit': 'Private department'},
                  rules={'d': '', 'l': 'Use only to verify organizational membership.'})
    said = unit if profile == 'organizational-unit' else _issue(
        source, schemas['issuing-agent'], holder,
        attributes={'issuedDate': '2026-10-19T00:00:00Z', 'role': 'Private role',
                    'name': {'d': '', 'u': Noncer().qb64, 'value': 'Private name'}},
        edges={'orgUnit': {'n': unit, 's': schemas['organizational-unit'].said, 'o': 'I2I'}},
        rules={'d': '', 'l': 'Use only to verify issuing authority.'})
    originals = {key: credentialing.credential(source.vault, key)['sad'] for key in (said, unit)}
    _introduce(source, target)
    if profile == 'issuing-agent':
        outbox = list(source.vault.db.outbox.getTopItemIter())
        exchanges = list(source.hby.db.exns.getTopItemIter())
        with pytest.raises(kering.ValidationError, match='Offers for linked credentials'):
            ipexing.start(source.vault, issuer, holder.pre, 'Offer', credential_said=said)
        assert list(source.vault.db.outbox.getTopItemIter()) == outbox
        assert list(source.hby.db.exns.getTopItemIter()) == exchanges
        return
    offered = ipexing.start(source.vault, issuer, holder.pre, 'Offer', credential_said=said)
    stream = exchanging.serializeMessage(source.hby, offered)
    previews = exchanging.loadParsedNestedSubstreams(source.hby, offered)
    assert len(previews) == len(originals)
    assert previews[0].serder.schema == schemas[profile].said
    private = {'Private department', 'Private role', 'Private name'}
    for original in originals.values():
        preview = next(nest.serder for nest in previews if nest.serder.schema == original['s'])
        assert preview.sad['u'] == preview.sad['rd'] == preview.sad['a'] == ''
        assert preview.sad['r']['l'] == original['r']['l']
        assert Saider(qb64=preview.sad['r']['d']).verify(sad=preview.sad['r'], kind=kering.Kinds.json)
        assert preview.sad['r']['d'] == Compactor(
            mad=original['r'], makify=True, compactify=True, kind=kering.Kinds.json).said
        private.update((original['d'], original['u'], original['rd'], original['a']['u'],
                        Compactor(mad=original['a'], makify=True, compactify=True, kind=kering.Kinds.json).said))
        assert holder.pre.encode() not in preview.raw
    disclosed = source.hby.db.exns.get((offered,)).raw + b''.join(nest.serder.raw for nest in previews)
    assert not [value for value in private if value and value.encode() in disclosed]
    assert all(original['r']['l'].encode() in disclosed for original in originals.values())
    _deliver_ipex(target.vault, stream)
    assert target.vault.exc.complete(offered)
    assert not credentialing.credentials(target.vault)
    agree = ipexing.respond(target.vault, offered, 'Agree')
    _deliver_ipex(source.vault, exchanging.serializeMessage(target.hby, agree))
    grant = ipexing.respond(source.vault, agree, 'Grant', credential_said=said)
    # Observer ingestion is covered at its service boundary; provide the accepted TEL here.
    for original in originals.values():
        for sn in (0, 1):
            regk = original['rd']
            target.vault.rgy.store.accept(regk, sn, source.vault.rgy.store.seqEvent(regk, sn))
    _deliver_ipex(target.vault, exchanging.serializeMessage(source.hby, grant))
    assert target.vault.exc.complete(grant)
    assert target.vault.db.accepted.get((said,)) is None
    ipexing.admit(target.vault, holder, grant)
    assert credentialing.credential(target.vault, said, received=True)['sad'] == originals[said]


@pytest.mark.parametrize('form', ['blinded', 'nested-blinded', 'compact', 'public-reference'])
def test_metadata_offer_distinguishes_public_text_from_staged_rule_disclosure(form):
    from keri.core import Diger

    reference = Diger(ser=b'rule-reference').qb64
    rules = {
        'blinded': {'d': '', 'u': Noncer().qb64, 'l': 'Sensitive terms'},
        'nested-blinded': {'d': '', 'nested': {'d': '', 'u': Noncer().qb64, 'l': 'Sensitive terms'}},
        'compact': reference,
        'public-reference': {'d': '', 'l': reference + ' is the governing public reference.'},
    }[form]
    original = acdcmap(israid=Diger(ser=b'issuer').qb64, uuid=Noncer().qb64,
                       attribute={'d': '', 'value': 'Private'}, rule=rules)
    if form == 'public-reference':
        preview = ipexing._offer_preview(original.sad)
        assert preview.sad['r']['l'] == original.sad['r']['l']
        from keri.core import Saider
        assert Saider(qb64=preview.sad['r']['d']).verify(sad=preview.sad['r'], kind=kering.Kinds.json)
    else:
        message = 'Disclose rule text' if form == 'compact' else 'staged terms negotiation'
        with pytest.raises(kering.ValidationError, match=message):
            ipexing._offer_preview(original.sad)


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
