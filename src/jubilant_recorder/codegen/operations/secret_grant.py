"""Emit jubilant code for recorded ``juju.grant_secret()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.grant_secret(...)`` call for this recorded event.

    ``app`` may be a single name or a list: ``Juju.grant_secret()`` takes
    ``str | Iterable[str]``, so a grant to several applications stays one
    call rather than losing every target after the first.
    """
    args = event["args"]
    identifier = args.get("identifier") or ""
    app = args.get("app") or ""
    return " " * indent + f"juju.grant_secret({identifier!r}, {app!r})"
