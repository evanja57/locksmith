.. _plugin-authoring:

Locksmith Plugin Interface
==========================

Locksmith loads provider integrations as Python plugins. A plugin can register
wallet pages, talk to services that operate witnesses or watchers, and keep provider-specific state.

The ownership boundary is:

* Locksmith owns the wallet, the open vault, and the shared runtime.
* The plugin owns its pages, provider data, and service calls.
* Keripy is used to manage keys, events, signatures, receipts, and KERI message parsing.
* The remote provider owns accounts and any hosted witnesses or watchers.

The bundled KERI Foundation plugin is the working example used throughout this
guide. It onboards an account, registers witnesses, connects a watcher, and
keeps the provider state needed to manage those services.

This document describes the interface implemented in the current Locksmith
source. A third-party provider can use a different service contract, account
model, and deployment architecture.

Distribution and Trust
----------------------

Locksmith does not have a plugin store or an install button. A provider that
wants its plugin included in the supported open source wallet can open a pull
request. A provider can also maintain a Locksmith fork with its plugin built
in.

Plugins are discovered through standard Python package entry points. Entry
points only provide discovery. A loaded plugin is trusted Python code running
inside the wallet process. It can access the open vault, the network, local
databases, and Qt widgets. Plugin code should receive the same review as wallet
core code.

There is currently no sandbox, permission system, or dependency isolation for
plugins.

KERI Terms Used by Plugins
--------------------------

Keripy owns the protocol implementation. Plugins should use Keripy APIs for
event creation, signing, parsing, key state, receipts, and OOBI resolution.
The following terms appear in the plugin interface and reference
implementation.

**AID**
   An autonomic identifier. It is a cryptographic identifier whose key history
   can be verified. AIDs appear in code as values such as ``hab.pre`` and
   witness EIDs.

**Hab**
   Keripy's local controller for one AID. A Hab creates and signs events. Its
   current key state is available through ``hab.kever``.

**Habery**
   The collection of local identifiers in the open vault. The current Habery
   is ``vault.hby``. Resolve an AID prefix with
   ``vault.hby.habByPre(prefix)`` to find its current Hab.

**KEL**
   The Key Event Log for an AID. It records inception, rotation, and interaction
   events in order. Keripy creates and verifies these events.

**Witness**
   A service that receives controller events and returns receipts. Witnesses
   are part of an AID's key state, so changing the witness set requires a KERI
   rotation.

**Watcher**
   A service that observes and answers questions about KERI key state. A
   watcher is not a witness and does not play the same role.

**OOBI**
   Out-of-band introduction data. An OOBI tells the wallet how to discover an
   AID and its endpoints. Locksmith already has helpers for resolving OOBIs.

**EXN**
   A signed KERI exchange message used by application protocols. The KERI
   Foundation plugin uses EXNs for authenticated account and onboarding calls.
   Keripy builds and signs them.

**KRAM**
   KERI request authentication. Before a service can verify a signed request,
   it needs the sender's key state. The reference plugin solves this first
   contact problem by introducing a temporary onboarding AID before sending
   the first authenticated request.

HIO is the other relevant runtime dependency:

**HIO doer**
   A cooperative task. Locksmith advances HIO doers while the Qt app is
   running. A doer must give control back promptly so the rest of the wallet
   can keep moving.

Where the Plugin Interface Lives
--------------------------------

The main interface files are:

``src/locksmith/plugins/base.py``
   The plugin classes and lifecycle methods.

``src/locksmith/plugins/manager.py``
   Plugin discovery and calls from Locksmith into each plugin.

``src/locksmith/core/apping.py``
   Vault open, close, and deletion ordering.

``src/locksmith/ui/vault/page.py``
   Plugin page registration, navigation, and account setup checks.

``src/locksmith/plugins/kerifoundation/``
   The complete bundled example.

``base.py`` defines the callable surface. ``manager.py`` shows which hooks
actually have host call sites.

Discovery and Initialization
----------------------------

Register the plugin class in ``pyproject.toml``:

.. code-block:: toml

   [project.entry-points."locksmith.plugins"]
   example_provider = "locksmith.plugins.example.plugin:ExampleProviderPlugin"

Use a unique lowercase name. The entry-point name should match ``plugin_id``.
You will need to ``pip install -e .`` after registering a plugin in ``pyproject.toml``.
When Locksmith starts, it does the following for each entry point:

#. Loads the registered class.
#. Creates it with no constructor arguments.
#. Calls ``initialize(app)``.
#. Registers its pages and menu widgets.
#. Keeps the instance under its ``plugin_id``.

This happens before a vault is open. The constructor and ``initialize`` must
work when ``app.vault`` and ``app.hby`` are unavailable. They can build
widgets, connect signals, and create clients that do not depend on a particular
vault.

If a plugin fails during startup, Locksmith logs the error and continues. The
manager does not roll back partially registered UI. Initialization should stay
small and deterministic.

Lifecycle
---------

The normal lifecycle is:

#. Locksmith starts and calls ``initialize(app)`` once.
#. A user opens a vault.
#. Locksmith calls ``on_vault_opened(vault)``.
#. The plugin opens its per-vault data and connects its pages to that vault.
#. The user works with the plugin.
#. Locksmith calls ``on_vault_closed(vault, clear=False)`` before closing the
   wallet databases.

The same plugin object may see several vaults during its lifetime. A Hab,
database handle, or task from the previous vault must not survive a vault
switch. Resolve current vault objects in ``on_vault_opened`` and detach them in
``on_vault_closed``.

Plugin databases must use the vault's base, storage root and temporary flag,
not only its display name. The Foundation plugin passes ``hby.base``,
``hby.db.headDirPath`` and ``hby.temp`` to its database. It removes temporary
data on close. Persistent data stays until the owning vault is deleted.

Vault deletion adds one important step. Locksmith first calls
``prepare_vault_deletion(vault)`` while identifiers and databases are still
available. A plugin can use that hook to cancel or remove remote resources. If
it raises an exception, Locksmith stops the deletion so the user is not left
with hosted resources that can no longer be managed locally.

After preparation succeeds, Locksmith stops the runtime, closes each plugin
with ``clear=True``, and clears the wallet data.

PluginBase Contract
-------------------

``PluginBase`` defines seven required members:

.. list-table:: Required plugin methods
   :header-rows: 1
   :widths: 27 73

   * - Member
     - What it does
   * - ``plugin_id``
     - Returns a stable, unique name for the plugin.
   * - ``initialize(app)``
     - Builds reusable UI and stores the application reference. No vault is
       open yet.
   * - ``on_vault_opened(vault)``
     - Opens per-vault state and gives the current vault to pages and services.
   * - ``on_vault_closed(vault, clear=False)``
     - Stops work, removes vault references, and closes plugin data. When
       ``clear`` is true, it also removes durable plugin data for that vault.
   * - ``get_menu_entry()``
     - Returns the button shown in Locksmith's main sidebar.
   * - ``get_menu_section()``
     - Returns the plugin submenu widgets.
   * - ``get_pages()``
     - Returns a mapping from page names to Qt widgets.

The following optional hooks have host call sites:

``prepare_vault_deletion(vault)``
   Clean up provider resources before local vault deletion. Raising an error
   stops the deletion.

``get_doers()``
   Return long-running HIO doers that should join the vault scheduler.

``get_witness_batches(vault, hab_pre)``
   Return witness groups that share authentication. Locksmith combines and
   deduplicates groups from every plugin.

``update_witness_state(vault, wit_eid)``
   Record provider state after Locksmith rotates onto a witness.

``update_witness_state_after_auth(vault, wit_eid)``
   Record provider state after witness authentication.

``after_identifier_authenticated(vault, hab)``
   Run provider work after Locksmith authenticates an identifier or group.

``get_witness_state`` is defined on ``PluginBase`` and ``on_account_created`` is
defined on ``AccountProviderPlugin``. Neither has a current host call site, so a
plugin cannot depend on either one being called.

``IdentifierUploadProviderPlugin``, ``WitnessProviderPlugin``,
``WatcherProviderPlugin``, and ``CredentialProviderPlugin`` are marker types.
They do not add dispatched methods. ``AccountProviderPlugin`` is the exception
because it adds setup gating.

Account Setup Gating
--------------------

Use ``AccountProviderPlugin`` when provider setup must finish before the normal
plugin pages are available. It adds two methods:

``is_setup_complete(vault)``
   Return whether this vault has completed setup.

``get_setup_page(vault)``
   Return ``(page_key, should_push_menu)``. The page key must also be returned
   by ``get_pages()``.

Locksmith checks these methods when the main plugin entry is selected. A
configured vault enters the normal submenu. An unconfigured vault goes to the
setup page. The KERI Foundation plugin considers setup complete when its local
account record reaches ``onboarded``.

Pages and Navigation
--------------------

All plugin and wallet pages share one registry. Prefix page keys with
``plugin_id``:

.. code-block:: text

   plugin_id: example_provider
   page keys: example_provider_onboarding
              example_provider_witnesses
              example_provider_watchers
   database:  example_provider_<vault name>

The current host does not reject duplicate plugin IDs or page keys. A later
registration can replace an earlier one, which is another reason to namespace
everything.

Plugins currently navigate through a private host method:

.. code-block:: python

   def _navigate(self, page_key: str) -> None:
       vault_page = getattr(self._app, "_vault_page", None)
       if vault_page is not None:
           vault_page._show_page(page_key)

Keep this call behind one plugin helper so a future public navigation API only
requires one local change.

If a page needs to refresh whenever it appears, expose an ``on_show`` method
and call it from the plugin navigation handler. Locksmith does not
automatically call ``on_show`` for plugin pages.

Minimal Plugin
--------------

The following example registers one page and binds it to the current vault. It
does not include provider storage or remote service calls.

.. code-block:: python

   from PySide6.QtGui import QIcon
   from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

   from locksmith.plugins import PluginBase
   from locksmith.ui.toolkit.widgets.buttons import BackButton
   from locksmith.ui.vault.menu import MenuButton


   class ProviderPage(QWidget):
       def __init__(self):
           super().__init__()
           self._vault = None

           layout = QVBoxLayout(self)
           layout.addWidget(QLabel("Provider"))

       def set_vault(self, vault) -> None:
           self._vault = vault


   class ExampleProviderPlugin(PluginBase):
       def __init__(self):
           self._app = None
           self._page = None

       @property
       def plugin_id(self) -> str:
           return "example_provider"

       def initialize(self, app) -> None:
           self._app = app
           self._page = ProviderPage()

       def on_vault_opened(self, vault) -> None:
           self._page.set_vault(vault)

       def on_vault_closed(self, vault, *, clear=False) -> None:
           self._page.set_vault(None)

       def get_menu_entry(self) -> MenuButton:
           return MenuButton(icon=QIcon(), label="Example Provider")

       def get_menu_section(self) -> list[QWidget]:
           back = BackButton(dark_mode=False)
           overview = MenuButton(icon=QIcon(), label="Overview")
           overview.clicked.connect(
               lambda: self._navigate("example_provider_overview")
           )
           return [back, overview]

       def get_pages(self) -> dict[str, QWidget]:
           return {"example_provider_overview": self._page}

       def _navigate(self, page_key: str) -> None:
           vault_page = getattr(self._app, "_vault_page", None)
           if vault_page is not None:
               vault_page._show_page(page_key)

Widgets should collect input and show results. Service calls, database work,
and multi-step KERI operations belong in separate service objects. The bundled
plugin follows this split.

Qt, Asyncio, and HIO
--------------------

Locksmith runs Qt and Python's asyncio loop together with qasync. A Qt signal
can start an asyncio task, and the completed task can update Qt widgets on the
same thread. Blocking HTTP, filesystem, or CPU work on that thread freezes the
wallet.

For work started by a UI action:

* Start one tracked ``asyncio.Task``.
* Run blocking libraries such as ``requests`` with ``asyncio.to_thread``.
* Reject a second click while the same operation is already running.
* Capture the vault and database that own the task.
* Cancel or finish the task when that vault closes.

Use ``get_doers()`` for long-lived cooperative work that belongs to the vault
scheduler. A plugin should not create a private HIO scheduler for ordinary
background work.

Cancelling ``asyncio.to_thread`` does not stop work already running in the
thread. If that work may create a remote resource, the plugin must observe the
late result and run compensating cleanup. The KF witness registrar implements
this pattern.

State Ownership
---------------

A provider plugin works with three kinds of state:

**Wallet and KERI state**
   AIDs, keys, KELs, witness key state, OOBIs, and contacts belong to the open
   Locksmith vault and Keripy stores.

**Plugin state**
   Provider account status, remote resource IDs, unfinished operation IDs, and
   cleanup records belong in a per-vault plugin database.

**Remote service state**
   Account approval, hosted resources, quotas, and billing belong to the
   provider service.

The remote service is not the source of truth for an AID's KERI key state. The
plugin should keep enough provider data locally to resume or clean up
unfinished work. Keripy remains authoritative for local KERI state.

Every operation should make the following explicit:

* Which vault owns it?
* Which local AID signs it?
* Which remote AID should answer?
* What is saved after each step?
* Can it resume after a restart?
* What must be cleaned up if the last step fails?

KERI Foundation Reference Implementation
----------------------------------------

The bundled plugin is the current reference implementation. Its modules are
split by responsibility:

``plugins/kerifoundation/plugin.py``
   Implements the Locksmith plugin interface and owns navigation and task
   cleanup.

``plugins/kerifoundation/onboarding/page.py``
   Collects the user's onboarding choices.

``plugins/kerifoundation/onboarding/service.py``
   Runs the onboarding steps and talks to the KF boot service.

``plugins/kerifoundation/witnesses/provision.py``
   Registers witnesses, resolves OOBIs, saves authentication state, and cleans
   up partial work.

``plugins/kerifoundation/watchers/list.py``
   Loads hosted watchers without freezing the UI.

``plugins/kerifoundation/db/basing.py``
   Stores KF account, witness, recovery, and attached-identifier records for
   each vault.

Vault Binding
~~~~~~~~~~~~~

``KeriFoundationPlugin.initialize`` creates the pages, the boot-service
client, and the Qt signal connections. It leaves vault-specific fields empty.

When a vault opens, the plugin opens its own database for that vault, connects
the database and client to its pages, and restores the saved boot-service AID.
When the vault closes, it cancels background work, removes those references
from every page, and closes the plugin database.

This prevents pages and late async results from writing through stale vault or
database references after a vault switch.

Onboarding Flow
~~~~~~~~~~~~~~~

The onboarding flow is:

#. The wallet fetches the provider's available witness and watcher options.
#. It creates the user's permanent account AID and a temporary ephemeral onboarding AID.
#. It introduces the temporary AID so the service can verify the first signed
   request.
#. The service allocates witnesses and a watcher.
#. The wallet registers the account AID with those witnesses and resolves their
   OOBIs.
#. The wallet rotates the account AID onto the new witness set and collects
   receipts when needed.
#. It resolves the watcher OOBI and introduces the account and its witnesses.
#. It tells the service that onboarding is complete, marks the local account
   as onboarded, and removes the temporary AID.

The service persists checkpoints before irreversible work. If the app closes
or a call fails, it can resume the session or clean up local and remote state.

Witnesses and Watchers
~~~~~~~~~~~~~~~~~~~~~~

The KF plugin has two witness flows. Account onboarding uses witnesses
allocated by the provider. After onboarding, another local AID can be attached
to the account and provision witnesses through the existing KF configuration.

The second flow still contains older direct witness-server configuration. It
shows registration, rollback, TOTP state, OOBI resolution, and rotation. A new
provider should normally use allocations returned by its service instead of
copying KF environment variables.

``get_witness_batches`` lets the plugin tell Locksmith which witnesses share
authentication. Locksmith combines the batches from every provider.

The working watcher flow happens during onboarding. The plugin resolves the
allocated watcher's OOBI and introduces the account AID and its witnesses. The
Watchers page can then list hosted watchers for that account.

``WatcherRegisterPage`` is currently a placeholder. Manual watcher
registration is not part of the working example yet.

Transport Boundary
~~~~~~~~~~~~~~~~~~

The KF client uses ordinary JSON for health checks and bootstrap
configuration. Account and onboarding actions use signed KERI exchange
messages with their CESR attachments.

``KFBootClient`` asks Keripy to create and sign those exchange messages, sends
them, and checks the route, sender, and message type in the reply. It also makes
sure the remote service has the account AID's current key state before asking
the service to verify an account request. ``kf-boot`` allocates hosted witnesses
and watchers and stores provider account and resource metadata. The witness and
watcher services remain responsible for their KERI protocol state.

A provider may use different routes, payloads, and account rules. The security
properties should remain explicit: signing AID, expected remote AID, sender key
state, reply verification, timeouts, and recovery or cleanup for partial work.

Implementation Order
--------------------

A narrow implementation order is:

#. Pick one provider namespace for the plugin ID, page names, database, and
   configuration.
#. Add the package and its ``pyproject.toml`` entry point.
#. Start with one page and implement the seven required methods.
#. Open and close a per-vault database correctly.
#. Put the provider HTTP contract in a service client, away from the widgets.
#. Add one complete user flow, including cancellation and cleanup.
#. Use Keripy and Locksmith helpers for KERI events, receipts, and OOBIs.
#. Add account gating only if the provider needs onboarding.
#. Add witness or watcher hooks only when the flow needs them.
#. Test a successful run, a failed remote call, cancellation, and vault close.

Complete one end-to-end flow before scaffolding additional provider features.

Testing the Plugin
------------------

The reference tests cover the main interface boundaries:

``tests/test_plugin_manager.py``
   Vault-open dispatch, doer scheduling, and witness batch merging.

``tests/test_kerifoundation_account_gating.py``
   Setup gating, vault switching, async task ownership, and database close.

``tests/test_kerifoundation_onboarding_service.py``
   Onboarding, restart and cancellation behavior, KERI reply checks, witness
   rotation, and watcher OOBIs.

``tests/test_kerifoundation_witnesses.py``
   Witness and watcher data, partial failure, cancellation, and cleanup.

``tests/test_kerifoundation_vault_deletion.py``
   Remote cleanup before local vault deletion.

Use fake provider HTTP responses in unit tests. Use real Keripy objects where
signing, rotation, receipts, OOBI resolution, or parsing matter. Tests should
cover observable behavior, especially recovery after partial failure. Tests
that only assert helper calls do not protect the plugin contract.

Before proposing a plugin for inclusion, run its focused tests, build the
documentation, and run a local end-to-end test against the real provider
services.

AI Agent Context
----------------

An AI task should include the exact Locksmith revision and provider contract.
It should read ``base.py``, ``manager.py``, the KF plugin, and the relevant
tests before editing.

Include these constraints:

* Use Keripy to build KERI and CESR messages.
* Keep ordinary provider API data separate from signed KERI messages.
* Never block the Qt event loop.
* Tie every background task to one vault and one cleanup path.
* Treat the current source and tests as authoritative.
* Keep changes small and test failure and cancellation, not only success.

For every authenticated operation, the task should identify the signing AID,
expected remote AID, persisted state, and rollback path. Missing any of those
usually means the flow is not understood yet.

Related Documentation
---------------------

See :doc:`kerifoundation-plugin` for the current KERI Foundation client and
boot-service details. That page describes the KF provider contract. This guide
describes the Locksmith plugin interface that another provider can use.
