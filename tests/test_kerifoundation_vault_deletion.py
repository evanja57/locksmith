from types import SimpleNamespace
from pathlib import Path

import pytest

from locksmith.plugins.kerifoundation.db.basing import (
    ACCOUNT_STATUS_ONBOARDED,
    KFBaser,
)
from locksmith.plugins.kerifoundation.onboarding.service import (
    KFVaultDeletionService,
    ONBOARDING_AUTH_NAMESPACE,
)
from locksmith.plugins.kerifoundation.plugin import KeriFoundationPlugin


class FakeHab(SimpleNamespace):
    pass


class FakeHby:
    def __init__(self, name="test-vault", *, base="", temp=False, headDirPath=None,
                 habs_by_pre=None, habs_by_name=None):
        self.name = name
        self.base = base
        self.temp = temp
        self._habs_by_pre = habs_by_pre or {}
        self._habs_by_name = habs_by_name or {}
        self.db = SimpleNamespace(headDirPath=headDirPath,
                                  names=SimpleNamespace(getTopItemIter=lambda keys=(): iter(())))

    def habByPre(self, pre):
        return self._habs_by_pre.get(pre)

    def habByName(self, alias, ns=None):
        return self._habs_by_name.get((alias, ns))

    def deleteHab(self, alias, ns=None):
        self._habs_by_name.pop((alias, ns), None)
        for pre, hab in list(self._habs_by_pre.items()):
            if getattr(hab, "name", None) == alias:
                del self._habs_by_pre[pre]


class FakeVault:
    def __init__(self, hby):
        self.hby = hby


class FakeApp:
    def __init__(self, hby):
        self.vault = FakeVault(hby)
        self.config = SimpleNamespace(environment=SimpleNamespace(value="development"))


class FakeBootClient:
    def __init__(self):
        self.boot_server_aid = ""
        self.calls: list[tuple] = []

    def clone(self):
        return self

    def set_boot_server_aid(self, aid: str):
        self.boot_server_aid = aid
        self.calls.append(("set_boot_server_aid", aid))

    def cancel_onboarding(self, hab, *, session_id: str, account_aid: str = "", reason: str = ""):
        self.calls.append(("cancel_onboarding", hab.pre, session_id, account_aid, reason))

    def delete_account(self, hab, *, account_aid: str, destination: str = ""):
        self.calls.append(("delete_account", hab.pre, account_aid, destination))


def test_kf_vault_deletion_service_cancels_saved_onboarding_session(tmp_path):
    auth_hab = FakeHab(pre="EHAB_AUTH", name="kf-auth")
    hby = FakeHby(
        habs_by_name={(auth_hab.name, ONBOARDING_AUTH_NAMESPACE): auth_hab},
    )
    app = FakeApp(hby)
    db = KFBaser(name="kf_delete_pending", headDirPath=str(tmp_path), reopen=True)
    boot_client = FakeBootClient()

    record, _ = db.ensure_account()
    record.account_aid = "AID_ACCOUNT"
    record.onboarding_session_id = "sess_pending"
    record.onboarding_auth_alias = auth_hab.name
    record.boot_server_aid = "BOOT_AID"
    db.pin_account(record)

    try:
        service = KFVaultDeletionService(app=app, db=db, boot_client=boot_client)
        service.delete_vault_account()
    finally:
        db.close(clear=True)

    assert boot_client.calls == [
        ("set_boot_server_aid", "BOOT_AID"),
        ("cancel_onboarding", auth_hab.pre, "sess_pending", "AID_ACCOUNT", "vault_deleted"),
    ]


def test_kf_vault_deletion_service_deletes_onboarded_account(tmp_path):
    account_hab = FakeHab(pre="AID_ACCOUNT", name="account")
    hby = FakeHby(habs_by_pre={account_hab.pre: account_hab})
    app = FakeApp(hby)
    db = KFBaser(name="kf_delete_onboarded", headDirPath=str(tmp_path), reopen=True)
    boot_client = FakeBootClient()

    record, _ = db.ensure_account()
    record.account_aid = account_hab.pre
    record.status = ACCOUNT_STATUS_ONBOARDED
    record.boot_server_aid = "BOOT_AID"
    db.pin_account(record)

    try:
        service = KFVaultDeletionService(app=app, db=db, boot_client=boot_client)
        service.delete_vault_account()
    finally:
        db.close(clear=True)

    assert boot_client.calls == [
        ("set_boot_server_aid", "BOOT_AID"),
        ("delete_account", account_hab.pre, account_hab.pre, "BOOT_AID"),
    ]


def test_kf_plugin_prepare_vault_deletion_uses_remote_teardown_service(qapp, tmp_path, monkeypatch):
    app = FakeApp(FakeHby(headDirPath=str(tmp_path)))
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    captured = {}

    class FakeDeletionService:
        def __init__(self, *, app, db, boot_client):
            captured["app"] = app
            captured["db"] = db
            captured["boot_client"] = boot_client

        def delete_vault_account(self):
            captured["deleted"] = True

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.KFVaultDeletionService",
        FakeDeletionService,
    )

    plugin.on_vault_opened(app.vault)
    try:
        plugin.prepare_vault_deletion(app.vault)
    finally:
        plugin.on_vault_closed(app.vault, clear=True)

    assert captured["app"] is app
    assert captured["db"] is not None
    assert captured["boot_client"] is not None
    assert captured["deleted"] is True


@pytest.mark.parametrize('scope', ['base', 'root'])
def test_kf_plugin_on_vault_closed_with_clear_deletes_plugin_db(qapp, tmp_path, monkeypatch, scope):
    # Keep a broken implementation inside the test directory too.
    monkeypatch.setattr(KFBaser, 'HeadDirPath', str(tmp_path))
    app = FakeApp(FakeHby(base='first' if scope == 'base' else '',
                          headDirPath=str(tmp_path / 'first') if scope == 'root' else str(tmp_path)))
    first = app.vault
    second = FakeVault(FakeHby(base='second' if scope == 'base' else '',
                               headDirPath=str(tmp_path / 'second') if scope == 'root' else str(tmp_path)))
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)
    try:
        for vault, aid in ((first, 'first-account'), (second, 'second-account')):
            app.vault = vault
            plugin.on_vault_opened(vault)
            assert plugin._db.get_account() is None
            record, _ = plugin._db.ensure_account()
            record.account_aid = aid
            plugin._db.pin_account(record)
            plugin.on_vault_closed(vault)

        app.vault = first
        plugin.on_vault_opened(first)
        assert plugin._db.get_account().account_aid == 'first-account'
        first_path = Path(plugin._db.path)
        plugin.on_vault_closed(first, clear=True)
        assert not first_path.exists()
        plugin.on_vault_opened(first)
        assert plugin._db.get_account() is None
        plugin.on_vault_closed(first, clear=True)

        app.vault = second
        plugin.on_vault_opened(second)
        assert plugin._db.get_account().account_aid == 'second-account'
    finally:
        plugin.on_vault_closed(app.vault, clear=True)


def test_kf_plugin_temporary_vault_removes_only_its_own_state(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(KFBaser, 'HeadDirPath', str(tmp_path))
    app = FakeApp(FakeHby(headDirPath=str(tmp_path)))
    persistent = app.vault
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)
    try:
        plugin.on_vault_opened(persistent)
        record, _ = plugin._db.ensure_account()
        record.account_aid = 'persistent-account'
        plugin._db.pin_account(record)
        plugin.on_vault_closed(persistent)

        app.vault = FakeVault(FakeHby(temp=True, headDirPath=str(tmp_path)))
        plugin.on_vault_opened(app.vault)
        assert plugin._db.get_account() is None
        plugin._db.ensure_account()
        temporary_path = Path(plugin._db.path)
        assert temporary_path.exists()
        plugin.on_vault_closed(app.vault)
        assert not temporary_path.exists()

        app.vault = persistent
        plugin.on_vault_opened(persistent)
        assert plugin._db.get_account().account_aid == 'persistent-account'
    finally:
        plugin.on_vault_closed(app.vault, clear=True)
