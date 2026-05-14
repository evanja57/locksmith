# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.onboarding.page module

Single-page onboarding UI for the KF plugin with a boot-server connection
gate, permanent-account AID selection, and progressive onboarding status.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from keri import help

from locksmith.core.habbing import list_eligible_local_identifiers
from locksmith.core.otping import create_totp_uri
from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_FAILED,
    ACCOUNT_STATUS_ONBOARDED,
    ACCOUNT_STATUS_PENDING_ONBOARDING,
    KFAccountRecord,
)
from locksmith.plugins.kerifoundation.onboarding.service import BootstrapConfig
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import (
    LocksmithButton,
    LocksmithInvertedButton,
    LocksmithRadioPanel,
)
from locksmith.ui.toolkit.widgets.dividers import LocksmithDivider
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, LocksmithLineEdit
from locksmith.ui.toolkit.widgets.panels import LocksmithQRPanel

logger = help.ogler.getLogger(__name__)


PHASE_NOT_STARTED = "not_started"
PHASE_BOOTSTRAP_REQUIRED = "bootstrap_required"
PHASE_ALIAS_INPUT = "alias_input"
PHASE_WITNESS_CHOICE = "witness_choice"
PHASE_REVIEW = "review"
PHASE_IN_PROGRESS = "in_progress"
PHASE_COMPLETED = "completed"

ALL_PHASES = (
    PHASE_NOT_STARTED,
    PHASE_BOOTSTRAP_REQUIRED,
    PHASE_ALIAS_INPUT,
    PHASE_WITNESS_CHOICE,
    PHASE_REVIEW,
    PHASE_IN_PROGRESS,
    PHASE_COMPLETED,
)

ALIAS_MIN_LENGTH = 3
ALIAS_MAX_LENGTH = 64
ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 _-]*$")

WITNESS_PROFILE_1_OF_1 = "1-of-1"
WITNESS_PROFILE_3_OF_4 = "3-of-4"
CREATE_NEW_ACCOUNT_AID = "__create_new_account_aid__"


def validate_alias(alias: str) -> tuple[bool, str]:
    """Validate an account alias and return (valid, message)."""
    stripped = alias.strip()
    if not stripped:
        return False, "Alias is required."
    if len(stripped) < ALIAS_MIN_LENGTH:
        return False, f"Alias must be at least {ALIAS_MIN_LENGTH} characters."
    if len(stripped) > ALIAS_MAX_LENGTH:
        return False, f"Alias must be at most {ALIAS_MAX_LENGTH} characters."
    if not ALIAS_PATTERN.match(stripped):
        return False, (
            "Alias must start with a letter or digit and contain only letters, "
            "digits, spaces, hyphens, or underscores."
        )
    return True, "Valid alias."


def witness_profile_params(code: str) -> tuple[int, int]:
    """Return (witness_count, toad) for a profile code."""
    if code == WITNESS_PROFILE_3_OF_4:
        return 4, 3
    return 1, 1


class KFOnboardingPage(QWidget):
    """Single-page progressive onboarding UI for the KF plugin."""

    confirm_requested = Signal(str, str, str)  # (alias, witness_profile_code, account_aid)
    open_account_requested = Signal()

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self._app = app
        self._db = None
        self._boot_client = None
        self._phase = PHASE_NOT_STARTED
        self._selected_witness_profile: str = ""
        self._run_in_progress = False
        self._progress_message = ""
        self._progress_error = ""
        self._boot_connected = False
        self._boot_verified = False
        self._boot_detail = "Connect to the boot surface to begin onboarding."
        self._boot_error = ""
        self._bootstrap: BootstrapConfig | None = None
        self._qr_results: list[dict] = []
        self._qr_batch_mode = True
        self._account_aid = ""
        self._preflight_task: asyncio.Task | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

    def set_app(self, app):
        self._app = app

    def set_db(self, db):
        if db is self._db:
            return
        self.shutdown()
        self._db = db
        self._reset_vault_state()

    def set_boot_client(self, boot_client):
        if boot_client is not self._boot_client:
            self.shutdown()
        self._boot_client = boot_client

    @property
    def phase(self) -> str:
        return self._phase

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)

        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(32, 24, 32, 32)
        self._content_layout.setSpacing(18)

        self._build_header()
        self._build_connection_section()
        self._build_hero_section()
        self._build_identity_section()
        self._build_witness_section()
        self._build_watcher_section()
        self._build_review_section()
        self._build_progress_section()

        # Backwards-compatible section handles used by existing focused tests.
        self._intro_section = self._hero_section
        self._alias_section = self._identity_section
        self._boot_section = self._connection_section

        self._content_layout.addStretch()
        outer.addWidget(scroll)

    def _build_header(self):
        title = QLabel("KERI Foundation Onboarding")
        title.setStyleSheet(
            f"""
            font-size: 24px;
            font-weight: 600;
            color: {colors.TEXT_PRIMARY};
        """
        )
        self._content_layout.addWidget(title)

        self._subtitle = QLabel()
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(
            f"""
            font-size: 14px;
            line-height: 20px;
            color: {colors.TEXT_SECONDARY};
        """
        )
        self._content_layout.addWidget(self._subtitle)

    def _build_hero_section(self):
        self._hero_section = self._make_card()
        lay = QVBoxLayout(self._hero_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("What happens during onboarding")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        body = QLabel(
            "This plugin creates or reuses one permanent local account AID for "
            "the vault, then finishes the hosted witness and watcher setup against `kf-boot`."
        )
        body.setWordWrap(True)
        body.setStyleSheet(self._body_text_css())
        lay.addWidget(body)

        self._hero_status = QLabel("")
        self._hero_status.setWordWrap(True)
        self._hero_status.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )
        lay.addWidget(self._hero_status)

        for text in (
            "A hidden ephemeral onboarding AID handles the authenticated bootstrap exchange.",
            "The wallet creates or selects the permanent account AID before hosted resources are allocated.",
            "The wallet registers those witnesses locally and resolves the required watcher before completion.",
        ):
            label = QLabel(f"  •  {text}")
            label.setWordWrap(True)
            label.setStyleSheet(self._body_text_css())
            lay.addWidget(label)

        self._content_layout.addWidget(self._hero_section)

    def _build_connection_section(self):
        self._connection_section = self._make_card()
        lay = QVBoxLayout(self._connection_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        heading = QLabel("Boot surface connection")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        desc = QLabel(
            "The registration flow only unlocks after the wallet can reach "
            "the boot server over `GET /health` and `GET /bootstrap/config`."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(self._body_text_css())
        lay.addWidget(desc)

        connection_row = QHBoxLayout()
        connection_row.setSpacing(10)
        self._connection_badge = QLabel()
        self._prepare_badge(self._connection_badge)
        self._connection_detail = QLabel()
        self._connection_detail.setWordWrap(True)
        connection_row.addWidget(self._connection_badge, alignment=Qt.AlignmentFlag.AlignTop)
        connection_row.addWidget(self._connection_detail, 1)
        lay.addLayout(connection_row)

        trust_row = QHBoxLayout()
        trust_row.setSpacing(10)
        self._trust_badge = QLabel()
        self._prepare_badge(self._trust_badge)
        self._trust_detail = QLabel()
        self._trust_detail.setWordWrap(True)
        trust_row.addWidget(self._trust_badge, alignment=Qt.AlignmentFlag.AlignTop)
        trust_row.addWidget(self._trust_detail, 1)
        lay.addLayout(trust_row)

        self._bootstrap_summary = QLabel("")
        self._bootstrap_summary.setWordWrap(True)
        self._bootstrap_summary.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )
        lay.addWidget(self._bootstrap_summary)

        self._retry_connection_btn = LocksmithInvertedButton("Retry Connection")
        self._retry_connection_btn.clicked.connect(self._refresh_boot_connection)
        lay.addWidget(self._retry_connection_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._content_layout.addWidget(self._connection_section)

    def _build_identity_section(self):
        self._identity_section = self._make_card()
        lay = QVBoxLayout(self._identity_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("Permanent account identity")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        desc = QLabel(
            "Choose the permanent local AID that will represent this vault's "
            "KERI Foundation account. You can reuse an existing local AID or "
            "create a new one as part of onboarding."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(self._body_text_css())
        lay.addWidget(desc)

        self._aid_selector = FloatingLabelComboBox("Account AID")
        self._aid_selector.currentIndexChanged.connect(self._on_account_selection_changed)
        lay.addWidget(self._aid_selector)

        self._aid_hint = QLabel("")
        self._aid_hint.setWordWrap(True)
        self._aid_hint.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )
        lay.addWidget(self._aid_hint)

        self._alias_container = QWidget()
        alias_layout = QVBoxLayout(self._alias_container)
        alias_layout.setContentsMargins(0, 4, 0, 0)
        alias_layout.setSpacing(8)

        self._alias_input = LocksmithLineEdit(
            placeholder_text="Alias for the new local account AID"
        )
        self._alias_input.setMaxLength(ALIAS_MAX_LENGTH)
        self._alias_input.textChanged.connect(self._on_alias_changed)
        alias_layout.addWidget(self._alias_input)

        self._alias_feedback = QLabel("")
        self._alias_feedback.setWordWrap(True)
        self._alias_feedback.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )
        alias_layout.addWidget(self._alias_feedback)

        lay.addWidget(self._alias_container)
        self._content_layout.addWidget(self._identity_section)

    def _build_witness_section(self):
        self._witness_section = self._make_card()
        lay = QVBoxLayout(self._witness_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("Witness profile")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        desc = QLabel(
            "Choose the hosted witness profile for the permanent account AID. "
            "The wallet creates or selects that local AID first, then the boot "
            "surface allocates hosted resources for it."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(self._body_text_css())
        lay.addWidget(desc)

        self._witness_group = QButtonGroup(self)
        self._witness_group.setExclusive(True)

        self._panel_1of1 = LocksmithRadioPanel(
            header="1-of-1",
            subheader="Single hosted witness. Simple setup for demos and low-friction onboarding.",
        )
        self._panel_3of4 = LocksmithRadioPanel(
            header="3-of-4",
            subheader="Four hosted witnesses with threshold three. Stronger resilience for production paths.",
        )

        self._witness_group.addButton(self._panel_1of1.radioButton(), 1)
        self._witness_group.addButton(self._panel_3of4.radioButton(), 2)
        self._witness_group.buttonToggled.connect(self._on_witness_profile_toggled)

        lay.addWidget(self._panel_1of1)
        lay.addWidget(self._panel_3of4)

        self._content_layout.addWidget(self._witness_section)

    def _build_watcher_section(self):
        self._watcher_section = self._make_card()
        lay = QVBoxLayout(self._watcher_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("Required watcher")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        desc = QLabel(
            "The boot surface always allocates one hosted watcher for the KF "
            "account. The wallet resolves that watcher locally before onboarding completes."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(self._body_text_css())
        lay.addWidget(desc)

        badge = QLabel("Required")
        self._prepare_badge(badge)
        badge.setStyleSheet(self._success_badge_css())
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        self._content_layout.addWidget(self._watcher_section)

    def _build_review_section(self):
        self._review_section = self._make_card()
        lay = QVBoxLayout(self._review_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("Review and begin")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        desc = QLabel(
            "This starts the real hosted onboarding flow. The ephemeral onboarding "
            "AID stays hidden, while the permanent account AID remains local to this wallet."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(self._body_text_css())
        lay.addWidget(desc)

        self._review_connection_label = QLabel("")
        self._review_identity_label = QLabel("")
        self._review_aid_label = QLabel("")
        self._review_witness_label = QLabel("")
        self._review_watcher_label = QLabel("Required hosted watcher")

        for name, widget in (
            ("Boot surface:", self._review_connection_label),
            ("Account mode:", self._review_identity_label),
            ("Permanent AID:", self._review_aid_label),
            ("Witness profile:", self._review_witness_label),
            ("Watcher:", self._review_watcher_label),
        ):
            row = QHBoxLayout()
            row.setSpacing(12)
            key = QLabel(name)
            key.setFixedWidth(120)
            key.setStyleSheet(
                f"font-size: 13px; font-weight: 500; color: {colors.TEXT_SECONDARY};"
            )
            widget.setWordWrap(True)
            widget.setStyleSheet(
                f"font-size: 13px; color: {colors.TEXT_PRIMARY};"
            )
            row.addWidget(key)
            row.addWidget(widget, 1)
            lay.addLayout(row)

        lay.addWidget(LocksmithDivider())

        self._confirm_btn = LocksmithButton(text="Begin Onboarding")
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        lay.addWidget(self._confirm_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._content_layout.addWidget(self._review_section)

    def _build_progress_section(self):
        self._progress_section = self._make_card()
        lay = QVBoxLayout(self._progress_section)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        heading = QLabel("Onboarding progress")
        heading.setStyleSheet(self._section_heading_css())
        lay.addWidget(heading)

        self._progress_status = QLabel("Onboarding has not started yet.")
        self._progress_status.setWordWrap(True)
        self._progress_status.setStyleSheet(self._body_text_css())
        lay.addWidget(self._progress_status)

        self._progress_badge = QLabel("")
        self._prepare_badge(self._progress_badge)
        lay.addWidget(self._progress_badge, alignment=Qt.AlignmentFlag.AlignLeft)

        self._qr_container = QWidget()
        self._qr_layout = QVBoxLayout(self._qr_container)
        self._qr_layout.setContentsMargins(0, 8, 0, 0)
        self._qr_layout.setSpacing(12)
        self._qr_container.setVisible(False)
        lay.addWidget(self._qr_container)

        self._open_account_btn = LocksmithButton(text="Open Account")
        self._open_account_btn.clicked.connect(self.open_account_requested.emit)
        self._open_account_btn.setVisible(False)
        lay.addWidget(self._open_account_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._content_layout.addWidget(self._progress_section)

    def _reset_vault_state(self):
        """Clear page-local onboarding state when switching vault databases."""
        self._phase = PHASE_NOT_STARTED
        self._selected_witness_profile = ""
        self._run_in_progress = False
        self._progress_message = ""
        self._progress_error = ""
        self._boot_connected = False
        self._boot_verified = False
        self._boot_detail = "Connect to the boot surface to begin onboarding."
        self._boot_error = ""
        self._bootstrap = None
        self._qr_results = []
        self._qr_batch_mode = True
        self._account_aid = ""

        if not hasattr(self, "_aid_selector"):
            return

        self._aid_selector.blockSignals(True)
        self._aid_selector.clear()
        self._aid_selector.addItem(
            "Create a new local AID during onboarding",
            userData=CREATE_NEW_ACCOUNT_AID,
        )
        self._aid_selector.setCurrentIndex(0)
        self._aid_selector.blockSignals(False)

        self._alias_input.blockSignals(True)
        self._alias_input.clear()
        self._alias_input.blockSignals(False)
        self._alias_feedback.setText("")
        self._alias_feedback.setStyleSheet(
            f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
        )

        self._witness_group.setExclusive(False)
        for panel in (self._panel_1of1, self._panel_3of4):
            panel.blockSignals(True)
            panel.setChecked(False)
            panel.blockSignals(False)
        self._witness_group.setExclusive(True)

        self._set_inputs_enabled(True)
        self._render_qr_codes()
        self._apply_phase_visibility()

    def on_show(self):
        """Called by the plugin each time the onboarding page is displayed."""
        record = self._db.get_account() if self._db else None
        self._populate_account_choices()
        self._restore_from_record(record)
        self._account_aid = record.account_aid if record is not None else self._account_aid

        if not self._run_in_progress and not self._is_onboarded_record(record):
            self._refresh_boot_connection()

        self._set_inputs_enabled(record is None or record.status != ACCOUNT_STATUS_ONBOARDED)
        self._update_phase()
        self._apply_phase_visibility()
        logger.info(
            "KF onboarding page show: phase='%s' account=%s",
            self._phase,
            self._describe_account(record),
        )

    def _populate_account_choices(self):
        selected_aid = self._current_account_aid()
        self._aid_selector.blockSignals(True)
        self._aid_selector.clear()
        self._aid_selector.addItem(
            "Create a new local AID during onboarding",
            userData=CREATE_NEW_ACCOUNT_AID,
        )

        identifiers = sorted(
            list_eligible_local_identifiers(self._app),
            key=lambda item: (item.get("alias", "").lower(), item.get("prefix", "")),
        )
        for item in identifiers:
            alias = str(item.get("alias", "") or "")
            prefix = str(item.get("prefix", "") or "")
            label = f"{alias} ({self._shorten(prefix)})"
            self._aid_selector.addItem(
                label,
                userData={"aid": prefix, "alias": alias},
            )

        target_aid = selected_aid or self._account_aid
        if target_aid:
            self._select_existing_account_aid(target_aid)
        else:
            self._aid_selector.setCurrentIndex(0)
        self._aid_selector.blockSignals(False)
        self._update_identity_ui()

    def _restore_from_record(self, record: KFAccountRecord | None):
        if record is None:
            return

        if record.account_aid:
            self._select_existing_account_aid(record.account_aid)
        elif self._aid_selector.count() > 0 and self._aid_selector.currentIndex() < 0:
            self._aid_selector.setCurrentIndex(0)

        if record.account_alias and not self._alias_input.text().strip():
            self._alias_input.setText(record.account_alias)

        if record.witness_profile_code and not self._selected_witness_profile:
            self._selected_witness_profile = record.witness_profile_code
            if record.witness_profile_code == WITNESS_PROFILE_1_OF_1:
                self._panel_1of1.setChecked(True)
            elif record.witness_profile_code == WITNESS_PROFILE_3_OF_4:
                self._panel_3of4.setChecked(True)

        if (
            record.status == ACCOUNT_STATUS_FAILED
            and not self._run_in_progress
            and not self._progress_error
        ):
            self._progress_message = ""
            if record.onboarding_session_id and record.onboarding_auth_alias:
                self._progress_error = (
                    "Previous onboarding failed after a hosted session was saved. "
                    "Local progress is preserved. Begin onboarding again to resume the saved session."
                )
            else:
                self._progress_error = (
                    "Previous onboarding failed before a safe resume point. "
                    "The attempt was abandoned locally. Review the selections and begin onboarding again."
                )

    def _update_phase(self):
        old_phase = self._phase
        record = self._db.get_account() if self._db else None

        if self._run_in_progress:
            self._phase = PHASE_IN_PROGRESS
        elif record is not None and record.status == ACCOUNT_STATUS_ONBOARDED:
            self._phase = PHASE_COMPLETED
        elif not self._boot_connected:
            self._phase = PHASE_BOOTSTRAP_REQUIRED
        else:
            identity_valid, _ = self._validate_identity_selection()
            if not identity_valid:
                self._phase = PHASE_ALIAS_INPUT
            elif not self._selected_witness_profile:
                self._phase = PHASE_WITNESS_CHOICE
            else:
                self._phase = PHASE_REVIEW

        if old_phase != self._phase:
            logger.info(
                "KF onboarding phase transition: '%s' -> '%s'",
                old_phase,
                self._phase,
            )

    def _apply_phase_visibility(self):
        controls_available = self._boot_connected or self._phase in {
            PHASE_IN_PROGRESS,
            PHASE_COMPLETED,
        }
        phase_idx = ALL_PHASES.index(self._phase) if self._phase in ALL_PHASES else 0
        witness_idx = ALL_PHASES.index(PHASE_WITNESS_CHOICE)
        review_idx = ALL_PHASES.index(PHASE_REVIEW)

        self._hero_section.setVisible(True)
        self._connection_section.setVisible(True)
        self._identity_section.setVisible(controls_available)
        self._witness_section.setVisible(controls_available and phase_idx >= witness_idx)
        self._watcher_section.setVisible(controls_available and phase_idx >= review_idx)
        self._review_section.setVisible(controls_available and phase_idx >= review_idx)
        self._progress_section.setVisible(
            self._phase in {PHASE_IN_PROGRESS, PHASE_COMPLETED} or bool(self._progress_error)
        )

        self._update_subtitle()
        self._update_identity_ui()
        self._update_hero_summary()
        self._update_connection_content()
        if controls_available and phase_idx >= review_idx:
            self._update_review_summary()
        self._update_progress_content()

    def _update_subtitle(self):
        msgs = {
            PHASE_NOT_STARTED: "Prepare the vault's KF account setup.",
            PHASE_BOOTSTRAP_REQUIRED: "Connect to the boot surface before registration becomes available.",
            PHASE_ALIAS_INPUT: "Choose or create the permanent local account identity.",
            PHASE_WITNESS_CHOICE: "Select a hosted witness profile for the account.",
            PHASE_REVIEW: "Review the account setup and begin onboarding.",
            PHASE_IN_PROGRESS: "Onboarding is in progress. Keep this page open.",
            PHASE_COMPLETED: "Your KERI Foundation account is set up.",
        }
        self._subtitle.setText(msgs.get(self._phase, ""))

    def _update_hero_summary(self):
        if self._boot_verified:
            connection = "Boot reply verified"
        elif self._boot_connected:
            connection = "Boot surface connected"
        else:
            connection = "Boot surface unavailable"

        if self._is_create_new_selected():
            identity = "Create a new local AID"
        else:
            identity = f"Reuse `{self._current_account_alias() or 'existing local AID'}`"

        profile = self._selected_witness_profile or "Witness profile pending"
        self._hero_status.setText(f"{connection}. {identity}. {profile}.")

    def _update_connection_content(self):
        if self._boot_connected:
            self._connection_badge.setText("Connected")
            self._connection_badge.setStyleSheet(self._success_badge_css())
            self._connection_detail.setText(self._boot_detail)
            self._connection_detail.setStyleSheet(
                f"font-size: 13px; color: {colors.TEXT_PRIMARY};"
            )
        else:
            self._connection_badge.setText("Unavailable")
            self._connection_badge.setStyleSheet(self._neutral_badge_css(foreground=colors.DANGER))
            self._connection_detail.setText(self._boot_error or self._boot_detail)
            self._connection_detail.setStyleSheet(
                f"font-size: 13px; color: {colors.DANGER};"
            )

        if self._boot_verified:
            self._trust_badge.setText("Verified")
            self._trust_badge.setStyleSheet(self._success_badge_css())
            self._trust_detail.setText(
                "The authenticated onboarding reply was verified against the boot-server identity."
            )
            self._trust_detail.setStyleSheet(
                f"font-size: 13px; color: {colors.SUCCESS_TEXT};"
            )
        else:
            self._trust_badge.setText("Pending")
            self._trust_badge.setStyleSheet(self._neutral_badge_css())
            self._trust_detail.setText(
                "Service identity verification happens after the first authenticated onboarding reply."
            )
            self._trust_detail.setStyleSheet(
                f"font-size: 13px; color: {colors.TEXT_SECONDARY};"
            )

        if self._bootstrap is None:
            self._bootstrap_summary.setText("")
            return

        option_codes = ", ".join(
            option.code for option in self._bootstrap.account_options if option.code
        ) or "none"
        region = self._bootstrap.region_name or self._bootstrap.region_id or "default"
        self._bootstrap_summary.setText(
            f"Region: {region}. Witness profiles: {option_codes}. "
            f"Hosted watcher required: {'yes' if self._bootstrap.watcher_required else 'no'}."
        )

    def _update_review_summary(self):
        if self._boot_connected:
            region = (
                self._bootstrap.region_name
                if self._bootstrap and self._bootstrap.region_name
                else self._bootstrap.region_id
                if self._bootstrap
                else ""
            )
            target = region or self._boot_host_label()
            self._review_connection_label.setText(f"Connected to {target}")
        else:
            self._review_connection_label.setText("Connection required")

        if self._is_create_new_selected():
            self._review_identity_label.setText("Create a new permanent local AID")
            self._review_aid_label.setText(self._current_account_alias() or "(alias required)")
        else:
            data = self._selected_account_item()
            self._review_identity_label.setText("Reuse an existing local AID")
            self._review_aid_label.setText(
                f"{data.get('alias', '(missing alias)')} ({self._shorten(data.get('aid', ''))})"
            )

        profile = self._selected_witness_profile
        if profile:
            count, toad = witness_profile_params(profile)
            self._review_witness_label.setText(
                f"{profile} ({count} witness{'es' if count > 1 else ''}, threshold {toad})"
            )
        else:
            self._review_witness_label.setText("(not selected)")

    def _update_progress_content(self):
        if self._phase == PHASE_IN_PROGRESS:
            self._progress_status.setText(self._progress_message or "Onboarding is in progress.")
            self._progress_badge.setText("IN PROGRESS")
            self._progress_badge.setStyleSheet(self._neutral_badge_css(foreground=colors.WARNING_BUTTON))
            self._progress_badge.setVisible(True)
            self._open_account_btn.setVisible(False)
        elif self._phase == PHASE_COMPLETED:
            status = self._progress_message or (
                "Onboarding is complete. Witness authenticator QR codes are ready below."
            )
            self._progress_status.setText(status)
            self._progress_badge.setText("COMPLETED")
            self._progress_badge.setStyleSheet(self._success_badge_css())
            self._progress_badge.setVisible(True)
            self._open_account_btn.setVisible(True)
        elif self._progress_error:
            self._progress_status.setText(self._progress_error)
            self._progress_badge.setText("FAILED")
            self._progress_badge.setStyleSheet(self._neutral_badge_css(foreground=colors.DANGER))
            self._progress_badge.setVisible(True)
            self._open_account_btn.setVisible(False)
        else:
            self._progress_status.setText(self._progress_message or "Onboarding has not started yet.")
            self._progress_badge.setVisible(False)
            self._open_account_btn.setVisible(False)

        self._qr_container.setVisible(bool(self._qr_results))

    def begin_run(self):
        self._run_in_progress = True
        self._progress_error = ""
        self._progress_message = "Starting onboarding..."
        self._boot_verified = False
        self._qr_results = []
        self._account_aid = self._current_account_aid()
        self._set_inputs_enabled(False)
        self._update_phase()
        self._apply_phase_visibility()

    def update_run(self, *, stage: str, detail: str, boot_verified=False, completed=False):
        self._progress_message = detail
        if stage == "bootstrap":
            self._boot_connected = True
            self._boot_detail = detail
            self._boot_error = ""
        elif stage == "boot_reply_verified":
            self._boot_detail = detail
        if boot_verified:
            self._boot_verified = True
        if completed:
            self._run_in_progress = False
        self._update_phase()
        self._apply_phase_visibility()

    def fail_run(self, message: str):
        self._run_in_progress = False
        self._progress_error = message
        self._progress_message = ""
        self._qr_results = []
        self._account_aid = ""
        self._set_inputs_enabled(True)
        self._update_phase()
        self._apply_phase_visibility()

    def complete_run(self, *, account_aid: str, results: list[dict], batch_mode: bool):
        self._run_in_progress = False
        self._progress_error = ""
        self._progress_message = (
            "Onboarding is complete. Witness authenticator QR codes are ready below."
        )
        self._account_aid = account_aid
        self._qr_results = list(results)
        self._qr_batch_mode = batch_mode
        self._boot_connected = True
        self._boot_verified = True
        self._set_inputs_enabled(False)
        self._render_qr_codes()
        self._update_phase()
        self._apply_phase_visibility()

    def _render_qr_codes(self):
        while self._qr_layout.count():
            child = self._qr_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        hab = (
            self._app.vault.hby.habByPre(self._account_aid)
            if self._app and self._account_aid and getattr(self._app, "vault", None)
            else None
        )
        controller_alias = getattr(hab, "name", self._account_aid or "account")
        controller_aid = getattr(hab, "pre", self._account_aid)

        if not hab or not self._qr_results:
            self._qr_container.setVisible(False)
            return

        if self._qr_batch_mode:
            seed = self._qr_results[0]["totp_seed"]
            uri = create_totp_uri(
                secret=seed,
                vault_name=f"KF-Batch-{controller_aid[:8]}",
                issuer="KERI Foundation",
            )
            panel = LocksmithQRPanel(
                number="1",
                witness_name="Batch TOTP",
                witness_eid=self._qr_results[0]["eid"],
                controller_alias=controller_alias,
                controller_aid=controller_aid,
                url=uri,
            )
            self._qr_layout.addWidget(panel)
            return

        for idx, res in enumerate(self._qr_results, start=1):
            uri = create_totp_uri(
                secret=res["totp_seed"],
                vault_name=f"KF-{res['eid'][:12]}",
                issuer="KERI Foundation",
            )
            panel = LocksmithQRPanel(
                number=str(idx),
                witness_name=res.get("name") or f"KF Witness {res['eid'][:12]}",
                witness_eid=res["eid"],
                controller_alias=controller_alias,
                controller_aid=controller_aid,
                url=uri,
            )
            self._qr_layout.addWidget(panel)

    def _set_inputs_enabled(self, enabled: bool):
        self._aid_selector.setEnabled(enabled)
        self._alias_input.setEnabled(enabled)
        self._panel_1of1.setEnabled(enabled)
        self._panel_3of4.setEnabled(enabled)
        self._confirm_btn.setEnabled(enabled)

    def _refresh_boot_connection(self):
        if self._run_in_progress:
            return

        if not self._boot_client:
            self._boot_connected = False
            self._boot_error = "KF onboarding boot client is not available."
            self._boot_detail = "Configure the KF onboarding surface before starting."
            self._bootstrap = None
            self._update_phase()
            self._apply_phase_visibility()
            return

        if self._preflight_task is not None and not self._preflight_task.done():
            return

        self._preflight_task = asyncio.create_task(
            self._refresh_boot_connection_async(
                boot_client=self._boot_client,
                db=self._db,
            )
        )

    async def _refresh_boot_connection_async(self, *, boot_client, db):
        task = asyncio.current_task()
        try:
            await asyncio.to_thread(boot_client.check_health)
            bootstrap = await asyncio.to_thread(boot_client.fetch_bootstrap_config)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            if task is not self._preflight_task or db is not self._db or boot_client is not self._boot_client:
                return
            self._boot_connected = False
            self._bootstrap = None
            self._boot_error = f"Could not connect to the KF boot surface: {ex}"
            self._boot_detail = "Retry after the boot server becomes reachable."
            logger.warning("KF onboarding boot preflight failed: %s", ex)
        else:
            if task is not self._preflight_task or db is not self._db or boot_client is not self._boot_client:
                return
            self._bootstrap = bootstrap
            self._boot_connected = True
            self._boot_error = ""
            host = self._boot_host_label()
            region = self._bootstrap.region_name or self._bootstrap.region_id or "default region"
            self._boot_detail = f"Connected to {host}. Bootstrap loaded for {region}."
            logger.info("KF onboarding boot preflight succeeded: %s", self._boot_detail)
        finally:
            if task is self._preflight_task:
                self._preflight_task = None

        self._update_phase()
        self._apply_phase_visibility()

    def shutdown(self):
        task = self._preflight_task
        if task is not None and not task.done():
            task.cancel()
            loop = task.get_loop()
            if not loop.is_running():
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
            return False
        self._preflight_task = None
        return True

    def _on_account_selection_changed(self, _index: int):
        self._update_identity_ui()
        self._update_phase()
        self._apply_phase_visibility()

    def _update_identity_ui(self):
        create_new = self._is_create_new_selected()
        self._alias_container.setVisible(create_new)

        if create_new:
            self._aid_hint.setText(
                "A new permanent local AID will be created locally before hosted witnesses and the watcher are allocated."
            )
            return

        data = self._selected_account_item()
        aid = data.get("aid", "")
        alias = data.get("alias", "")
        if aid:
            self._aid_hint.setText(
                f"Reuse the existing local AID `{self._shorten(aid)}` for the KF account alias `{alias}`."
            )
        else:
            self._aid_hint.setText("Select a local AID or create a new one.")

    def _on_alias_changed(self, text: str):
        if not self._is_create_new_selected():
            return

        valid, message = validate_alias(text)
        if not text.strip():
            self._alias_feedback.setText("")
            self._alias_feedback.setStyleSheet(
                f"font-size: 12px; color: {colors.TEXT_SECONDARY};"
            )
        elif valid:
            self._alias_feedback.setText(f"\u2713 {message}")
            self._alias_feedback.setStyleSheet(
                f"font-size: 12px; color: {colors.SUCCESS_TEXT};"
            )
        else:
            self._alias_feedback.setText(message)
            self._alias_feedback.setStyleSheet(
                f"font-size: 12px; color: {colors.DANGER};"
            )

        self._update_phase()
        self._apply_phase_visibility()

    def _on_witness_profile_toggled(self, _button, checked):
        if not checked:
            return

        if self._panel_1of1.isChecked():
            self._selected_witness_profile = WITNESS_PROFILE_1_OF_1
        elif self._panel_3of4.isChecked():
            self._selected_witness_profile = WITNESS_PROFILE_3_OF_4
        else:
            self._selected_witness_profile = ""

        logger.info(
            "KF onboarding witness profile selected: '%s'",
            self._selected_witness_profile,
        )

        self._update_phase()
        self._apply_phase_visibility()

    def _on_confirm_clicked(self):
        if not self._boot_connected:
            logger.warning("KF onboarding confirm blocked: boot surface is not connected")
            return

        alias = self._current_account_alias()
        account_aid = self._current_account_aid()
        identity_valid, message = self._validate_identity_selection()
        if not identity_valid:
            logger.warning("KF onboarding confirm blocked: %s", message)
            return

        if not self._selected_witness_profile:
            logger.warning("KF onboarding confirm blocked: no witness profile selected")
            return

        logger.info(
            "KF onboarding confirm requested: alias='%s' witness_profile='%s' account_aid='%s'",
            alias,
            self._selected_witness_profile,
            account_aid or "create_new",
        )

        if self._db:
            record = self._db.get_account()
            if record is not None and record.status in {
                ACCOUNT_STATUS_PENDING_ONBOARDING,
                ACCOUNT_STATUS_FAILED,
            }:
                count, toad = witness_profile_params(self._selected_witness_profile)
                record.account_alias = alias
                record.account_aid = account_aid
                record.witness_profile_code = self._selected_witness_profile
                record.witness_count = count
                record.toad = toad
                self._db.pin_account(record)

        self.confirm_requested.emit(alias, self._selected_witness_profile, account_aid)

    def _validate_identity_selection(self) -> tuple[bool, str]:
        if self._is_create_new_selected():
            return validate_alias(self._alias_input.text())

        data = self._selected_account_item()
        aid = data.get("aid", "")
        alias = data.get("alias", "")
        if not aid or not alias:
            return False, "Select an existing local AID or choose to create a new one."
        return True, "Existing local AID selected."

    def _selected_account_item(self) -> dict[str, str]:
        data = self._aid_selector.currentData()
        return data if isinstance(data, dict) else {}

    def _is_create_new_selected(self) -> bool:
        return self._aid_selector.currentData() == CREATE_NEW_ACCOUNT_AID

    def _current_account_alias(self) -> str:
        if self._is_create_new_selected():
            return self._alias_input.text().strip()
        return str(self._selected_account_item().get("alias", "") or "")

    def _current_account_aid(self) -> str:
        if self._is_create_new_selected():
            return ""
        return str(self._selected_account_item().get("aid", "") or "")

    def _select_existing_account_aid(self, account_aid: str):
        for idx in range(self._aid_selector.count()):
            data = self._aid_selector.itemData(idx)
            if isinstance(data, dict) and data.get("aid") == account_aid:
                self._aid_selector.setCurrentIndex(idx)
                return
        self._aid_selector.setCurrentIndex(0)

    def _boot_host_label(self) -> str:
        surfaces = getattr(self._boot_client, "_surfaces", None)
        onboarding_url = getattr(surfaces, "onboarding_url", "")
        if not onboarding_url:
            return "the configured boot surface"
        parsed = urlparse(onboarding_url)
        return parsed.netloc or onboarding_url

    @staticmethod
    def _shorten(text: str, keep: int = 16) -> str:
        if len(text) <= keep:
            return text
        return f"{text[:keep]}..."

    @staticmethod
    def _prepare_badge(label: QLabel):
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(30)
        label.setContentsMargins(0, 0, 0, 0)

    @staticmethod
    def _make_card(*, background: str | None = None, border: str | None = None) -> QFrame:
        card = QFrame()
        card.setObjectName("kfOnboardingCard")
        card.setStyleSheet(
            f"""
            QFrame#kfOnboardingCard {{
                background-color: {background or colors.WHITE};
                border: 1px solid {border or colors.BORDER};
                border-radius: 10px;
            }}
        """
        )
        return card

    @staticmethod
    def _section_heading_css() -> str:
        return f"""
            font-size: 16px;
            font-weight: 700;
            color: {colors.TEXT_PRIMARY};
        """

    @staticmethod
    def _body_text_css() -> str:
        return f"""
            font-size: 14px;
            line-height: 20px;
            color: {colors.TEXT_SECONDARY};
        """

    @staticmethod
    def _success_badge_css() -> str:
        return f"""
            background-color: {colors.BACKGROUND_SUCCESS};
            color: {colors.SUCCESS_TEXT};
            border-radius: 15px;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 12px;
        """

    @staticmethod
    def _neutral_badge_css(*, foreground: str | None = None) -> str:
        return f"""
            background-color: {colors.BACKGROUND_HOVER};
            color: {foreground or colors.TEXT_SECONDARY};
            border-radius: 15px;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 12px;
        """

    @staticmethod
    def _is_onboarded_record(record: KFAccountRecord | None) -> bool:
        return record is not None and record.status == ACCOUNT_STATUS_ONBOARDED

    @staticmethod
    def _describe_account(record: KFAccountRecord | None) -> str:
        if record is None:
            return "missing"
        return (
            f"status='{record.status}' "
            f"account_aid='{record.account_aid or '-'}' "
            f"account_alias='{record.account_alias or '-'}' "
            f"witness_profile_code='{record.witness_profile_code or '-'}' "
            f"region_id='{record.region_id or '-'}'"
        )
