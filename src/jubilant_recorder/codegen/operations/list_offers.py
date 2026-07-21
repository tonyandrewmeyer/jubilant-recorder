from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit a ``juju.cli("offers", ...)`` call.

    jubilant 1.10 has no client method for ``ApplicationOffers.
    ListApplicationOffers`` — ``juju.cli()`` is the public escape hatch
    (``jubilant/_juju.py:527``; already used by jubilant's own
    ``bootstrap()``). The correlator's filter fields (model/application/offer
    name — see ``correlate.py``) don't map onto ``juju offers`` flags, so
    they're not forwarded; the recorded call always lists everything.
    """
    pad = " " * indent
    call = 'juju.cli("offers", "--format=json")'
    return f"{pad}{var_name} = {call}" if var_name else f"{pad}{call}"
