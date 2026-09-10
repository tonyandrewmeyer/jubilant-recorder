"""Emit jubilant code for recorded ``juju.wait()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a jubilant ``wait()`` call using the ``jubilant.all_active`` predicate.

    The session-log op name is ``wait_for_idle`` (historical / semantic), but
    jubilant 1.10's ``Juju`` class only exposes ``wait(ready, *, timeout=...)``
    with a predicate. ``jubilant.all_active`` is the canonical "every unit
    is active" predicate; pair with an optional ``apps`` filter when the
    original call had one.
    """
    args = event["args"]
    apps = args.get("apps")
    parts: list[str] = []
    if apps:
        # Spell the app names out rather than unpacking a list literal:
        # `all_active(s, *['a', 'b'])` and `all_active(s, 'a', 'b')` do the
        # same thing, and only one of them reads like code someone wrote.
        rendered = ", ".join(repr(a) for a in apps)
        parts.append(f"lambda s: jubilant.all_active(s, {rendered})")
    else:
        parts.append("jubilant.all_active")
    timeout = args.get("timeout")
    if timeout is not None:
        parts.append(f"timeout={timeout}")
    return " " * indent + f"juju.wait({', '.join(parts)})"
