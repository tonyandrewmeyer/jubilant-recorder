from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.consume(...)` call.

    ``offer_url`` (per CMR-FACADE-RECON.md §2.2) is the resolved/canonicalized
    URL the two-hop ``Model.consume()`` call produces — it's passed straight
    through as jubilant's ``model_and_app`` positional arg rather than split
    into owner/model/app parts, since jubilant's ``consume()`` concatenates
    ``owner``/``controller`` onto ``model_and_app`` unconditionally when given
    separately; passing the whole resolved string is equivalent and avoids
    guessing at a split the recorder can't verify.
    """
    args = event["args"]
    offer_url = args["offer_url"]
    alias = args.get("application_alias")

    parts: list[str] = [repr(offer_url)]
    if alias:
        parts.append(repr(alias))

    return " " * indent + f"juju.consume({', '.join(parts)})"
