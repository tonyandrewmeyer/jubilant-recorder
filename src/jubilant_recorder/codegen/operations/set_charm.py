from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("refresh", ...)`` call.

    jubilant 1.10 has no client method for ``Application.SetCharm`` —
    ``juju.cli()`` is the public escape hatch. The correlator captures the
    resolved ``charm_url``/``channel``/``force`` (rendered as ``--switch``/
    ``--channel``/``--force``); ``config_settings``, ``storage_constraints``,
    and ``resource_ids`` have no ``juju refresh`` flag equivalent and are
    flagged with a ``# TODO`` rather than silently dropped.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("set_charm event missing app")

    parts: list[str] = ['"refresh"', repr(app)]
    charm_url = args.get("charm_url")
    if charm_url:
        parts.extend(['"--switch"', repr(charm_url)])
    channel = args.get("channel")
    if channel:
        parts.extend(['"--channel"', repr(channel)])
    if args.get("force"):
        parts.append('"--force"')

    pad = " " * indent
    call = f"{pad}juju.cli({', '.join(parts)})"

    unrepresentable = [
        name
        for name, key in (
            ("config settings", "config_settings"),
            ("storage constraints", "storage_constraints"),
            ("resource ids", "resource_ids"),
        )
        if args.get(key)
    ]
    if unrepresentable:
        todo = f"{pad}# TODO: SetCharm also carried {', '.join(unrepresentable)} — not representable as `juju refresh` flags"
        return f"{todo}\n{call}"
    return call
