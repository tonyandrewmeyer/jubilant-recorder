"""Emit a comment placeholder for events with no dedicated emitter."""

from __future__ import annotations

import json
from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a commented placeholder for an unrecognised event."""
    op = event.get("op", "<unknown>")
    pad = " " * indent
    payload = {
        "op": op,
        "args": event.get("args", {}),
        "result": event.get("result", {}),
    }
    serialized = json.dumps(payload, sort_keys=True, indent=2)
    lines = [f"{pad}# TODO: manual step — {op}"]
    lines.extend(f"{pad}# {line}" for line in serialized.splitlines())
    return "\n".join(lines)
