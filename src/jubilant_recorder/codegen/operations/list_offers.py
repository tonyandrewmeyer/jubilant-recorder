from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.cli("offers", ...)` call.

    The correlator's `ApplicationOffers.ListApplicationOffers` unwrap
    (`correlate.py`) only ever surfaces the first `OfferFilter` as a flat
    ``model_name``/``application_name``/``offer_name`` dict — it does not
    hand back a list of filter terms. A bare ``offer_name`` filter maps
    cleanly onto `juju offers`'s single positional filter-term argument;
    anything involving ``model_name``/``application_name`` is too
    structured to render as a single CLI term without guessing, so it
    falls back to a manual-step comment instead.
    """
    args = event["args"]
    model_name = args.get("model_name")
    application_name = args.get("application_name")
    offer_name = args.get("offer_name")
    pad = " " * indent

    if not model_name and not application_name and not offer_name:
        return pad + 'juju.cli("offers", "--format=json")'
    if offer_name and not model_name and not application_name:
        return pad + f'juju.cli("offers", "--format=json", {offer_name!r})'
    return pad + "# TODO: manual step: list_offers with complex filter"
