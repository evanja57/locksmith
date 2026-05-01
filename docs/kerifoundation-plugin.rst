KERI Foundation Plugin
======================

This document covers the Locksmith side of the KERI Foundation plugin.

The canonical server contract lives in the `kf-boot` README. This document keeps
the client-side obligations and the current transition state in one place.

Client Contract
---------------

The plugin is account-gated.

- no local KF account record means show onboarding
- a local record that is not onboarded means resume onboarding
- an onboarded record means show the normal KF pages

The plugin owns:

- the hidden ephemeral onboarding AID
- permanent account AID creation
- local key management
- witness registration and witness authentication flows
- witness and watcher OOBI resolution
- local witness auth state and local account state persistence

The plugin does not own:

- hosted witness or watcher allocation
- account approval state on the server
- hosted resource lifecycle on the server

Authenticated client-server traffic uses:

- CESR-over-HTTP over HTTPS/TLS
- KRAM for onboarding and approved-account requests

Auth principals:

- onboarding uses the hidden ephemeral onboarding AID
- approved-account management uses the permanent account AID

First-contact rule:

- before the first KRAM-authenticated onboarding request, the plugin must send
  or precede it with the ephemeral AID inception or keystate material so
  `kf-boot` can resolve sender state

Onboarding Responsibilities
---------------------------

1. Fetch bootstrap config from `kf-boot`.
2. Create the hidden ephemeral onboarding AID locally.
3. Start onboarding on the onboarding surface.
4. Receive the allocated witness list and required watcher details.
5. Create the permanent public account AID locally using that witness list.
6. Complete witness registration and local auth setup.
7. Resolve the watcher OOBI locally.
8. Complete onboarding.
9. Switch all later operations to the approved-account surface.

Current Transition
------------------

The repo still contains transitional raw witness-server configuration and UI
paths from the earlier server-oriented model.

Those paths are legacy. Do not expand them.

The target model is:

- onboarding and account management through `kf-boot`
- hosted witness and watcher rows fetched from `kf-boot`
- local witness auth state kept in the plugin where needed

Legacy witness provisioning code still reads environment variables such as
`KF_DEV_WITNESS_URL_*` and `KF_DEV_BOOT_URL_*`. That is transitional support,
not the long-term plugin contract.

Boot Surface Configuration
--------------------------

The Step 4/5/6 onboarding flow reads the public boot surfaces from plugin-local
defaults in `locksmith.plugins.kerifoundation.core.configing`.

Development is hardcoded to the local `kf-boot` stack at
`http://127.0.0.1:9723/onboarding` and `http://127.0.0.1:9723/account`.
Staging and production routes intentionally default to blank until the real
hosted URLs are available.

Temporary local-stack variants should be added as explicit configing values,
not `.env`-driven runtime overrides.

`/bootstrap/config` remains plain HTTPS+JSON. Authenticated onboarding and
approved-account requests are posted as CESR-over-HTTP with KRAM-authenticated
messages signed by the appropriate local AID.
