# -*- encoding: utf-8 -*-
"""
locksmith.core.identifying module

Functions for working with KERI Identifiers
"""
from hio.base import doing
from keri import help
from keri import kering
from keri.core import coring
from keri.db import dbing
from keri.help import helping

from locksmith.db.basing import IdentifierMetaInfo

logger = help.ogler.getLogger(__name__)


def recommend_toad(num_witnesses):
    """Recommend an appropriate TOAD value based on witness count."""
    match num_witnesses:
        case 0:
            return 0
        case 1:
            return 1
        case 2 | 3:
            return 2
        case 4:
            return 3
        case 5 | 6:
            return 4
        case 7:
            return 5
        case 8 | 9:
            return 7
        case 10:
            return 8
        case n if n > 10:
            return int(n * 0.8)
    return 0


def validate_toad(toad, num_witnesses):
    """
    Validate TOAD value against witness count.
    
    Args:
        toad: The TOAD value to validate
        num_witnesses: Number of witnesses after rotation (current + adds - cuts)
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if num_witnesses > 0:
        if toad < 1 or toad > num_witnesses:
            return False, f"TOAD must be between 1 and {num_witnesses} for {num_witnesses} witness(es)"
    else:
        if toad != 0:
            return False, "TOAD must be 0 when there are no witnesses"
    return True, None


def rotate_identifier(app, hab, isith=None, nsith=None, count=None, toad=None, cuts=None, adds=None,
                      proxy=None, authenticate=False, codes=None):

    rotate_doer = RotateDoer(app, hab, isith=isith, nsith=nsith, count=count,
                             toad=toad, cuts=cuts, adds=adds, proxy=proxy,
                             authenticate=authenticate, codes=codes, signal_bridge=app.vault.signals)

    app.vault.extend([rotate_doer])


def authenticate_witnesses(app, hab, codes, proxy=None):
    """
    Trigger witness authentication and delegation for an identifier after rotation.

    Args:
        app: Application instance with vault
        hab: Habitat (identifier) to authenticate
        codes: List of "witness_id:passcode" strings
        proxy: Optional proxy Hab for delegation
    """
    auth_doer = AuthenticateWitnessesDoer(
        app=app,
        hab=hab,
        codes=codes,
        proxy=proxy,
        signal_bridge=app.vault.signals
    )

    app.vault.extend([auth_doer])


class RotateDoer(doing.DoDoer):
    """
    Doer for asynchronous identifier rotation with delegation and witness support.

    Handles the complete rotation workflow including:
    - Rotating the identifier keys
    - Waiting for witness receipts
    - Waiting for delegation approval (if delegated)
    - Sending events to delegator
    - Updating witness states
    - Signaling completion to UI
    """

    def __init__(self, app, hab, isith=None, nsith=None, count=None,
                 toad=None, cuts=None, adds=None, proxy=None, authenticate=False,
                 codes=None, signal_bridge=None):
        """
        Initialize the RotateDoer.

        Args:
            app: Application instance with vault
            hab: Hab instance to rotate
            isith: Current signing threshold as int or str hex or list of str weights
            nsith: Next signing threshold as int or str hex or list of str weights
            count: Next number of signing keys
            toad: Witness threshold after cuts and adds (int or str hex)
            cuts: List of qb64 pre of witnesses to be removed
            adds: List of qb64 pre of witnesses to be added
            proxy: Optional proxy Hab for delegation
            authenticate: Whether to authenticate with witnesses
            codes: List of witness:code authentication pairs
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hab = hab
        self.hby = self.app.vault.hby
        self.signal_bridge = signal_bridge

        # Rotation parameters
        self.isith = isith
        self.nsith = nsith
        self.count = count
        self.toad = toad
        self.authenticate = authenticate
        self.codes = codes if codes is not None else []
        self.cuts = cuts if cuts is not None else []
        self.adds = adds if adds is not None else []

        # Setup doers from vault
        self.proxy = proxy
        self.swain = self.app.vault.swain
        self.postman = self.app.vault.postman

        doers = [doing.doify(self.rotate_do)]

        super(RotateDoer, self).__init__(doers=doers)

    def rotate_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for identifier rotation.

        Performs ONLY the key rotation operation. Authentication and delegation
        are handled separately by AuthenticateWitnessesDoer.

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
            # Perform the rotation
            self.hab.rotate(
                isith=self.isith,
                nsith=self.nsith,
                ncount=self.count,
                toad=self.toad,
                cuts=list(self.cuts),
                adds=list(self.adds)
            )

            # Log rotation details
            logger.info(f"Rotation complete for {self.hab.name} ({self.hab.pre})")
            logger.info(f"New Sequence No.: {self.hab.kever.sn}")
            for idx, verfer in enumerate(self.hab.kever.verfers):
                logger.info(f"\tPublic key {idx + 1}: {verfer.qb64}")

            # Update witness states for witnesses that were rotated OUT (cuts) via plugin hooks
            if hasattr(self.app, 'plugin_manager') and self.app.plugin_manager:
                for wit in self.cuts:
                    self.app.plugin_manager.update_witness_state_after_rotation(self.app.vault, wit)
                    logger.info(f"Notified plugins about rotated-out witness {wit}")

            # Set auth_pending if there are witnesses (authentication still needed)
            if self.hab.kever.wits:
                identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=True)
                self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)
                logger.info(f"Set auth_pending=True for {self.hab.pre} (witnesses need authentication)")

            # Signal rotation complete to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="RotateDoer",
                    event_type="rotation_complete",
                    data={
                        'alias': self.hab.name,
                        'pre': self.hab.pre,
                        'sn': self.hab.kever.sn,
                        'has_witnesses': bool(self.hab.kever.wits),
                        'is_delegated': bool(self.hab.kever.delpre),
                        'success': True
                    }
                )

            logger.info(f"Identifier {self.hab.name} ({self.hab.pre}) rotation complete")
            return

        except Exception as e:
            logger.exception(f"RotateDoer failed with exception: {e}")

            # Signal failure to UI
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="RotateDoer",
                    event_type="rotation_failed",
                    data={
                        'alias': self.hab.name if self.hab else None,
                        'pre': self.hab.pre if self.hab else None,
                        'error': str(e),
                        'success': False
                    }
                )
            if self.hab.kever.wits:
                identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=True)
                self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)
            return

class AuthenticateWitnessesDoer(doing.DoDoer):
    """
    Doer for witness authentication and delegation after rotation.

    Handles the complete post-rotation workflow including:
    - Waiting for witness receipts with authentication
    - Waiting for delegation approval (if delegated)
    - Sending events to delegator
    - Updating auth_pending state
    - Signaling completion to UI
    """

    def __init__(self, app, hab, codes, proxy=None, signal_bridge=None):
        """
        Initialize the AuthenticateWitnessesDoer.

        Args:
            app: Application instance with vault
            hab: Habitat (identifier) to authenticate
            codes: List of "witness_id:passcode" strings
            proxy: Optional proxy Hab for delegation
            signal_bridge: DoerSignalBridge for UI communication
        """
        self.app = app
        self.hab = hab
        self.hby = self.app.vault.hby
        self.codes = codes
        self.proxy = proxy
        self.signal_bridge = signal_bridge

        # Setup doers from vault
        self.swain = self.app.vault.swain
        self.postman = self.app.vault.postman

        doers = [doing.doify(self.authenticate_do)]
        super().__init__(doers=doers)

    def authenticate_do(self, tymth, tock=0.0, **opts):
        """
        Generator method for witness authentication and delegation.

        Handles both witness authentication and delegation approval after rotation.

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
            # Build authentication dict from codes
            auths = {}
            if self.codes:
                code_time = helping.nowIso8601()
                for arg in self.codes:
                    wit, code = arg.split(":")
                    auths[wit] = f"{code}#{code_time}"

            # Handle delegation if present
            if self.hab.kever.delpre:
                logger.info(f"Waiting for delegation approval for {self.hab.pre}...")
                self.swain.delegation(
                    pre=self.hab.pre,
                    sn=self.hab.kever.sn,
                    auths=auths,
                    proxy=self.proxy
                )

                # Wait for delegation to complete
                while not self.swain.complete(self.hab.kever.prefixer, coring.Seqner(sn=self.hab.kever.sn)):
                    yield self.tock

            # Handle witness authentication if present
            elif self.hab.kever.wits:
                logger.info(f"Authenticating witnesses for {self.hab.pre} with {len(auths)} codes")

                # Attempt to collect receipts with authentication
                yield from self.app.vault.receiptor.receipt(
                    self.hab.pre,
                    sn=self.hab.kever.sn,
                    auths=auths
                )

                # Verify we got enough receipts to meet TOAD
                wigs = self.hab.db.wigs.get(keys=dbing.dgKey(self.hab.pre, self.hab.kever.serder.said))
                if len(wigs) < self.hab.kever.toader.num:
                    error_msg = f"Insufficient witness receipts: got {len(wigs)}, need {self.hab.kever.toader.num}"
                    logger.error(error_msg)

                    # Set auth_pending flag
                    identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=True)
                    self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)

                    # Signal failure
                    if self.signal_bridge:
                        self.signal_bridge.emit_doer_event(
                            doer_name="AuthenticateWitnessesDoer",
                            event_type="witness_authentication_failed",
                            data={
                                'alias': self.hab.name,
                                'pre': self.hab.pre,
                                'error': error_msg,
                                'success': False
                            }
                        )
                    return

            # Send event to delegator if needed
            if self.hab.kever.delpre:
                sender = self.proxy if self.proxy is not None else self.hab
                yield from self.postman.sendEventToDelegator(
                    hab=self.hab,
                    sender=sender,
                    fn=self.hab.kever.sn
                )

            # Update witness states for all current witnesses after successful authentication
            # via plugin hooks (marks them as active / no longer reserved for rotation)
            if hasattr(self.app, 'plugin_manager') and self.app.plugin_manager:
                for wit in self.hab.kever.wits:
                    self.app.plugin_manager.update_witness_state_after_auth(self.app.vault, wit)
                    logger.info(f"Notified plugins about authenticated witness {wit}")

            # Clear auth_pending flag if it was set
            identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=False)
            self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)

            # Signal success
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="AuthenticateWitnessesDoer",
                    event_type="witness_authentication_success",
                    data={
                        'alias': self.hab.name,
                        'pre': self.hab.pre,
                        'sn': self.hab.kever.sn,
                        'success': True
                    }
                )

            logger.info(f"Witness authentication and delegation complete for {self.hab.name} ({self.hab.pre})")
            return

        except (kering.ValidationError, kering.AuthError) as e:
            logger.error(f"Witness authentication/delegation failed: {e}")

            # Set auth_pending flag
            identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=True)
            self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="AuthenticateWitnessesDoer",
                    event_type="witness_authentication_failed",
                    data={
                        'alias': self.hab.name,
                        'pre': self.hab.pre,
                        'error': str(e),
                        'success': False
                    }
                )
            return

        except Exception as e:
            logger.exception(f"AuthenticateWitnessesDoer failed with exception: {e}")

            # Set auth_pending flag
            if self.hab:
                identifier_meta_info = IdentifierMetaInfo(prefix=self.hab.pre, auth_pending=True)
                self.app.vault.db.idm.pin(keys=(self.hab.pre,), val=identifier_meta_info)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    doer_name="AuthenticateWitnessesDoer",
                    event_type="witness_authentication_failed",
                    data={
                        'alias': self.hab.name if self.hab else None,
                        'pre': self.hab.pre if self.hab else None,
                        'error': str(e),
                        'success': False
                    }
                )
            return
