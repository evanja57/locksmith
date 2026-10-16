# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.page module

Main vault page container displayed when a vault is open.
Manages the navigation menu and sub-pages via a dynamic string-keyed registry.
"""
from typing import Any, TYPE_CHECKING

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QSizePolicy, QWidget
from keri import help

from locksmith.ui.toolkit.pages.base import BasePage
from locksmith.ui.vault.credentials.issued.list import IssuedCredentialsListPage
from locksmith.ui.vault.credentials.received.list import ReceivedCredentialsListPage
from locksmith.ui.vault.credentials.schema.list import SchemaListPage
from locksmith.ui.vault.credentials.activity import CredentialActivityPage
from locksmith.ui.vault.identifiers.list import IdentifierListPage
from locksmith.ui.vault.groups.list import GroupIdentifierListPage
from locksmith.ui.vault.menu import VaultNavMenu
from locksmith.ui.vault.notifications import NotificationsListPage
from locksmith.ui.vault.remotes.list import RemoteIdentifierListPage
from locksmith.ui.vault.settings.page import SettingsPage

if TYPE_CHECKING:
    from locksmith.ui.window import LocksmithWindow
    from locksmith.plugins.base import AccountProviderPlugin

logger = help.ogler.getLogger(__name__)


class VaultPage(BasePage):
    """
    Main vault page container displayed when a vault is open.

    Contains:
    - Left sidebar: VaultNavMenu for navigation
    - Right content area: QStackedWidget with sub-pages

    Pages are registered via string keys. Core pages are registered at init;
    plugin pages are registered dynamically via register_page().
    """

    def __init__(self, parent: "LocksmithWindow | None" = None):
        super().__init__(parent)

        self.vault_name: str | None = None
        self.main_window = parent
        assert self.main_window is not None, "VaultPage requires a parent window"
        self.app = self.main_window.app
        self._current_page_key: str | None = None

        # Ensure VaultPage fills the entire main_stack area
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Create main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create left navigation menu
        self.nav_menu = VaultNavMenu(self)
        main_layout.addWidget(self.nav_menu, 0)

        # Create stacked widget for sub-pages
        self.content_stack = QStackedWidget()
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_stack.setContentsMargins(0, 0, 0, 0)

        # Dynamic page registry: string key -> QWidget
        self._pages: dict[str, QWidget] = {}

        # Register core pages
        self._register_core_pages()

        # Track previous vault sub-page key for back navigation
        self._previous_vault_page_key = "identifiers"

        # Add content_stack with stretch factor to fill remaining space
        main_layout.addWidget(self.content_stack, 1)

        # Connect navigation menu signals
        self._connect_navigation()

        logger.info("VaultPage container initialized")

    def _register_core_pages(self):
        """Register the built-in core vault pages."""
        self.register_page("identifiers", IdentifierListPage(self))
        self.register_page("remotes", RemoteIdentifierListPage(self))
        self.register_page("groups", GroupIdentifierListPage(self))
        self.register_page("credentials", IssuedCredentialsListPage(self))
        self.register_page("settings", SettingsPage(self))
        self.register_page("issued_credentials", IssuedCredentialsListPage(self))
        self.register_page("received_credentials", ReceivedCredentialsListPage(self))
        self.register_page("credential_activity", CredentialActivityPage(self))
        self.register_page("schema", SchemaListPage(self))
        self.register_page("notifications", NotificationsListPage(self))

    def register_page(self, key: str, widget: QWidget) -> None:
        """Register a page widget under a string key.

        Args:
            key: Unique page key (e.g. 'identifiers', 'witnesses')
            widget: The page widget to register
        """
        if key in self._pages:
            logger.warning(f"Page key '{key}' already registered, replacing")
            old_widget = self._pages[key]
            self.content_stack.removeWidget(old_widget)
        self._pages[key] = widget
        self.content_stack.addWidget(widget)
        logger.debug(f"Registered page '{key}'")

    def _connect_navigation(self):
        """Connect navigation menu signals to internal sub-page navigation."""
        # Core vault navigation
        self.nav_menu.identifiers_clicked.connect(
            lambda: self._show_vault_page("identifiers")
        )
        self.nav_menu.remote_identifiers_clicked.connect(
            lambda: self._show_vault_page("remotes")
        )
        self.nav_menu.group_identifiers_clicked.connect(
            lambda: self._show_vault_page("groups")
        )
        self.nav_menu.credentials_clicked.connect(
            lambda: self._show_vault_page("credentials")
        )
        self.nav_menu.settings_clicked.connect(
            lambda: self._show_vault_page("settings")
        )

        # Plugin entry click handler
        self.nav_menu.plugin_section_clicked.connect(self._on_plugin_entry_clicked)

        # Credentials submenu navigation (unchanged)
        self.nav_menu.issued_credentials_clicked.connect(
            lambda: self._show_credentials_page("issued_credentials")
        )
        self.nav_menu.received_credentials_clicked.connect(
            lambda: self._show_credentials_page("received_credentials")
        )
        self.nav_menu.schema_clicked.connect(
            lambda: self._show_vault_page("schema")
        )
        self.nav_menu.activity_clicked.connect(
            lambda: self._show_credentials_page("credential_activity")
        )

        self._pages['credential_activity'].attention_changed.connect(
            self.nav_menu.activity_button.set_attention)

        # back_to_vault_from_credentials_clicked no longer emitted (menu emits identifiers_clicked directly)

        # Settings vault deletion
        settings_page = self._pages.get("settings")
        if settings_page and hasattr(settings_page, "vault_deleted"):
            settings_page.vault_deleted.connect(self._on_vault_deleted)

        logger.info("Navigation menu connected to internal sub-page navigation")

    # -------------------------------------------------------------------------
    # Page display methods
    # -------------------------------------------------------------------------

    def _show_page(self, key: str) -> None:
        """Show a page by its string key.

        Args:
            key: The page key to display
        """
        widget = self._pages.get(key)
        if widget is None:
            logger.error(f"No page registered for key '{key}'")
            return
        logger.info(f"Showing page: {key}")
        self._current_page_key = key
        self.content_stack.setCurrentWidget(widget)
        if self.app.vault:
            self.app.vault.signals.emit_doer_event("MenuDoer", "load", {"subpage": key})

    def _show_vault_page(self, key: str) -> None:
        """Show a vault page and track for back navigation."""
        self._previous_vault_page_key = key
        self._show_page(key)

    def _show_credentials_page(self, key: str) -> None:
        """Show a credentials sub-page."""
        logger.info(f"Showing credentials sub-page: {key}")
        self._previous_vault_page_key = key
        self._current_page_key = key
        widget = self._pages.get(key)
        if widget:
            self.content_stack.setCurrentWidget(widget)

    # -------------------------------------------------------------------------
    # Plugin entry handler
    # -------------------------------------------------------------------------

    def _on_plugin_entry_clicked(self, plugin_id: str):
        """Handle click on a plugin's entry button in the vault menu."""
        plugin = self.app.plugin_manager.get_plugin(plugin_id)
        if not plugin:
            logger.warning(f"Plugin '{plugin_id}' not found in plugin manager")
            return

        from locksmith.plugins.base import AccountProviderPlugin
        if isinstance(plugin, AccountProviderPlugin):
            if plugin.is_setup_complete(self.app.vault):
                self.nav_menu.push_plugin_menu(plugin_id)
                self._navigate_to_first_plugin_page(plugin_id)
            else:
                page_key, should_push_menu = plugin.get_setup_page(self.app.vault)
                if should_push_menu:
                    self.nav_menu.push_plugin_menu(plugin_id)
                self._show_page(page_key)
        else:
            self.nav_menu.push_plugin_menu(plugin_id)
            self._navigate_to_first_plugin_page(plugin_id)

    def _navigate_to_first_plugin_page(self, plugin_id: str) -> None:
        """Click the first nav button in the plugin menu, triggering highlight + navigation."""
        nav_btns = self.nav_menu._plugin_nav_buttons.get(plugin_id, [])
        if nav_btns:
            nav_btns[0].click()

    # -------------------------------------------------------------------------
    # Notifications
    # -------------------------------------------------------------------------

    def show_credential_activity(self, said, *, received=None, open_dialog=True):
        self.nav_menu.switch_to_credentials_menu()
        self.nav_menu.activity_button.click()
        self._pages['credential_activity'].show_exchange(said, received=received, open_dialog=open_dialog)

    def start_credential_exchange(self, action, *, schema=None, credential_said=None, received=False):
        from locksmith.ui.vault.credentials.start import StartExchangeDialog
        self._credential_exchange_dialog = StartExchangeDialog(
            self.app, self, action, schema=schema, credential_said=credential_said, received=received)
        self._credential_exchange_dialog.submitted.connect(
            lambda said: self.show_credential_activity(said, received=action == 'Apply', open_dialog=False))
        self._credential_exchange_dialog.open()

    def show_notifications(self):
        """Show notifications page - called from toolbar."""
        logger.info("Showing notifications page")
        self._show_page("notifications")
        notifications_page = self._pages.get("notifications")
        if notifications_page and hasattr(notifications_page, "on_show"):
            notifications_page.on_show()

    # -------------------------------------------------------------------------
    # Vault deletion
    # -------------------------------------------------------------------------

    def _on_vault_deleted(self, vault_name: str):
        """Handle vault deletion from settings page."""
        logger.info(f"Vault '{vault_name}' deleted, navigating to home")
        if self.main_window:
            self.main_window.vault_drawer._refresh_vault_list()
            self.main_window.nav_manager.clear_navigation_stack()
            from locksmith.ui.navigation import Pages
            self.main_window.nav_manager.navigate_to(Pages.HOME)

    # -------------------------------------------------------------------------
    # Toolbar / lifecycle
    # -------------------------------------------------------------------------

    def get_toolbar_config(self) -> dict[str, Any]:
        return {
            'show_vaults_button': False,
            'show_lock_button': True,
            'show_notifications_button': True,
            'show_settings_button': True,
        }

    def on_show(self, **params):
        super().on_show(**params)
        self.vault_name = params.get('vault_name', 'Unknown Vault')
        logger.info(f"VaultPage showing for vault: {self.vault_name}")

        # Reset nav menu to vault menu
        self.nav_menu.pop_to_vault_menu()

        # Update nav menu with vault name
        self.nav_menu.set_vault_name(self.vault_name)

        # Update all sub-pages with vault name
        for page in self._pages.values():
            if hasattr(page, "set_vault_name"):
                page.set_vault_name(self.vault_name)

        # Show Identifiers sub-page by default
        self._show_page("identifiers")

    def on_hide(self):
        super().on_hide()
        logger.info(f"VaultPage hiding for vault: {self.vault_name}")
