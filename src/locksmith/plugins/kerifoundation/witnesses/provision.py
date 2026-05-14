# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.witnesses.provision module

Combined server-selection, provisioning, registration, and QR-code page.

The user selects one or more witness servers, then clicks
"Provision & Register".  The page provisions a witness on each
selected server, registers the controller AID with each witness,
resolves OOBIs, and displays TOTP QR codes.  If any step fails the
entire run is rolled back (best-effort deprovisioning + Organizer and
DB cleanup).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import pyotp
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QButtonGroup, QFrame,
)
from keri import help
from keri.help import helping

from locksmith.core.otping import create_totp_uri
from locksmith.core.remoting import (
    describe_oobi_resolution_state,
    purge_oobi_resolution_state,
    resolve_oobi,
)
from locksmith.plugins.kerifoundation.core.configing import load_witness_servers
from locksmith.plugins.kerifoundation.core.remoting import (
    deprovision_witness,
    provision_witness,
    register_with_witness,
)
from locksmith.plugins.kerifoundation.db.basing import (
    ProvisionedWitnessRecord,
    WitnessBatches,
    WitnessRecord,
)
from locksmith.ui import colors
from locksmith.ui.styles import get_monospace_font_family
from locksmith.ui.toolkit.widgets import (
    LocksmithButton,
    LocksmithInvertedButton,
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioPanel
from locksmith.ui.toolkit.widgets.dividers import LocksmithDivider
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.toolkit.widgets.panels import FlowLayout, LocksmithQRPanel

from locksmith.plugins.kerifoundation.witnesses.widgets import WitnessServerCard

logger = help.ogler.getLogger(__name__)


async def _await_blocking_result(func, /, *args, on_cancel_result=None, **kwa):
    """Run blocking work without losing cancellation-side effects.

    Started thread work is shielded from cancellation. If it finishes after
    this coroutine is cancelled, the late result is handed to
    on_cancel_result before cancellation is re-raised.
    """
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwa))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancel:
        try:
            result = await task
        except Exception:
            logger.warning("Background witness operation failed after cancellation", exc_info=True)
            raise asyncio.CancelledError from cancel
        if on_cancel_result is not None:
            on_cancel_result(result)
        raise


# ---------------------------------------------------------------------------
# Shared hosted-witness helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HostedWitnessAllocation:
    """Hosted witness details returned by boot-backed onboarding/account views."""

    eid: str
    witness_url: str
    oobi: str
    boot_url: str = ""
    name: str = ""
    region_id: str = ""
    region_name: str = ""


@dataclass(frozen=True)
class HostedWitnessRegistration:
    """Local witness-registration result reused by onboarding and UI flows."""

    results: list[dict]
    batch_mode: bool


def persist_provisioned_witnesses(db, hab_pre, entries):
    persisted = []
    failures = []

    if not entries:
        return persisted, failures

    if not db:
        return persisted, list(entries)

    for entry in entries:
        try:
            record = ProvisionedWitnessRecord(
                boot_url=entry["boot_url"],
                witness_url=entry["witness_url"],
                eid=entry["eid"],
                oobi=entry["oobi"],
                hab_pre=hab_pre,
                provisioned_at=helping.nowIso8601(),
            )
            db.provisionedWitnesses.pin(
                keys=(hab_pre, entry["boot_url"]),
                val=record,
            )
            persisted.append(entry)
        except Exception:
            logger.warning(
                "Failed to persist provisioned witness recovery state for %s",
                entry.get("eid", "unknown"),
                exc_info=True,
            )
            failures.append(entry)

    return persisted, failures


def persist_registration_results(db, hab_pre, hab, results, batch_mode):
    if not db:
        raise ValueError("KF witness database is not available.")

    now = helping.nowIso8601()
    persisted_state = {"witness_keys": [], "batch_eids": None}

    for res in results:
        record = WitnessRecord(
            eid=res["eid"],
            url=extract_base_url(res["oobi"]) or res.get("witness_url", ""),
            oobi=res["oobi"],
            totp_seed=res["totp_seed"],
            hab_pre=hab.pre,
            registered_at=now,
            batch_mode=batch_mode,
        )
        witness_key = (hab.pre, res["eid"])
        db.witnesses.pin(keys=witness_key, val=record)
        persisted_state["witness_keys"].append(witness_key)
        logger.info("Stored witness record for %s on %s", res["eid"][:12], hab.pre[:12])

    if batch_mode and results:
        batch_eids = [r["eid"] for r in results]
        existing = db.witBatches.get(keys=(hab.pre,))
        if existing:
            if batch_eids not in existing.batches:
                existing.batches.append(batch_eids)
                db.witBatches.pin(keys=(hab.pre,), val=existing)
                persisted_state["batch_eids"] = batch_eids
        else:
            db.witBatches.pin(
                keys=(hab.pre,),
                val=WitnessBatches(batches=[batch_eids]),
            )
            persisted_state["batch_eids"] = batch_eids

    return persisted_state


def remove_persisted_registration_state(db, hab_pre, persisted_state):
    if not db or not persisted_state:
        return

    for witness_key in persisted_state.get("witness_keys", []):
        try:
            db.witnesses.rem(keys=witness_key)
        except Exception:
            logger.warning(
                "Failed to remove witness record during rollback for %s",
                witness_key,
                exc_info=True,
            )

    batch_eids = persisted_state.get("batch_eids")
    if not batch_eids:
        return

    try:
        existing = db.witBatches.get(keys=(hab_pre,))
        if not existing:
            return
        remaining_batches = [batch for batch in existing.batches if batch != batch_eids]
        if remaining_batches:
            existing.batches = remaining_batches
            db.witBatches.pin(keys=(hab_pre,), val=existing)
        else:
            db.witBatches.rem(keys=(hab_pre,))
    except Exception:
        logger.warning(
            "Failed to remove witness batch during rollback for %s",
            hab_pre,
            exc_info=True,
        )


def _hosted_registration_result(witness, reg):
    oobi = reg.get("oobi") or witness.oobi
    return {
        "eid": witness.eid,
        "totp_seed": reg["totp_seed"],
        "oobi": oobi,
        "boot_url": witness.boot_url,
        "witness_url": witness.witness_url,
        "name": witness.name,
    }


async def _deprovision_witness_observed(eid: str, boot_url: str) -> bool:
    completed = False

    def remember_result(result):
        nonlocal completed
        completed = bool(result)

    try:
        return bool(await _await_blocking_result(
            deprovision_witness,
            eid,
            boot_url,
            on_cancel_result=remember_result,
        ))
    except asyncio.CancelledError:
        if not completed:
            logger.warning(
                "Witness deprovision did not finish before cancellation for %s via %s",
                eid,
                boot_url,
            )
        return completed


async def rollback_registration_state(app, db, hab_pre, provisioned_entries, persisted_state, resolved_eids):
    if app and hasattr(app, "vault") and app.vault:
        for eid in resolved_eids:
            try:
                app.vault.org.rem(eid)
                logger.info("Removed witness %s from Organizer during rollback", eid[:12])
            except Exception:
                logger.warning("Failed to remove %s from Organizer", eid[:12], exc_info=True)

    remove_persisted_registration_state(db, hab_pre, persisted_state)

    rollback_failures = []
    for entry in provisioned_entries:
        boot_url = entry.get("boot_url", "")
        if not boot_url:
            logger.error(
                "Witness rollback missing boot URL for %s during account %s cleanup",
                entry.get("eid", "unknown"),
                hab_pre,
            )
            rollback_failures.append(entry)
            continue

        ok = await _deprovision_witness_observed(entry["eid"], boot_url)
        if not ok:
            logger.error(
                "Witness rollback deprovision failed for %s via %s",
                entry["eid"],
                boot_url,
            )
            rollback_failures.append(entry)
            continue

        purge_oobi_resolution_state(app, oobi=entry.get("oobi"))

    persisted_failures = []
    persistence_failures = []
    if db:
        failed_eids = {f["eid"] for f in rollback_failures}
        for entry in provisioned_entries:
            if entry["eid"] not in failed_eids and entry.get("boot_url"):
                try:
                    db.provisionedWitnesses.rem(keys=(hab_pre, entry["boot_url"]))
                except Exception:
                    pass

        failed_results = [res for res in provisioned_entries if res["eid"] in failed_eids]
        persisted_failures, persistence_failures = persist_provisioned_witnesses(
            db,
            hab_pre,
            failed_results,
        )
    else:
        persistence_failures = rollback_failures

    return rollback_failures, persisted_failures, persistence_failures


def format_eid_list(entries):
    return ", ".join(entry["eid"][:12] + "..." for entry in entries)


def format_oobi_resolution_failure(app, hab_pre, result):
    resolution_state = describe_oobi_resolution_state(
        app,
        pre=result.get("eid"),
        oobi=result.get("oobi"),
    )
    return (
        f"Failed to resolve OOBI for witness {result['eid']}.\n"
        f"Account AID: {hab_pre}\n"
        f"Witness URL: {result.get('witness_url') or '-'}\n"
        f"Boot URL: {result.get('boot_url') or '-'}\n"
        f"OOBI: {result.get('oobi') or '-'}\n"
        f"Resolver: {resolution_state}"
    )


def format_cleanup_failure_details(rollback_failures, persisted_failures, persistence_failures):
    details = []
    if rollback_failures:
        details.append(f"rollback={format_eid_list(rollback_failures)}")
    if persisted_failures:
        details.append(f"pending={format_eid_list(persisted_failures)}")
    if persistence_failures:
        details.append(f"unsaved={format_eid_list(persistence_failures)}")
    if not details:
        return ""
    return "Cleanup after witness registration failure was incomplete: " + " ".join(details)


def extract_base_url(oobi):
    return normalize_url(oobi)


def normalize_url(url):
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            return ""
        base = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            base += f":{parsed.port}"
        return base
    except Exception:
        return ""


class HostedWitnessRegistrar:
    """Headless witness registrar reused by KF onboarding."""

    def __init__(self, app=None, db=None):
        self._app = app
        self._db = db

    async def register(self, *, hab, witnesses: list[HostedWitnessAllocation], batch_mode=True, persist=True):
        if not witnesses:
            return HostedWitnessRegistration(results=[], batch_mode=batch_mode)

        secret = pyotp.random_base32() if batch_mode else None
        results = []
        rollback_db = self._db if persist else None
        persisted_state = None
        resolved_eids = []

        try:
            for witness in witnesses:
                def remember_cancelled_registration(reg, witness=witness):
                    results.append(_hosted_registration_result(witness, reg))

                reg = await _await_blocking_result(
                    register_with_witness,
                    hab,
                    witness.eid,
                    witness.witness_url,
                    secret=secret,
                    on_cancel_result=remember_cancelled_registration,
                )
                results.append(_hosted_registration_result(witness, reg))

            if persist:
                persist_provisioned_witnesses(self._db, hab.pre, results)

            for res in results:
                success = await resolve_oobi(
                    self._app,
                    pre=res["eid"],
                    oobi=res["oobi"],
                    force=True,
                    alias=res.get("name") or f"KF Witness {res['eid'][:12]}",
                    cid=hab.pre,
                    tag="witness",
                )
                if not success:
                    message = format_oobi_resolution_failure(self._app, hab.pre, res)
                    logger.error("%s", message)
                    raise ValueError(message)
                resolved_eids.append(res["eid"])

            if persist:
                persisted_state = persist_registration_results(
                    self._db,
                    hab.pre,
                    hab,
                    results,
                    batch_mode,
                )
        except asyncio.CancelledError:
            logger.info("Hosted witness registration cancelled for account %s", hab.pre)
            await rollback_registration_state(
                self._app,
                rollback_db,
                hab.pre,
                results,
                persisted_state,
                resolved_eids,
            )
            raise
        except Exception as exc:
            logger.exception("Hosted witness registration failed for account %s", hab.pre)
            rollback_failures, persisted_failures, persistence_failures = await rollback_registration_state(
                self._app,
                rollback_db,
                hab.pre,
                results,
                persisted_state,
                resolved_eids,
            )
            cleanup_details = format_cleanup_failure_details(
                rollback_failures,
                persisted_failures,
                persistence_failures,
            )
            if cleanup_details:
                logger.error("%s", cleanup_details)
                raise ValueError(f"{exc}\n\n{cleanup_details}") from exc
            raise

        return HostedWitnessRegistration(results=results, batch_mode=batch_mode)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class WitnessProvisionPage(LocksmithFormPage):
    """Server selection → provision → register → QR code display."""

    completed = Signal(str, list)
    cancelled = Signal()

    def __init__(self, app=None, parent=None):
        super().__init__(
            title="Add Witnesses",
            icon_path=":/assets/material-icons/witness1.svg",
            parent=parent,
        )
        self._app = app
        self._db = None
        self._hab_pre = None
        self._server_cards: list[WitnessServerCard] = []
        self._provision_task: asyncio.Task | None = None
        self._reg_hab = None
        self._reg_batch_mode = False
        self._provisioned_in_run: list[dict] = []   # for main-thread rollback
        self._resolved_eids: list[str] = []          # for Organizer rollback
        self._persisted_registration_state: dict | None = None
        self._completed_witnesses: list[dict] = []
        self._setup_form()

    def set_app(self, app):
        self._app = app

    def set_db(self, db):
        if db is not self._db:
            self.shutdown()
        self._db = db

    def set_identifier(self, hab_pre: str):
        if hab_pre != self._hab_pre:
            self.shutdown()
        self._hab_pre = hab_pre

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_form(self):
        cl = self.content_layout
        cl.setSpacing(0)

        # -- Identifier info card --
        self._id_card = QFrame()
        self._id_card.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
            }}
        """)
        card_layout = QVBoxLayout(self._id_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(8)

        id_heading = QLabel("Identifier")
        id_heading.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {colors.TEXT_SECONDARY}; "
            "text-transform: uppercase; letter-spacing: 1px; border: none;"
        )
        card_layout.addWidget(id_heading)

        mono = get_monospace_font_family()
        self._id_alias_label = QLabel("—")
        self._id_alias_label.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {colors.TEXT_PRIMARY}; border: none;"
        )
        self._id_alias_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self._id_alias_label)

        self._id_prefix_label = QLabel("")
        self._id_prefix_label.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SECONDARY}; font-family: {mono}; border: none;"
        )
        self._id_prefix_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._id_prefix_label.setVisible(False)
        card_layout.addWidget(self._id_prefix_label)

        cl.addWidget(self._id_card)
        cl.addSpacing(20)

        # -- Server selection --
        server_heading = QLabel("Select Witness Servers")
        server_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {colors.TEXT_PRIMARY};"
        )
        cl.addWidget(server_heading)
        cl.addSpacing(4)

        server_desc = QLabel(
            "Choose the servers to provision witnesses on for this identifier."
        )
        server_desc.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SECONDARY};")
        server_desc.setWordWrap(True)
        cl.addWidget(server_desc)
        cl.addSpacing(8)

        self._select_all_label = QLabel('<a href="#" style="color: #2196F3;">Select All</a>')
        self._select_all_label.setTextFormat(Qt.TextFormat.RichText)
        self._select_all_label.linkActivated.connect(self._on_select_all)
        cl.addWidget(self._select_all_label)
        cl.addSpacing(8)

        self._server_flow_container = QWidget()
        self._server_flow_layout = QVBoxLayout(self._server_flow_container)
        self._server_flow_layout.setContentsMargins(0, 0, 0, 0)
        self._server_flow_layout.setSpacing(0)
        self._server_flow = FlowLayout(spacing=12)
        self._server_flow_layout.addLayout(self._server_flow)
        cl.addWidget(self._server_flow_container)
        cl.addSpacing(8)

        self._server_empty_label = QLabel("")
        self._server_empty_label.setWordWrap(True)
        self._server_empty_label.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )
        self._server_empty_label.setVisible(False)
        cl.addWidget(self._server_empty_label)

        # -- Divider --
        cl.addSpacing(20)
        cl.addWidget(LocksmithDivider())
        cl.addSpacing(20)

        # -- Authentication mode --
        mode_label = QLabel("Authentication Mode")
        mode_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {colors.TEXT_PRIMARY};"
        )
        cl.addWidget(mode_label)
        cl.addSpacing(4)

        mode_desc = QLabel(
            "Choose how TOTP secrets are generated for witness authentication."
        )
        mode_desc.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SECONDARY};")
        mode_desc.setWordWrap(True)
        cl.addWidget(mode_desc)
        cl.addSpacing(12)

        self._mode_group = QButtonGroup(self)

        self._batch_panel = LocksmithRadioPanel(
            header="Batch",
            subheader="One shared secret — single QR code for all witnesses",
        )
        self._batch_panel.setChecked(True)
        self._mode_group.addButton(self._batch_panel.radioButton(), 0)

        self._individual_panel = LocksmithRadioPanel(
            header="Individual",
            subheader="Separate secret per witness — one QR code each",
        )
        self._mode_group.addButton(self._individual_panel.radioButton(), 1)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(12)
        mode_layout.addWidget(self._batch_panel)
        mode_layout.addWidget(self._individual_panel)
        mode_layout.addStretch()
        cl.addLayout(mode_layout)

        # -- Divider --
        cl.addSpacing(24)
        cl.addWidget(LocksmithDivider())
        cl.addSpacing(20)

        # -- Buttons --
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._back_btn = LocksmithInvertedButton("Back")
        self._back_btn.clicked.connect(self.cancelled.emit)
        btn_layout.addWidget(self._back_btn)

        btn_layout.addStretch()

        self._action_btn = LocksmithButton("Provision && Register")
        self._action_btn.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self._action_btn)

        cl.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SECONDARY};"
        )
        cl.addWidget(self._status_label)

        # -- QR container (hidden) --
        self._qr_container = QWidget()
        self._qr_layout = QVBoxLayout(self._qr_container)
        self._qr_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_layout.setContentsMargins(0, 16, 0, 0)
        self._qr_container.setVisible(False)
        cl.addWidget(self._qr_container)

        # -- Done button (hidden) --
        self._done_btn = LocksmithButton("I've Scanned the QR Code")
        self._done_btn.setVisible(False)
        self._done_btn.clicked.connect(self._emit_completed)
        cl.addWidget(self._done_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        cl.addStretch()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_show(self):
        self.clear_error()
        self.clear_success()
        self._status_label.setText("")
        self._qr_container.setVisible(False)
        self._done_btn.setVisible(False)
        self._back_btn.setVisible(True)
        self._back_btn.setEnabled(True)
        self._action_btn.setVisible(True)
        self._action_btn.setEnabled(True)
        self._provisioned_in_run = []
        self._resolved_eids = []
        self._persisted_registration_state = None
        self._completed_witnesses = []

        self._populate_identifier_card()
        self._populate_server_cards()

        self.scroll_area.verticalScrollBar().setValue(0)

    def _emit_completed(self):
        self.completed.emit(self._hab_pre or "", list(self._completed_witnesses))

    def _populate_identifier_card(self):
        if not self._app or not self._hab_pre:
            self._id_alias_label.setText("—")
            self._id_prefix_label.clear()
            self._id_prefix_label.setVisible(False)
            return

        hab = self._app.vault.hby.habByPre(self._hab_pre)
        if hab:
            alias = self._get_controller_alias(hab)
            self._id_alias_label.setText(alias or self._hab_pre)
            self._id_alias_label.setToolTip(alias or self._hab_pre)
            if alias and alias != self._hab_pre:
                self._id_prefix_label.setText(self._hab_pre)
                self._id_prefix_label.setToolTip(self._hab_pre)
                self._id_prefix_label.setVisible(True)
            else:
                self._id_prefix_label.clear()
                self._id_prefix_label.setVisible(False)
        else:
            self._id_alias_label.setText(self._hab_pre)
            self._id_prefix_label.clear()
            self._id_prefix_label.setVisible(False)

    def _populate_server_cards(self):
        # Clear existing cards
        while self._server_flow.count():
            child = self._server_flow.takeAt(0)
            if child and child.widget():
                child.widget().deleteLater()
        self._server_cards.clear()

        servers = load_witness_servers(self._app) if self._app else []
        registered_urls, pending_boot_urls = self._load_existing_server_state()

        for server in servers:
            card = WitnessServerCard(server)
            witness_url = normalize_url(server.witness_url)
            boot_url = normalize_url(server.boot_url)

            if witness_url in registered_urls:
                if boot_url in pending_boot_urls:
                    logger.warning(
                        "Witness server %s is both registered and pending for %s; "
                        "treating it as registered",
                        server.witness_url,
                        self._hab_pre,
                    )
                card.set_status("registered")
            elif boot_url in pending_boot_urls:
                card.set_status("pending")

            self._server_cards.append(card)
            self._server_flow.addWidget(card)

        has_servers = bool(self._server_cards)
        has_available = any(card.is_available() for card in self._server_cards)
        self._select_all_label.setVisible(has_available)
        self._server_empty_label.setVisible((not has_servers) or (not has_available))
        if not has_servers:
            message = self._server_configuration_hint()
        elif not has_available:
            message = (
                "All configured witness servers are already registered or pending "
                "for this identifier."
            )
        else:
            message = ""
        self._server_empty_label.setText(message)
        self._action_btn.setEnabled(has_available)
        self._server_flow_container.updateGeometry()
        self._server_flow_container.adjustSize()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_select_all(self, _link=None):
        available_cards = [card for card in self._server_cards if card.is_available()]
        all_checked = bool(available_cards) and all(c.is_checked() for c in available_cards)
        for card in available_cards:
            card.set_checked(not all_checked)

    def _get_selected_servers(self):
        return [
            c.server_config
            for c in self._server_cards
            if c.is_available() and c.is_checked()
        ]

    def _on_action_clicked(self):
        self.clear_error()
        self.clear_success()

        if self._provision_task is not None and not self._provision_task.done():
            return

        if not self._app or not self._app.vault:
            self.show_error("No vault open.")
            return

        hab = self._app.vault.hby.habByPre(self._hab_pre)
        if not hab:
            self.show_error(f"Identifier '{self._hab_pre}' not found.")
            return

        selected = self._get_selected_servers()
        if not selected:
            self.show_error("Select at least one witness server.")
            return

        batch_mode = self._batch_panel.isChecked()
        secret = pyotp.random_base32() if batch_mode else None

        self._persisted_registration_state = None
        self._provisioned_in_run = []
        self._resolved_eids = []
        self._action_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._set_cards_enabled(False)
        self._batch_panel.setEnabled(False)
        self._individual_panel.setEnabled(False)

        self._status_label.setText("Starting...")

        self._reg_hab = hab
        self._reg_batch_mode = batch_mode

        self._provision_task = asyncio.create_task(
            self._run_provision_registration(
                hab_pre=self._hab_pre,
                hab=hab,
                servers=selected,
                secret=secret,
                db=self._db,
                vault=getattr(self._app, "vault", None),
            )
        )

    def _set_cards_enabled(self, enabled):
        for card in self._server_cards:
            card.set_interactive(enabled)

    async def _run_provision_registration(self, *, hab_pre, hab, servers, secret, db, vault):
        task = asyncio.current_task()
        total = len(servers)
        provisioned = []
        results = []

        try:
            if not self._is_current_provision_task(task, db, vault, hab_pre):
                self._finish_provision_task(task)
                return

            await self._provision_selected_servers(
                hab_pre=hab_pre,
                servers=servers,
                provisioned=provisioned,
                db=db,
                vault=vault,
                owner_task=task,
            )

            for i, entry in enumerate(provisioned):
                if not self._is_current_provision_task(task, db, vault, hab_pre):
                    await self._rollback_abandoned_provisioned_entries(provisioned, db=db, hab_pre=hab_pre)
                    self._finish_provision_task(task)
                    return
                self._status_label.setText(f"Registering with witness {i + 1}/{total}...")
                reg = await _await_blocking_result(
                    register_with_witness,
                    hab,
                    entry["eid"],
                    entry["witness_url"],
                    secret=secret,
                )
                oobi = reg.get("oobi") or entry["oobi"]
                results.append({
                    "eid": entry["eid"],
                    "totp_seed": reg["totp_seed"],
                    "oobi": oobi,
                    "boot_url": entry["boot_url"],
                    "witness_url": entry["witness_url"],
                })
        except asyncio.CancelledError:
            await self._rollback_abandoned_provisioned_entries(provisioned, db=db, hab_pre=hab_pre)
            self._finish_provision_task(task)
            raise
        except Exception as exc:
            logger.exception("Provision-and-register failed")
            rollback_failures = await self._rollback_provisioned_entries(provisioned)
            if self._is_current_provision_task(task, db, vault, hab_pre):
                self._handle_error(str(exc), results, rollback_failures)
            else:
                self._persist_provision_recovery_state(db, hab_pre, rollback_failures)
            self._finish_provision_task(task)
            return

        if not self._is_current_provision_task(task, db, vault, hab_pre):
            await self._rollback_abandoned_provisioned_entries(provisioned, db=db, hab_pre=hab_pre)
            self._finish_provision_task(task)
            return

        self._provisioned_in_run = [
            {"eid": r["eid"], "boot_url": r["boot_url"], "witness_url": r["witness_url"]}
            for r in results
        ]
        self._persist_provisioned_witnesses(results)

        self._status_label.setText("Resolving witness OOBIs...")
        await self._finalize_registration(results)
        self._finish_provision_task(task)

    async def _provision_selected_servers(
        self,
        *,
        hab_pre,
        servers,
        provisioned,
        db,
        vault,
        owner_task,
    ):
        total = len(servers)
        entries_by_index = {}
        task_servers = {}

        def sync_provisioned():
            provisioned[:] = [
                entries_by_index[index]
                for index in sorted(entries_by_index)
            ]

        self._status_label.setText(f"Provisioning {total} witness(es)...")
        for index, server in enumerate(servers):
            provision_task = asyncio.create_task(
                asyncio.to_thread(provision_witness, hab_pre, server.boot_url)
            )
            task_servers[provision_task] = (index, server)

        try:
            pending = set(task_servers)
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for completed_task in done:
                    index, server = task_servers[completed_task]
                    prov = completed_task.result()
                    entries_by_index[index] = {
                        "eid": prov["eid"],
                        "oobi": prov["oobi"],
                        "boot_url": server.boot_url,
                        "witness_url": server.witness_url,
                    }

                sync_provisioned()
                if not self._is_current_provision_task(owner_task, db, vault, hab_pre):
                    await self._remember_finished_provisions(
                        task_servers,
                        entries_by_index,
                    )
                    sync_provisioned()
                    return

                self._status_label.setText(
                    f"Provisioned {len(entries_by_index)}/{total} witnesses..."
                )
        except asyncio.CancelledError:
            await self._remember_finished_provisions(task_servers, entries_by_index)
            sync_provisioned()
            raise
        except Exception:
            await self._remember_finished_provisions(task_servers, entries_by_index)
            sync_provisioned()
            raise

        provisioned[:] = [entries_by_index[index] for index in range(total)]

    @staticmethod
    async def _remember_finished_provisions(task_servers, entries_by_index):
        if not task_servers:
            return

        task_list = list(task_servers)
        results = await asyncio.gather(*task_list, return_exceptions=True)
        for provision_task, result in zip(task_list, results):
            index, server = task_servers[provision_task]
            if index in entries_by_index:
                continue
            if isinstance(result, BaseException):
                logger.warning(
                    "Witness provisioning task did not complete cleanly",
                    exc_info=(type(result), result, result.__traceback__),
                )
                continue
            entries_by_index[index] = {
                "eid": result["eid"],
                "oobi": result["oobi"],
                "boot_url": server.boot_url,
                "witness_url": server.witness_url,
            }

    async def _rollback_provisioned_entries(self, entries):
        failures = []
        for entry in entries:
            ok = await _deprovision_witness_observed(entry["eid"], entry["boot_url"])
            if not ok:
                failures.append(entry.copy())
        return failures

    async def _rollback_abandoned_provisioned_entries(self, entries, *, db, hab_pre):
        if not entries:
            return
        failures = await self._rollback_provisioned_entries(entries)
        self._persist_provision_recovery_state(db, hab_pre, failures)
        entries.clear()

    @staticmethod
    def _persist_provision_recovery_state(db, hab_pre, entries):
        if not entries:
            return
        persisted, failures = persist_provisioned_witnesses(db, hab_pre, entries)
        if failures:
            logger.error(
                "Could not save recovery state for %d provisioned witness(es) after task shutdown",
                len(failures),
            )
        if persisted:
            logger.warning(
                "Saved %d provisioned witness(es) as pending after task shutdown",
                len(persisted),
            )

    def _is_current_provision_task(self, task, db, vault, hab_pre) -> bool:
        return (
            task is self._provision_task
            and db is self._db
            and vault is getattr(self._app, "vault", None)
            and hab_pre == self._hab_pre
        )

    def _finish_provision_task(self, task):
        if task is self._provision_task:
            self._provision_task = None

    def _handle_error(self, error, results, rollback_failures):
        """Handle failure — clean up local DB and show appropriate message."""
        message = f"Registration failed: {error}"
        persisted_failures = []
        persistence_failures = []

        if rollback_failures:
            persisted_failures, persistence_failures = self._persist_provisioned_witnesses(
                rollback_failures
        )

        if persisted_failures:
            failed_list = format_eid_list(persisted_failures)
            message += (
                f"\n\nCould not deprovision {len(persisted_failures)} witness(es): "
                f"{failed_list}. These witnesses remain provisioned and were saved as pending."
            )

        if persistence_failures:
            failed_list = format_eid_list(persistence_failures)
            message += (
                f"\n\nCould not save recovery state for {len(persistence_failures)} "
                f"witness(es): {failed_list}. Cleanup is partial; you may need to "
                "remove them manually."
            )

        self.show_error(message)
        self._populate_server_cards()
        self._status_label.setText("")
        self._re_enable_form()

    async def _finalize_registration(self, results):
        """Resolve OOBIs, persist records, and show QR codes.

        If any OOBI resolution fails, roll back the entire run:
        deprovision all witnesses, remove from Organizer, clean DB.
        """
        total = len(results)
        try:
            for index, res in enumerate(results, start=1):
                alias = self._witness_alias(res["eid"])
                self._status_label.setText(
                    f"Resolving witness OOBI {index}/{total} for {alias}..."
                )
                success = await resolve_oobi(
                    self._app,
                    pre=res["eid"],
                    oobi=res["oobi"],
                    force=True,
                    alias=alias,
                    cid=self._reg_hab.pre,
                    tag="witness",
                )
                if not success:
                    message = format_oobi_resolution_failure(self._app, self._reg_hab.pre, res)
                    logger.error("%s", message)
                    raise ValueError(message)
                self._resolved_eids.append(res["eid"])

            self._persisted_registration_state = self._persist_registration_results(
                results,
                self._reg_hab,
                self._reg_batch_mode,
            )
            self._completed_witnesses = [{"eid": res["eid"]} for res in results]
            self._show_qr_codes(results, self._reg_hab, self._reg_batch_mode)

        except Exception as exc:
            logger.exception("Witness registration finalization failed")
            rollback_message = await self._rollback_finalization(
                results,
                self._persisted_registration_state,
            )
            message = f"Registration failed: {exc}"
            if rollback_message:
                message += f"\n\n{rollback_message}"
            self.show_error(message)
            self._populate_server_cards()
            self._status_label.setText("")
            self._re_enable_form()
            return

        self._status_label.setText("")
        self.show_success(
            f"Successfully registered {total} witness(es). "
            "You must scan the QR code below with your authenticator app before continuing."
        )
        self._done_btn.setVisible(True)
        self._back_btn.setVisible(False)
        self._action_btn.setVisible(False)

    async def _rollback_finalization(self, results, persisted_state=None):
        """Roll back after OOBI resolution failure.

        Removes witnesses from Organizer, deprovisions on server, and
        cleans up local DB records.
        """
        # Remove any already-resolved witnesses from Organizer
        if self._app and hasattr(self._app, "vault") and self._app.vault:
            for eid in self._resolved_eids:
                try:
                    self._app.vault.org.rem(eid)
                    logger.info(f"Removed witness {eid[:12]}... from Organizer during rollback")
                except Exception:
                    logger.warning(f"Failed to remove {eid[:12]}... from Organizer", exc_info=True)
        self._resolved_eids.clear()

        self._remove_persisted_registration_state(persisted_state)

        # Deprovision all witnesses on servers (best-effort)
        rollback_failures = []
        for entry in self._provisioned_in_run:
            ok = await _deprovision_witness_observed(entry["eid"], entry["boot_url"])
            if not ok:
                rollback_failures.append(entry)

        # Clean up local DB
        persisted_failures = []
        persistence_failures = []
        if self._db:
            failed_eids = {f["eid"] for f in rollback_failures}
            for entry in self._provisioned_in_run:
                if entry["eid"] not in failed_eids:
                    try:
                        self._db.provisionedWitnesses.rem(keys=(self._hab_pre, entry["boot_url"]))
                    except Exception:
                        pass

            failed_results = [res for res in results if res["eid"] in failed_eids]
            persisted_failures, persistence_failures = self._persist_provisioned_witnesses(
                failed_results
            )
        else:
            persistence_failures = rollback_failures

        if rollback_failures:
            failed_list = format_eid_list(rollback_failures)
            logger.warning(
                f"Could not deprovision {len(rollback_failures)} witnesses during rollback: "
                f"{failed_list}"
            )

        messages = []
        if persisted_failures:
            failed_list = format_eid_list(persisted_failures)
            messages.append(
                f"Could not deprovision {len(persisted_failures)} witness(es): {failed_list}. "
                "These witnesses remain provisioned and were saved as pending."
            )
        if persistence_failures:
            failed_list = format_eid_list(persistence_failures)
            messages.append(
                f"Could not save recovery state for {len(persistence_failures)} "
                f"witness(es): {failed_list}. Cleanup is partial; you may need to "
                "remove them manually."
            )

        self._persisted_registration_state = None
        return "\n\n".join(messages)

    # ------------------------------------------------------------------
    # Persistence (reused from register.py)
    # ------------------------------------------------------------------

    def _persist_registration_results(self, results, hab, batch_mode):
        if not self._db:
            raise ValueError("KF witness database is not available.")

        now = helping.nowIso8601()
        persisted_state = {"witness_keys": [], "batch_eids": None}

        for res in results:
            record = WitnessRecord(
                eid=res["eid"],
                url=extract_base_url(res["oobi"]) or res.get("witness_url", ""),
                oobi=res["oobi"],
                totp_seed=res["totp_seed"],
                hab_pre=hab.pre,
                registered_at=now,
                batch_mode=batch_mode,
            )
            witness_key = (hab.pre, res["eid"])
            self._db.witnesses.pin(keys=witness_key, val=record)
            persisted_state["witness_keys"].append(witness_key)
            logger.info(f"Stored witness record for {res['eid'][:12]}... on {hab.pre[:12]}...")

        if batch_mode and results:
            batch_eids = [r["eid"] for r in results]
            existing = self._db.witBatches.get(keys=(hab.pre,))
            if existing:
                if batch_eids not in existing.batches:
                    existing.batches.append(batch_eids)
                    self._db.witBatches.pin(keys=(hab.pre,), val=existing)
                    persisted_state["batch_eids"] = batch_eids
            else:
                self._db.witBatches.pin(
                    keys=(hab.pre,),
                    val=WitnessBatches(batches=[batch_eids]),
                )
                persisted_state["batch_eids"] = batch_eids

        return persisted_state

    # ------------------------------------------------------------------
    # QR codes (reused from register.py)
    # ------------------------------------------------------------------

    def _show_qr_codes(self, results, hab, batch_mode):
        while self._qr_layout.count():
            child = self._qr_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        controller_alias = self._get_controller_alias(hab)

        if batch_mode:
            seed = results[0]["totp_seed"]
            uri = create_totp_uri(
                secret=seed,
                vault_name=f"KF-Batch-{hab.pre[:8]}",
                issuer="KERI Foundation",
            )
            panel = LocksmithQRPanel(
                number="1",
                witness_name="Batch TOTP",
                witness_eid=results[0]["eid"],
                controller_alias=controller_alias,
                controller_aid=hab.pre,
                url=uri,
            )
            self._qr_layout.addWidget(panel)
        else:
            for i, res in enumerate(results, start=1):
                uri = create_totp_uri(
                    secret=res["totp_seed"],
                    vault_name=f"KF-{res['eid'][:12]}",
                    issuer="KERI Foundation",
                )
                panel = LocksmithQRPanel(
                    number=str(i),
                    witness_name=self._witness_alias(res["eid"]),
                    witness_eid=res["eid"],
                    controller_alias=controller_alias,
                    controller_aid=hab.pre,
                    url=uri,
                )
                self._qr_layout.addWidget(panel)

        self._qr_container.setVisible(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_controller_alias(self, hab):
        hab_name = getattr(hab, "name", "")
        if hab_name:
            return hab_name

        if self._app and hasattr(self._app, "vault") and self._app.vault:
            hby = self._app.vault.hby
            if hby and getattr(hby, "db", None):
                try:
                    for (ns, alias), prefix in hby.db.names.getTopItemIter(keys=()):
                        if ns == "" and prefix == hab.pre:
                            return alias
                except Exception:
                    logger.debug("Unable to derive controller alias from names DB", exc_info=True)
        return hab.pre

    def _server_configuration_hint(self):
        environment = getattr(getattr(self._app, "config", None), "environment", None)
        env_name = getattr(environment, "value", str(environment or "")).lower()
        prefix = "KF_DEV" if env_name == "development" else "KF_PROD"
        return (
            "No witness servers are configured for this environment. "
            f"Set {prefix}_WITNESS_URL_1 and {prefix}_BOOT_URL_1 to enable provisioning."
        )

    def _witness_alias(self, eid):
        if self._app and hasattr(self._app, "vault") and self._app.vault and self._app.vault.org:
            remote_id = self._app.vault.org.get(eid)
            if remote_id and remote_id.get("alias"):
                return remote_id["alias"]
        return f"KF Witness {eid[:12]}"

    def _load_existing_server_state(self):
        registered_urls = set()
        pending_boot_urls = set()

        if not self._db or not self._hab_pre:
            return registered_urls, pending_boot_urls

        try:
            for _, record in self._db.witnesses.getTopItemIter(keys=(self._hab_pre,)):
                registered_url = normalize_url(record.url)
                if not registered_url and record.oobi:
                    registered_url = extract_base_url(record.oobi)
                if registered_url:
                    registered_urls.add(registered_url)
        except Exception:
            logger.warning("Failed loading registered witness state", exc_info=True)

        try:
            for _, record in self._db.provisionedWitnesses.getTopItemIter(keys=(self._hab_pre,)):
                boot_url = normalize_url(record.boot_url)
                if boot_url:
                    pending_boot_urls.add(boot_url)
        except Exception:
            logger.warning("Failed loading pending witness state", exc_info=True)

        return registered_urls, pending_boot_urls

    def _persist_provisioned_witnesses(self, entries):
        persisted = []
        failures = []

        if not entries:
            return persisted, failures

        if not self._db:
            return persisted, list(entries)

        for entry in entries:
            try:
                record = ProvisionedWitnessRecord(
                    boot_url=entry["boot_url"],
                    witness_url=entry["witness_url"],
                    eid=entry["eid"],
                    oobi=entry["oobi"],
                    hab_pre=self._hab_pre,
                    provisioned_at=helping.nowIso8601(),
                )
                self._db.provisionedWitnesses.pin(
                    keys=(self._hab_pre, entry["boot_url"]),
                    val=record,
                )
                persisted.append(entry)
            except Exception:
                logger.warning(
                    "Failed to persist provisioned witness recovery state for %s",
                    entry.get("eid", "unknown"),
                    exc_info=True,
                )
                failures.append(entry)

        return persisted, failures

    def _remove_persisted_registration_state(self, persisted_state):
        if not self._db or not persisted_state:
            return

        for witness_key in persisted_state.get("witness_keys", []):
            try:
                self._db.witnesses.rem(keys=witness_key)
            except Exception:
                logger.warning(
                    "Failed to remove witness record during rollback for %s",
                    witness_key,
                    exc_info=True,
                )

        batch_eids = persisted_state.get("batch_eids")
        if not batch_eids:
            return

        try:
            existing = self._db.witBatches.get(keys=(self._hab_pre,))
            if not existing:
                return
            remaining_batches = [batch for batch in existing.batches if batch != batch_eids]
            if remaining_batches:
                existing.batches = remaining_batches
                self._db.witBatches.pin(keys=(self._hab_pre,), val=existing)
            else:
                self._db.witBatches.rem(keys=(self._hab_pre,))
        except Exception:
            logger.warning(
                "Failed to remove witness batch during rollback for %s",
                self._hab_pre,
                exc_info=True,
            )

    def _re_enable_form(self):
        self._action_btn.setEnabled(any(card.is_available() for card in self._server_cards))
        self._back_btn.setEnabled(True)
        self._back_btn.setVisible(True)
        self._set_cards_enabled(True)
        self._batch_panel.setEnabled(True)
        self._individual_panel.setEnabled(True)

    def shutdown(self):
        task = self._provision_task
        if task is not None and not task.done():
            task.cancel()
            loop = task.get_loop()
            if not loop.is_running():
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
            return False
        self._provision_task = None
        return True
