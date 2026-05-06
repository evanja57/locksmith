from types import SimpleNamespace

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
    def __init__(self, name="test-vault", *, habs_by_pre=None, habs_by_name=None):
        self.name = name
        self._habs_by_pre = habs_by_pre or {}
        self._habs_by_name = habs_by_name or {}
        self.db = SimpleNamespace(names=SimpleNamespace(getTopItemIter=lambda keys=(): iter(())))

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
    app = FakeApp(FakeHby())
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.KFBaser",
        lambda name, reopen=True: KFBaser(
            name=name,
            headDirPath=str(tmp_path),
            reopen=reopen,
        ),
    )

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


def test_kf_plugin_on_vault_closed_with_clear_deletes_plugin_db(qapp, tmp_path, monkeypatch):
    app = FakeApp(FakeHby())
    plugin = KeriFoundationPlugin()
    plugin.initialize(app)

    monkeypatch.setattr(
        "locksmith.plugins.kerifoundation.plugin.KFBaser",
        lambda name, reopen=True: KFBaser(
            name=name,
            headDirPath=str(tmp_path),
            reopen=reopen,
        ),
    )

    plugin.on_vault_opened(app.vault)
    plugin._db.ensure_account()

    plugin.on_vault_closed(app.vault, clear=True)

    reopened = KFBaser(
        name="kf_test-vault",
        headDirPath=str(tmp_path),
        reopen=True,
    )
    try:
        assert reopened.get_account() is None
    finally:
        reopened.close(clear=True)
