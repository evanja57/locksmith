# -*- encoding: utf-8 -*-
"""
locksmith.core.apping module

This module contains main Locksmith Application class
"""
from pathlib import Path

from keri import help

from locksmith.core.configing import LocksmithConfig
from locksmith.core.vaulting import Vault
from locksmith.db.basing import LocksmithBaser
from locksmith.plugins.manager import PluginManager

logger = help.ogler.getLogger(__name__)


class LocksmithApplication:
    """
    Main application class for Locksmith.

    Manages application state including vaults, haberies, and KERI operations.
    """

    def __init__(self, config: LocksmithConfig | None = None):
        """
        Initialize the Locksmith application.

        Args:
            config: LocksmithConfig instance (will create one if not provided)
        """
        # Configuration
        if config is None:
            config = LocksmithConfig.get_instance()
        self.config = config

        # Application state
        self.name = None  # Current vault name
        self.hby = None  # Habery instance
        self.hab = None  # Current Hab (habitat/identifier)

        # Vault management
        self.vault: Vault | None = None  # Current Vault instance
        self.qtask = None  # QtTask running the vault
        self.rgy = None  # Regery instance

        # API client
        self._essr = None

        # Database
        self.db = None

        # Plugin manager
        self.plugin_manager = PluginManager(self)

    @property
    def protectedUrl(self) -> str:
        """Protected ESSR endpoint URL from config."""
        return self.config.protected_url

    @property
    def root(self) -> str:
        """API AID for ESSR encryption from config.
        
        Note: Despite the name 'root', this returns the API AID (delegated AID)
        which is the encryption target for ESSR. The loadbalancer can only sign
        as its delegated AID, not the parent root AID.
        """
        return self.config.api_aid

    @property
    def unprotectedUrl(self) -> str:
        """Unprotected API endpoint URL from config."""
        return self.config.unprotected_url

    def open_vault(self, name: str, vault, qtask):
        """
        Open a vault and store references.

        Args:
            name (str): Name of the vault
            vault: Vault instance
            qtask: QtTask instance running the vault
        """
        # Close existing vault if any
        self.close_vault()

        # Store new vault
        self.name = name
        self.vault = vault
        self.qtask = qtask
        self.hby = vault.hby
        self.rgy = vault.rgy

        # Give the vault a back-reference to the plugin manager
        vault.plugin_manager = self.plugin_manager

        # Notify plugins that vault is open
        self.plugin_manager.on_vault_opened(vault)

        # Resolve default OOBIs if they haven't been resolved yet
        self._resolve_default_oobis_if_needed()

    def close_vault(self):
        """Close the currently open vault."""
        if self.qtask is not None:
            logger.info(f"Closing vault: {self.name}")

            # Notify plugins before teardown
            if self.vault is not None:
                self.vault.closed = True
                self.plugin_manager.on_vault_closed(self.vault)

            # Request shutdown
            self.qtask.shutdown()

            # Cleanup
            self.qtask.cleanup()

            # Close dependent stores before the Habery.
            if self.vault is not None:
                self.vault.db.close()
                self.vault.rep.mbx.close()
                self.vault.notifier.noter.close()
            if self.rgy is not None:
                self.rgy.close()
            if self.hby is not None:
                self.hby.close()

            # Clear references
            self.qtask = None
            self.vault = None
            self.hby = None
            self.rgy = None
            self.hab = None
            self.name = None

            logger.info("Vault closed")

    def delete_vault(self, vault_name: str) -> bool:
        """
        Delete a vault and all its database files from disk.

        Uses KERI's built-in close(clear=True) method on each database instance
        to properly delete files. This is the correct KERI pattern since each 
        class knows its own path.

        Args:
            vault_name: Name of the vault to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        # Verify this is the currently open vault
        if self.name != vault_name:
            logger.error(f"Cannot delete vault '{vault_name}' - it is not the currently open vault")
            return False

        if self.vault is None or self.hby is None:
            logger.error(f"Cannot delete vault '{vault_name}' - vault is not properly open")
            return False

        logger.info(f"Deleting vault '{vault_name}' using close(clear=True)")

        try:
            self.plugin_manager.prepare_vault_deletion(self.vault)
        except Exception:
            logger.exception(f"Aborting vault deletion for '{vault_name}' during plugin cleanup")
            return False

        # First, shutdown the QtTask to stop all doers
        self.vault.closed = True
        if self.qtask is not None:
            self.qtask.shutdown()
            self.qtask.cleanup()
            self.qtask = None

        self.plugin_manager.on_vault_closed(self.vault, clear=True)

        # Close dependent stores before the Habery. Its close method leaves the
        # Configer file in place, so clear that file explicitly.
        databases_to_clear = [
            ('LocksmithBaser', self.vault.db),
            ('Mailboxer', self.vault.rep.mbx),
            ('Noter', self.vault.notifier.noter),
            ('ACDC registry', self.rgy.baser),
            ('HaberyConfiger', self.hby.cf),
            ('Habery', self.hby),
        ]

        # Close each with clear=True to delete files
        deleted_count = 0
        error_count = 0

        for name, db in databases_to_clear:
            try:
                logger.info(f"Closing {name} with clear=True")
                db.close(clear=True)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to close/clear {name}: {e}")
                error_count += 1

        # Clear references
        self.vault = None
        self.hby = None
        self.rgy = None
        self.hab = None
        self.name = None

        if error_count == 0:
            logger.info(f"Vault '{vault_name}' deleted successfully")
            return True
        else:
            logger.error(f"Vault '{vault_name}' deletion had {error_count} errors")
            return False

    @property
    def is_vault_open(self) -> bool:
        """
        Check if a vault is currently open.

        Returns:
            bool: True if a vault is open, False otherwise
        """
        return self.vault is not None and self.qtask is not None

    def _resolve_default_oobis_if_needed(self):
        """
        Check if default OOBIs need to be resolved and resolve them if necessary.

        This is called after opening a vault to ensure default OOBIs (root and API)
        are resolved on first open after vault creation.

        TODO(KERI Foundation): Populate root_aid, api_aid, root_oobi, api_oobi in configing.py.
        This will no-op until those values are set.
        """
        if self.hby is None:
            return

        from locksmith.core import remoting

        # Check if root OOBI needs resolution
        if hasattr(self.config, 'root_oobi') and self.config.root_oobi:
            if not self.hby.db.roobi.get(keys=(self.config.root_oobi,)):
                logger.info(f"Resolving default root OOBI: {self.config.root_oobi}")
                remoting.resolve_oobi_sync(
                    app=self,
                    pre=self.config.root_aid,
                    oobi=self.config.root_oobi,
                    alias="Root",
                )

        # Check if API OOBI needs resolution
        if hasattr(self.config, 'api_oobi') and self.config.api_oobi:
            if not self.hby.db.roobi.get(keys=(self.config.api_oobi,)):
                logger.info(f"Resolving default API OOBI: {self.config.api_oobi}")
                remoting.resolve_oobi_sync(
                    app=self,
                    pre=self.config.api_aid,
                    oobi=self.config.api_oobi,
                    alias="API",
                )

    def environments(self):
        """
        List Locksmith vault environments.

        Uses Locksmith's runtime database as the source of truth so generic KERI
        environments such as witnesses do not appear in the vault drawer.

        Returns:
            list: List of vault names
        """
        base_path = Path(self.config.base) if self.config.base else Path()
        candidates = (
            Path("/usr/local/var") / Path(LocksmithBaser.TailDirPath) / base_path,
            Path.home() / Path(LocksmithBaser.AltTailDirPath) / base_path,
        )
        rt_home = next((path for path in candidates if path.is_dir()), None)
        if rt_home is None:
            return []

        return sorted(
            path.name
            for path in rt_home.iterdir()
            if (path / 'data.mdb').is_file()
        )
        
