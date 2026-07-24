from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("suspend-relation"|"resume-relation", ...)`` call.

    jubilant 1.10 has no client method for
    ``Application.SetRelationsSuspended`` — ``juju.cli()`` is the public
    escape hatch. The RPC's ``suspended`` bool selects which CLI subcommand
    applies; ``message`` is only accepted by ``suspend-relation``, so it is
    dropped (not rendered) on the resume path rather than passed to a flag
    that doesn't exist there.
    """
    args = event["args"]
    relation_ids = args.get("relation_ids") or []
    if not relation_ids:
        raise ValueError("set_relations_suspended event missing relation_ids")

    subcommand = '"suspend-relation"' if args.get("suspended") else '"resume-relation"'
    parts: list[str] = [subcommand, *(repr(str(rid)) for rid in relation_ids)]

    message = args.get("message")
    if args.get("suspended") and message:
        parts.extend(['"--message"', repr(message)])

    return " " * indent + f"juju.cli({', '.join(parts)})"
