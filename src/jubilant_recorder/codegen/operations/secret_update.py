"""Emit jubilant code for recorded ``juju.update_secret()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.update_secret(...)`` call.

    Secret content is always redacted in the session log.  A ``# TODO``
    comment is emitted above the call when content is non-empty so the user
    knows to substitute real values.  If content was not changed in the
    recorded session (empty dict), the comment is still emitted to draw
    attention.
    """
    args = event["args"]
    identifier = args.get("identifier") or ""
    content = args.get("content") or {}
    info = args.get("info")
    name = args.get("name")
    auto_prune = args.get("auto_prune") or False

    parts: list[str] = [repr(identifier), repr(content)]
    if info is not None:
        parts.append(f"info={info!r}")
    if name is not None:
        parts.append(f"name={name!r}")
    if auto_prune:
        parts.append("auto_prune=True")

    pad = " " * indent
    todo = f"{pad}# TODO: replace with real secret content"
    call = f"{pad}juju.update_secret({', '.join(parts)})"
    return f"{todo}\n{call}"
