from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit `juju.cli("show-offer", ...)` call(s).

    Correlator gives ``offer_urls`` (list of strings) — see `correlate.py`'s
    ``("ApplicationOffers", "GetConsumeDetails")`` unwrap. `juju show-offer`
    takes a single offer URL at a time, so a multi-URL event renders one
    call per URL rather than a single variadic call.
    """
    args = event["args"]
    offer_urls = args.get("offer_urls") or []
    pad = " " * indent

    if not offer_urls:
        return pad + "# TODO: manual step: get_consume_details with no offer_urls"

    lines = [pad + f'juju.cli("show-offer", "--format=json", {url!r})' for url in offer_urls]
    return "\n".join(lines)
