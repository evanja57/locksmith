# -*- encoding: utf-8 -*-
"""
Focused tests for the KF onboarding page UI state, progressive section
visibility, alias validation, witness profile selection, confirm action,
and resume-from-record behavior.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from types import SimpleNamespace

from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_FAILED,
    ACCOUNT_STATUS_ONBOARDED,
    ACCOUNT_STATUS_PENDING_ONBOARDING,
    KFAccountRecord,
    KFBaser,
)
from locksmith.plugins.kerifoundation.onboarding.page import (
    ALIAS_MAX_LENGTH,
    ALIAS_MIN_LENGTH,
    PHASE_ALIAS_INPUT,
    PHASE_BOOTSTRAP_REQUIRED,
    PHASE_COMPLETED,
    PHASE_REVIEW,
    PHASE_WITNESS_CHOICE,
    KFOnboardingPage,
    validate_alias,
    witness_profile_params,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path, name="test-onboarding-ui"):
    return KFBaser(name=name, headDirPath=str(tmp_path), reopen=True)


class FakeBootClient:
    def __init__(self, *, available=True):
        self.available = available

    def clone(self):
        return self

    def check_health(self):
        if not self.available:
            raise RuntimeError("boot unavailable")
        return {"status": "ok"}

    def fetch_bootstrap_config(self):
        if not self.available:
            raise RuntimeError("boot unavailable")
        return SimpleNamespace(
            watcher_required=True,
            region_id="us-west-2",
            region_name="US West",
            account_options=[
                SimpleNamespace(code="1-of-1"),
                SimpleNamespace(code="3-of-4"),
            ],
        )


class FakeHab:
    def __init__(self, alias, pre):
        self.name = alias
        self.pre = pre


class FakeNames:
    def __init__(self, items):
        self._items = items

    def getTopItemIter(self, keys=()):
        return iter(self._items)


class FakeHby:
    def __init__(self, habs=None):
        self._hab_by_alias = {hab.name: hab for hab in (habs or [])}
        self.db = SimpleNamespace(
            names=FakeNames(
                [
                    (("", hab.name), hab.pre)
                    for hab in (habs or [])
                ]
            )
        )

    def habByName(self, alias):
        return self._hab_by_alias.get(alias)


class FakeVault:
    def __init__(self, habs=None):
        self.hby = FakeHby(habs=habs)


class FakeApp:
    def __init__(self, habs=None):
        self.vault = FakeVault(habs=habs)


def _make_page(tmp_path, record=None, *, app=None, boot_available=True):
    """Create an onboarding page wired to a temporary database."""
    db = _make_db(tmp_path)
    if record is not None:
        db.pin_account(record)
    else:
        db.ensure_account()
    page = KFOnboardingPage(app=app)
    page.set_db(db)
    page.set_boot_client(FakeBootClient(available=boot_available))
    return page, db


# ---------------------------------------------------------------------------
# validate_alias unit tests
# ---------------------------------------------------------------------------


class TestValidateAlias:
    def test_empty_alias(self):
        valid, msg = validate_alias("")
        assert not valid

    def test_whitespace_only(self):
        valid, _ = validate_alias("   ")
        assert not valid

    def test_too_short(self):
        valid, _ = validate_alias("ab")
        assert not valid
        assert ALIAS_MIN_LENGTH == 3

    def test_minimum_length(self):
        valid, _ = validate_alias("abc")
        assert valid

    def test_too_long(self):
        valid, _ = validate_alias("x" * (ALIAS_MAX_LENGTH + 1))
        assert not valid

    def test_max_length(self):
        valid, _ = validate_alias("x" * ALIAS_MAX_LENGTH)
        assert valid

    def test_starts_with_special(self):
        valid, _ = validate_alias("-bad")
        assert not valid

    def test_valid_with_hyphens_underscores_spaces(self):
        valid, _ = validate_alias("my KF account-1_test")
        assert valid

    def test_valid_starts_with_digit(self):
        valid, _ = validate_alias("1account")
        assert valid

    def test_invalid_special_chars(self):
        valid, _ = validate_alias("bad@alias")
        assert not valid


# ---------------------------------------------------------------------------
# witness_profile_params
# ---------------------------------------------------------------------------


class TestWitnessProfileParams:
    def test_1_of_1(self):
        count, toad = witness_profile_params("1-of-1")
        assert count == 1
        assert toad == 1

    def test_3_of_4(self):
        count, toad = witness_profile_params("3-of-4")
        assert count == 4
        assert toad == 3

    def test_unknown_defaults_to_1_of_1(self):
        count, toad = witness_profile_params("unknown")
        assert count == 1
        assert toad == 1


# ---------------------------------------------------------------------------
# Phase / section visibility tests
# ---------------------------------------------------------------------------


class TestOnboardingPhases:
    def test_initial_phase_is_alias_input(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            assert page.phase == PHASE_ALIAS_INPUT
            # Intro and alias sections not hidden
            assert not page._intro_section.isHidden()
            assert not page._alias_section.isHidden()
            # Later sections hidden
            assert page._witness_section.isHidden()
            assert page._review_section.isHidden()
            assert page._progress_section.isHidden()
        finally:
            db.close()

    def test_boot_connection_required_when_boot_surface_unavailable(self, qapp, tmp_path):
        page, db = _make_page(tmp_path, boot_available=False)
        try:
            page.on_show()
            assert page.phase == PHASE_BOOTSTRAP_REQUIRED
            assert page._identity_section.isHidden()
            assert not page._connection_section.isHidden()
        finally:
            db.close()

    def test_valid_alias_shows_witness_section(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("my-account")
            assert page.phase == PHASE_WITNESS_CHOICE
            assert not page._witness_section.isHidden()
            # Review still hidden until witness chosen
            assert page._review_section.isHidden()
        finally:
            db.close()

    def test_witness_selection_shows_review(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("my-account")
            page._panel_1of1.setChecked(True)
            assert page.phase == PHASE_REVIEW
            assert not page._review_section.isHidden()
            assert not page._watcher_section.isHidden()
            assert not page._boot_section.isHidden()
        finally:
            db.close()

    def test_3_of_4_selection(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("prod-account")
            page._panel_3of4.setChecked(True)
            assert page.phase == PHASE_REVIEW
            assert page._selected_witness_profile == "3-of-4"
        finally:
            db.close()

    def test_existing_aid_selection_skips_alias_requirement(self, qapp, tmp_path):
        app = FakeApp(habs=[FakeHab("existing-account", "AID_EXISTING")])
        page, db = _make_page(tmp_path, app=app)
        try:
            page.on_show()
            page._aid_selector.setCurrentIndex(1)
            assert page.phase == PHASE_WITNESS_CHOICE
            assert page._alias_container.isHidden()
            assert page._current_account_aid() == "AID_EXISTING"
            assert page._current_account_alias() == "existing-account"
        finally:
            db.close()

    def test_clearing_alias_hides_later_sections(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("my-account")
            page._panel_1of1.setChecked(True)
            assert page.phase == PHASE_REVIEW

            page._alias_input.setText("")
            assert page.phase == PHASE_ALIAS_INPUT
            assert page._witness_section.isHidden()
            assert page._review_section.isHidden()
        finally:
            db.close()

    def test_onboarded_record_shows_completed(self, qapp, tmp_path):
        record = KFAccountRecord(
            account_alias="done-account",
            status=ACCOUNT_STATUS_ONBOARDED,
            witness_profile_code="1-of-1",
            witness_count=1,
            toad=1,
        )
        page, db = _make_page(tmp_path, record=record)
        try:
            page.on_show()
            assert page.phase == PHASE_COMPLETED
            assert not page._progress_section.isHidden()
        finally:
            db.close()

    def test_failed_record_shows_review(self, qapp, tmp_path):
        record = KFAccountRecord(
            account_alias="fail-account",
            status=ACCOUNT_STATUS_FAILED,
            witness_profile_code="3-of-4",
            witness_count=4,
            toad=3,
        )
        page, db = _make_page(tmp_path, record=record)
        try:
            page.on_show()
            assert page.phase == PHASE_REVIEW
            assert not page._review_section.isHidden()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Resume / prefill tests
# ---------------------------------------------------------------------------


class TestOnboardingResume:
    def test_resume_prefills_alias(self, qapp, tmp_path):
        record = KFAccountRecord(
            account_alias="resumed-alias",
            status=ACCOUNT_STATUS_PENDING_ONBOARDING,
        )
        page, db = _make_page(tmp_path, record=record)
        try:
            page.on_show()
            assert page._alias_input.text() == "resumed-alias"
        finally:
            db.close()

    def test_resume_prefills_witness_profile(self, qapp, tmp_path):
        record = KFAccountRecord(
            account_alias="resumed-alias",
            status=ACCOUNT_STATUS_PENDING_ONBOARDING,
            witness_profile_code="3-of-4",
            witness_count=4,
            toad=3,
        )
        page, db = _make_page(tmp_path, record=record)
        try:
            page.on_show()
            assert page._selected_witness_profile == "3-of-4"
            assert page._panel_3of4.isChecked()
            assert page.phase == PHASE_REVIEW
        finally:
            db.close()

    def test_resume_does_not_overwrite_user_input(self, qapp, tmp_path):
        record = KFAccountRecord(
            account_alias="old-alias",
            status=ACCOUNT_STATUS_PENDING_ONBOARDING,
        )
        page, db = _make_page(tmp_path, record=record)
        try:
            # Simulate user already typed something
            page._alias_input.setText("user-typed")
            page.on_show()
            # Should not overwrite
            assert page._alias_input.text() == "user-typed"
        finally:
            db.close()

    def test_switching_to_new_vault_clears_previous_vault_prefill_state(self, qapp, tmp_path):
        first = _make_db(tmp_path, name="first-vault-onboarding")
        second = _make_db(tmp_path, name="second-vault-onboarding")
        app = FakeApp()
        page = KFOnboardingPage(app=app)
        page.set_boot_client(FakeBootClient(available=True))

        try:
            first.ensure_account()
            second.ensure_account()

            page.set_db(first)
            page.on_show()
            page._alias_input.setText("carry-over-alias")
            page._panel_3of4.setChecked(True)

            assert page._alias_input.text() == "carry-over-alias"
            assert page._selected_witness_profile == "3-of-4"
            assert page._panel_3of4.isChecked()

            page.set_db(second)
            page.on_show()

            assert page._alias_input.text() == ""
            assert page._selected_witness_profile == ""
            assert not page._panel_1of1.isChecked()
            assert not page._panel_3of4.isChecked()
            assert page._is_create_new_selected() is True
            assert page.phase == PHASE_ALIAS_INPUT
        finally:
            first.close()
            second.close()


# ---------------------------------------------------------------------------
# Confirm action tests
# ---------------------------------------------------------------------------


class TestOnboardingConfirm:
    def test_confirm_persists_choices(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("confirm-test")
            page._panel_1of1.setChecked(True)

            # Track signal emission
            received = []
            page.confirm_requested.connect(lambda a, w, aid: received.append((a, w, aid)))

            page._on_confirm_clicked()

            # Signal emitted
            assert len(received) == 1
            assert received[0] == ("confirm-test", "1-of-1", "")

            # Record updated in DB
            record = db.get_account()
            assert record is not None
            assert record.account_alias == "confirm-test"
            assert record.account_aid == ""
            assert record.witness_profile_code == "1-of-1"
            assert record.witness_count == 1
            assert record.toad == 1
            # Status should still be pending (not marked onboarded by UI task)
            assert record.status == ACCOUNT_STATUS_PENDING_ONBOARDING
        finally:
            db.close()

    def test_confirm_persists_selected_existing_account_aid(self, qapp, tmp_path):
        app = FakeApp(habs=[FakeHab("existing-account", "AID_EXISTING")])
        page, db = _make_page(tmp_path, app=app)
        try:
            page.on_show()
            page._aid_selector.setCurrentIndex(1)
            page._panel_1of1.setChecked(True)

            received = []
            page.confirm_requested.connect(lambda a, w, aid: received.append((a, w, aid)))

            page._on_confirm_clicked()

            assert received == [("existing-account", "1-of-1", "AID_EXISTING")]
            record = db.get_account()
            assert record is not None
            assert record.account_alias == "existing-account"
            assert record.account_aid == "AID_EXISTING"
        finally:
            db.close()

    def test_confirm_blocked_without_alias(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._panel_1of1.setChecked(True)
            # Alias is empty

            received = []
            page.confirm_requested.connect(lambda a, w, aid: received.append((a, w, aid)))

            page._on_confirm_clicked()
            assert len(received) == 0
        finally:
            db.close()

    def test_confirm_blocked_without_witness_profile(self, qapp, tmp_path):
        page, db = _make_page(tmp_path)
        try:
            page.on_show()
            page._alias_input.setText("some-alias")

            received = []
            page.confirm_requested.connect(lambda a, w, aid: received.append((a, w, aid)))

            page._on_confirm_clicked()
            assert len(received) == 0
        finally:
            db.close()


class TestOnboardingLogging:
    def test_alias_typing_does_not_log_every_edit(self, qapp, tmp_path, caplog):
        page, db = _make_page(tmp_path)
        try:
            caplog.set_level("INFO")
            page.on_show()
            page._alias_input.setText("some-alias")

            assert not any(
                "KF onboarding alias validation:" in record.getMessage()
                for record in caplog.records
            )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Integration with account gating
# ---------------------------------------------------------------------------


class TestOnboardingGatingIntegration:
    def test_pending_account_lands_on_onboarding(self, qapp, tmp_path):
        """Verify the existing gating still routes to onboarding for non-onboarded accounts."""
        from locksmith.plugins.kerifoundation.plugin import KeriFoundationPlugin
        from types import SimpleNamespace

        class FakeHby:
            def __init__(self):
                self.name = "gating-test"
                self.db = SimpleNamespace(names=SimpleNamespace(getTopItemIter=lambda keys=(): iter(())))

            def habByName(self, alias):
                return None

        class FakeVault:
            def __init__(self):
                self.hby = FakeHby()

        app = SimpleNamespace(
            config=SimpleNamespace(environment=SimpleNamespace(value="development"))
        )
        vault = FakeVault()
        plugin = KeriFoundationPlugin()
        plugin.initialize(app)

        # Monkeypatch DB to use tmp_path
        original_baser = KFBaser
        plugin.on_vault_opened.__func__  # just to verify it exists

        db = KFBaser(name=f"kf_{vault.hby.name}", headDirPath=str(tmp_path), reopen=True)
        plugin._db = db
        plugin._onboarding_page.set_db(db)

        try:
            assert plugin.is_setup_complete(vault) is False
            page_key, should_push_menu = plugin.get_setup_page(vault)
            assert page_key == "kf_onboarding"
            assert should_push_menu is True
        finally:
            db.close()
