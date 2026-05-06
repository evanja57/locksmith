# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.db.basing module

LMDB storage for KERI Foundation plugin state — account gating state,
witness records, witness batch groupings, and (future) watcher records.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from keri.db import dbing, koming


ACCOUNT_STATUS_PENDING_ONBOARDING = "pending_onboarding"
ACCOUNT_STATUS_ONBOARDED = "onboarded"
ACCOUNT_STATUS_FAILED = "failed"
ACCOUNT_RECORD_KEY = ("default",)


@dataclass
class KFAccountRecord:
    """Durable local account state for the one-account-per-vault KF plugin."""

    account_aid: str = ""
    account_alias: str = ""
    status: str = ACCOUNT_STATUS_PENDING_ONBOARDING
    created_at: str = ""
    onboarded_at: str = ""
    witness_profile_code: str = ""
    witness_count: int = 0
    toad: int = 0
    watcher_required: bool = True
    region_id: str = ""
    boot_server_aid: str = ""
    onboarding_session_id: str = ""
    onboarding_auth_alias: str = ""


@dataclass
class WitnessRecord:
    """Persisted state for a single registered KF witness."""
    eid: str = ""              # witness AID (prefix)
    url: str = ""              # base URL of witness server
    oobi: str = ""             # full OOBI URL
    totp_seed: str = ""        # decrypted base32 TOTP seed
    hab_pre: str = ""          # controller AID that registered
    registered_at: str = ""    # ISO8601 timestamp
    batch_mode: bool = False   # True if registered with a shared secret


@dataclass
class WitnessBatches:
    """Groups of witness EIDs that share a single TOTP secret."""
    batches: list = field(default_factory=list)  # list[list[str]]


@dataclass
class ProvisionedWitnessRecord:
    """Persisted state for a witness provisioned on a configured server."""

    boot_url: str = ""
    witness_url: str = ""
    eid: str = ""
    oobi: str = ""
    hab_pre: str = ""
    provisioned_at: str = ""


@dataclass
class WatcherRecord:
    """Stub for future watcher support."""
    eid: str = ""
    url: str = ""
    oobi: str = ""


@dataclass
class AttachedIdentifierRecord:
    """Local identifier intentionally attached to this provider."""
    prefix: str = ""
    attached_at: str = ""


class KFBaser(dbing.LMDBer):
    """LMDB database for KERI Foundation plugin."""

    TailDirPath = "keri/kf"
    AltTailDirPath = ".keri/kf"
    TempPrefix = "kf"

    def __init__(self, name="kerifoundation", headDirPath=None, reopen=True, **kwa):
        self.accounts = None
        self.witnesses = None
        self.witBatches = None
        self.provisionedWitnesses = None
        self.watchers = None
        self.attachedIdentifiers = None

        super(KFBaser, self).__init__(name=name, headDirPath=headDirPath, reopen=reopen, **kwa)

    def reopen(self, **kwa):
        super(KFBaser, self).reopen(**kwa)

        self.accounts = koming.Komer(db=self, subkey='acct.', klas=KFAccountRecord)
        self.witnesses = koming.Komer(db=self, subkey='wit.', klas=WitnessRecord)
        self.witBatches = koming.Komer(db=self, subkey='witb.', klas=WitnessBatches)
        self.provisionedWitnesses = koming.Komer(
            db=self, subkey='pwit.', klas=ProvisionedWitnessRecord
        )
        self.watchers = koming.Komer(db=self, subkey='wat.', klas=WatcherRecord)
        self.attachedIdentifiers = koming.Komer(
            db=self, subkey='idn.', klas=AttachedIdentifierRecord
        )

        return self.env

    def get_account(self) -> KFAccountRecord | None:
        """Return the single local KF account record for this vault, if any."""
        return self.accounts.get(keys=ACCOUNT_RECORD_KEY)

    def pin_account(self, record: KFAccountRecord) -> None:
        """Persist the single local KF account record for this vault."""
        self.accounts.pin(keys=ACCOUNT_RECORD_KEY, val=record)

    def ensure_account(self) -> tuple[KFAccountRecord, bool]:
        """Create the default local KF account record when missing."""
        record = self.get_account()
        if record is not None:
            return record, False

        record = KFAccountRecord(created_at=datetime.now(timezone.utc).isoformat())
        self.pin_account(record)
        return record, True

    def list_attached_identifier_prefixes(self) -> list[str]:
        return [prefix for (prefix,), _ in self.attachedIdentifiers.getTopItemIter(keys=())]

    def is_identifier_attached(self, prefix: str) -> bool:
        return self.attachedIdentifiers.get(keys=(prefix,)) is not None

    def attach_identifier(self, prefix: str) -> None:
        self.attachedIdentifiers.pin(
            keys=(prefix,),
            val=AttachedIdentifierRecord(
                prefix=prefix,
                attached_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
