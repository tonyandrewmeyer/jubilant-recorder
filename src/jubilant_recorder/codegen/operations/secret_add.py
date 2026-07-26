"""Emit jubilant code for recorded ``juju.add_secret()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.add_secret(...)`` call.

    Secret content is always redacted in the session log (values replaced with
    ``"<REDACTED>"``).  Codegen emits a ``# TODO`` comment above the call so
    the user knows to substitute real values before running the test.
    """
    args = event["args"]
    name = args.get("name") or ""
    content = args.get("content") or {}
    info = args.get("info")

    parts: list[str] = [repr(name), repr(content)]
    if info is not None:
        parts.append(f"info={info!r}")

    pad = " " * indent
    todo = f"{pad}# TODO: replace with real secret content"
    call = f"{pad}juju.add_secret({', '.join(parts)})"
    return f"{todo}\n{call}"
