"""Emit jubilant code for recorded ``juju.cli("find-offers", ...)`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit a ``juju.cli("find-offers", ...)`` call.

    Corresponds to ``ApplicationOffers.FindApplicationOffers``.  jubilant has
    no client method for it, so this takes ``juju.cli()`` — the same route
    ``list_offers`` took for ``ListApplicationOffers``, which is this op's
    twin in every respect that matters here: a read, no client method, and
    correlator filter fields that do not map onto the CLI's flags.

    ``juju find-offers`` takes options only and no positionals (verified
    against juju 3.6.27), and its filtering flags do not correspond to the
    ``OfferFilter`` fields the correlator captures, so — exactly as in
    ``list_offers`` — the recorded ``model_name``/``application_name``/
    ``offer_name`` filters are **not** forwarded and the emitted call finds
    everything.  A generated test that needs the filter must add it by hand.
    """
    pad = " " * indent
    call = 'juju.cli("find-offers", "--format=json")'
    return f"{pad}{var_name} = {call}" if var_name else f"{pad}{call}"
