from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    args = event["args"]
    identifier = args.get("identifier") or ""
    app = args.get("app") or ""
    return " " * indent + f"juju.grant_secret({identifier!r}, {app!r})"
