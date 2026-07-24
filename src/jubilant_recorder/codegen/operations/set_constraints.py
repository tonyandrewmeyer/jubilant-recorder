from __future__ import annotations

from typing import Any


def _render_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("set-constraints", ...)`` call.

    jubilant 1.10 has no client method for ``Application.SetConstraints`` —
    ``juju.cli()`` is the public escape hatch. Each constraint key/value
    pair renders as one ``key=value`` positional argument, matching how
    ``juju set-constraints`` itself takes constraints on the command line.
    """
    args = event["args"]
    app = args.get("app") or ""
    if not app:
        raise ValueError("set_constraints event missing app")

    constraints = args.get("constraints") or {}
    parts: list[str] = ['"set-constraints"', repr(app)]
    for key in sorted(constraints):
        parts.append(repr(f"{key}={_render_value(constraints[key])}"))

    return " " * indent + f"juju.cli({', '.join(parts)})"
