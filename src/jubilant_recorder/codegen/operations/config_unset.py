"""Emit jubilant code for recorded ``juju.cli()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("config", ..., "--reset", ...)`` call.

    jubilant 1.10 has no client method for
    ``Application.UnsetApplicationsConfig`` — ``juju.cli()`` is the public
    escape hatch. ``options`` (the keys to reset to their charm defaults)
    renders as a single comma-joined ``--reset`` value, matching how
    ``juju config --reset`` itself takes multiple keys.
    """
    args = event["args"]
    app = args.get("app") or ""
    options = args.get("options") or []
    if not app:
        raise ValueError("config_unset event missing app")
    if not options:
        raise ValueError("config_unset event missing options")

    parts = ['"config"', repr(app), '"--reset"', repr(",".join(options))]
    return " " * indent + f"juju.cli({', '.join(parts)})"
