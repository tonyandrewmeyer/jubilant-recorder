from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("remove-offer", ...)`` call.

    jubilant 1.10 has no client method for ``ApplicationOffers.DestroyOffers``
    — ``juju.cli()`` is the public escape hatch. The correlator captures a
    list of offer URLs plus a ``force`` bool (see ``correlate.py``); both are
    forwarded straight through rather than collapsing to the single-URL,
    always-forced shape.
    """
    args = event["args"]
    offer_urls = args.get("offer_urls") or []
    if not offer_urls or not offer_urls[0]:
        raise ValueError("remove_offer event missing offer_urls")

    parts: list[str] = ['"remove-offer"']
    if args.get("force"):
        parts.append('"--force"')
    parts.extend(repr(url) for url in offer_urls)

    return " " * indent + f"juju.cli({', '.join(parts)})"
