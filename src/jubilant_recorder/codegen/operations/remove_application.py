"""Emit jubilant code for recorded ``juju.remove_application()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.remove_application(...)`` call for this recorded event."""
    args = event["args"]
    app = args["app"]
    apps = app if isinstance(app, list) else [app]
    rendered = ", ".join(repr(a) for a in apps)
    return " " * indent + f"juju.remove_application({rendered})"
