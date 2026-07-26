"""Emit jubilant code for recorded ``juju.offer()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.offer(...)` call.

    ``model_tag`` (per CMR-FACADE-RECON.md §2.1) is a UUID on the wire — the
    recorder has no way to resolve it back to a model name, so it's dropped
    rather than fabricated into a dotted ``model.app`` form. This assumes the
    offer was made against the model being recorded; a cross-model offer
    (offering from a *different* model than the recording's own) will replay
    against the wrong model until model_tag resolution lands (see the open
    question in CMR-FACADE-RECON.md §4).
    """
    args = event["args"]
    app = args["app"]
    endpoints = args.get("endpoints") or {}
    endpoint_names = list(endpoints.keys()) if isinstance(endpoints, dict) else list(endpoints)

    parts: list[str] = [repr(app)]
    if len(endpoint_names) == 1:
        parts.append(f"endpoint={endpoint_names[0]!r}")
    else:
        parts.append(f"endpoint={endpoint_names!r}")
    offer_name = args.get("offer_name")
    if offer_name and offer_name != app:
        parts.append(f"name={offer_name!r}")

    return " " * indent + f"juju.offer({', '.join(parts)})"
