# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.onboarding.service module

KF onboarding orchestration and boot-backed account transport helpers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin
from uuid import uuid4

import pyotp
import requests
from keri import help
from keri.app import agenting
from keri.app.httping import CESR_ATTACHMENT_HEADER, CESR_CONTENT_TYPE, CESR_DESTINATION_HEADER
from keri.core import parsing
from keri.core.serdering import SerderKERI
from keri.db import dbing
from keri.help import helping
from keri.peer import exchanging
from hio.base import doing

from locksmith.core.remoting import (
    introduce_watcher_observed_aid,
    message_version,
    purge_oobi_resolution_state,
    resolve_oobi_blocking,
)
from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_ONBOARDED,
    ACCOUNT_STATUS_PENDING_ONBOARDING,
    KFAccountRecord,
)
from locksmith.plugins.kerifoundation.core.configing import (
    KFSurfaceConfig,
    load_kf_surfaces,
)
from locksmith.plugins.kerifoundation.witnesses.provision import (
    HostedWitnessAllocation,
    HostedWitnessRegistrar,
    HostedWitnessRegistration,
    extract_base_url,
)

logger = help.ogler.getLogger(__name__)


ProgressFn = Callable[..., None] | None
ONBOARDING_AUTH_NAMESPACE = "kf_onboarding"
ONBOARDING_AUTH_ALIAS_PREFIX = "kf-onboarding"


@dataclass(frozen=True)
class BootstrapOption:
    code: str
    witness_count: int = 0
    toad: int = 0


@dataclass(frozen=True)
class BootstrapConfig:
    watcher_required: bool
    region_id: str
    region_name: str
    account_options: list[BootstrapOption] = field(default_factory=list)

    def option(self, code: str) -> BootstrapOption | None:
        for option in self.account_options:
            if option.code == code:
                return option
        return None


@dataclass(frozen=True)
class HostedWatcherAllocation:
    eid: str
    url: str
    oobi: str
    name: str = ""
    region_id: str = ""
    region_name: str = ""
    status: str = ""


@dataclass(frozen=True)
class CesrReply:
    ilk: str
    route: str
    sender: str
    said: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class OnboardingStartReply:
    session_id: str
    witnesses: list[HostedWitnessAllocation]
    watcher: HostedWatcherAllocation | None
    toad: int
    witness_count: int
    region_id: str
    region_name: str
    state: str = ""
    account_aid: str = ""
    failure_reason: str = ""


@dataclass(frozen=True)
class AccountWitnessRow:
    eid: str
    name: str
    url: str
    region_id: str = ""
    region_name: str = ""
    oobi: str = ""
    status: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class AccountWatcherRow:
    eid: str
    name: str
    url: str
    region_id: str = ""
    region_name: str = ""
    oobi: str = ""
    status: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class OnboardingOutcome:
    account_aid: str
    boot_server_aid: str
    witness_profile_code: str
    bootstrap: BootstrapConfig
    session_id: str
    witness_registration: HostedWitnessRegistration
    watcher: HostedWatcherAllocation | None


class KFBootError(RuntimeError):
    """Raised when a boot-surface request cannot be completed."""


class KFBootClient:
    """HTTP/CESR helper for the locked KF boot contract."""

    def __init__(self, app: Any, surfaces: KFSurfaceConfig | None = None):
        self._app = app
        self._surfaces = surfaces or load_kf_surfaces(app)
        self._boot_server_aid = ""
        self._surface_keystate: dict[tuple[str, str], int] = {}

    @property
    def boot_server_aid(self) -> str:
        return self._boot_server_aid

    def set_boot_server_aid(self, aid: str) -> None:
        self._boot_server_aid = aid or ""

    def clone(self) -> "KFBootClient":
        """Return an isolated client snapshot safe to hand to a worker thread."""
        client = KFBootClient(self._app, surfaces=self._surfaces)
        client._boot_server_aid = self._boot_server_aid
        client._surface_keystate = dict(self._surface_keystate)
        return client

    def check_health(self) -> dict[str, Any]:
        self._require_onboarding_url()

        response = requests.get(self._surfaces.health_url, timeout=10)
        response.raise_for_status()

        try:
            body = response.json()
        except ValueError:
            body = {}

        return body if isinstance(body, dict) else {}

    def fetch_bootstrap_config(self) -> BootstrapConfig:
        self._require_onboarding_url()

        response = requests.get(self._surfaces.bootstrap_url, timeout=15)
        response.raise_for_status()
        body = response.json()

        bootstrap = {}
        region = body.get("region", {}) if isinstance(body, dict) else {}
        if isinstance(body, dict):
            bootstrap = body.get("bootstrap", body)
        options = [
            BootstrapOption(
                code=str(option.get("code", "")),
                witness_count=int(option.get("witness_count", 0) or 0),
                toad=int(option.get("toad", 0) or 0),
            )
            for option in bootstrap.get("account_options", [])
            if isinstance(option, dict) and option.get("code")
        ]
        return BootstrapConfig(
            watcher_required=bool(bootstrap.get("watcher_required", True)),
            region_id=str(region.get("id", "") or ""),
            region_name=str(region.get("name", "") or ""),
            account_options=options,
        )

    def send_ephemeral_inception(self, hab: Any) -> None:
        msg = hab.makeOwnInception()
        self._post_cesr(
            url=self._surfaces.onboarding_url,
            ims=msg,
            destination=self._destination(surface="onboarding"),
            require_reply=False,
        )
        self._surface_keystate[("onboarding", hab.pre)] = 0

    def start_onboarding(
        self,
        hab: Any,
        *,
        alias: str,
        account_aid: str,
        witness_profile_code: str,
        region_id: str,
        watcher_required: bool,
    ) -> OnboardingStartReply:
        payload = {
            "account_alias": alias,
            "account_aid": account_aid,
            "chosen_profile_code": witness_profile_code,
            "region_id": region_id,
            "watcher_required": watcher_required,
        }
        reply = self.send_exn(
            surface="onboarding",
            hab=hab,
            route="/onboarding/session/start",
            payload=payload,
        )
        return self._normalize_start_reply(reply.payload, fallback_region_id=region_id)

    def session_status(
        self,
        hab: Any,
        *,
        session_id: str,
        destination: str = "",
        fallback_region_id: str = "",
    ) -> OnboardingStartReply:
        reply = self.send_exn(
            surface="onboarding",
            hab=hab,
            route="/onboarding/session/status",
            payload={"session_id": session_id},
            destination=destination,
        )
        return self._normalize_start_reply(reply.payload, fallback_region_id=fallback_region_id)

    def create_account(
        self,
        hab: Any,
        *,
        session_id: str,
        account_aid: str,
        alias: str,
        witness_profile_code: str,
        witnesses: list[HostedWitnessAllocation],
        watcher: HostedWatcherAllocation | None,
        region_id: str,
    ) -> CesrReply:
        payload = {
            "session_id": session_id,
            "account_aid": account_aid,
            "account_alias": alias,
            "chosen_profile_code": witness_profile_code,
            "region_id": region_id,
            "witness_eids": [witness.eid for witness in witnesses],
            "watcher_eid": watcher.eid if watcher is not None else "",
        }
        return self.send_exn(
            surface="onboarding",
            hab=hab,
            route="/onboarding/account/create",
            payload=payload,
        )

    def complete_onboarding(
        self,
        hab: Any,
        *,
        session_id: str,
        account_aid: str,
    ) -> CesrReply:
        payload = {
            "session_id": session_id,
            "account_aid": account_aid,
        }
        return self.send_exn(
            surface="onboarding",
            hab=hab,
            route="/onboarding/complete",
            payload=payload,
        )

    def cancel_onboarding(
        self,
        hab: Any,
        *,
        session_id: str,
        account_aid: str = "",
        reason: str = "",
    ) -> CesrReply:
        payload = {"session_id": session_id}
        if account_aid:
            payload["account_aid"] = account_aid
        if reason:
            payload["reason"] = reason
        return self.send_exn(
            surface="onboarding",
            hab=hab,
            route="/onboarding/cancel",
            payload=payload,
        )

    def list_account_witnesses(
        self,
        hab: Any,
        *,
        account_aid: str,
        destination: str = "",
    ) -> list[AccountWitnessRow]:
        reply = self.send_exn(
            surface="account",
            hab=hab,
            route="/account/witnesses",
            payload={"account_aid": account_aid},
            destination=destination,
        )
        return self._normalize_witness_rows(reply.payload)

    def list_account_watchers(
        self,
        hab: Any,
        *,
        account_aid: str,
        destination: str = "",
    ) -> list[AccountWatcherRow]:
        reply = self.send_exn(
            surface="account",
            hab=hab,
            route="/account/watchers",
            payload={"account_aid": account_aid},
            destination=destination,
        )
        return self._normalize_watcher_rows(reply.payload)

    def delete_account(
        self,
        hab: Any,
        *,
        account_aid: str,
        destination: str = "",
    ) -> CesrReply:
        return self.send_exn(
            surface="account",
            hab=hab,
            route="/account/delete",
            payload={"account_aid": account_aid},
            destination=destination,
        )

    def send_exn(
        self,
        *,
        surface: str,
        hab: Any,
        route: str,
        payload: dict[str, Any],
        destination: str = "",
    ) -> CesrReply:
        dest = destination or self._destination(surface=surface)
        if surface == "account":
            self._ensure_surface_keystate(surface=surface, hab=hab, destination=dest)
        serder, end = exchanging.exchange(
            route=route,
            payload=payload,
            sender=hab.pre,
            recipient=dest or None,
        )
        ims = hab.endorse(serder=serder, last=False, pipelined=False)
        attachment = bytearray(ims)
        del attachment[:serder.size]
        if end:
            attachment.extend(end)
        return self._post_cesr(
            url=self._surface_url(surface),
            body=serder.raw,
            attachment=attachment,
            destination=dest,
            require_reply=True,
            expected_kinds=("rpy", "exn"),
            expected_route=route,
            expected_sender=dest or self._boot_server_aid,
        )

    def _post_cesr(
        self,
        *,
        url: str,
        ims: bytearray | bytes | None = None,
        body: bytes | bytearray | None = None,
        attachment: bytes | bytearray | None = None,
        destination: str = "",
        require_reply: bool,
        expected_kinds: tuple[str, ...] = (),
        expected_route: str = "",
        expected_sender: str = "",
    ) -> CesrReply | None:
        if ims is not None:
            body, attachment = split_cesr_message(ims)

        if body is None:
            raise KFBootError("Missing CESR request body")

        headers = {
            "Content-Type": CESR_CONTENT_TYPE,
            "Content-Length": str(len(body)),
        }
        if attachment:
            headers[CESR_ATTACHMENT_HEADER] = bytes(attachment).decode("utf-8")
        if destination:
            headers[CESR_DESTINATION_HEADER] = destination

        response = requests.post(url, data=body, headers=headers, timeout=30)
        if response.status_code >= 400:
            raise KFBootError(self._format_http_error(response))

        if not require_reply:
            return None

        reply = parse_cesr_http_reply(
            self._app,
            response,
            expected_kinds=expected_kinds,
            expected_route=expected_route,
            expected_sender=expected_sender,
        )
        if reply.sender:
            self._boot_server_aid = reply.sender
        return reply

    @staticmethod
    def _format_http_error(response) -> str:
        status = f"{response.status_code} {getattr(response, 'reason', '')}".strip()
        detail = ""

        try:
            payload = response.json()
        except Exception:
            payload = None

        if isinstance(payload, dict):
            title = str(payload.get("title", "") or "").strip()
            description = str(payload.get("description", "") or "").strip()
            detail = " - ".join(part for part in (title, description) if part)

        if not detail:
            detail = str(getattr(response, "text", "") or "").strip()

        if detail:
            return f"Boot service request failed: {status} for {response.url}: {detail}"
        return f"Boot service request failed: {status} for {response.url}"

    def _ensure_surface_keystate(self, *, surface: str, hab: Any, destination: str = "") -> None:
        current_sn = int(getattr(getattr(hab, "kever", None), "sn", 0) or 0)
        cache_key = (surface, hab.pre)
        synced_sn = self._surface_keystate.get(cache_key, -1)
        if synced_sn >= current_sn:
            return

        for _, msg in self._iter_surface_keystate_messages(
            hab=hab,
            start_sn=synced_sn + 1,
            end_sn=current_sn,
        ):
            self._post_cesr(
                url=self._surface_url(surface),
                ims=msg,
                destination=destination,
                require_reply=False,
            )

        self._surface_keystate[cache_key] = current_sn

    @staticmethod
    def _iter_surface_keystate_messages(*, hab: Any, start_sn: int, end_sn: int):
        """Replay fully attached KEL events so remote auth surfaces see witnessed rotations."""

        messages = {}
        for msg in hab.db.clonePreIter(pre=hab.pre):
            raw = bytes(msg)
            serder = SerderKERI(raw=raw)
            sn = int(getattr(serder, "sn", serder.ked.get("s", 0)) or 0)
            if sn < start_sn or sn > end_sn or sn in messages:
                continue
            messages[sn] = raw

        for sn in range(start_sn, end_sn + 1):
            yield sn, messages.get(sn, bytes(hab.makeOwnEvent(sn=sn)))

    def _normalize_start_reply(
        self,
        payload: dict[str, Any],
        *,
        fallback_region_id: str,
    ) -> OnboardingStartReply:
        session = payload.get("session", {}) if isinstance(payload.get("session"), dict) else {}
        session_id = str(
            payload.get("session_id")
            or session.get("session_id")
            or session.get("id")
            or ""
        )
        witnesses = [
            self._normalize_witness_allocation(entry, fallback_region_id=fallback_region_id)
            for entry in _rows_from_payload(payload, "witnesses")
        ]
        watcher = None
        raw_watcher = payload.get("watcher")
        if isinstance(raw_watcher, dict):
            watcher = self._normalize_watcher_allocation(raw_watcher, fallback_region_id=fallback_region_id)
        else:
            watchers = _rows_from_payload(payload, "watchers")
            if watchers:
                watcher = self._normalize_watcher_allocation(watchers[0], fallback_region_id=fallback_region_id)

        toad = int(payload.get("toad", 0) or 0)
        witness_count = int(payload.get("witness_count", 0) or len(witnesses))
        region_id = str(payload.get("region_id", "") or fallback_region_id)
        region_name = str(payload.get("region_name", "") or "")
        state = str(payload.get("state") or session.get("state") or "")
        account_aid = str(payload.get("account_aid") or session.get("account_aid") or "")
        failure_reason = str(payload.get("failure_reason") or session.get("failure_reason") or "")
        if not session_id:
            raise KFBootError("Onboarding reply did not include a session identifier")
        return OnboardingStartReply(
            session_id=session_id,
            witnesses=witnesses,
            watcher=watcher,
            toad=toad,
            witness_count=witness_count,
            region_id=region_id,
            region_name=region_name,
            state=state,
            account_aid=account_aid,
            failure_reason=failure_reason,
        )

    @staticmethod
    def _normalize_witness_allocation(
        raw: dict[str, Any],
        *,
        fallback_region_id: str,
    ) -> HostedWitnessAllocation:
        return HostedWitnessAllocation(
            eid=str(raw.get("eid", "") or ""),
            witness_url=str(raw.get("witness_url") or raw.get("url") or ""),
            boot_url=str(raw.get("boot_url", "") or ""),
            oobi=_pick_oobi(raw),
            name=str(raw.get("name", "") or ""),
            region_id=str(raw.get("region_id", "") or fallback_region_id),
            region_name=str(raw.get("region_name", "") or ""),
        )

    @staticmethod
    def _normalize_watcher_allocation(
        raw: dict[str, Any],
        *,
        fallback_region_id: str,
    ) -> HostedWatcherAllocation:
        return HostedWatcherAllocation(
            eid=str(raw.get("eid", "") or ""),
            url=str(raw.get("watcher_url") or raw.get("url") or ""),
            oobi=_pick_oobi(raw),
            name=str(raw.get("name", "") or ""),
            region_id=str(raw.get("region_id", "") or fallback_region_id),
            region_name=str(raw.get("region_name", "") or ""),
            status=str(raw.get("status", "") or ""),
        )

    def _normalize_witness_rows(self, payload: dict[str, Any]) -> list[AccountWitnessRow]:
        rows = []
        for entry in _rows_from_payload(payload, "witnesses"):
            rows.append(
                AccountWitnessRow(
                    eid=str(entry.get("eid", "") or ""),
                    name=str(entry.get("name", "") or ""),
                    url=str(entry.get("url") or entry.get("witness_url") or ""),
                    region_id=str(entry.get("region_id", "") or ""),
                    region_name=str(entry.get("region_name", "") or ""),
                    oobi=_pick_oobi(entry),
                    status=str(entry.get("status", "") or ""),
                    created_at=str(entry.get("created_at", "") or ""),
                )
            )
        return rows

    def _normalize_watcher_rows(self, payload: dict[str, Any]) -> list[AccountWatcherRow]:
        rows = []
        for entry in _rows_from_payload(payload, "watchers"):
            rows.append(
                AccountWatcherRow(
                    eid=str(entry.get("eid", "") or ""),
                    name=str(entry.get("name", "") or ""),
                    url=str(entry.get("url") or entry.get("watcher_url") or ""),
                    region_id=str(entry.get("region_id", "") or ""),
                    region_name=str(entry.get("region_name", "") or ""),
                    oobi=_pick_oobi(entry),
                    status=str(entry.get("status", "") or ""),
                    created_at=str(entry.get("created_at", "") or ""),
                )
            )
        return rows

    def _destination(self, *, surface: str) -> str:
        if surface == "account":
            return self._surfaces.account_destination or self._boot_server_aid
        return self._surfaces.onboarding_destination or self._boot_server_aid

    def _surface_url(self, surface: str) -> str:
        if surface == "account":
            if self._surfaces.account_url:
                return self._surfaces.account_url
            raise KFBootError(
                "KF account surface URL is not configured. "
                "Set KF_DEV_ACCOUNT_URL or KF_PROD_ACCOUNT_URL."
            )

        self._require_onboarding_url()
        return self._surfaces.onboarding_url

    def _require_onboarding_url(self) -> None:
        if self._surfaces.onboarding_url:
            return
        raise KFBootError(
            "KF onboarding surface URL is not configured. "
            "Set KF_DEV_ONBOARDING_URL or KF_PROD_ONBOARDING_URL."
        )


class KFOnboardingService:
    """Execute the Step 4/5/6 client flow against the locked contract."""

    def __init__(
        self,
        *,
        app: Any,
        db: Any,
        boot_client: KFBootClient,
        witness_registrar: HostedWitnessRegistrar | None = None,
    ):
        self._app = app
        self._db = db
        self._boot_client = boot_client
        self._witness_registrar = witness_registrar or HostedWitnessRegistrar(app=app, db=db)

    def onboard(
        self,
        *,
        alias: str,
        witness_profile_code: str,
        account_aid: str = "",
        progress: ProgressFn = None,
    ) -> OnboardingOutcome:
        record = self._ensure_account_record()
        self._emit(progress, stage="bootstrap", detail="Fetching bootstrap config")
        bootstrap = self._boot_client.fetch_bootstrap_config()

        option = bootstrap.option(witness_profile_code)
        if option is None:
            raise KFBootError(f"Unsupported witness profile '{witness_profile_code}' from bootstrap config")

        self._emit(
            progress,
            stage="bootstrap",
            detail=(
                f"Bootstrap loaded for region '{bootstrap.region_name or bootstrap.region_id or 'default'}' "
                f"with profile '{witness_profile_code}'"
            ),
        )

        start: OnboardingStartReply | None = None
        account_hab = None
        ehab = None
        witness_registration: HostedWitnessRegistration | None = None
        created_new_account = not self._account_hab_exists(
            record=record,
            alias=alias,
            requested_account_aid=account_aid,
        )

        try:
            self._emit(progress, stage="account_aid", detail="Preparing permanent local account AID")
            account_hab = self._create_or_load_account_hab(
                record=record,
                alias=alias,
                requested_account_aid=account_aid,
            )
            self._pin_account_progress(
                record=record,
                alias=alias,
                witness_profile_code=witness_profile_code,
                witness_count=option.witness_count,
                toad=option.toad,
                watcher_required=bootstrap.watcher_required,
                region_id=bootstrap.region_id,
                account_aid=account_hab.pre,
                boot_server_aid=self._boot_client.boot_server_aid,
                status=ACCOUNT_STATUS_PENDING_ONBOARDING,
            )

            ehab, created_new_auth = self._load_or_create_onboarding_hab(record=record)
            if created_new_auth:
                self._emit(progress, stage="ephemeral_aid", detail="Created hidden onboarding AID")
            else:
                self._emit(progress, stage="ephemeral_aid", detail="Loaded hidden onboarding AID for retry")

            start, session_cleared = self._load_existing_session(
                ehab=ehab,
                record=record,
                account_hab=account_hab,
                bootstrap=bootstrap,
                progress=progress,
            )
            if session_cleared:
                ehab, _ = self._load_or_create_onboarding_hab(record=record)
                self._emit(progress, stage="ephemeral_aid", detail="Created hidden onboarding AID")
            if start is None:
                self._emit(progress, stage="ephemeral_aid", detail="Sending onboarding inception to the boot surface")
                self._boot_client.send_ephemeral_inception(ehab)
                self._emit(progress, stage="session_start", detail="Starting authenticated onboarding session")
                start = self._boot_client.start_onboarding(
                    ehab,
                    alias=alias,
                    account_aid=account_hab.pre,
                    witness_profile_code=witness_profile_code,
                    region_id=bootstrap.region_id,
                    watcher_required=bootstrap.watcher_required,
                )

            self._emit(
                progress,
                stage="boot_reply_verified",
                detail=f"Verified boot reply from {self._boot_client.boot_server_aid or 'discovered boot server'}",
                boot_verified=True,
            )

            self._validate_allocated_profile(
                start=start,
                option=option,
                watcher_required=bootstrap.watcher_required,
            )

            self._pin_account_progress(
                record=record,
                alias=alias,
                witness_profile_code=witness_profile_code,
                witness_count=start.witness_count or option.witness_count,
                toad=start.toad or option.toad,
                watcher_required=bootstrap.watcher_required,
                region_id=start.region_id or bootstrap.region_id,
                account_aid=account_hab.pre,
                boot_server_aid=self._boot_client.boot_server_aid,
                status=ACCOUNT_STATUS_PENDING_ONBOARDING,
                onboarding_session_id=start.session_id,
                onboarding_auth_alias=ehab.name,
            )

            needs_rotation = self._account_needs_witness_rotation(
                hab=account_hab,
                allocated_witness_eids=[witness.eid for witness in start.witnesses],
                toad=start.toad or option.toad,
            )

            witness_registration = self._load_existing_witness_registration(
                account_aid=account_hab.pre,
                witnesses=start.witnesses,
            )
            if witness_registration is None:
                self._emit(
                    progress,
                    stage="witness_registration",
                    detail="Registering the account AID with allocated witnesses",
                )
                witness_registration = self._witness_registrar.register(
                    hab=account_hab,
                    witnesses=start.witnesses,
                    batch_mode=True,
                    persist=True,
                )
            else:
                self._emit(
                    progress,
                    stage="witness_registration",
                    detail="Reusing persisted witness registration state from the prior attempt",
                )

            if needs_rotation:
                self._emit(
                    progress,
                    stage="witness_rotation",
                    detail="Rotating the local account AID onto the hosted witness set",
                )
                self._rotate_account_to_allocated_witnesses(
                    hab=account_hab,
                    registration=witness_registration,
                    allocated_witness_eids=[witness.eid for witness in start.witnesses],
                    toad=start.toad or option.toad,
                )

            if start.watcher is not None:
                self._emit(progress, stage="watcher_resolution", detail="Resolving the required hosted watcher OOBI")
                self._resolve_watcher_oobi(account_hab=account_hab, watcher=start.watcher)
                self._emit(
                    progress,
                    stage="watcher_binding",
                    detail="Introducing the permanent account AID to the hosted watcher",
                )
                self._introduce_account_to_watcher(
                    account_hab=account_hab,
                    watcher=start.watcher,
                    witnesses=start.witnesses,
                )

            self._emit(progress, stage="account_create", detail="Sending /onboarding/account/create")
            self._boot_client.create_account(
                ehab,
                session_id=start.session_id,
                account_aid=account_hab.pre,
                alias=alias,
                witness_profile_code=witness_profile_code,
                witnesses=start.witnesses,
                watcher=start.watcher,
                region_id=start.region_id or bootstrap.region_id,
            )

            self._emit(progress, stage="complete", detail="Sending /onboarding/complete")
            self._boot_client.complete_onboarding(
                ehab,
                session_id=start.session_id,
                account_aid=account_hab.pre,
            )
        except Exception:
            if self._should_preserve_onboarding_session(start=start, account_hab=account_hab):
                self._pin_account_progress(
                    record=record,
                    alias=alias,
                    witness_profile_code=witness_profile_code,
                    witness_count=(start.witness_count if start is not None else option.witness_count) or option.witness_count,
                    toad=(start.toad if start is not None else option.toad) or option.toad,
                    watcher_required=bootstrap.watcher_required,
                    region_id=(start.region_id if start is not None else bootstrap.region_id) or bootstrap.region_id,
                    account_aid=getattr(account_hab, "pre", record.account_aid),
                    boot_server_aid=self._boot_client.boot_server_aid or record.boot_server_aid,
                    status=record.status,
                    onboarding_session_id=start.session_id if start is not None else record.onboarding_session_id,
                    onboarding_auth_alias=getattr(ehab, "name", "") or record.onboarding_auth_alias,
                )
            else:
                self._abandon_onboarding_run(
                    ehab=ehab,
                    start=start,
                    account_hab=account_hab,
                    witness_registration=witness_registration,
                )
                self._clear_onboarding_session(record, delete_auth_hab=True)
                if created_new_account and account_hab is not None:
                    self._delete_local_account_hab(account_hab)
                    record.account_aid = ""
                    record.account_alias = ""
            raise

        if account_hab is None or start is None or witness_registration is None:
            raise KFBootError("Onboarding did not complete all required phases")

        self._complete_onboarding_record(
            record=record,
            alias=alias,
            witness_profile_code=witness_profile_code,
            witness_count=start.witness_count or option.witness_count,
            toad=start.toad or option.toad,
            watcher_required=bootstrap.watcher_required,
            region_id=start.region_id or bootstrap.region_id,
            account_aid=account_hab.pre,
            boot_server_aid=self._boot_client.boot_server_aid,
            status=ACCOUNT_STATUS_ONBOARDED,
            onboarded_at=helping.nowIso8601(),
        )
        self._clear_onboarding_session(record, delete_auth_hab=True)

        self._emit(progress, stage="completed", detail="Onboarding complete", completed=True, boot_verified=True)
        return OnboardingOutcome(
            account_aid=account_hab.pre,
            boot_server_aid=self._boot_client.boot_server_aid,
            witness_profile_code=witness_profile_code,
            bootstrap=bootstrap,
            session_id=start.session_id,
            witness_registration=witness_registration,
            watcher=start.watcher,
        )

    def _load_existing_session(
        self,
        *,
        ehab: Any,
        record: KFAccountRecord,
        account_hab: Any,
        bootstrap: BootstrapConfig,
        progress: ProgressFn,
    ) -> tuple[OnboardingStartReply | None, bool]:
        if not record.onboarding_session_id:
            return None, False

        try:
            self._emit(progress, stage="session_start", detail="Resuming the saved onboarding session")
            start = self._boot_client.session_status(
                ehab,
                session_id=record.onboarding_session_id,
                destination=record.boot_server_aid,
                fallback_region_id=bootstrap.region_id,
            )
        except Exception as exc:
            if self._can_discard_stored_session(record=record, account_hab=account_hab):
                logger.warning(
                    "Discarding stale KF onboarding session %s after status lookup failure: %s",
                    record.onboarding_session_id,
                    exc,
                )
                self._clear_onboarding_session(record, delete_auth_hab=True)
                return None, True
            raise

        if start.account_aid and start.account_aid != account_hab.pre:
            raise KFBootError(
                "The saved onboarding session is bound to a different permanent account AID."
            )

        if start.state in {"failed", "cancelled", "expired"}:
            if self._can_discard_stored_session(record=record, account_hab=account_hab):
                self._clear_onboarding_session(record, delete_auth_hab=True)
                return None, True
            raise KFBootError(
                start.failure_reason
                or "The saved onboarding session closed after local witness changes. Resume is no longer safe."
            )

        return start, False

    def _create_or_load_account_hab(
        self,
        *,
        record: KFAccountRecord,
        alias: str,
        requested_account_aid: str,
    ):
        existing = None
        if requested_account_aid:
            existing = self._app.vault.hby.habByPre(requested_account_aid)
            if existing is None:
                raise KFBootError(
                    f"Selected local account AID {requested_account_aid} is missing from the local wallet"
                )
        elif record.account_aid:
            existing = self._app.vault.hby.habByPre(record.account_aid)
            if existing is None:
                raise KFBootError(
                    f"Persisted account AID {record.account_aid} is missing from the local wallet"
                )
        else:
            existing = self._app.vault.hby.habByName(alias)

        if existing is not None:
            if requested_account_aid and existing.pre != requested_account_aid:
                raise KFBootError(
                    f"Selected account AID mismatch for alias '{alias}': {existing.pre} != {requested_account_aid}"
                )
            if not requested_account_aid and record.account_aid and existing.pre != record.account_aid:
                raise KFBootError(
                    f"Local account AID mismatch for alias '{alias}': {existing.pre} != {record.account_aid}"
                )
            if not requested_account_aid and not record.account_aid:
                raise KFBootError(
                    f"Alias '{alias}' is already used by another local identifier. "
                    "Choose a different KF account alias."
                )
            logger.info("Reusing existing local account AID for alias '%s': %s", alias, existing.pre)
            return existing

        hab = self._app.vault.hby.makeHab(
            name=alias,
            algo="randy",
            icount=1,
            isith="1",
            ncount=1,
            nsith="1",
            wits=[],
            toad=0,
        )
        logger.info("Created permanent local account AID %s for alias '%s'", hab.pre, alias)
        return hab

    def _account_hab_exists(
        self,
        *,
        record: KFAccountRecord,
        alias: str,
        requested_account_aid: str,
    ) -> bool:
        if requested_account_aid:
            return self._app.vault.hby.habByPre(requested_account_aid) is not None
        if record.account_aid:
            return self._app.vault.hby.habByPre(record.account_aid) is not None
        return self._app.vault.hby.habByName(alias) is not None

    def _load_or_create_onboarding_hab(self, *, record: KFAccountRecord) -> tuple[Any, bool]:
        if record.onboarding_auth_alias:
            existing = self._app.vault.hby.habByName(
                record.onboarding_auth_alias,
                ns=ONBOARDING_AUTH_NAMESPACE,
            )
            if existing is not None:
                return existing, False
            raise KFBootError(
                "The saved onboarding session is missing its hidden auth principal. "
                "Do not start a second onboarding run until the stored state is cleared."
            )

        alias = f"{ONBOARDING_AUTH_ALIAS_PREFIX}-{uuid4().hex[:12]}"
        hab = self._app.vault.hby.makeHab(
            name=alias,
            ns=ONBOARDING_AUTH_NAMESPACE,
            transferable=False,
            icount=1,
            isith="1",
            ncount=0,
            nsith="0",
            wits=[],
            toad=0,
        )
        return hab, True

    def _clear_onboarding_session(self, record: KFAccountRecord, *, delete_auth_hab: bool) -> None:
        auth_alias = record.onboarding_auth_alias
        record.onboarding_session_id = ""
        record.onboarding_auth_alias = ""
        self._db.pin_account(record)
        if delete_auth_hab and auth_alias:
            self._delete_onboarding_hab(auth_alias)

    def _delete_onboarding_hab(self, alias: str) -> None:
        try:
            self._app.vault.hby.deleteHab(alias, ns=ONBOARDING_AUTH_NAMESPACE)
        except Exception:
            logger.warning("Failed deleting hidden KF onboarding AID %s", alias, exc_info=True)

    def _delete_local_account_hab(self, hab: Any) -> None:
        try:
            self._app.vault.hby.deleteHab(hab.name)
        except Exception:
            logger.warning("Failed deleting abandoned local account AID %s", getattr(hab, "pre", ""), exc_info=True)

    def _load_existing_witness_registration(
        self,
        *,
        account_aid: str,
        witnesses: list[HostedWitnessAllocation],
    ) -> HostedWitnessRegistration | None:
        if not self._db or not account_aid or not witnesses:
            return None

        results: list[dict[str, Any]] = []
        witness_eids = [witness.eid for witness in witnesses]
        for witness in witnesses:
            saved = self._db.witnesses.get(keys=(account_aid, witness.eid))
            if saved is None or not saved.totp_seed:
                return None
            results.append(
                {
                    "eid": witness.eid,
                    "oobi": saved.oobi or witness.oobi,
                    "totp_seed": saved.totp_seed,
                    "boot_url": witness.boot_url,
                    "witness_url": witness.witness_url,
                }
            )

        batch_mode = False
        try:
            existing = self._db.witBatches.get(keys=(account_aid,))
            if existing is not None:
                batch_mode = witness_eids in existing.batches
        except Exception:
            logger.warning("Failed reading persisted witness batch state for %s", account_aid, exc_info=True)

        return HostedWitnessRegistration(results=results, batch_mode=batch_mode)

    @staticmethod
    def _should_preserve_onboarding_session(
        *,
        start: OnboardingStartReply | None,
        account_hab: Any | None,
    ) -> bool:
        if start is None or account_hab is None:
            return False
        allocated = [witness.eid for witness in start.witnesses]
        current = list(getattr(getattr(account_hab, "kever", None), "wits", []) or [])
        return bool(allocated) and current == allocated

    def _can_discard_stored_session(self, *, record: KFAccountRecord, account_hab: Any) -> bool:
        if record.account_aid and record.account_aid != getattr(account_hab, "pre", ""):
            return False
        current = list(getattr(getattr(account_hab, "kever", None), "wits", []) or [])
        if current:
            return False
        return not self._has_any_local_witness_state(getattr(account_hab, "pre", ""))

    def _has_any_local_witness_state(self, account_aid: str) -> bool:
        if not self._db or not account_aid:
            return False
        for (hab_pre, _eid), _record in self._db.witnesses.getTopItemIter(keys=()):
            if hab_pre == account_aid:
                return True
        return False

    def _complete_onboarding_record(
        self,
        *,
        record: KFAccountRecord,
        alias: str,
        witness_profile_code: str,
        witness_count: int,
        toad: int,
        watcher_required: bool,
        region_id: str,
        account_aid: str,
        boot_server_aid: str,
        status: str,
        onboarded_at: str,
    ) -> None:
        self._pin_account_progress(
            record=record,
            alias=alias,
            witness_profile_code=witness_profile_code,
            witness_count=witness_count,
            toad=toad,
            watcher_required=watcher_required,
            region_id=region_id,
            account_aid=account_aid,
            boot_server_aid=boot_server_aid,
            status=status,
            onboarded_at=onboarded_at,
            onboarding_session_id="",
            onboarding_auth_alias=record.onboarding_auth_alias,
        )

    def _account_needs_witness_rotation(
        self,
        *,
        hab: Any,
        allocated_witness_eids: list[str],
        toad: int,
    ) -> bool:
        current_wits = list(getattr(getattr(hab, "kever", None), "wits", []) or [])
        current_toad = getattr(getattr(getattr(hab, "kever", None), "toader", None), "num", None)

        if current_wits == list(allocated_witness_eids) and (current_toad is None or current_toad == toad):
            return False

        if current_wits:
            raise KFBootError(
                "The selected permanent account AID already has a different witness configuration. "
                "Choose a fresh local AID or one that already matches the allocated witness pool."
            )

        return True

    def _rotate_account_to_allocated_witnesses(
        self,
        *,
        hab: Any,
        registration: HostedWitnessRegistration,
        allocated_witness_eids: list[str],
        toad: int,
    ) -> None:
        auths = self._build_witness_auths(registration)
        if len(allocated_witness_eids) == 1:
            witness_eid = allocated_witness_eids[0]
            witness_url = self._single_witness_url(registration=registration, witness_eid=witness_eid)
            try:
                hab.rotate(toad=toad, cuts=[], adds=list(allocated_witness_eids))
                self._receipt_single_witness_rotation(
                    hab=hab,
                    witness_eid=witness_eid,
                    witness_url=witness_url,
                    auth=auths.get(witness_eid, ""),
                )
            except Exception as exc:
                raise KFBootError(f"Failed rotating the local account AID onto hosted witnesses: {exc}") from exc
            return

        receiptor = agenting.Receiptor(hby=self._app.vault.hby)

        def rotate_and_receipt(tymth, tock=0.0, **opts):
            _ = opts
            receiptor.wind(tymth)
            _ = (yield tock)
            hab.rotate(toad=toad, cuts=[], adds=list(allocated_witness_eids))
            yield from receiptor.receipt(hab.pre, sn=hab.kever.sn, auths=auths)
            return

        runner = doing.doify(rotate_and_receipt)
        try:
            doing.Doist(tock=0.03125, real=True).do(doers=[receiptor, runner], limit=30.0)
        except Exception as exc:
            raise KFBootError(f"Failed rotating the local account AID onto hosted witnesses: {exc}") from exc

    def _receipt_single_witness_rotation(
        self,
        *,
        hab: Any,
        witness_eid: str,
        witness_url: str,
        auth: str,
    ) -> None:
        msg = bytearray(hab.makeOwnEvent(sn=hab.kever.sn))
        serder = SerderKERI(raw=bytearray(msg))
        attachments = bytes(msg[serder.size:])
        headers = {
            "Content-Type": CESR_CONTENT_TYPE,
            CESR_ATTACHMENT_HEADER: attachments.decode("utf-8"),
            CESR_DESTINATION_HEADER: witness_eid,
        }
        if auth:
            headers["Authorization"] = auth

        response = requests.post(
            urljoin(witness_url.rstrip("/") + "/", "receipts"),
            headers=headers,
            data=bytes(serder.raw),
            timeout=15,
        )
        if response.status_code != 200:
            raise KFBootError(
                f"Witness {witness_eid} rejected the rotation event with status {response.status_code}"
            )

        hab.psr.parseOne(ims=bytearray(response.content))
        dgkey = dbing.dgKey(hab.pre, hab.kever.serder.said)
        wigs = hab.db.wigs.get(keys=dgkey)
        if len(wigs) < hab.kever.toader.num:
            raise KFBootError(
                f"Insufficient witness receipts after rotation: got {len(wigs)}, need {hab.kever.toader.num}"
            )

    @staticmethod
    def _single_witness_url(*, registration: HostedWitnessRegistration, witness_eid: str) -> str:
        for result in registration.results:
            if str(result.get("eid", "")) != witness_eid:
                continue
            url = str(result.get("witness_url", "") or "")
            if url:
                return url
            oobi = str(result.get("oobi", "") or "")
            if oobi:
                base = extract_base_url(oobi)
                if base:
                    return base
        raise KFBootError(f"Hosted witness registration did not include a usable URL for {witness_eid}")

    @staticmethod
    def _build_witness_auths(registration: HostedWitnessRegistration) -> dict[str, str]:
        code_time = helping.nowIso8601()
        auths: dict[str, str] = {}
        for result in registration.results:
            seed = str(result.get("totp_seed", "") or "")
            eid = str(result.get("eid", "") or "")
            if not seed or not eid:
                raise KFBootError("Hosted witness registration did not return usable authentication material")
            auths[eid] = f"{pyotp.TOTP(seed).now()}#{code_time}"
        return auths

    @staticmethod
    def _validate_allocated_profile(
        *,
        start: OnboardingStartReply,
        option: BootstrapOption,
        watcher_required: bool,
    ) -> None:
        if len(start.witnesses) != option.witness_count:
            raise KFBootError(
                "Allocated witness profile does not match the requested witness profile"
            )
        if start.witness_count and start.witness_count != option.witness_count:
            raise KFBootError(
                "Allocated witness profile does not match the requested witness profile"
            )
        if (start.toad or option.toad) != option.toad:
            raise KFBootError(
                "Allocated witness profile does not match the requested witness profile"
            )
        eids = [witness.eid for witness in start.witnesses if witness.eid]
        if len(eids) != len(start.witnesses) or len(set(eids)) != len(eids):
            raise KFBootError("Allocated witness profile contains invalid witness identifiers")
        if watcher_required and start.watcher is None:
            raise KFBootError("Onboarding reply did not include the required hosted watcher")

    def _abandon_onboarding_run(
        self,
        *,
        ehab: Any | None,
        start: OnboardingStartReply | None,
        account_hab: Any | None,
        witness_registration: HostedWitnessRegistration | None,
    ) -> None:
        if start is not None and ehab is not None:
            try:
                self._boot_client.cancel_onboarding(
                    ehab,
                    session_id=start.session_id,
                    account_aid=getattr(account_hab, "pre", "") if account_hab is not None else "",
                    reason="client_abandoned",
                )
            except Exception:
                logger.warning("Failed abandoning KF onboarding session %s", start.session_id, exc_info=True)

        if witness_registration is not None:
            self._remove_local_witness_state(
                account_aid=getattr(account_hab, "pre", ""),
                registration=witness_registration,
            )
            for result in witness_registration.results:
                purge_oobi_resolution_state(self._app, oobi=result.get("oobi"))
            self._remove_remote_ids([result["eid"] for result in witness_registration.results])
        elif start is not None and account_hab is not None:
            self._remove_local_witness_state_from_allocations(
                account_aid=account_hab.pre,
                witnesses=start.witnesses,
            )
            for witness in start.witnesses:
                purge_oobi_resolution_state(self._app, oobi=witness.oobi)
            self._remove_remote_ids([witness.eid for witness in start.witnesses])

        if start is not None and start.watcher is not None:
            purge_oobi_resolution_state(self._app, oobi=start.watcher.oobi)
            self._remove_remote_ids([start.watcher.eid])

    def _remove_local_witness_state(
        self,
        *,
        account_aid: str,
        registration: HostedWitnessRegistration,
    ) -> None:
        if not self._db or not account_aid:
            return

        for result in registration.results:
            try:
                self._db.witnesses.rem(keys=(account_aid, result["eid"]))
            except Exception:
                logger.warning("Failed removing local witness state for %s", result["eid"], exc_info=True)

            boot_url = str(result.get("boot_url", "") or "")
            if not boot_url:
                continue
            try:
                self._db.provisionedWitnesses.rem(keys=(account_aid, boot_url))
            except Exception:
                logger.warning(
                    "Failed removing provisioned witness state for %s on %s",
                    result["eid"],
                    account_aid,
                    exc_info=True,
                )

        if registration.batch_mode and registration.results:
            batch_eids = [result["eid"] for result in registration.results]
            try:
                existing = self._db.witBatches.get(keys=(account_aid,))
                if existing is None:
                    return
                remaining_batches = [batch for batch in existing.batches if batch != batch_eids]
                if remaining_batches:
                    existing.batches = remaining_batches
                    self._db.witBatches.pin(keys=(account_aid,), val=existing)
                else:
                    self._db.witBatches.rem(keys=(account_aid,))
            except Exception:
                logger.warning("Failed removing witness batch state for %s", account_aid, exc_info=True)

    def _remove_local_witness_state_from_allocations(
        self,
        *,
        account_aid: str,
        witnesses: list[HostedWitnessAllocation],
    ) -> None:
        registration = HostedWitnessRegistration(
            results=[
                {
                    "eid": witness.eid,
                    "boot_url": witness.boot_url,
                }
                for witness in witnesses
            ],
            batch_mode=False,
        )
        self._remove_local_witness_state(account_aid=account_aid, registration=registration)

    def _remove_remote_ids(self, eids: list[str]) -> None:
        if not self._app or not getattr(self._app, "vault", None) or not getattr(self._app.vault, "org", None):
            return

        for eid in eids:
            try:
                self._app.vault.org.rem(eid)
            except Exception:
                logger.warning("Failed removing remote identifier %s from Organizer", eid, exc_info=True)

    def _resolve_watcher_oobi(self, *, account_hab: Any, watcher: HostedWatcherAllocation) -> None:
        if not watcher.oobi:
            raise KFBootError("Hosted watcher reply is missing an OOBI")

        alias = watcher.name or f"KF Watcher {watcher.eid[:12]}"
        resolved = resolve_oobi_blocking(
            self._app,
            pre=watcher.eid,
            oobi=watcher.oobi,
            force=True,
            alias=alias,
            cid=account_hab.pre,
            tag="watcher",
        )
        if not resolved:
            raise KFBootError(f"Failed to resolve hosted watcher OOBI for {watcher.eid}")

    def _introduce_account_to_watcher(
        self,
        *,
        account_hab: Any,
        watcher: HostedWatcherAllocation,
        witnesses: list[HostedWitnessAllocation],
    ) -> None:
        introduce_watcher_observed_aid(
            self._app,
            hab=account_hab,
            watcher_eid=watcher.eid,
            observed_aid=account_hab.pre,
            observed_oobis=self._account_witness_oobis(
                account_aid=account_hab.pre,
                witnesses=witnesses,
            ),
        )

    @staticmethod
    def _account_witness_oobis(*, account_aid: str, witnesses: list[HostedWitnessAllocation]) -> list[str]:
        oobis = []
        for witness in witnesses:
            base = witness.witness_url or extract_base_url(witness.oobi)
            if base:
                oobis.append(urljoin(base, f"/oobi/{account_aid}/witness/{witness.eid}"))
        if not oobis:
            raise KFBootError("Allocated witnesses did not provide usable witness OOBI URLs")
        return oobis

    def _ensure_account_record(self) -> KFAccountRecord:
        if self._db is None:
            raise KFBootError("KF account database is not available")
        record = self._db.get_account()
        if record is None:
            record, _ = self._db.ensure_account()
        return record

    def _pin_account_progress(
        self,
        *,
        record: KFAccountRecord,
        alias: str,
        witness_profile_code: str,
        witness_count: int,
        toad: int,
        watcher_required: bool,
        region_id: str,
        account_aid: str,
        boot_server_aid: str,
        status: str,
        onboarded_at: str = "",
        onboarding_session_id: str | None = None,
        onboarding_auth_alias: str | None = None,
    ) -> None:
        record.account_aid = account_aid
        record.account_alias = alias
        record.status = status
        record.witness_profile_code = witness_profile_code
        record.witness_count = witness_count
        record.toad = toad
        record.watcher_required = watcher_required
        record.region_id = region_id
        record.boot_server_aid = boot_server_aid
        if onboarding_session_id is not None:
            record.onboarding_session_id = onboarding_session_id
        if onboarding_auth_alias is not None:
            record.onboarding_auth_alias = onboarding_auth_alias
        if onboarded_at:
            record.onboarded_at = onboarded_at
        self._db.pin_account(record)

    @staticmethod
    def _emit(progress: ProgressFn, **kwa) -> None:
        if progress is not None:
            progress(**kwa)


class KFVaultDeletionService:
    """Tear down KF remote state before the local vault is deleted."""

    def __init__(
        self,
        *,
        app: Any,
        db: Any,
        boot_client: KFBootClient,
    ):
        self._app = app
        self._db = db
        self._boot_client = boot_client

    def delete_vault_account(self) -> None:
        if self._db is None:
            return

        record = self._db.get_account()
        if record is None:
            return

        if record.boot_server_aid:
            self._boot_client.set_boot_server_aid(record.boot_server_aid)

        if record.onboarding_session_id:
            self._cancel_saved_onboarding(record)
            return

        if record.status == ACCOUNT_STATUS_ONBOARDED:
            if not record.account_aid:
                raise KFBootError(
                    "The local KF account record is missing the permanent account AID required for deletion."
                )
            self._delete_onboarded_account(record)

    def _cancel_saved_onboarding(self, record: KFAccountRecord) -> None:
        if not record.onboarding_auth_alias:
            raise KFBootError(
                "The saved KF onboarding session is missing its hidden auth principal and cannot be cancelled safely."
            )

        ehab = self._app.vault.hby.habByName(
            record.onboarding_auth_alias,
            ns=ONBOARDING_AUTH_NAMESPACE,
        )
        if ehab is None:
            raise KFBootError(
                "The saved KF onboarding session is missing its hidden auth principal and cannot be cancelled safely."
            )

        logger.info(
            "Cancelling saved KF onboarding session %s before vault deletion",
            record.onboarding_session_id,
        )
        self._boot_client.cancel_onboarding(
            ehab,
            session_id=record.onboarding_session_id,
            account_aid=record.account_aid,
            reason="vault_deleted",
        )

    def _delete_onboarded_account(self, record: KFAccountRecord) -> None:
        hab = self._app.vault.hby.habByPre(record.account_aid)
        if hab is None:
            raise KFBootError(
                f"Permanent KF account AID {record.account_aid} is missing from the local wallet and cannot authenticate deletion."
            )

        logger.info(
            "Deleting hosted KF account state for %s before vault deletion",
            record.account_aid,
        )
        self._boot_client.delete_account(
            hab,
            account_aid=record.account_aid,
            destination=record.boot_server_aid,
        )


def split_cesr_message(ims: bytearray | bytes) -> tuple[bytes, bytes]:
    """Split a CESR message into body and attachment bytes."""
    buf = bytearray(ims)
    serder = SerderKERI(raw=bytes(buf))
    body = bytes(buf[:serder.size])
    attachment = bytes(buf[serder.size:])
    return body, attachment


def parse_cesr_http_reply(
    app: Any,
    response: requests.Response,
    *,
    expected_kinds: tuple[str, ...] = (),
    expected_route: str = "",
    expected_sender: str = "",
) -> CesrReply:
    """Parse a CESR-over-HTTP reply and return the last KERI message payload."""
    ims = bytearray(response.content or b"")
    attachment = response.headers.get(CESR_ATTACHMENT_HEADER, "")
    if attachment:
        ims.extend(attachment.encode("utf-8"))
    if not ims:
        raise KFBootError("Authenticated boot reply was empty")

    parser = parsing.Parser(
        kvy=app.vault.hby.kvy,
        rvy=app.vault.hby.rvy,
        exc=app.vault.hby.exc,
        local=False,
        version=message_version(ims),
    )
    parser.parse(ims=bytearray(ims))
    app.vault.hby.kvy.processEscrows()

    serders = split_cesr_stream(ims)
    if not serders:
        raise KFBootError("Unable to parse a KERI message from boot reply")

    last = serders[-1]
    ilk = str(last.ked.get("t", "") or "")
    if expected_kinds and ilk not in expected_kinds:
        expected = ", ".join(expected_kinds)
        raise KFBootError(f"Boot reply had unexpected ilk '{ilk}', expected {expected}")

    route = str(last.ked.get("r", "") or "")
    if expected_route and route != expected_route:
        raise KFBootError(
            f"Boot reply had unexpected route '{route}', expected '{expected_route}'"
        )

    sender = getattr(last, "pre", "") or last.ked.get("i", "")
    if expected_sender and not sender:
        raise KFBootError("Boot reply did not include a verifiable sender AID")
    if expected_sender and sender != expected_sender:
        raise KFBootError(
            f"Boot reply sender {sender} did not match expected boot service {expected_sender}"
        )
    if sender and sender not in app.vault.hby.kevers:
        raise KFBootError(f"Boot reply sender {sender} is not verifiable after parsing the prepended KEL")

    payload = last.ked.get("a", {})
    if not isinstance(payload, dict):
        payload = {}
    return CesrReply(
        ilk=ilk,
        route=route,
        sender=str(sender or ""),
        said=str(last.said or ""),
        payload=payload,
    )


def split_cesr_stream(ims: bytes | bytearray) -> list[SerderKERI]:
    """Split a JSON CESR stream into KERI serders."""
    serders: list[SerderKERI] = []
    buf = bytearray(ims)
    while buf:
        serder = SerderKERI(raw=bytes(buf))
        serders.append(serder)
        del buf[:serder.size]
        while buf and buf[0] != 0x7B:  # '{' starts the next JSON-encoded message
            del buf[:1]
    return serders


def _rows_from_payload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key, [])
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(rows, dict):
        return [rows]
    return []


def _pick_oobi(raw: dict[str, Any]) -> str:
    oobis = raw.get("oobis")
    if isinstance(oobis, list):
        for item in oobis:
            if isinstance(item, str) and item:
                return item
    value = raw.get("oobi", "")
    return value.strip() if isinstance(value, str) else ""
