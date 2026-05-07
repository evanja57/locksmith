# -*- encoding: utf-8 -*-
"""
locksmith.core.grouping module

Doers and helpers for KERI group multisig identifier operations.
"""
from ordered_set import OrderedSet as oset

from hio.base import doing
from keri import help, kering
from keri.app import grouping as keri_grouping
from keri.app import habbing as keri_habbing
from keri.app import organizing
from keri.core import coring
from keri.core.serdering import SerderKERI
from keri.peer import exchanging

from locksmith.db.basing import IdentifierMetaInfo

logger = help.ogler.getLogger(__name__)


def get_contacts_for_multisig(app):
    """
    Get contacts eligible for multisig participation.
    Returns list of dicts with id, alias keys.
    Filters to transferable identifiers only.

    Args:
        app: Application instance with vault

    Returns:
        list: List of dicts with 'id', 'alias' keys for eligible contacts
    """
    org = organizing.Organizer(hby=app.vault.hby)
    contacts = org.list()
    kevers = app.vault.hby.kevers

    eligible = []
    for contact in contacts:
        pre = contact['id']
        # Filter out remote multisig identifiers (multiple signing keys)
        if pre in kevers and kevers[pre].transferable and len(kevers[pre].verfers) == 1:
            eligible.append({
                'id': pre,
                'alias': contact.get('alias', '')
            })
    return eligible


def extract_smids_from_selections(app, mhab_alias, selected_contacts):
    """
    Build smids list from local hab and selected contacts.

    Args:
        app: Application instance with vault
        mhab_alias: Alias of the local member hab
        selected_contacts: List of selected contact dicts with 'id' key

    Returns:
        list: List of qb64 AIDs for smids
    """
    mhab = app.vault.hby.habByName(mhab_alias)
    if not mhab:
        raise ValueError(f"Local identifier '{mhab_alias}' not found")

    smids = [mhab.pre]
    for contact in selected_contacts:
        pre = contact.get('id')
        if pre and pre not in smids:
            smids.append(pre)

    return smids


def resolve_member_key_states(hby, smids, rmids):
    """
    Resolve member key states for group rotation.

    Each member contributes verfers[0] (current signing key) and ndigers[0]
    (next rotation key digest) per keripy convention.

    Args:
        hby: Habery instance
        smids: List of signing member AIDs
        rmids: List of rotation member AIDs

    Returns:
        tuple: (merfers, migers) - lists of Verfer and Diger instances
    """
    merfers = []
    for smid in smids:
        if smid not in hby.kevers:
            raise kering.ConfigurationError(f"Unknown signing member {smid}")
        merfers.append(hby.kevers[smid].verfers[0])

    migers = []
    for rmid in rmids:
        if rmid not in hby.kevers:
            raise kering.ConfigurationError(f"Unknown rotation member {rmid}")
        migers.append(hby.kevers[rmid].ndigers[0])

    return merfers, migers


def get_shared_witnesses(ghab):
    """
    Get witnesses shared between the group hab and the local member hab.

    Used to determine which witnesses need post-counselor TOTP authentication.

    Args:
        ghab: GroupHab instance

    Returns:
        list: List of witness AIDs shared between group and local member
    """
    group_wits = set(ghab.kever.wits)
    mhab_wits = set(ghab.mhab.kever.wits)
    return list(group_wits.intersection(mhab_wits))


def rotate_group_identifier(app, ghab, isith=None, nsith=None, toad=None,
                            cuts=None, adds=None, smids=None, rmids=None):
    """
    Initiate a group multisig rotation.

    Creates and launches a GroupMultisigRotateDoer.

    Args:
        app: Application instance with vault
        ghab: GroupHab instance to rotate
        isith: Current signing threshold
        nsith: Next signing threshold
        toad: Witness threshold after rotation
        cuts: List of witness AIDs to remove
        adds: List of witness AIDs to add
        smids: Signing member AIDs (defaults to current)
        rmids: Rotation member AIDs (defaults to smids)
    """
    doer = GroupMultisigRotateDoer(
        app=app, ghab=ghab, smids=smids, rmids=rmids,
        isith=isith, nsith=nsith, toad=toad, cuts=cuts, adds=adds,
        signal_bridge=app.vault.signals
    )
    app.vault.extend([doer])


def get_pending_multisig_rotation_proposals(app):
    """
    Get all pending multisig rotation proposals from notifier.

    Args:
        app: Application instance with vault

    Returns:
        list: List of proposal dicts with rid, said, exn, datetime keys
    """
    proposals = []
    for (dt, rid), note in app.vault.notifier.noter.notes.getTopItemIter():
        route = note.pad.get('a', {}).get('r', '')
        if '/multisig/rot' in route and not note.read:
            said = note.attrs.get('d', '')
            if said:
                try:
                    exn, pathed = exchanging.cloneMessage(app.vault.hby, said)
                    if exn:
                        proposals.append({
                            'rid': rid,
                            'said': said,
                            'exn': exn,
                            'pathed': pathed,
                            'datetime': note.datetime
                        })
                except Exception as e:
                    logger.warning(f"Failed to clone multisig rotation proposal {said}: {e}")
    return proposals


class GroupMultisigInceptDoer(doing.DoDoer):
    """
    Doer for asynchronous group multisig identifier inception.

    Handles the complete group identifier creation workflow including:
    - Creating the group hab via hby.makeGroupHab()
    - Creating inception EXN message via grouping.multisigInceptExn()
    - Sending EXN to all participants via postman.send()
    - Starting Counselor escrow processing
    - Signaling completion/progress to UI
    """

    def __init__(self, app, alias, mhab, smids, rmids=None, isith=None, nsith=None,
                 wits=None, toad=0, delpre=None, signal_bridge=None, **kwargs):
        """
        Initialize the GroupMultisigInceptDoer.

        Args:
            app: Application instance with vault
            alias: Alias for the new group identifier
            mhab: Local member hab (Hab instance)
            smids: List of signing member AIDs (qb64 strings)
            rmids: Optional list of rotation member AIDs (defaults to smids)
            isith: Signing threshold (int or str)
            nsith: Next signing threshold (int or str, defaults to isith)
            wits: List of witness AIDs
            toad: Threshold of acceptable duplicity
            delpre: Optional delegator prefix for delegated group
            signal_bridge: DoerSignalBridge for UI communication
            **kwargs: Additional parameters for makeGroupHab
        """
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.mhab = mhab
        self.smids = smids
        self.rmids = rmids if rmids is not None else smids
        self.isith = isith if isith is not None else len(smids)
        self.nsith = nsith if nsith is not None else self.isith
        self.wits = wits or []
        self.toad = toad
        self.delpre = delpre
        self.signal_bridge = signal_bridge
        self.kwargs = kwargs

        # Get vault components
        self.postman = app.vault.postman
        self.counselor = app.vault.counselor

        doers = [doing.doify(self.incept_do)]

        super(GroupMultisigInceptDoer, self).__init__(doers=doers)

    def incept_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for group multisig identifier inception.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        # Enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Signal inception started
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigInceptDoer",
                    event_type="group_inception_started",
                    data={'alias': self.alias, 'smids': self.smids}
                )

            # Step 1: Create group hab
            logger.info(f"Creating group hab '{self.alias}' with smids: {self.smids}")
            ghab = self.hby.makeGroupHab(
                group=self.alias,
                mhab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                isith=self.isith,
                nsith=self.nsith,
                wits=self.wits,
                toad=self.toad,
                delpre=self.delpre,
                **self.kwargs
            )

            # Step 2: Get inception event (partially signed)
            icp = ghab.makeOwnInception(allowPartiallySigned=True)
            serder = SerderKERI(raw=icp)

            logger.info(f"Group hab created with prefix: {ghab.pre}")

            # Step 3: Create EXN message
            exn, atc = keri_grouping.multisigInceptExn(
                hab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                icp=icp,
                delegator=self.delpre
            )

            logger.info(f"Created multisig inception EXN: {exn.said}")

            # Step 4: Send to all other participants
            others = [pre for pre in self.smids if pre != self.mhab.pre]
            for recpt in others:
                self.postman.send(
                    src=self.mhab.pre,
                    dest=recpt,
                    topic="multisig",
                    serder=exn,
                    attachment=atc
                )
                logger.info(f"Sent multisig inception EXN to {recpt}")

            # Signal EXN sent
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigInceptDoer",
                    event_type="group_inception_exn_sent",
                    data={'alias': self.alias, 'pre': ghab.pre, 'recipients': others}
                )

            # Step 5: Start counselor escrow
            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Number(sn=0)
            saider = coring.Diger(qb64=serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, number=seqner, diger=saider)

            logger.info(f"Started counselor escrow for {ghab.pre}")

            # Signal waiting for signatures
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigInceptDoer",
                    event_type="group_inception_waiting",
                    data={'alias': self.alias, 'pre': ghab.pre}
                )

            # Step 6: Wait for completion
            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            # Step 7: Signal success
            logger.info(f"Group identifier {self.alias} ({ghab.pre}) created successfully")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigInceptDoer",
                    event_type="group_identifier_created",
                    data={
                        'alias': self.alias,
                        'pre': ghab.pre,
                        'success': True
                    }
                )

            self.app.vault.remove([self])
            return

        except Exception as e:
            logger.exception(f"GroupMultisigInceptDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigInceptDoer",
                    event_type="group_inception_failed",
                    data={
                        'alias': self.alias,
                        'error': str(e),
                        'success': False
                    }
                )
            self.app.vault.remove([self])
            return


class MultisigJoinDoer(doing.DoDoer):
    """
    Doer for joining an existing multisig group proposal.

    Handles:
    - Joining the group hab via hby.joinGroupHab()
    - Creating response EXN message
    - Sending response to initiator
    - Starting Counselor escrow processing
    - Signaling completion to UI
    """

    def __init__(self, app, alias, proposal_said, mhab, signal_bridge=None):
        """
        Initialize the MultisigJoinDoer.

        Args:
            app: Application instance with vault
            alias: Alias for the group identifier
            proposal_said: SAID of the proposal EXN message
            mhab: Local member hab (Hab instance)
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.signal_bridge = signal_bridge

        # Get vault components
        self.postman = app.vault.postman
        self.counselor = app.vault.counselor

        doers = [doing.doify(self.join_do)]

        super(MultisigJoinDoer, self).__init__(doers=doers)

    def join_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for joining a multisig group proposal.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        # Enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Step 1: Clone the proposal EXN message
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"Could not find proposal EXN: {self.proposal_said}")

            # Extract proposal data
            payload = exn.ked.get('a', {})
            embeds = exn.ked.get('e', {})

            gid = payload.get('gid')
            smids = payload.get('smids', [])
            rmids = payload.get('rmids', smids)
            delegator = payload.get('delegator')

            # Get the inception event from embeds (as SAD/dict, not raw bytes from pathed)
            icp_sad = embeds.get('icp')
            if icp_sad is None:
                raise ValueError("No inception event found in proposal")

            oicp = SerderKERI(sad=icp_sad)

            logger.info(f"Joining group '{self.alias}' with prefix {gid}")

            # Verify local identifier is in smids
            if self.mhab.pre not in smids:
                raise ValueError(f"Local identifier {self.mhab.pre} not in proposal smids")

            # Step 2: Extract initialization parameters from the original inception event
            inits = dict()
            inits["isith"] = oicp.ked["kt"]
            inits["nsith"] = oicp.ked["nt"]
            inits["estOnly"] = kering.TraitCodex.EstOnly in oicp.ked.get("c", [])
            inits["DnD"] = kering.TraitCodex.DoNotDelegate in oicp.ked.get("c", [])
            inits["toad"] = oicp.ked["bt"]
            inits["wits"] = oicp.ked["b"]
            inits["delpre"] = oicp.ked["di"] if "di" in oicp.ked else None

            # Step 3: Create group hab with the same parameters (derives same prefix)
            ghab = self.hby.makeGroupHab(
                group=self.alias,
                mhab=self.mhab,
                smids=smids,
                rmids=rmids,
                **inits
            )

            logger.info(f"Created group hab with prefix: {ghab.pre}")

            # Step 4: Get our own signed version of the inception
            own_icp = ghab.makeOwnInception(allowPartiallySigned=True)
            own_serder = SerderKERI(raw=own_icp)

            # Step 5: Create response EXN
            resp_exn, resp_atc = keri_grouping.multisigInceptExn(
                hab=self.mhab,
                smids=smids,
                rmids=rmids,
                icp=own_icp,
                delegator=delegator
            )

            logger.info(f"Created response EXN: {resp_exn.said}")

            # Step 6: Send to all other participants
            others = [pre for pre in smids if pre != self.mhab.pre]
            for recpt in others:
                self.postman.send(
                    src=self.mhab.pre,
                    dest=recpt,
                    topic="multisig",
                    serder=resp_exn,
                    attachment=resp_atc
                )
                logger.info(f"Sent multisig join response to {recpt}")

            # Step 7: Start counselor escrow
            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Number(sn=0)
            saider = coring.Diger(qb64=own_serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, number=seqner, diger=saider)

            logger.info(f"Started counselor escrow for {ghab.pre}")

            # Signal waiting
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigJoinDoer",
                    event_type="group_join_waiting",
                    data={'alias': self.alias, 'pre': ghab.pre}
                )

            # Step 8: Wait for completion
            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            # Step 9: Signal success
            logger.info(f"Successfully joined group {self.alias} ({ghab.pre})")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigJoinDoer",
                    event_type="group_identifier_joined",
                    data={
                        'alias': self.alias,
                        'pre': ghab.pre,
                        'success': True
                    }
                )

            self.app.vault.remove([self])
            return

        except Exception as e:
            logger.exception(f"MultisigJoinDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigJoinDoer",
                    event_type="group_join_failed",
                    data={
                        'alias': self.alias,
                        'error': str(e),
                        'success': False
                    }
                )
            self.app.vault.remove([self])
            return


class GroupMultisigRotateDoer(doing.DoDoer):
    """
    Doer for initiating a group multisig rotation.

    Mirrors keripy GroupMultisigRotate.rotateDo. Handles:
    - Resolving member key states (verfers/ndigers)
    - Creating the rotation event via ghab.rotate()
    - Creating and sending rotation EXN to all participants
    - Starting Counselor escrow for signature collection
    - Waiting for counselor completion (cgms)
    - Post-counselor witness authentication hooks
    - Signaling progress/completion to UI
    """

    def __init__(self, app, ghab, smids=None, rmids=None, isith=None, nsith=None,
                 toad=None, cuts=None, adds=None, data=None, signal_bridge=None):
        """
        Initialize the GroupMultisigRotateDoer.

        Args:
            app: Application instance with vault
            ghab: GroupHab instance to rotate
            smids: Signing member AIDs (defaults to ghab.smids)
            rmids: Rotation member AIDs (defaults to smids)
            isith: Current signing threshold
            nsith: Next signing threshold
            toad: Witness threshold after rotation
            cuts: List of witness AIDs to remove
            adds: List of witness AIDs to add
            data: Optional list of seal dicts
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hby = app.vault.hby
        self.ghab = ghab
        self.smids = smids
        self.rmids = rmids
        self.isith = isith
        self.nsith = nsith
        self.toad = toad
        self.cuts = cuts if cuts is not None else []
        self.adds = adds if adds is not None else []
        self.data = data
        self.signal_bridge = signal_bridge

        # Get vault components
        self.postman = app.vault.postman
        self.counselor = app.vault.counselor

        doers = [doing.doify(self.rotate_do)]

        super(GroupMultisigRotateDoer, self).__init__(doers=doers)

    def rotate_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for group multisig rotation.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Default smids/rmids to current group members
            if self.smids is None:
                self.smids = self.ghab.smids
            if self.rmids is None:
                self.rmids = self.smids

            # Signal rotation started
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigRotateDoer",
                    event_type="group_rotation_started",
                    data={'alias': self.ghab.name, 'pre': self.ghab.pre, 'smids': self.smids}
                )

            # Step 1: Resolve member key states
            logger.info(f"Resolving member key states for rotation of {self.ghab.name}")
            merfers, migers = resolve_member_key_states(self.hby, self.smids, self.rmids)

            # Step 2: Validate local member is in signing members
            if self.ghab.mhab.pre not in self.smids:
                raise kering.ConfigurationError(
                    f"{self.ghab.mhab.pre} not in signing members {self.smids} for this event"
                )

            # Step 3: Create rotation event
            prefixer = coring.Prefixer(qb64=self.ghab.pre)
            seqner = coring.Number(sn=self.ghab.kever.sn + 1)

            rot = self.ghab.rotate(
                isith=self.isith, nsith=self.nsith,
                toad=self.toad, cuts=list(self.cuts), adds=list(self.adds),
                data=self.data, verfers=merfers, digers=migers
            )

            rserder = SerderKERI(raw=rot)
            logger.info(f"Created group rotation event for {self.ghab.name}, sn={seqner.sn}")

            # Step 4: Create rotation EXN message
            exn, atc = keri_grouping.multisigRotateExn(
                ghab=self.ghab, smids=self.smids, rmids=self.rmids,
                rot=bytearray(rot)
            )

            # Step 5: Send to all other members
            others = list(oset(self.smids + (self.rmids or [])))
            others.remove(self.ghab.mhab.pre)

            for recpt in others:
                self.postman.send(
                    src=self.ghab.mhab.pre, dest=recpt,
                    topic="multisig", serder=exn,
                    attachment=bytearray(atc)
                )
                logger.info(f"Sent multisig rotation EXN to {recpt}")

            # Signal EXN sent
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigRotateDoer",
                    event_type="group_rotation_exn_sent",
                    data={'alias': self.ghab.name, 'pre': self.ghab.pre, 'recipients': others}
                )

            # Step 6: Start counselor escrow
            self.counselor.start(
                ghab=self.ghab, prefixer=prefixer, number=seqner,
                diger=coring.Diger(qb64=rserder.said)
            )
            logger.info(f"Started counselor escrow for rotation of {self.ghab.pre}")

            # Step 7: Wait for counselor completion
            while True:
                saider = self.hby.db.cgms.get(keys=(self.ghab.pre, seqner.qb64))
                if saider is not None:
                    break
                yield self.tock

            # Step 8: Handle delegation if present
            if self.ghab.kever.delpre:
                yield from self.postman.sendEventToDelegator(
                    hab=self.ghab, sender=self.ghab.mhab, fn=self.ghab.kever.sn
                )

            # Step 9: Check for shared witnesses needing authentication
            shared_witnesses = get_shared_witnesses(self.ghab)
            needs_witness_auth = len(shared_witnesses) > 0

            if needs_witness_auth:
                identifier_meta_info = IdentifierMetaInfo(prefix=self.ghab.pre, auth_pending=True)
                self.app.vault.db.idm.pin(keys=(self.ghab.pre,), val=identifier_meta_info)
                logger.info(f"Set auth_pending=True for {self.ghab.pre} ({len(shared_witnesses)} shared witnesses)")

            # Step 10: Signal success
            logger.info(f"Group rotation complete for {self.ghab.name} ({self.ghab.pre})")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigRotateDoer",
                    event_type="group_rotation_complete",
                    data={
                        'alias': self.ghab.name,
                        'pre': self.ghab.pre,
                        'sn': self.ghab.kever.sn,
                        'success': True,
                        'shared_witnesses': shared_witnesses,
                        'needs_witness_auth': needs_witness_auth
                    }
                )

            self.app.vault.remove([self])
            return

        except Exception as e:
            logger.exception(f"GroupMultisigRotateDoer failed: {e}")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="GroupMultisigRotateDoer",
                    event_type="group_rotation_failed",
                    data={
                        'alias': self.ghab.name if self.ghab else None,
                        'pre': self.ghab.pre if self.ghab else None,
                        'error': str(e),
                        'success': False
                    }
                )
            self.app.vault.remove([self])
            return


class MultisigRotationJoinDoer(doing.DoDoer):
    """
    Doer for joining a group multisig rotation proposal.

    Mirrors keripy JoinDoer.rotate(). Handles:
    - Cloning the rotation proposal EXN
    - Applying the rotation event via ghab.rotate(serder=orot)
    - Creating and sending response EXN
    - Starting Counselor escrow
    - Waiting for counselor completion
    - Signaling progress/completion to UI
    """

    def __init__(self, app, proposal_said, mhab, group_alias=None, signal_bridge=None):
        """
        Initialize the MultisigRotationJoinDoer.

        Args:
            app: Application instance with vault
            proposal_said: SAID of the rotation proposal EXN message
            mhab: Local member hab
            group_alias: Optional alias for the group (only if group not yet known locally)
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hby = app.vault.hby
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.group_alias = group_alias
        self.signal_bridge = signal_bridge

        # Get vault components
        self.postman = app.vault.postman
        self.counselor = app.vault.counselor

        doers = [doing.doify(self.join_rotate_do)]

        super(MultisigRotationJoinDoer, self).__init__(doers=doers)

    def join_rotate_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for joining a multisig rotation.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Step 1: Clone the rotation proposal EXN
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"Could not find rotation proposal EXN: {self.proposal_said}")

            # Step 2: Extract payload and embedded rotation event
            payload = exn.ked['a']
            smids = payload['smids']
            rmids = payload['rmids']

            embeds = exn.ked['e']
            orot = SerderKERI(sad=embeds['rot'])

            pre = orot.ked['i']
            logger.info(f"Joining group rotation for {pre}, sn={orot.sn}")

            # Step 3: Validate local member is in members
            both = list(set(smids + (rmids or [])))
            if self.mhab.pre not in both:
                raise ValueError(f"Local identifier {self.mhab.pre} not in rotation members {both}")

            # Step 4: Find or create group hab
            if pre in self.hby.habs:
                ghab = self.hby.habs[pre]
            else:
                if not self.group_alias:
                    raise ValueError(f"Group {pre} not found locally and no alias provided")
                ghab = self.hby.joinGroupHab(
                    pre, group=self.group_alias, mhab=self.mhab,
                    smids=smids, rmids=rmids
                )
                logger.info(f"Created local group hab {self.group_alias} for {pre}")

            # Step 5: Apply rotation event (joiner path - signs and processes)
            ghab.rotate(serder=orot, smids=smids, rmids=rmids)

            # Step 6: Get own partially signed event
            rot = ghab.makeOwnEvent(allowPartiallySigned=True, sn=orot.sn)

            # Step 7: Create response EXN
            resp_exn, resp_atc = keri_grouping.multisigRotateExn(
                ghab, smids=ghab.smids, rmids=ghab.rmids, rot=rot
            )

            # Step 8: Send to all other members
            others = list(oset(smids + (rmids or [])))
            others.remove(ghab.mhab.pre)

            for recpt in others:
                self.postman.send(
                    src=ghab.mhab.pre, dest=recpt,
                    topic="multisig", serder=resp_exn,
                    attachment=resp_atc
                )
                logger.info(f"Sent multisig rotation join response to {recpt}")

            # Step 9: Start counselor escrow
            serder = SerderKERI(raw=rot)
            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Number(sn=serder.sn)

            self.counselor.start(
                ghab=ghab, prefixer=prefixer, number=seqner,
                diger=coring.Diger(qb64=serder.said)
            )
            logger.info(f"Started counselor escrow for rotation join of {ghab.pre}")

            # Signal waiting
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigRotationJoinDoer",
                    event_type="group_rotation_join_waiting",
                    data={'alias': ghab.name, 'pre': ghab.pre}
                )

            # Step 10: Wait for counselor completion
            while True:
                saider = self.hby.db.cgms.get(keys=(ghab.pre, seqner.qb64))
                if saider is not None:
                    break
                yield self.tock

            # Step 11: Check for shared witnesses
            shared_witnesses = get_shared_witnesses(ghab)
            needs_witness_auth = len(shared_witnesses) > 0

            if needs_witness_auth:
                identifier_meta_info = IdentifierMetaInfo(prefix=ghab.pre, auth_pending=True)
                self.app.vault.db.idm.pin(keys=(ghab.pre,), val=identifier_meta_info)

            # Step 12: Signal success
            logger.info(f"Successfully joined group rotation for {ghab.name} ({ghab.pre})")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigRotationJoinDoer",
                    event_type="group_rotation_joined",
                    data={
                        'alias': ghab.name,
                        'pre': ghab.pre,
                        'sn': ghab.kever.sn,
                        'success': True,
                        'shared_witnesses': shared_witnesses,
                        'needs_witness_auth': needs_witness_auth
                    }
                )

            self.app.vault.remove([self])
            return

        except Exception as e:
            logger.exception(f"MultisigRotationJoinDoer failed: {e}")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="MultisigRotationJoinDoer",
                    event_type="group_rotation_join_failed",
                    data={
                        'error': str(e),
                        'success': False
                    }
                )
            self.app.vault.remove([self])
            return


def get_pending_multisig_proposals(app):
    """
    Get all pending multisig inception proposals from notifier.

    Args:
        app: Application instance with vault

    Returns:
        list: List of proposal dicts with rid, said, exn, datetime keys
    """
    proposals = []
    for (dt, rid), note in app.vault.notifier.noter.notes.getTopItemIter():
        route = note.pad.get('a', {}).get('r', '')
        if '/multisig/icp' in route and not note.read:
            said = note.attrs.get('d', '')
            if said:
                try:
                    exn, pathed = exchanging.cloneMessage(app.vault.hby, said)
                    if exn:
                        proposals.append({
                            'rid': rid,
                            'said': said,
                            'exn': exn,
                            'pathed': pathed,
                            'datetime': note.datetime
                        })
                except Exception as e:
                    logger.warning(f"Failed to clone multisig proposal {said}: {e}")
    return proposals


def check_pending_multisig(app, hab):
    """
    Check if a group identifier has pending signatures.

    Args:
        app: Application instance with vault
        hab: Habery instance (identifier)

    Returns:
        bool: True if identifier has pending signatures
    """
    if not isinstance(hab, keri_habbing.GroupHab):
        return False
    try:
        pending = True if app.vault.hby.db.gpse.get(keys=(hab.pre,)) else False
        return pending
    except Exception as e:
        logger.warning(f"Failed to check pending multisig for {hab.pre}: {e}")
        return False


class CounselingCompletionDoer(doing.DoDoer):
    """
    Doer that resumes waiting for counselor completion on vault restart.

    Used for both inception (sn=0) and rotation (sn>0) events.
    Emits a generic 'group_counseling_complete' event when done.
    """

    def __init__(self, vault, prefixer, seqner, ghab):
        """
        Initialize the CounselingCompletionDoer.

        Args:
            vault: Vault instance
            prefixer: Prefixer for the group identifier
            seqner: Seqner for the event sequence number
            ghab: GroupHab instance
        """
        self.vault = vault
        self.counselor = self.vault.counselor
        self.prefixer = prefixer
        self.seqner = seqner
        self.ghab = ghab
        self.signal_bridge = self.vault.signals

        doers = [doing.doify(self.complete_counseling_do)]

        super(CounselingCompletionDoer, self).__init__(doers=doers)

    def complete_counseling_do(self, tymth, tock=0.0, **opts):

        # Enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        # Maybe we need self.counselor.start() here?

        while not self.counselor.complete(self.prefixer, self.seqner):
            yield self.tock

        logger.info(f"Counseling complete for {self.ghab.name} ({self.ghab.pre}), sn={self.seqner.sn}")

        if self.ghab.pre not in self.vault.hby.prefixes:
            kever = self.vault.hby.kevers[self.ghab.pre]
            if len(kever.wits) == 0: # Prevents receiptor error when there are no witnesses
                self.vault.hby.prefixes.add(self.ghab.pre)

        if self.signal_bridge:
            logger.info(f"Signaling completion of counseling for {self.ghab.name}")
            data = {
                'alias': self.ghab.name,
                'pre': self.ghab.pre,
                'sn': self.seqner.sn,
                'success': True
            }

            # For rotation completions (sn > 0), include shared witness info
            if self.seqner.sn > 0:
                shared_witnesses = get_shared_witnesses(self.ghab)
                data['shared_witnesses'] = shared_witnesses
                data['needs_witness_auth'] = len(shared_witnesses) > 0

                if shared_witnesses:
                    identifier_meta_info = IdentifierMetaInfo(prefix=self.ghab.pre, auth_pending=True)
                    self.vault.db.idm.pin(keys=(self.ghab.pre,), val=identifier_meta_info)

            # Emit generic counseling completion event
            self.signal_bridge.emit_doer_event(
                doer_name="CounselingCompletionDoer",
                event_type="group_counseling_complete",
                data=data
            )

        self.vault.remove([self])
        return
