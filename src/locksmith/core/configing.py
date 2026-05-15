import os
from dataclasses import dataclass
from enum import Enum

from keri import help

# TODO(KERI Foundation): Set your root AID here
DEFAULT_ROOT_AID=""
# TODO(KERI Foundation): Set your API AID here
DEFAULT_API_AID=""
# TODO(KERI Foundation): Set your root OOBI here
DEFAULT_ROOT_OOBI=""
# TODO(KERI Foundation): Set your API OOBI here
DEFAULT_API_OOBI=""
DEFAULT_UNPROTECTED_URL=""
DEFAULT_PROTECTED_URL=""

ENABLE_TURRET_BROWSER_PLUGIN = False

# TODO(KERI Foundation): Set your staging environment values here
STAGING_ROOT_AID=""
STAGING_API_AID=""
STAGING_ROOT_OOBI=""
STAGING_API_OOBI=""
STAGING_UNPROTECTED_URL=""
STAGING_PROTECTED_URL=""

# TODO(KERI Foundation): Set your production environment values here
PRODUCTION_ROOT_AID=""
PRODUCTION_API_AID=""
PRODUCTION_ROOT_OOBI=""
PRODUCTION_API_OOBI=""
PRODUCTION_UNPROTECTED_URL=""
PRODUCTION_PROTECTED_URL=""


logger = help.ogler.getLogger(__name__)

class Environments(Enum):
    PRODUCTION = 'production'
    STAGING = 'staging'
    DEVELOPMENT = 'development'


DEFAULT_PASSCODE = "DoB2-e4Rr-gVOr-Nb1Y-7yBl-gI3n-i4cB-gf07"  # Development only

@dataclass
class LocksmithConfig:
    _instance = None
    appName = 'Locksmith'
    # Flet assets directory for pictures, fonts, and the like.
    assetsDir: str = './assets'
    # The specific font to use from the fonts subdirectory within the assetsDir.
    font: str = 'fonts/SourceCodePro-Light.ttf'

    # TODO(KERI Foundation): Provider identifiers to connect with
    root_aid: str = DEFAULT_ROOT_AID
    api_aid: str = DEFAULT_API_AID

    # TODO(KERI Foundation): OOBIs of provider AIDs
    root_oobi: str = DEFAULT_ROOT_OOBI
    api_oobi: str = DEFAULT_API_OOBI

    # TODO(KERI Foundation): Provider API URLs
    unprotected_url: str = DEFAULT_UNPROTECTED_URL
    protected_url: str = DEFAULT_PROTECTED_URL

    # The environment the app is being run in.
    environment: Environments = Environments.DEVELOPMENT

    # Vault creation parameters (defaults for new vaults/identifiers)
    temp: bool = False  # Temporary datastore (data cleared on app exit)
    salt: str = "0123456789abcdef"  # Default salt for key derivation
    algo: str = "salty"  # Algorithm for key derivation
    tier: str = "low"  # Security tier for key derivation
    base: str = ""  # Base directory for KERI databases (will be set in __init__)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        environment = os.environ.get('LOCKSMITH_ENVIRONMENT')
        match environment:
            case Environments.PRODUCTION.value:
                environment = Environments.PRODUCTION
            case Environments.STAGING.value:
                environment = Environments.STAGING
            case Environments.DEVELOPMENT.value:
                environment = Environments.DEVELOPMENT
            case _:
                environment = Environments.DEVELOPMENT
        logger.info(f'Running in the {environment} environment')

        # Set defaults for each environment
        match environment:
            case Environments.PRODUCTION:
                root_aid = PRODUCTION_ROOT_AID
                api_aid = PRODUCTION_API_AID
                root_oobi = PRODUCTION_ROOT_OOBI
                api_oobi = PRODUCTION_API_OOBI
                unprotected_url = PRODUCTION_UNPROTECTED_URL
                protected_url = PRODUCTION_PROTECTED_URL

            case Environments.STAGING:
                root_aid = STAGING_ROOT_AID
                api_aid = STAGING_API_AID
                root_oobi = STAGING_ROOT_OOBI
                api_oobi = STAGING_API_OOBI
                unprotected_url = STAGING_UNPROTECTED_URL
                protected_url = STAGING_PROTECTED_URL

            case Environments.DEVELOPMENT:
                root_aid = DEFAULT_ROOT_AID
                api_aid = DEFAULT_API_AID
                root_oobi = DEFAULT_ROOT_OOBI
                api_oobi = DEFAULT_API_OOBI
                unprotected_url = DEFAULT_UNPROTECTED_URL
                protected_url = DEFAULT_PROTECTED_URL

        # Environment variable overrides if available
        root_aid = os.environ.get('LOCKSMITH_ROOT_AID', root_aid)
        api_aid = os.environ.get('LOCKSMITH_API_AID', api_aid)
        root_oobi = os.environ.get('LOCKSMITH_ROOT_OOBI', root_oobi)
        api_oobi = os.environ.get('LOCKSMITH_API_OOBI', api_oobi)
        unprotected_url = os.environ.get('LOCKSMITH_UNPROTECTED_URL', unprotected_url)
        protected_url = os.environ.get('LOCKSMITH_PROTECTED_URL', protected_url)

        self.root_aid = root_aid
        self.api_aid = api_aid
        self.root_oobi = root_oobi
        self.api_oobi = api_oobi
        self.unprotected_url = unprotected_url
        self.protected_url = protected_url
        self.environment = environment

        # Plugin-specific configuration keyed by plugin_id.
        # Plugins read their config from plugin_configs.get("plugin_id", {}).
        # Example: "your_plugin_id": {
        #     "root_aid": ,
        #     "api_aid": ,
        #     "root_oobi": ,
        #     "api_oobi": ,
        #     "unprotected_url": ,
        #     "protected_url": ,
        # }
        self.plugin_configs: dict[str, dict] = {}

    def resalt(self) -> str:
        """
        Generate a new random salt for key derivation.
        
        Returns:
            str: New 21-character random salt
        """
        from keri.core import signing
        self.salt = signing.Salter().qb64[2:23]
        return self.salt
