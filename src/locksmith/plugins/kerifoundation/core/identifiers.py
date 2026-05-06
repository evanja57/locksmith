# -*- encoding: utf-8 -*-
"""
locksmith.plugins.kerifoundation.core.identifiers module

Shared helpers for iterating local identifiers.
"""
from __future__ import annotations

from typing import Any

import keri.app.habbing as keri_habbing


def iter_local_identifier_choices(app: Any):
    """Yield ``(alias, prefix)`` for each non-group local identifier.

    Skips namespaced entries and group habs so that only directly-owned
    individual identifiers are returned.
    """
    if not app or not hasattr(app, "vault") or not app.vault:
        return

    hby = app.vault.hby
    if not hby or not getattr(hby, "db", None):
        return

    for (ns, alias), prefix in hby.db.names.getTopItemIter(keys=()):
        if ns != "":
            continue

        hab = hby.habByName(alias)
        if hab is None or isinstance(hab, keri_habbing.GroupHab):
            continue

        yield alias, prefix
