"""Emit jubilant code for recorded ``juju.cli()`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("set-application-base", ...)`` call.

    jubilant 1.10 has no client method for
    ``Application.UpdateApplicationBase`` — ``juju.cli()`` is the public
    escape hatch. ``base_name``/``base_channel`` (e.g. ``ubuntu``/``24.04``)
    are joined into the ``name@channel`` form ``juju set-application-base``
    expects, matching the ``ubuntu@24.04`` convention used elsewhere for
    bases (see ``deploy.py``'s ``base`` kwarg).
    """
    args = event["args"]
    app = args.get("app") or ""
    base_name = args.get("base_name")
    base_channel = args.get("base_channel")
    if not app:
        raise ValueError("update_application_base event missing app")
    if not base_name or not base_channel:
        raise ValueError("update_application_base event missing base")

    parts: list[str] = [
        '"set-application-base"',
        repr(app),
        repr(f"{base_name}@{base_channel}"),
    ]
    if args.get("force"):
        parts.append('"--force"')

    return " " * indent + f"juju.cli({', '.join(parts)})"
