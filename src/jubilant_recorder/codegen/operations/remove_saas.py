from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a `juju.cli("remove-saas", ...)` call.

    Correlator gives ``app`` (the consumed SAAS application name) — see
    `correlate.py`'s ``("Application", "DestroyConsumedApplications")``
    unwrap, which only surfaces the first ``application-tag`` on the wire.
    A list is also accepted defensively, matching the sibling
    ``remove_application`` emitter's handling of a possible future
    multi-app unwrap. jubilant has no dedicated ``remove_saas()`` client
    method, so this shells out via the public `Juju.cli()` escape hatch.
    """
    args = event["args"]
    app = args.get("app")
    pad = " " * indent

    if not app:
        return pad + "# TODO: manual step: remove_saas with no app"

    names = app if isinstance(app, list) else [app]
    force = bool(args.get("force"))

    parts: list[str] = ["remove-saas"]
    if force:
        parts.append("--force")
    parts.extend(names)
    rendered = ", ".join(repr(p) for p in parts)
    return pad + f"juju.cli({rendered})"
