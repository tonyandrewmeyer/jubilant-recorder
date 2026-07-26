"""Emit jubilant code for recorded ``juju.run()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit a ``juju.run(...)`` call for this recorded event."""
    args = event["args"]
    unit = args["unit"]
    action = args["action"]
    params = args.get("params") or {}
    parts: list[str] = [repr(unit), repr(action)]
    if params:
        parts.append(f"params={params!r}")
    call = f"juju.run({', '.join(parts)})"
    pad = " " * indent
    if var_name:
        return f"{pad}{var_name} = {call}"
    return f"{pad}{call}"
