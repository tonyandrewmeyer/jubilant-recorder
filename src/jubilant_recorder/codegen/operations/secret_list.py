"""Emit jubilant code for recorded ``juju.secrets()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.secrets(...)`` call.

    Corresponds to ``Secrets.ListSecrets`` from libjuju.  Rendered as an
    inspection-only call (no variable capture) since ``ListSecrets`` in a
    recorded session is typically informational.
    """
    args = event["args"]
    owner = args.get("owner")

    parts: list[str] = []
    if owner is not None:
        parts.append(f"owner={owner!r}")

    return " " * indent + f"juju.secrets({', '.join(parts)})"
