from __future__ import annotations

import json
from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    op = event.get("op", "<unknown>")
    pad = " " * indent
    payload = {
        "op": op,
        "args": event.get("args", {}),
        "result": event.get("result", {}),
    }
    serialized = json.dumps(payload, sort_keys=True, indent=2)
    lines = [f"{pad}# TODO: manual step — {op}"]
    for line in serialized.splitlines():
        lines.append(f"{pad}# {line}")
    return "\n".join(lines)
