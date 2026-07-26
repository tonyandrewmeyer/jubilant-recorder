"""Emit jubilant code for recorded ``juju.deploy()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.deploy(...)` call.

    Drops kwargs at their jubilant defaults (``trust=False``, ``num_units=1``,
    ``base=None``, …) so the emitted line stays tight when the session
    only used the basics. All non-default kwargs the recorder captures are
    propagated through here.
    """
    args = event["args"]
    parts: list[str] = [repr(args["charm"])]
    app = args.get("app")
    if app:
        parts.append(f"app={app!r}")
    base = args.get("base")
    if base:
        parts.append(f"base={base!r}")
    channel = args.get("channel")
    if channel:
        parts.append(f"channel={channel!r}")
    revision = args.get("revision")
    if revision is not None:
        parts.append(f"revision={revision}")
    num_units = args.get("num_units")
    if num_units is not None and num_units != 1:
        parts.append(f"num_units={num_units}")
    constraints = args.get("constraints")
    if constraints:
        parts.append(f"constraints={constraints!r}")
    to = args.get("to")
    if to:
        parts.append(f"to={to!r}")
    config = args.get("config")
    if config:
        parts.append(f"config={config!r}")
    resources = args.get("resources")
    if resources:
        parts.append(f"resources={resources!r}")
    trust = args.get("trust")
    if trust:
        parts.append("trust=True")
    force = args.get("force")
    if force:
        parts.append("force=True")
    return " " * indent + f"juju.deploy({', '.join(parts)})"
