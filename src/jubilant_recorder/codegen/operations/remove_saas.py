"""Emit jubilant code for recorded ``juju.cli()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("remove-saas", ...)`` call.

    jubilant 1.10 has no client method for ``Application.
    DestroyConsumedApplications`` — ``juju.cli()`` is the public escape
    hatch. The correlator captures the consumed (SAAS) application name
    under ``app`` (see ``correlate.py``), matching the sibling
    ``DestroyApplication`` RPC's naming.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("remove_saas event missing app")

    return " " * indent + f'juju.cli("remove-saas", {app!r})'
