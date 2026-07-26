"""Emit jubilant code for recorded ``juju.remove_relation()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.remove_relation(...)`` call for this recorded event."""
    args = event["args"]
    a = args["app1_endpoint"]
    b = args["app2_endpoint"]
    return " " * indent + f"juju.remove_relation({a!r}, {b!r})"
