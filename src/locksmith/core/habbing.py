# -*- encoding: utf-8 -*-
"""
locksmith.core.habs module

Functions for working with KERI Haberies (habbing instances)
"""
from hio.base import doing
from keri import help
from keri import kering
from keri.app import habbing, keeping, delegating
from keri.core import coring, signing
from keri.core.serdering import SerderKERI
from keri.vdr import credentialing

from locksmith.core.vaulting import run_vault_controller
from locksmith.core.grouping import GroupMultisigInceptDoer

logger = help.ogler.getLogger(__name__)


def format_bran(bran):
    """
    Format bran (passcode) by removing dashes.

    Args:
        bran (str): The passcode to format

    Returns:
        str: Formatted passcode
    """
    if bran:
        bran = bran.replace('-', '')
    return bran


def check_passcode(name, base, bran, salt=None, tier=None, pidx=None, algo=None, seed=None):
    """
    Check if a passcode is valid for a given keystore.

    Args:
        name (str): Name of the keystore
        base (str): Base directory for the keystore
        bran (str): Passcode
        salt (str, optional): Salt for signing keys
        tier (str, optional): Tier for key derivation
        pidx (int, optional): Path index
        algo (str, optional): Algorithm
        seed (str, optional): Seed

    Raises:
        kering.AuthError: If passcode is incorrect
        ValueError: If bran is too short
    """
    ks = keeping.Keeper(name=name, base=base, temp=False, reopen=True)
    aeid = ks.gbls.get('aeid')

    if bran and not seed:  # create seed from stretch of bran as salt
        if len(bran) < 21:
            raise ValueError('Bran (passcode seed material) too short.')
        bran = coring.MtrDex.Salt_128 + 'A' + bran[:21]  # qb64 salt for seed
        signer = signing.Salter(qb64=bran).signer(transferable=False, tier=None, temp=None)
        seed = signer.qb64
        if not aeid:  # aeid must not be empty event on initial creation
            aeid = signer.verfer.qb64  # lest it remove encryption

    if salt is None:  # salt for signing keys not aeid seed
        salt = signing.Salter(raw=b'0123456789abcdef').qb64
    else:
        # If salt is the default hex string from config, treat as raw bytes
        if salt == "0123456789abcdef":
            salt = signing.Salter(raw=b'0123456789abcdef').qb64
        else:
            try:
                salt = signing.Salter(qb64=salt).qb64
            except kering.UnexpectedCodeError:
                # Fallback: try treating as raw bytes if qb64 fails
                # This handles cases where config might have a raw string that looks like code
                if isinstance(salt, str):
                   salt = signing.Salter(raw=salt.encode("utf-8")).qb64
                else:
                   salt = signing.Salter(raw=salt).qb64

    try:
        keeping.Manager(ks=ks, seed=seed, aeid=aeid, pidx=pidx, algo=algo, salt=salt, tier=tier)
    except kering.AuthError as ex:
        raise ex
    finally:
        ks.close()


def open_hby(name, base, bran, app, salt=None):
    """
    Opens a Habery and creates a Vault with running QtTask.

    Args:
        name (str): Name of the habery
        base (str): Base directory
        bran (str): Passcode
        app (LocksmithApplication): Application instance
        salt (str, optional): Salt for signing keys

    Returns:
        tuple: (vault, qtask) - Vault instance and QtTask instance

    Raises:
        kering.AuthError: If authentication fails
        ValueError: If habery opening fails
    """
    # Handle salt configuration
    if salt is None:
        salt = signing.Salter(raw=b'0123456789abcdef').qb64
    else:
        # If salt is the default hex string from config, treat as raw bytes
        if salt == "0123456789abcdef":
            salt = signing.Salter(raw=b'0123456789abcdef').qb64
        else:
            try:
                # check if it is already valid qb64
                salt = signing.Salter(qb64=salt).qb64
            except kering.UnexpectedCodeError:
                # Fallback: try treating as raw bytes if qb64 fails
                if isinstance(salt, str):
                    salt = signing.Salter(raw=salt.encode("utf-8")).qb64
                else:
                    salt = signing.Salter(raw=salt).qb64

    try:
        hby = habbing.Habery(name=name, bran=bran, free=True, cf=None, base=base, salt=salt)
    except kering.AuthError:
        logger.error(f'Passcode incorrect for {name}')
        raise
    except ValueError:
        logger.error(f'Open Habery failed on ValueError for {name}')
        raise
    rgy = credentialing.Regery(hby=hby, name=hby.name, base=base, temp=False)
    return run_vault_controller(app=app, hby=hby, rgy=rgy)


def keystore_exists(name, base):
    """
    Checks if the keystore exists.

    Args:
        name (str): Name of the keystore
        base (str): Base directory

    Returns:
        bool: True if keystore exists, False otherwise
    """
    ks = keeping.Keeper(name=name, base=base, temp=False, reopen=True)
    aeid = ks.gbls.get('aeid')
    exists = aeid is not None
    ks.close()
    return exists


def is_vault_encrypted(name, base):
    """
    Checks if the vault is encrypted (has a non-empty AEID).

    Args:
        name (str): Name of the keystore
        base (str): Base directory

    Returns:
        bool: True if encrypted, False otherwise
    """
    ks = keeping.Keeper(name=name, base=base, temp=False, reopen=True)
    aeid = ks.gbls.get('aeid')
    
    # Check if aeid is present and not empty
    # In KERI, unencrypted vaults might have empty string or None for aeid
    is_encrypted = False
    if aeid:
        if isinstance(aeid, bytes):
            is_encrypted = len(aeid) > 0
        else:
            is_encrypted = len(str(aeid)) > 0
            
    ks.close()
    return is_encrypted


def load_potential_delegators(app, delegation_type='local'):
    """
    Load potential delegators for identifier delegation.

    Args:
        app: Application instance with vault
        delegation_type: 'local' or 'remote'

    Returns:
        list: List of dicts with 'id', 'alias' keys for potential delegators
    """
    from keri.app import organizing

    delegators = []

    if delegation_type == 'local':
        # Load local identifiers that can be delegators
        for name, pre in app.vault.hby.habs.items():
            delegators.append({
                'id': pre.pre,
                'alias': name
            })
    else:  # remote
        # Load remote identifiers that can be delegators
        org = organizing.Organizer(hby=app.vault.hby)
        remote_ids = org.list()
        kevers = app.vault.hby.kevers

        # Filter to only transferable identifiers
        for remote_id in remote_ids:
            rid = remote_id['id']
            if rid in kevers and kevers[rid].transferable:
                delegators.append({
                    'id': rid,
                    'alias': remote_id.get('alias', '')
                })

    return delegators


def load_potential_proxies(app):
    """
    Load potential proxies for remote delegation.
    Proxies are local identifiers that can sign on behalf of the delegatee.

    Args:
        app: Application instance with vault

    Returns:
        list: List of dicts with 'id', 'alias' keys for potential proxies
    """
    proxies = []
    for name, hab in app.vault.hby.habs.items():
        proxies.append({
            'id': hab.pre,
            'alias': name
        })
    return proxies


def get_local_identifiers_for_dropdown(app):
    """
    Load identifiers.

    Args:
        app: Application instance with vault

    Returns:
        dict: Dict of identifier information keyed by to_string
    """
    identifiers = {}
    # Load local identifiers
    for aid, hab in app.vault.hby.habs.items():
        identifiers[f"{hab.name} - {aid}"] = {
            'aid': aid,
            'alias': hab.name
        }

    return identifiers


def list_eligible_local_identifiers(app):
    """
    List root-namespace, non-group local identifiers.

    Args:
        app: Application instance with an open vault

    Returns:
        list: List of dicts with ``alias`` and ``prefix`` keys
    """
    identifiers = []

    if not app or not hasattr(app, 'vault') or not app.vault or not getattr(app.vault, 'hby', None):
        logger.info("Eligible local identifier load skipped: vault or habery unavailable")
        return identifiers

    logger.info("Loading eligible local identifiers")

    hby = app.vault.hby
    for (ns, alias), prefix in hby.db.names.getTopItemIter(keys=()):
        if ns != "":
            continue

        hab = hby.habByName(alias)
        if hab is None:
            logger.warning(f"Skipping eligible local identifier entry with missing hab: alias={alias}")
            continue

        if isinstance(hab, habbing.GroupHab):
            logger.debug(f"Skipping group identifier from eligible local identifier list: {alias}")
            continue

        identifiers.append({
            'alias': alias,
            'prefix': prefix,
        })

    logger.info(f"Loaded {len(identifiers)} eligible local identifiers")
    return identifiers


def get_local_non_multisig_identifiers_for_dropdown(app):
    """
    Load identifiers.

    Args:
        app: Application instance with vault

    Returns:
        dict: Dict of identifier information keyed by to_string
    """
    identifiers = {}
    for identifier in list_eligible_local_identifiers(app):
        identifiers[f"{identifier['alias']} - {identifier['prefix']}"] = {
            'aid': identifier['prefix'],
            'alias': identifier['alias']
        }
    return identifiers


def load_group_members(app):
    """
    Load members for group multisig identifier creation.

    Args:
        app: Application instance with members list

    Returns:
        list: List of dicts with member information
    """
    if not hasattr(app, 'members') or not app.members:
        return []

    return [
        {
            'id': m['id'],
            'alias': m['alias'],
            'index': idx
        }
        for idx, m in enumerate(app.members)
    ]


def create_identifier(app, alias, key_type='salty', **kwargs):
    """
    Create a new identifier with the specified parameters.

    Args:
        app: Application instance with vault
        alias: Alias name for the identifier
        key_type: Type of keys ('salty', 'randy', or 'group')
        **kwargs: Additional parameters:
            - salt: Salt for key chain (salty type)
            - icount: Number of signing keys
            - isith: Signing threshold
            - ncount: Number of rotation keys
            - nsith: Rotation threshold
            - smids: Signing member IDs (group type)
            - rmids: Rotation member IDs (group type)
            - wits: List of witness IDs
            - toad: Threshold of acceptable duplicity
            - estOnly: Establishment only flag
            - DnD: Do not delegate flag
            - delpre: Delegator prefix (for delegation)
            - delegation_type: 'none', 'local', or 'remote'
            - proxy_alias: Proxy identifier alias (for remote delegation)

    Returns:
        dict: Result with 'success' bool, 'message' str, and optionally 'pre' (identifier prefix)
    """
    try:
        # Validate alias
        if not alias or alias == '':
            return {'success': False, 'message': 'Alias is required'}

        # Build kwargs for identifier creation
        creation_kwargs = {
            'algo': key_type,
            'estOnly': kwargs.get('estOnly', False),
            'DnD': kwargs.get('DnD', False),
            'wits': kwargs.get('wits', []),
            'toad': kwargs.get('toad', '0'),
        }

        # Add delegator if specified
        if kwargs.get('delpre'):
            creation_kwargs['delpre'] = kwargs['delpre']

        # Handle different key types
        if key_type == 'salty':
            # Key chain with salt
            salt = kwargs.get('salt')
            if not salt or len(salt) != 21:
                return {'success': False, 'message': 'Salt is required and must be 21 characters long'}

            creation_kwargs['salt'] = signing.Salter(raw=salt.encode('utf-8')).qb64
            creation_kwargs['icount'] = int(kwargs.get('icount', 1))
            creation_kwargs['isith'] = int(kwargs.get('isith', 1))
            creation_kwargs['ncount'] = int(kwargs.get('ncount', 1))
            creation_kwargs['nsith'] = int(kwargs.get('nsith', 1))

        elif key_type == 'randy':
            # Random keys
            creation_kwargs['salt'] = None
            creation_kwargs['icount'] = int(kwargs.get('icount', 1))
            creation_kwargs['isith'] = int(kwargs.get('isith', 1))
            creation_kwargs['ncount'] = int(kwargs.get('ncount', 1))
            creation_kwargs['nsith'] = int(kwargs.get('nsith', 1))

        elif key_type == 'group':
            # Group multisig
            creation_kwargs['isith'] = int(kwargs.get('isith', 1))
            creation_kwargs['nsith'] = int(kwargs.get('nsith', 1))

            smids = kwargs.get('smids', [])
            rmids = kwargs.get('rmids', smids)  # Default to smids if not specified

            if not smids:
                return {'success': False, 'message': 'Signing members are required for group multisig'}

            creation_kwargs['smids'] = smids
            creation_kwargs['rmids'] = rmids

        else:
            return {'success': False, 'message': f'Unknown key type: {key_type}'}

        # Get delegation type
        delegation_type = kwargs.get('delegation_type', 'none')

        # Handle different delegation scenarios
        if key_type == 'group':
            # Group multisig creation using GroupMultisigInceptDoer
            smids = creation_kwargs.get('smids', [])
            rmids = creation_kwargs.get('rmids', smids)
            isith = creation_kwargs.get('isith', len(smids))
            nsith = creation_kwargs.get('nsith', isith)

            # Get mhab from mhab_alias parameter
            mhab_alias = kwargs.get('mhab_alias')
            if not mhab_alias:
                return {'success': False, 'message': 'Local member identifier (mhab_alias) is required for group multisig'}

            mhab = app.vault.hby.habByName(mhab_alias)
            if not mhab:
                return {'success': False, 'message': f"Local identifier '{mhab_alias}' not found"}

            # Create and launch GroupMultisigInceptDoer
            group_incept_doer = GroupMultisigInceptDoer(
                app=app,
                alias=alias,
                mhab=mhab,
                smids=smids,
                rmids=rmids,
                isith=isith,
                nsith=nsith,
                wits=creation_kwargs.get('wits', []),
                toad=int(creation_kwargs.get('toad', 0)),
                delpre=creation_kwargs.get('delpre'),
                signal_bridge=app.vault.signals
            )
            app.vault.extend([group_incept_doer])

            return {
                'success': True,
                'message': f'Creating group identifier, waiting for multisig collaboration...',
                'async': True
            }

        elif delegation_type == 'remote' or delegation_type == 'none':
            # Remote delegation or no delegation - use InceptDoer for async handling
            proxy_alias = kwargs.get('proxy_alias')
            proxy = app.vault.hby.habByName(proxy_alias) if proxy_alias else None

            # Create and launch InceptDoer
            incept_doer = InceptDoer(
                app=app,
                alias=alias,
                proxy=proxy,
                signal_bridge=app.vault.signals,
                **creation_kwargs
            )
            app.vault.extend([incept_doer])

            return {
                'success': True,
                'message': f'Creating identifier...',
                'async': True
            }

        elif delegation_type == 'local':
            # Local delegation - synchronous creation
            from keri.db import dbing

            hab = app.vault.hby.makeHab(name=alias, **creation_kwargs)
            serder, _, _ = hab.getOwnEvent(sn=0)

            if creation_kwargs.get('delpre'):
                delegator_hab = app.vault.hby.habByPre(creation_kwargs['delpre'])
                anchor = dict(i=hab.pre, s="0", d=hab.pre)
                delegator_hab.interact(data=[anchor])
                seqner = coring.Seqner(sn=delegator_hab.kever.serder.sn)
                couple = seqner.qb64b + delegator_hab.kever.serder.saidb
                dgkey = dbing.dgKey(anchor['i'], anchor['d'])
                app.vault.hby.db.setAes(dgkey, couple)

            return {
                'success': True,
                'message': f'Identifier {hab.pre} created successfully',
                'pre': hab.pre
            }

    except Exception as e:
        logger.exception(f"Error creating identifier: {e}")
        return {
            'success': False,
            'message': f'Error creating identifier: {str(e)}'
        }


def delete_identifier(app, alias):
    """
    Delete an identifier with the specified alias.

    Args:
        app: Application instance with vault
        alias: Alias name of the identifier to delete

    Returns:
        dict: Result with 'success' bool and 'message' str
    """
    try:
        # Validate alias
        if not alias or alias == '':
            return {'success': False, 'message': 'Alias is required'}

        hab = app.hby.habByName(alias)
        pre = hab.pre

        if type(hab) == habbing.GroupHab:
            # Remove an incomplete multisig group from all escrows.
            try:
                app.vault.remove([app.vault.counseling_completion_doers[pre]])
            except Exception as e:
                logger.warning(f"Attempted to remove counseling completion doer for group identifier: {e}")

            # 1. Group Partially Signed Escrow
            app.vault.hby.db.gpse.rem(keys=(pre,))

            # 2. Group Delegatee Escrow
            app.vault.hby.db.gdee.rem(keys=(pre,))

            # 3. Group Partial Witness Escrow
            app.vault.hby.db.gpwe.rem(keys=(pre,))

            # 4. Completed Group Multisig markers (if any partial completion exists)
            #    This is keyed by (pre, seqner.qb64), so you may need to iterate:
            for keys, saider in app.vault.hby.db.cgms.getTopItemIter(keys=(pre,)):
                app.vault.hby.db.cgms.rem(keys=keys)

            try:
                app.vault.hby.deleteHab(alias)
            except KeyError as e:
                logger.warning(f"Attempted to delete group identifier. This message is expected ONLY when deleting "
                               f"group identifiers with incomplete inception signatures: {e}")

        else:
            app.vault.hby.deleteHab(alias)

        # Emit signal if signal bridge is available
        if hasattr(app.vault, 'signals') and app.vault.signals:
            app.vault.signals.emit_doer_event(
                doer_name="DeleteIdentifier",
                event_type="identifier_deleted",
                data={
                    'alias': alias,
                    'success': True
                }
            )

        logger.info(f"Identifier '{alias}' deleted successfully")
        return {
            'success': True,
            'message': f"Identifier '{alias}' deleted successfully"
        }

    except Exception as e:
        logger.exception(f"Error deleting identifier: {e}")
        return {
            'success': False,
            'message': f'Error deleting identifier: {str(e)}'
        }


class InceptDoer(doing.DoDoer):
    """
    Doer for asynchronous identifier inception with delegation and witness support.

    Handles the complete identifier creation workflow including:
    - Creating the identifier
    - Waiting for witness receipts
    - Waiting for delegation approval (if delegated)
    - Sending events to delegator
    - Signaling completion to UI
    """

    def __init__(self, app, alias, proxy=None, signal_bridge=None, **kwargs):
        """
        Initialize the InceptDoer.

        Args:
            app: Application instance with vault
            alias: Alias for the new identifier
            proxy: Optional proxy hab for delegation
            signal_bridge: DoerSignalBridge for UI communication
            **kwargs: Parameters for identifier creation
        """
        self.app = app
        self.hby = self.app.vault.hby
        self.alias = alias
        self.proxy = proxy
        self.signal_bridge = signal_bridge
        self.creation_kwargs = kwargs

        # Setup doers
        self.swain = delegating.Anchorer(hby=self.hby, proxy=self.proxy)
        self.postman = self.app.vault.postman

        doers = [self.swain, doing.doify(self.incept_do)]

        super(InceptDoer, self).__init__(doers=doers)

    def incept_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for identifier inception.

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
            # Create the identifier
            hab = self.hby.makeHab(name=self.alias, **self.creation_kwargs)

            # Get witness and receiptor doers from vault
            wit_doer = self.app.vault.witDoer

            # Handle delegation if present
            if hab.kever.delpre:
                logger.info(f"Waiting for delegation approval for {hab.pre}...")
                self.swain.delegation(pre=hab.pre, sn=0)

                # Wait for delegation to complete
                while not self.swain.complete(hab.kever.prefixer, coring.Seqner(sn=hab.kever.sn)):
                    yield self.tock

            # Handle witness receipts if present
            elif hab.kever.wits:
                logger.info(f"Waiting for witness receipts for {hab.pre}...")
                wit_doer.msgs.append(dict(pre=hab.pre))

                # Wait for witness receipts
                while not wit_doer.cues:
                    _ = yield self.tock

            # Send event to delegator if needed
            if hab.kever.delpre:
                sender = self.proxy if self.proxy is not None else hab
                yield from self.postman.sendEventToDelegator(hab=hab, sender=sender, fn=hab.kever.sn)

            # Cleanup
            to_remove = [self.swain]
            self.remove(to_remove)

            # Signal success to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="InceptDoer",
                    event_type="identifier_created",
                    data={
                        'alias': self.alias,
                        'pre': hab.pre,
                        'success': True
                    }
                )

            logger.info(f"Identifier {self.alias} ({hab.pre}) created successfully")
            self.app.vault.remove([self])
            return

        except Exception as e:
            logger.exception(f"InceptDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="InceptDoer",
                    event_type="identifier_creation_failed",
                    data={
                        'alias': self.alias,
                        'error': str(e),
                        'success': False
                    }
                )
            self.app.vault.remove([self])
            return


def get_identifier_details(app, hab):
    """
    Get detailed information about an identifier.

    Args:
        app: Application instance with vault
        hab: Habery instance (identifier)

    Returns:
        dict: Identifier details including:
            - pre: Identifier prefix
            - alias: Identifier alias
            - kel: Key Event Log (string)
            - key_type: Type description string
            - is_group_multisig: Boolean
            - do_not_delegate: Boolean
            - sequence_number: Current sequence number
            - witnesses: List of witness prefixes
            - witness_count: Number of witnesses
            - witness_receipts: Number of receipts received
            - witness_threshold: Witness threshold
            - public_keys: List of public key strings
            - needs_resubmit: Whether resubmit is needed
    """
    from keri.app import habbing as keri_habbing
    from keri.app.keeping import Algos
    from keri.db import dbing

    kever = hab.kever
    ser = kever.serder

    # Determine key type
    if isinstance(hab, keri_habbing.GroupHab):
        key_type = "Group Multisig Identifier"
        is_group_multisig = True
    elif hasattr(hab, 'algo'):
        if hab.algo == Algos.salty:
            key_type = "Hierarchical Key Chain Identifier"
        elif hab.algo == Algos.randy:
            key_type = "Random Key Generation Identifier"
        else:
            key_type = "Unknown"
        is_group_multisig = False
    else:
        key_type = "Unknown"
        is_group_multisig = False

    # Get Key Event Log
    kel = bytearray()
    for msg in hab.db.clonePreIter(pre=hab.pre):
        kel.extend(msg)
    kel_str = str(kel)[12:-2] if len(kel) > 14 else str(kel)

    pretty_kel = ""
    for msg in hab.db.clonePreIter(pre=hab.pre):
        serder = SerderKERI(raw=msg)
        attachments = msg[serder.size:]

        pretty_kel += f"{serder.pretty()}\n{attachments.decode('utf-8')}\n\n"

    # Get witness receipts
    dgkey = dbing.dgKey(ser.preb, ser.saidb)
    wigs = hab.db.getWigs(dgkey)

    # Check if resubmit is needed
    needs_resubmit = len(kever.wits) != len(wigs) if len(kever.wits) > 0 else False

    # Get public keys
    public_keys = [verfer.qb64 for verfer in kever.verfers]

    # Get Do Not Delegate flag
    do_not_delegate = kever.serder.ked.get("c", False)

    return {
        'pre': hab.pre,
        'alias': hab.name,
        'kel': kel_str,
        'pretty_kel': pretty_kel,
        'key_type': key_type,
        'is_group_multisig': is_group_multisig,
        'do_not_delegate': do_not_delegate,
        'sequence_number': kever.sner.num,
        'witnesses': list(kever.wits),
        'witness_count': len(kever.wits),
        'witness_receipts': len(wigs),
        'witness_threshold': kever.toader.num,
        'public_keys': public_keys,
        'needs_resubmit': needs_resubmit
    }


def generate_oobi(app, hab, role='witness'):
    """
    Generate OOBI URL and QR code for an identifier.

    Args:
        app: Application instance
        hab: Habery instance (identifier)
        role: Role type ('witness', 'controller', 'mailbox')

    Returns:
        dict: Result with 'success' bool, 'oobi' URL string, 'qr_code' base64 string
    """
    import random
    import io
    import base64
    from urllib.parse import urljoin, urlparse
    try:
        import qrcode
    except ImportError:
        qrcode = None
        logger.warning("qrcode library not installed, QR code generation will be skipped")

    try:
        oobis = []

        if role == 'witness':
            # Fetch URL OOBIs for all witnesses
            for wit in hab.kever.wits:
                urls = hab.fetchUrls(eid=wit, scheme=kering.Schemes.http) or hab.fetchUrls(
                    eid=wit, scheme=kering.Schemes.https
                )
                if not urls:
                    continue

                url = urls[kering.Schemes.http] if kering.Schemes.http in urls else urls.get(kering.Schemes.https)
                if url:
                    up = urlparse(url)
                    oobis.append(urljoin(up.geturl(), f'/oobi/{hab.pre}/witness/{wit}'))

        elif role == 'controller':
            # Fetch controller URL OOBIs
            urls = hab.fetchUrls(eid=hab.pre, scheme=kering.Schemes.http) or hab.fetchUrls(
                eid=hab.pre, scheme=kering.Schemes.https
            )
            if urls:
                url = urls[kering.Schemes.http] if kering.Schemes.http in urls else urls.get(kering.Schemes.https)
                if url:
                    up = urlparse(url)
                    oobis.append(urljoin(up.geturl(), f'/oobi/{hab.pre}/controller'))

        elif role == 'mailbox':
            # Fetch agent/mailbox URL OOBIs
            roleUrls = hab.fetchRoleUrls(
                hab.pre, scheme=kering.Schemes.http, role=kering.Roles.agent
            ) or hab.fetchRoleUrls(hab.pre, scheme=kering.Schemes.https, role=kering.Roles.agent)

            if roleUrls and 'agent' in roleUrls:
                for eid, urls in roleUrls['agent'].items():
                    url = urls[kering.Schemes.http] if kering.Schemes.http in urls else urls.get(kering.Schemes.https)
                    if url:
                        up = urlparse(url)
                        oobis.append(urljoin(up.geturl(), f'/oobi/{hab.pre}/agent/{eid}'))

        if not oobis:
            return {
                'success': False,
                'oobi': None,
                'qr_code': None,
                'message': f'No {role} OOBIs available'
            }

        # Select random OOBI if multiple available
        oobi_url = random.choice(oobis)

        # Generate QR code
        qr_code_base64 = None
        if qrcode:
            try:
                img = qrcode.make(oobi_url)
                f = io.BytesIO()
                img.save(f, format='PNG')
                f.seek(0)
                qr_code_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                logger.warning(f"Failed to generate QR code: {e}")

        return {
            'success': True,
            'oobi': oobi_url,
            'qr_code': qr_code_base64
        }

    except Exception as e:
        logger.exception(f"Error generating OOBI: {e}")
        return {
            'success': False,
            'oobi': None,
            'qr_code': None,
            'message': str(e)
        }


def get_delegates_awaiting_approval(app, hab):
    """
    Get list of delegates awaiting approval for an identifier.

    Args:
        app: Application instance with vault
        hab: Habery instance (identifier)

    Returns:
        list: List of dicts with delegate information:
            - pre: Delegate prefix
            - sn: Sequence number
            - edig: Event digest
    """
    delegates = []

    try:
        for (pre, sn), edig in app.vault.hby.db.delegables.getItemIter():
            delegates.append({
                'pre': pre,
                'sn': sn[-1],  # Get last element of sequence number
                'edig': edig,
                'sn_full': sn  # Keep full sn for later use
            })

    except Exception as e:
        logger.exception(f"Error getting delegates: {e}")

    return delegates


def confirm_delegates(app, hab, selected_delegates):
    """
    Confirm selected delegates for approval.

    Args:
        app: Application instance with vault
        hab: Habery instance (identifier)
        selected_delegates: List of delegate dicts from get_delegates_awaiting_approval

    Returns:
        dict: Result with 'success' bool and 'message' str
    """
    try:
        # Convert selected delegates to format expected by ConfirmDoer
        escrowed = [(d['pre'], d['sn_full'], d['edig']) for d in selected_delegates]

        # Create and launch ConfirmDoer
        # ConfirmDoer is defined later in this file, but available at runtime
        # type: ignore
        confirm_doer = ConfirmDoer(
            app=app,
            alias=hab.name,
            escrowed=escrowed,
            auto=True,
            interact=True
        )

        # Add to app's doer queue
        app.vault.extend([confirm_doer])

        return {
            'success': True,
            'message': f'Confirming {len(selected_delegates)} delegate(s)...'
        }

    except Exception as e:
        logger.exception(f"Error confirming delegates: {e}")
        return {
            'success': False,
            'message': f'Error confirming delegates: {str(e)}'
        }


def refresh_keystate(app, hab):
    """
    Refresh key state for group multisig members.

    Args:
        app: Application instance with vault
        hab: Habery instance (identifier - must be GroupHab)

    Returns:
        dict: Result with 'success' bool and 'message' str
    """
    from keri.app import habbing as keri_habbing
    from keri.app import organizing

    try:
        if not isinstance(hab, keri_habbing.GroupHab):
            return {
                'success': False,
                'message': 'Identifier is not a group multisig'
            }

        org = organizing.Organizer(hby=app.vault.hby)

        # Query key state for each member
        for pre in hab.smids:
            if pre in app.vault.hby.habs.keys():
                continue  # Don't query key state for self

            remote_id = org.get(pre)
            if remote_id:
                logger.info(f"Querying key state for {remote_id.get('alias', 'unknown')} with pre: {pre}")
                # TODO: Implement OOBI resolution for key state refresh
                # This would require async/await or a doer
                # For now, just log the intent

        return {
            'success': True,
            'message': 'Key state refresh initiated for group members'
        }

    except Exception as e:
        logger.exception(f"Error refreshing key state: {e}")
        return {
            'success': False,
            'message': f'Error refreshing key state: {str(e)}'
        }


class ConfirmDoer(doing.DoDoer):
    """
    Doer for confirming delegate approvals.

    This is adapted from the Flet implementation to work with PySide6.
    """

    def __init__(self, app, alias, escrowed, interact=False, auto=False, authenticate=False, codes=None,
                 codeTime=None):
        """
        Initialize the ConfirmDoer.

        Args:
            app: Application instance with vault
            alias: Alias of the delegator identifier
            escrowed: List of tuples (pre, sn, edig) for delegates to confirm
            interact: Whether to use interaction events (default False)
            auto: Whether to auto-approve (default False)
            authenticate: Whether to authenticate with witnesses (default False)
            codes: Authentication codes (default None)
            codeTime: Code timestamp (default None)
        """
        from keri.app import agenting, delegating

        hby = app.vault.hby
        self.escrowed = escrowed
        self.hbyDoer = app.vault.hbyDoer
        self.witq = agenting.WitnessInquisitor(hby=hby)
        self.postman = app.vault.postman
        self.counselor = app.vault.counselor
        self.notifier = app.vault.notifier
        self.mux = app.vault.mux
        self.authenticate = authenticate
        self.codes = codes if codes is not None else []
        self.codeTime = codeTime

        exc = app.vault.exc
        try:
            delegating.loadHandlers(hby=hby, exc=exc, notifier=self.notifier)
        except Exception as e:
            logger.info(f"Error loading delegation handlers: {e}")

        self.mbx = app.vault.mbx

        doers = [self.witq]
        self.toRemove = list(doers)
        doers.extend([doing.doify(self.confirmDo)])

        self.alias = alias
        self.hby = hby
        self.interact = interact
        self.auto = auto
        super(ConfirmDoer, self).__init__(doers=doers)

    def confirmDo(self, tymth, tock=0.0, **kwa):
        """
        Generator method for confirming delegates.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        from keri.db import dbing
        from keri.core import serdering, coring
        from keri.app import habbing, grouping, agenting
        from ordered_set import OrderedSet as oset
        from keri import core

        # Enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            while True:
                esc = self.escrowed
                for pre, sn, edig in esc:
                    dgkey = dbing.dgKey(pre, edig)
                    eraw = self.hby.db.getEvt(dgkey)
                    if eraw is None:
                        continue
                    eserder = serdering.SerderKERI(raw=bytes(eraw))  # escrowed event

                    ilk = eserder.sad["t"]
                    if ilk in (coring.Ilks.dip,):
                        typ = "inception"
                        delpre = eserder.sad["di"]

                    elif ilk in (coring.Ilks.drt,):
                        typ = "rotation"
                        dkever = self.hby.kevers[eserder.pre]
                        delpre = dkever.delpre

                    else:
                        continue

                    if delpre in self.hby.prefixes:
                        hab = self.hby.habs[delpre]

                        if self.auto:
                            approve = True
                        else:
                            # In UI context, assume auto-approve
                            approve = True

                        if not approve:
                            continue

                        if isinstance(hab, habbing.GroupHab):
                            aids = hab.smids

                            anchor = dict(i=eserder.ked["i"], s=eserder.snh, d=eserder.said)
                            if self.interact:
                                msg = hab.interact(data=[anchor])
                            else:
                                logger.warning("Confirm does not support rotation for delegation approval with group multisig")
                                continue

                            serder = serdering.SerderKERI(raw=msg)
                            exn, atc = grouping.multisigInteractExn(ghab=hab, aids=aids, ixn=bytearray(msg))
                            others = list(oset(hab.smids + (hab.rmids or [])))
                            others.remove(hab.mhab.pre)

                            for recpt in others:  # send notification to other participants
                                self.postman.send(src=hab.mhab.pre, dest=recpt, topic="multisig", serder=exn,
                                                  attachment=atc)

                            prefixer = coring.Prefixer(qb64=hab.pre)
                            sner = core.Number(num=serder.sn, code=core.NumDex.Huge)
                            saider = coring.Saider(qb64b=serder.saidb)
                            self.counselor.start(ghab=hab, prefixer=prefixer, seqner=sner, saider=saider)

                            while True:
                                saider = self.hby.db.cgms.get(keys=(prefixer.qb64, sner.qb64))
                                if saider is not None:
                                    break

                                yield self.tock

                            logger.info(f"Delegate {eserder.pre} {typ} event committed.")

                            self.remove(self.toRemove)
                            return True

                        else:
                            cur = hab.kever.sner.num

                            anchor = dict(i=eserder.ked["i"], s=eserder.snh, d=eserder.said)
                            if self.interact:
                                hab.interact(data=[anchor])
                            else:
                                hab.rotate(data=[anchor])

                            auths = {}
                            if self.authenticate:
                                from keri.help import helping
                                codeTime = helping.fromIso8601(
                                    self.codeTime) if self.codeTime is not None else helping.nowIso8601()
                                for arg in self.codes:
                                    (wit, code) = arg.split(":")
                                    auths[wit] = f"{code}#{codeTime}"

                            witDoer = agenting.WitnessReceiptor(hby=self.hby, auths=auths)
                            self.extend(doers=[witDoer])
                            self.toRemove.append(witDoer)  # type: ignore
                            yield self.tock

                            if hab.kever.wits:
                                witDoer.msgs.append(dict(pre=hab.pre, sn=cur+1))
                                while not witDoer.cues:
                                    _ = yield self.tock

                            logger.info(f'Delegator Prefix  {hab.pre}')
                            logger.info(f'\tDelegate {eserder.pre} {typ} Anchored at Seq. No.  {hab.kever.sner.num}')

                            # wait for confirmation of fully committed event
                            if eserder.pre in self.hby.kevers:

                                self.witq.query(src=hab.pre, pre=eserder.pre, sn=eserder.sn)

                                while eserder.sn < self.hby.kevers[eserder.pre].sn:
                                    yield self.tock

                                logger.info(f"Delegate {eserder.pre} {typ} event committed.")
                            else:  # It should be an inception event then...
                                wits = [werfer.qb64 for werfer in eserder.berfers]
                                self.witq.query(src=hab.pre, pre=eserder.pre, sn=eserder.sn, wits=wits)
                                while eserder.pre not in self.hby.kevers:
                                    yield self.tock

                                logger.info(f"Delegate {eserder.pre} {typ} event committed.")

                            self.hby.db.delegables.rem(keys=(pre, sn))
                            self.remove(self.toRemove)
                            return True

                    yield self.tock

                yield self.tock
        except Exception as e:
            logger.exception(f"ConfirmDoer failed with exception: {e}")


class TestDoer(doing.Doer):
    """
    Test doer that logs a message every second to verify hio integration.
    Can emit signals via a signal bridge when count reaches a threshold.
    """

    def __init__(self, signal_bridge=None, **kwa):
        """
        Initialize the test doer.

        Args:
            signal_bridge: Optional DoerSignalBridge instance for emitting Qt signals
        """
        super().__init__(tock=1.0, **kwa)  # Run every 1 second
        self.count = 0
        self.signal_bridge = signal_bridge

    def enter(self, **kwa):
        """Called when doer starts."""
        logger.info("TestDoer: Entering")
        self.count = 0

    def recur(self, tyme):
        """Called every tock (1 second)."""
        self.count += 1
        logger.info(f"TestDoer: Running (count: {self.count}, tyme: {tyme:.2f})")

        # Emit signal if bridge is available
        if self.signal_bridge:
            self.signal_bridge.emit_test_count(self.count)

            # Emit special event when count reaches 10
            if self.count >= 10:
                logger.info("TestDoer: Count reached 10, emitting doer_event")
                self.signal_bridge.emit_doer_event(
                    doer_name="TestDoer",
                    event_type="count_threshold_reached",
                    data={"count": self.count, "threshold": 10}
                )
                # Stop the doer after reaching threshold
                return True

        # Return False to keep running (or True to stop)
        return False

    def exit(self):
        """Called when doer exits."""
        logger.info(f"TestDoer: Exiting (ran {self.count} times)")
