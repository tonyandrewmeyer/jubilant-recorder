"""Emit jubilant code for recorded ``juju.scale()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.scale(...)`` call for this recorded event."""
    args = event["args"]
    return " " * indent + f"juju.scale({args['app']!r}, units={args['units']})"
