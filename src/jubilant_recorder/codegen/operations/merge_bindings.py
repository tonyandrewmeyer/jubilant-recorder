from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("bind", ...)`` call.

    jubilant 1.10 has no client method for ``Application.MergeBindings`` —
    ``juju.cli()`` is the public escape hatch. ``bindings`` maps endpoint
    names to spaces, with the empty-string key (per the wire convention
    shared with ``ApplicationGetBindings``) meaning "default space for
    unlisted endpoints" — ``juju bind`` takes that as a bare positional
    argument, and ``endpoint=space`` pairs for the rest. ``force`` has no
    ``juju bind`` flag equivalent and is flagged with a ``# TODO``.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("merge_bindings event missing app")

    bindings = dict(args.get("bindings") or {})
    default_space = bindings.pop("", None)

    parts: list[str] = ['"bind"', repr(app)]
    if default_space:
        parts.append(repr(default_space))
    for endpoint in sorted(bindings):
        parts.append(repr(f"{endpoint}={bindings[endpoint]}"))

    pad = " " * indent
    call = f"{pad}juju.cli({', '.join(parts)})"

    if args.get("force"):
        todo = f"{pad}# TODO: MergeBindings also carried force=True — no `juju bind` flag equivalent"
        return f"{todo}\n{call}"
    return call
