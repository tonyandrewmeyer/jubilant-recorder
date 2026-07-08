from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    args = event["args"]
    a = args["app1_endpoint"]
    b = args["app2_endpoint"]
    return " " * indent + f"juju.remove_relation({a!r}, {b!r})"
