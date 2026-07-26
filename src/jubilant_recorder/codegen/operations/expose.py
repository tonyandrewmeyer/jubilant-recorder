"""Emit jubilant code for recorded ``juju.cli()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("expose", ...)`` call.

    jubilant 1.10 has no client method for ``Application.Expose`` —
    ``juju.cli()`` is the public escape hatch. Per-endpoint exposure
    (``exposed_endpoints`` restricting exposure to specific spaces/CIDRs)
    has no single-call ``juju expose`` equivalent — the CLI takes one
    ``--endpoints``/``--to-spaces``/``--to-cidrs`` set per invocation, so a
    multi-endpoint restriction can't be collapsed into one line. Flagged
    with a ``# TODO`` rather than silently dropped.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("expose event missing app")

    pad = " " * indent
    call = f'{pad}juju.cli("expose", {app!r})'

    exposed_endpoints = args.get("exposed_endpoints") or {}
    if exposed_endpoints:
        endpoints = ", ".join(sorted(exposed_endpoints))
        todo = (
            f"{pad}# TODO: Expose restricted to specific spaces/CIDRs on "
            f"endpoint(s) {endpoints} — not representable in one `juju expose` call"
        )
        return f"{todo}\n{call}"
    return call
