"""Emit jubilant code for recorded ``juju.grant_secret()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.grant_secret(...)`` call for this recorded event."""
    args = event["args"]
    identifier = args.get("identifier") or ""
    app = args.get("app") or ""
    return " " * indent + f"juju.grant_secret({identifier!r}, {app!r})"
