"""Emit ``juju.status()`` for a recorded ``juju status``.

Used only for statuses observed through the PATH shim, where there is no
model snapshot to summarise: the shim records the argv and execs the real
binary, so codegen knows the user asked for status but not what it said.
``juju.status()`` is the honest translation of "the user looked at the
model here" — it is the same call, it re-fetches at test time, and the
tagger's delta-derived assertions attach to it if the session carried any.

Statuses recorded by ``RecordingJuju`` or the libjuju tap keep their
existing rendering (a ``# juju status: …`` summary comment, or an
assertion) — those have a snapshot, so a bare call would say less than the
comment does.
"""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit a ``juju.status()`` call, optionally bound to a variable."""
    del event
    call = "juju.status()"
    if var_name:
        return " " * indent + f"{var_name} = {call}"
    return " " * indent + call
