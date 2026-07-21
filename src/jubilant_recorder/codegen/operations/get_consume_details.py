from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("show-offer", ...)`` call.

    jubilant 1.10 has no client method for ``ApplicationOffers.
    GetConsumeDetails`` — ``juju.cli()`` is the public escape hatch. The
    correlator captures a list of offer URLs (see ``correlate.py``); ``
    user_tag`` has no ``juju show-offer`` flag equivalent and is dropped,
    same as ``create_offer``'s ``model_tag``.
    """
    args = event["args"]
    offer_urls = args.get("offer_urls") or []
    if not offer_urls or not offer_urls[0]:
        raise ValueError("get_consume_details event missing offer_urls")

    parts = ['"show-offer"', '"--format=json"', *(repr(url) for url in offer_urls)]

    return " " * indent + f"juju.cli({', '.join(parts)})"
