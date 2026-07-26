"""Emit jubilant code for recorded ``juju.cli()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("unexpose", ...)`` call.

    jubilant 1.10 has no client method for ``Application.Unexpose`` —
    ``juju.cli()`` is the public escape hatch. Unlike ``Expose``,
    ``juju unexpose`` fully represents a per-endpoint restriction via a
    single ``--endpoints`` flag, so ``exposed_endpoints`` forwards cleanly.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("unexpose event missing app")

    parts: list[str] = ['"unexpose"', repr(app)]
    exposed_endpoints = args.get("exposed_endpoints") or []
    if exposed_endpoints:
        parts.extend(['"--endpoints"', repr(",".join(exposed_endpoints))])

    return " " * indent + f"juju.cli({', '.join(parts)})"
