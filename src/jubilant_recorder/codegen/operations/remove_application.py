"""Emit jubilant code for recorded ``juju.remove_application()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.remove_application(...)`` call for this recorded event."""
    args = event["args"]
    app = args["app"]
    apps = app if isinstance(app, list) else [app]
    parts = [repr(a) for a in apps]
    if args.get("destroy_storage"):
        parts.append("destroy_storage=True")
    if args.get("force"):
        parts.append("force=True")
    return " " * indent + f"juju.remove_application({', '.join(parts)})"
