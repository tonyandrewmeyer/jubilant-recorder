from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    args = event["args"]
    return " " * indent + f"juju.scale({args['app']!r}, units={args['units']})"
