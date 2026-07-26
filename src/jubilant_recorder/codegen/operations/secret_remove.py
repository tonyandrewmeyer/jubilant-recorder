"""Emit jubilant code for recorded ``juju.remove_secret()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.remove_secret(...)`` call for this recorded event."""
    args = event["args"]
    identifier = args.get("identifier") or ""
    revision = args.get("revision")

    parts: list[str] = [repr(identifier)]
    if revision is not None:
        parts.append(f"revision={revision!r}")

    return " " * indent + f"juju.remove_secret({', '.join(parts)})"
