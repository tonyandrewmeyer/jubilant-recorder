from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.cli("remove-offer", ...)` call.

    Correlator gives ``offer_urls`` (list of strings) and ``force`` (bool) —
    see `correlate.py`'s ``("ApplicationOffers", "DestroyOffers")`` unwrap.
    jubilant has no dedicated ``remove_offer()`` client method, so this
    shells out via the public `Juju.cli()` escape hatch.
    """
    args = event["args"]
    offer_urls = args.get("offer_urls") or []
    force = bool(args.get("force"))
    pad = " " * indent

    if not offer_urls:
        return pad + "# TODO: manual step: remove_offer with no offer_urls"

    parts: list[str] = ["remove-offer"]
    if force:
        parts.append("--force")
    parts.extend(offer_urls)
    rendered = ", ".join(repr(p) for p in parts)
    return pad + f"juju.cli({rendered})"
