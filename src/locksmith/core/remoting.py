# -*- encoding: utf-8 -*-
"""
locksmith.core.remoting module

Functions and services for resolving OOBIs and managing remote identifiers
"""
import asyncio
import datetime
import time
from typing import TYPE_CHECKING

from keri.app.forwarding import StreamPoster

if TYPE_CHECKING:
    pass

from hio.base import doing
from keri import help, kering
from keri.app import organizing, forwarding
from keri.app.habbing import GroupHab
from keri.core import parsing, serdering
from keri.core.serdering import SerderKERI
from keri.db import basing
from keri.help import helping
from keri.peer import exchanging
from mnemonic import Mnemonic

logger = help.ogler.getLogger(__name__)


def message_version(ims: bytes | bytearray) -> kering.Versionage:
    """Return the KERI wire version for a complete raw message."""
    if kering.sniff(ims) == kering.Colds.msg:
        return kering.smell(ims).pvrsn

    return kering.Vrsn_2_0


def upsert_remote_id_metadata(app, pre: str, *, alias=None, cid=None, tag=None, oobi=None):
    """Create or update Organizer metadata for a resolved remote identifier."""
    if not pre:
        return None

    data = {
        'last-refresh': helping.nowIso8601(),
    }
    if alias:
        data['alias'] = alias
    if cid:
        data['cid'] = cid
    if tag:
        data['tag'] = tag
    if oobi:
        data['oobi'] = oobi

    app.vault.org.update(pre, data)
    return app.vault.org.get(pre)


def get_remote_id_details(app, remote_id_pre: str) -> dict:
    """
    Retrieve detailed information about a remote identifier.

    Args:
        app: The application instance containing vault and hby references
        remote_id_pre: The AID (prefix) of the remote identifier

    Returns:
        Dictionary containing remote identifier details
    """
    hby = app.vault.hby

    # Get the kever (key event log) for this identifier
    kever = hby.kevers.get(remote_id_pre)

    # Get organizer data for alias and metadata
    org = organizing.Organizer(hby=hby)
    remote_data = org.get(remote_id_pre) or {}

    # Extract alias
    alias = remote_data.get('alias', '')

    # Extract OOBI
    oobi = remote_data.get('oobi', None)

    # Extract sequence number from kever
    sequence_number = kever.sn if kever and hasattr(kever, 'sn') else None

    # Extract keystate updated timestamp
    keystate_updated_at = 'N/A'
    if 'last-refresh' in remote_data:
        dt = datetime.datetime.fromisoformat(remote_data['last-refresh'])
        keystate_updated_at = dt.strftime('%Y-%m-%d %I:%M %p')
    elif kever and kever.dater:
        dt = datetime.datetime.fromisoformat(f'{kever.dater.dts}')
        keystate_updated_at = dt.strftime('%Y-%m-%d %I:%M %p')

    # Extract roles from remote_data (e.g., ['Witness'])
    roles = remote_data.get('roles', [])

    # Extract existing role assignments from ends database
    existing_roles = []
    mailboxes = []
    for (cid, role, eid), end in hby.db.ends.getTopItemIter():
        if eid == remote_id_pre and end.allowed:
            existing_roles.append((cid, role, eid))
        if cid == remote_id_pre and role == 'mailbox':
            mailboxes.append(eid)

    # Get Key Event Log
    kel = bytearray()
    for msg in hby.db.clonePreIter(pre=remote_id_pre):
        kel.extend(msg)
    kel_str = str(kel)[12:-2] if len(kel) > 14 else str(kel)

    pretty_kel = ""
    for msg in hby.db.clonePreIter(pre=remote_id_pre):
        serder = SerderKERI(raw=msg)
        attachments = msg[serder.size:]

        pretty_kel += f"{serder.pretty()}\n{attachments.decode('utf-8')}\n\n"


    return {
        'id': remote_id_pre,
        'alias': alias,
        'oobi': oobi,
        'kel': kel_str,
        'pretty_kel': pretty_kel,
        'sequence_number': sequence_number,
        'keystate_updated_at': keystate_updated_at,
        'roles': roles,
        'existing_roles': existing_roles,
        'mailboxes': mailboxes,
    }


def describe_oobi_resolution_state(app, *, pre: str | None = None, oobi: str | None = None) -> str:
    """Summarize the local resolver state for an OOBI for diagnostics."""

    vault = getattr(app, "vault", None)
    hby = getattr(vault, "hby", None)
    db = getattr(hby, "db", None)

    if db is None:
        return "resolver_state=unknown(no_hby_db)"

    roobi = db.roobi.get(keys=(oobi,)) if oobi else None
    queued = bool(db.oobis.get(keys=(oobi,))) if oobi else False
    pending_client = bool(db.coobi.get(keys=(oobi,))) if oobi else False
    retry_escrow = bool(db.eoobi.get(keys=(oobi,))) if oobi else False

    kevers = getattr(hby, "kevers", {})
    pre_known = bool(pre and pre in kevers)

    parts = [
        f"roobi_state={getattr(roobi, 'state', '-')}",
        f"queued={queued}",
        f"pending_client={pending_client}",
        f"retry_escrow={retry_escrow}",
        f"pre_known={pre_known}",
    ]
    return "resolver_state(" + ", ".join(parts) + ")"


def purge_oobi_resolution_state(app, *, oobi: str | None) -> None:
    """Remove local resolver state for an OOBI that should no longer be retried."""

    if not oobi:
        return

    vault = getattr(app, "vault", None)
    hby = getattr(vault, "hby", None)
    db = getattr(hby, "db", None)
    if db is None:
        return

    for store_name in ("oobis", "coobi", "eoobi", "roobi", "moobi"):
        store = getattr(db, store_name, None)
        if store is None:
            continue
        try:
            store.rem(keys=(oobi,))
        except Exception:
            logger.warning("Failed purging %s OOBI state for %s", store_name, oobi, exc_info=True)


def introduce_watcher_observed_aid(
    app,
    *,
    hab,
    watcher_eid: str,
    observed_aid: str,
    observed_oobis: list[str],
    timeout_seconds: float = 10.0,
) -> None:
    """Send the local controller KEL and watcher-add reply to a hosted watcher."""

    if not watcher_eid:
        raise ValueError("watcher_eid is required")
    if not observed_aid:
        raise ValueError("observed_aid is required")
    observed_oobis = [oobi for oobi in dict.fromkeys(observed_oobis or []) if oobi]
    if not observed_oobis:
        raise ValueError("observed_oobis is required")

    ender = hab.db.ends.get(keys=(hab.pre, "watcher", watcher_eid))
    if not ender or not ender.allowed:
        msg = hab.reply(
            route="/end/role/add",
            data=dict(cid=hab.pre, role="watcher", eid=watcher_eid),
        )
        hab.psr.parseOne(ims=bytes(msg))

    postman = forwarding.StreamPoster(
        hby=app.vault.hby,
        hab=hab,
        recp=watcher_eid,
        topic="reply",
    )

    for msg in hab.db.cloneDelegation(hab.kever):
        serder = serdering.SerderKERI(raw=msg)
        postman.send(serder=serder, attachment=msg[serder.size:])

    for msg in hab.db.clonePreIter(pre=hab.pre):
        serder = serdering.SerderKERI(raw=msg)
        postman.send(serder=serder, attachment=msg[serder.size:])

    for observed_oobi in observed_oobis:
        msg = hab.reply(
            route=f"/watcher/{watcher_eid}/add",
            data=dict(cid=hab.pre, oid=observed_aid, oobi=observed_oobi),
        )
        raw = bytes(msg)
        hab.psr.parseOne(ims=raw)
        serder = SerderKERI(raw=raw)
        postman.send(serder=serder, attachment=raw[serder.size:])

    doer = doing.DoDoer(doers=postman.deliver())
    try:
        doing.Doist(tock=0.03125, real=True).do(doers=[doer], limit=timeout_seconds)
    except Exception as exc:
        raise ValueError(f"Failed introducing observed AID {observed_aid} to watcher {watcher_eid}: {exc}") from exc


async def resolve_oobi(app, pre: str, oobi: str | None = None, force=False, alias=None, cid=None, tag=None):
    """
    Resolves an OOBI with the connected Vault's Habery and recreates the full Remote ID data in Organizer.
    This includes a workaround because resolving an OOBI resets all attributes for a Remote ID including the alias.

    Parameters:
        app: Application instance with vault access
        pre (str): The AID prefix of the target AID to resolve the OOBI against
        oobi (str): The OOBI url to resolve
        force (bool): If true, the existing OOBI resolution will be cleared and re-resolved
        alias (str): The alias of the target AID to resolve the OOBI against
        cid (str): The controller AID of the target
        tag (str): The tag of the target

    Returns:
        bool: True if OOBI resolved successfully, False otherwise
    """
    obr = basing.OobiRecord(date=helping.nowIso8601())
    obr.oobialias = alias

    if force:
        app.vault.hby.db.roobi.rem(keys=(oobi,))

    start_time = helping.nowUTC()
    timeout_delta = datetime.timedelta(seconds=15)
    poll_interval = 0.125

    app.vault.hby.db.oobis.put(keys=(oobi,), val=obr)

    while not app.vault.hby.db.roobi.get(keys=(oobi,)):
        if helping.nowUTC() > start_time + timeout_delta:
            logger.info(f'OOBI resolve timeout for {alias} ({oobi})')
            return False
        await asyncio.sleep(poll_interval)

    if pre not in app.vault.hby.kevers:
        logger.error(f'OOBI Resolution failed for alias {alias} and OOBI {oobi}, {pre} not found in KERI DB.')
        return False

    upsert_remote_id_metadata(
        app,
        pre,
        alias=alias,
        cid=cid,
        tag=tag,
        oobi=oobi,
    )

    logger.info(f'OOBI resolved: {alias} {oobi}')
    return True


def get_remote_identifiers_for_dropdown(app):
    """
    Load identifiers.

    Args:
        app: Application instance with vault

    Returns:
        dict: Dict of identifier information keyed by to_string
    """
    rm_ids_raw = app.vault.org.list()
    remote_identifiers = {}
    # Load remote identifiers
    for rm_id in rm_ids_raw:
        key = f"{rm_id['alias']} - {rm_id['id']}"
        remote_identifiers[key] = {
            'aid': rm_id['id'],
            'alias': rm_id['alias'],
        }
        if rm_id.get('oobi'):
            remote_identifiers[key]['oobi'] = rm_id['oobi']

    return remote_identifiers


def resolve_oobi_sync(app, pre: str | None, oobi: str | None = None, force=False, alias=None, cid=None, tag=None):
    """
    Synchronous wrapper to resolve an OOBI using a Doer.

    For async operations in the vault's doer chain, use ResolveOobiDoer directly.
    For immediate resolution with blocking, use this function.

    Parameters:
        app: Application instance with vault access
        pre (str): The AID prefix of the target AID
        oobi (str): The OOBI url to resolve
        force (bool): If true, clear and re-resolve existing OOBI
        alias (str): The alias of the target AID
        cid (str): The controller AID of the target
        tag (str): The tag of the target

    Returns:
        ResolveOobiDoer: The doer instance (add to vault.extend() to run)
    """
    doer = ResolveOobiDoer(
        app=app,
        pre=pre,
        oobi=oobi,
        force=force,
        alias=alias,
        cid=cid,
        tag=tag,
        signal_bridge=app.vault.signals if hasattr(app.vault, 'signals') else None
    )

    app.vault.extend([doer])
    return doer


def resolve_oobi_blocking(
        app,
        pre: str,
        oobi: str | None = None,
        force=False,
        alias=None,
        cid=None,
        tag=None,
        timeout_seconds: float = 15.0,
        tock: float = 0.125,
):
    """Resolve an OOBI synchronously without blocking the UI event loop."""

    qtask = getattr(app, "qtask", None)
    if qtask is None:
        doer = ResolveOobiDoer(
            app=app,
            pre=pre,
            oobi=oobi,
            force=force,
            alias=alias,
            cid=cid,
            tag=tag,
            timeout_seconds=timeout_seconds,
        )
        doing.Doist(tock=tock, real=True).do(doers=[doer], limit=timeout_seconds + tock)
        return doer.resolved

    obr = basing.OobiRecord(date=helping.nowIso8601())
    obr.oobialias = alias

    if force:
        app.vault.hby.db.roobi.rem(keys=(oobi,))
        logger.info(f"Forcing re-resolution of OOBI: {oobi}")

    app.vault.hby.db.oobis.put(keys=(oobi,), val=obr)
    logger.info(f"OOBI written to database: {alias} ({oobi})")

    start_time = helping.nowUTC()
    timeout_delta = datetime.timedelta(seconds=timeout_seconds)
    sleep_interval = max(tock, 0.05)

    while not app.vault.hby.db.roobi.get(keys=(oobi,)) and pre not in app.vault.hby.kevers:
        if helping.nowUTC() > start_time + timeout_delta:
            logger.warning("OOBI resolve timeout for %s (%s)", alias, oobi)
            return False
        time.sleep(sleep_interval)

    if pre not in app.vault.hby.kevers:
        logger.error(
            "OOBI resolution failed for alias %s and OOBI %s, %s not found in KERI DB.",
            alias,
            oobi,
            pre,
        )
        return False

    upsert_remote_id_metadata(
        app,
        pre,
        alias=alias,
        cid=cid,
        tag=tag,
        oobi=oobi,
    )
    logger.info(f"OOBI resolved: {alias} {oobi}")
    return True


class ResolveOobiDoer(doing.DoDoer):
    """
    Doer for asynchronous OOBI resolution.

    Handles the complete OOBI resolution workflow including:
    - Writing OOBI to database
    - Waiting for resolution with timeout
    - Updating Organizer with remote ID data
    - Preserving alias and metadata
    - Signaling completion to UI
    """

    def __init__(
            self,
            app,
            pre: str,
            oobi: str | None = None,
            force=False,
            alias=None,
            cid=None,
            tag=None,
            signal_bridge=None,
            timeout_seconds: float = 15.0,
    ):
        """
        Initialize the ResolveOobiDoer.

        Args:
            app: Application instance with vault
            pre: The AID prefix of the target AID
            oobi: The OOBI url to resolve
            force: If true, clear and re-resolve existing OOBI
            alias: The alias of the target AID
            cid: The controller AID of the target
            tag: The tag of the target
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.pre = pre
        self.oobi = oobi
        self.force = force
        self.alias = alias
        self.cid = cid
        self.tag = tag
        self.signal_bridge = signal_bridge
        self.timeout_seconds = timeout_seconds
        self.resolved = False
        self.completed = False

        doers = [doing.doify(self.resolve_do)]

        super(ResolveOobiDoer, self).__init__(doers=doers)

    def resolve_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for OOBI resolution.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Create OOBI record with alias
            obr = basing.OobiRecord(date=helping.nowIso8601())
            obr.oobialias = self.alias

            # Force re-resolution if requested
            if self.force:
                self.app.vault.hby.db.roobi.rem(keys=(self.oobi,))
                logger.info(f"Forcing re-resolution of OOBI: {self.oobi}")

            # Write OOBI to database for resolution
            self.app.vault.hby.db.oobis.put(keys=(self.oobi,), val=obr)
            logger.info(f"OOBI written to database: {self.alias} ({self.oobi})")

            # Wait for OOBI resolution with timeout
            start_time = helping.nowUTC()
            timeout_delta = datetime.timedelta(seconds=self.timeout_seconds)

            while not self.app.vault.hby.db.roobi.get(keys=(self.oobi,)) and self.pre not in self.app.vault.hby.kevers:
                if helping.nowUTC() > start_time + timeout_delta:
                    logger.warning(f'OOBI resolve timeout for {self.alias} ({self.oobi})')

                    # Signal timeout to UI
                    if self.signal_bridge:
                        self.signal_bridge.emit_doer_event(
                            doer_name="ResolveOobiDoer",
                            event_type="oobi_resolution_timeout",
                            data={
                                'alias': self.alias,
                                'pre': self.pre,
                                'oobi': self.oobi,
                                'success': False
                            }
                        )
                    self.completed = True
                    return

                yield self.tock

            # Verify the prefix is now in kevers
            if self.pre not in self.app.vault.hby.kevers:
                logger.error(
                    f'OOBI Resolution failed for alias {self.alias} and OOBI {self.oobi}, '
                    f'{self.pre} not found in KERI DB after resolution.'
                )

                # Signal failure to UI
                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        doer_name="ResolveOobiDoer",
                        event_type="oobi_resolution_failed",
                        data={
                            'alias': self.alias,
                            'pre': self.pre,
                            'oobi': self.oobi,
                            'error': 'Prefix not found in KERI DB',
                            'success': False
                        }
                    )
                self.completed = True
                return

            upsert_remote_id_metadata(
                self.app,
                self.pre,
                alias=self.alias,
                cid=self.cid,
                tag=self.tag,
                oobi=self.oobi,
            )
            logger.info(f'Updated remote ID in Organizer: {self.alias} ({self.pre})')

            # Now signal success
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="ResolveOobiDoer",
                    event_type="oobi_resolved",
                    data={
                        'alias': self.alias,
                        'pre': self.pre,
                        'oobi': self.oobi,
                        'cid': self.cid,
                        'tag': self.tag,
                        'success': True
                    }
                )
                logger.info("OOBI resolution signaled")

            logger.info(f'OOBI resolved successfully: {self.alias} ({self.oobi})')
            self.resolved = True
            self.completed = True
            return

        except Exception as e:
            logger.exception(f"ResolveOobiDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="ResolveOobiDoer",
                    event_type="oobi_resolution_failed",
                    data={
                        'alias': self.alias if self.alias else None,
                        'pre': self.pre if self.pre else None,
                        'oobi': self.oobi if self.oobi else None,
                        'error': str(e),
                        'success': False
                        }
                    )
            self.completed = True
            return


def resolve_default_oobis(app):
    """
    Resolve the default OOBIs (root and api) for a newly created vault.

    This should be called after vault creation to ensure default OOBIs
    are properly resolved and available.

    Parameters:
        app: Application instance with vault and config access
    """
    # Resolve root OOBI
    if hasattr(app.config, 'root_oobi'):
        logger.info(f"Resolving default root OOBI: {app.config.root_oobi}")
        resolve_oobi_sync(
            app=app,
            pre=None,  # Will be determined from OOBI
            oobi=app.config.root_oobi,
            alias="Root",
            tag="root"
        )

    # Resolve API OOBI
    if hasattr(app.config, 'api_oobi'):
        logger.info(f"Resolving default API OOBI: {app.config.api_oobi}")
        resolve_oobi_sync(
            app=app,
            pre=None,  # Will be determined from OOBI
            oobi=app.config.api_oobi,
            alias="API",
            tag="api"
        )


def delete_remote_id(app, alias, rm_id):
    try:
        # Validate alias
        if (not alias or alias == '') and not rm_id or rm_id == '':
            return {'success': False, 'message': 'Alias and prefix are required'}

        app.vault.org.rem(rm_id)

        # Emit signal if signal bridge is available
        if hasattr(app.vault, 'signals') and app.vault.signals:
            app.vault.signals.emit_doer_event(
                doer_name="DeleteRemoteIdentifier",
                event_type="remote_identifier_deleted",
                data={
                    'alias': alias,
                    'success': True
                }
            )

        logger.info(f"Remote identifier '{alias}' deleted successfully")
        return {
            'success': True,
            'message': f"Remote identifier '{alias}' deleted successfully"
        }

    except Exception as e:
        logger.exception(f"Error deleting remote identifier: {e}")
        return {
            'success': False,
            'message': f'Error deleting remote identifier: {str(e)}'
        }


class ImportDoer(doing.DoDoer):
    """
    Doer for importing remote identifiers from files.

    Handles the import workflow including:
    - Reading and parsing KERI event messages
    - Processing escrows
    - Updating Organizer with remote ID data
    - Signaling completion to UI
    """

    def __init__(self, app, file, alias, signal_bridge=None):
        """
        Initialize the ImportDoer.

        Args:
            app: Application instance with vault
            file: Path to the file containing KERI event messages
            alias: The alias for the imported remote identifier
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.file = file
        self.alias = alias
        self.signal_bridge = signal_bridge
        self.org = self.app.vault.org
        self.hby = self.app.vault.hby

        doers = [doing.doify(self.importDo)]

        super(ImportDoer, self).__init__(doers=doers)

    def importDo(self, tymth, tock=0.0, **kwa):
        """
        Import remote identifier from file.

        Parameters:
            tymth (function): injected function wrapper closure returned by .tymen() of
                Tymist instance. Calling tymth() returns associated Tymist .tyme.
            tock (float): injected initial tock value

        Returns:  doifiable Doist compatible generator method
        """
        # enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            with open(self.file, 'rb') as f:
                ims = f.read()

                parsing.Parser(
                    kvy=self.hby.kvy,
                    rvy=self.hby.rvy,
                    local=False,
                    version=message_version(ims),
                ).parse(ims)
                self.hby.kvy.processEscrows()

                serder = SerderKERI(raw=ims)
                pre = serder.pre

                remoteId = {
                    'alias': self.alias,
                    'last-refresh': helping.nowIso8601()
                }
                self.org.update(pre, remoteId)

                # Signal success to UI
                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        doer_name="ImportDoer",
                        event_type="remote_identifier_imported",
                        data={
                            'alias': self.alias,
                            'pre': pre,
                            'file': self.file,
                            'success': True
                        }
                    )

                logger.info(f'Remote identifier imported successfully: {self.alias} ({pre})')

            self.exit()
            return True

        except Exception as e:
            logger.exception(f"ImportDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="ImportDoer",
                    event_type="import_failed",
                    data={
                        'alias': self.alias,
                        'file': self.file,
                        'error': str(e),
                        'success': False
                    }
                )

            self.exit()
            return False


def generate_challenge():
    """
    Generate a random 12-word mnemonic phrase for challenge verification.

    Returns:
        str: A 12-word mnemonic phrase (space-separated)
    """
    mnem = Mnemonic(language='english')
    phrase = mnem.generate(strength=128)
    logger.info("Generated challenge phrase")
    return phrase


def refresh_keystate(app, remote_id_pre: str, oobi: str = None):
    """
    Refresh the keystate for a remote identifier by re-resolving its OOBI.

    Args:
        app: Application instance with vault access
        remote_id_pre: The AID prefix of the remote identifier
        oobi: Optional OOBI URL to use for refresh

    Returns:
        ResolveOobiDoer: The doer instance (already added to vault.extend())
    """
    # Get current remote ID data to extract OOBI if not provided
    if not oobi:
        org = organizing.Organizer(hby=app.vault.hby)
        remote_data = org.get(remote_id_pre) or {}
        oobi = remote_data.get('oobi')

    if not oobi:
        logger.error(f"No OOBI available for remote ID {remote_id_pre}")
        return None

    # Get alias for logging
    org = organizing.Organizer(hby=app.vault.hby)
    remote_data = org.get(remote_id_pre) or {}
    alias = remote_data.get('alias', remote_id_pre)

    logger.info(f"Refreshing keystate for {alias} ({remote_id_pre})")

    # Use resolve_oobi_sync with force=True to refresh
    doer = resolve_oobi_sync(
        app=app,
        pre=remote_id_pre,
        oobi=oobi,
        force=True,
        alias=alias
    )

    return doer


def delete_role(app, cid: str, role: str, eid: str):
    """
    Delete a role assignment for a remote identifier.

    Args:
        app: Application instance with vault access
        cid: Controller AID
        role: Role name (e.g., "gateway", "watcher", "mailbox")
        eid: Endpoint AID (the remote identifier)

    Returns:
        dict: Result with success status and message
    """
    try:
        hby = app.vault.hby

        # Remove the role from the ends database
        hby.db.ends.rem(keys=(cid, role, eid))

        logger.info(f"Deleted role '{role}' for remote ID {eid} (controller: {cid})")

        # Emit signal if available
        if hasattr(app.vault, 'signals') and app.vault.signals:
            app.vault.signals.emit_doer_event(
                doer_name="DeleteRole",
                event_type="role_deleted",
                data={
                    'cid': cid,
                    'role': role,
                    'eid': eid,
                    'success': True
                }
            )

        return {
            'success': True,
            'message': f"Role '{role}' deleted successfully"
        }

    except Exception as e:
        logger.exception(f"Error deleting role: {e}")
        return {
            'success': False,
            'message': f'Error deleting role: {str(e)}'
        }


class ChallengeVerificationDoer(doing.DoDoer):
    """
    Doer for sending challenge verification responses.

    This doer handles the workflow of responding to a challenge from a remote identifier:
    - Creates an exchange message with the challenge response
    - Endorses the message with the hab's signature
    - Sends it via postman to the remote identifier
    - Signals completion to UI
    """

    def __init__(self, app, hab_pre: str, remote_id_pre: str, challenge_words: list, signal_bridge=None):
        """
        Initialize the ChallengeVerificationDoer.

        Args:
            app: Application instance with vault
            hab_pre: The prefix of the local identifier to verify with
            remote_id_pre: The prefix of the remote identifier being verified
            challenge_words: List of 12 words from the challenge phrase
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hab_pre = hab_pre
        self.remote_id_pre = remote_id_pre
        self.challenge_words = challenge_words
        self.signal_bridge = signal_bridge
        self.hby = app.vault.hby

        doers = [doing.doify(self.verify_do)]

        super(ChallengeVerificationDoer, self).__init__(doers=doers)

    def verify_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for challenge verification.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Get the hab for the selected identifier
            hab = self.hby.habs.get(self.hab_pre)

            if not hab:
                logger.error(f"Hab not found for prefix: {self.hab_pre}")
                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        doer_name="ChallengeVerificationDoer",
                        event_type="challenge_verification_failed",
                        data={
                            'error': 'Identifier not found',
                            'success': False
                        }
                    )
                return

            # Create payload with challenge response
            payload = dict(i=self.hab_pre, words=self.challenge_words)

            # Create exchange message
            exn, _ = exchanging.exchange(route='/challenge/response', payload=payload, sender=hab.pre)

            # Endorse the message
            ims = hab.endorse(serder=exn, last=False, framed=True)
            del ims[:exn.size]

            # Get sender hab (handle group habs)
            sender_hab = hab.mhab if isinstance(hab, GroupHab) else hab

            # Send via postman
            postman = StreamPoster(hby=self.app.vault.hby, recp=self.remote_id_pre, hab=sender_hab, topic="challenge")
            postman.send(
                serder=exn,
                attachment=ims
            )
            # Wait for postman cues (delivery confirmation)
            doer = doing.DoDoer(doers=postman.deliver())
            self.extend([doer])

            while not doer.done:
                yield self.tock

            logger.info(f"Challenge response sent to {self.remote_id_pre}")

            # Signal success
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="ChallengeVerificationDoer",
                    event_type="challenge_response_sent",
                    data={
                        'hab_pre': self.hab_pre,
                        'remote_id_pre': self.remote_id_pre,
                        'success': True
                    }
                )

            return

        except Exception as e:
            logger.exception(f"ChallengeVerificationDoer failed: {e}")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="ChallengeVerificationDoer",
                    event_type="challenge_verification_failed",
                    data={
                        'error': str(e),
                        'success': False
                    }
                )
            return


class SetRoleDoer(doing.DoDoer):
    """
    Doer for setting roles on remote identifiers.

    This doer handles the workflow of assigning a role (gateway, watcher, mailbox)
    to a remote identifier:
    - Checks if role is already set
    - Creates role assignment reply message
    - Sends delegation and identifier messages to remote
    - Updates ends database
    - Signals completion to UI
    """

    def __init__(self, app, hab_pre: str, remote_id_pre: str, role: str, signal_bridge=None):
        """
        Initialize the SetRoleDoer.

        Args:
            app: Application instance with vault
            hab_pre: The prefix of the local identifier (controller)
            remote_id_pre: The prefix of the remote identifier (endpoint)
            role: Role to assign (should be Roles enum value or string)
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hab_pre = hab_pre
        self.remote_id_pre = remote_id_pre
        self.role = role
        self.signal_bridge = signal_bridge
        self.hby = app.vault.hby

        doers = [doing.doify(self.set_role_do)]

        super(SetRoleDoer, self).__init__(doers=doers)

    def set_role_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for setting role.

        Args:
            tymth: Tymist function for time management
            tock: Initial tock value

        Yields:
            tock: Current tock value for doer scheduling
        """
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            # Get the hab
            hab = self.hby.habs.get(self.hab_pre)

            if not hab:
                logger.error(f"Hab not found for prefix: {self.hab_pre}")
                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        doer_name="SetRoleDoer",
                        event_type="set_role_failed",
                        data={
                            'error': 'Identifier not found',
                            'success': False
                        }
                    )
                return

            # Check if role is already set
            ender = hab.db.ends.get(keys=(hab.pre, self.role, self.remote_id_pre))
            if ender and ender.allowed:
                logger.info(
                    f"Role '{self.role}' is already set for remote ID '{self.remote_id_pre}'. "
                    "Skipping role assignment."
                )
                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        doer_name="SetRoleDoer",
                        event_type="role_already_set",
                        data={
                            'hab_pre': self.hab_pre,
                            'remote_id_pre': self.remote_id_pre,
                            'role': self.role,
                            'success': True
                        }
                    )
                return

            # Create role assignment message
            if not ender or not ender.allowed:
                msg = hab.reply(
                    route="/end/role/add",
                    data=dict(cid=hab.pre, role=self.role, eid=self.remote_id_pre)
                )
                hab.psr.parseOne(ims=msg)

            while not hab.loadEndRole(cid=hab.pre, role=self.role, eid=self.remote_id_pre):
                yield self.tock

            # Create postman for sending messages
            postman = forwarding.StreamPoster(
                hby=self.hby,
                hab=hab,
                recp=self.remote_id_pre,
                topic="reply"
            )

            # Send delegation messages
            for msg in hab.db.cloneDelegation(hab.kever):
                serder = serdering.SerderKERI(raw=msg)
                postman.send(serder=serder, attachment=msg[serder.size:])

            # Send identifier messages
            for msg in hab.db.clonePreIter(pre=hab.pre):
                serder = serdering.SerderKERI(raw=msg)
                postman.send(serder=serder, attachment=msg[serder.size:])

            # Deliver messages
            doer = doing.DoDoer(doers=postman.deliver())
            self.extend([doer])

            while not doer.done:
                yield self.tock

            logger.info(f"Role '{self.role}' set for remote ID {self.remote_id_pre}")

            # Signal success
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="SetRoleDoer",
                    event_type="role_set",
                    data={
                        'hab_pre': self.hab_pre,
                        'remote_id_pre': self.remote_id_pre,
                        'role': self.role,
                        'success': True
                    }
                )

            return

        except Exception as e:
            logger.exception(f"SetRoleDoer failed: {e}")

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="SetRoleDoer",
                    event_type="set_role_failed",
                    data={
                        'error': str(e),
                        'success': False
                    }
                )
            return
