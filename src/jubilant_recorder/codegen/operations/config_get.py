"""Emit jubilant code for recorded ``juju.config()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit a ``juju.config(...)`` read call.

    jubilant's ``config()`` always returns the full config dict — there is
    no ``keys=`` filter on the call itself. When the recorded ``keys`` arg
    names specific keys, note them in a trailing comment rather than
    fabricating a jubilant kwarg that doesn't exist.
    """
    args = event["args"]
    app = args["app"]
    keys = args.get("keys")
    pad = " " * indent
    call = f"juju.config({app!r})"
    line = f"{pad}{var_name} = {call}" if var_name else f"{pad}{call}"
    if keys:
        line += f"  # requested keys: {keys!r} — juju.config() always returns the full dict"
    return line
