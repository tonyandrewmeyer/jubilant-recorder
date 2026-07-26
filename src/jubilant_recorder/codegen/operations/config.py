"""Emit jubilant code for recorded ``juju.config()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.config(...)`` call for this recorded event."""
    args = event["args"]
    app = args["app"]
    values = args["values"]
    return " " * indent + f"juju.config({app!r}, values={values!r})"
