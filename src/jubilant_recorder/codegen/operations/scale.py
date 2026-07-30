"""Emit jubilant code for recorded ``add-unit``/``scale-application`` calls.

jubilant 1.10 has no ``Juju.scale()`` method — only ``add_unit()`` (relative:
"add N more units") and ``remove_unit()``. There is no absolute "set to N"
primitive at all. See the CLI corpus notes F1/F2.

The "scale" op is shared by two sources that don't have a common jubilant
primitive: ``Application.AddUnits`` (relative) and
``Application.ScaleApplications`` (absolute, K8s-only). ``args["mode"]``
disambiguates them:

* ``"relative"`` (default, for events recorded before this field existed —
  ``AddUnits`` is the more common source) → ``juju.add_unit(app,
  num_units=units, to=..., attach_storage=...)``. ``to``/``attach_storage``
  are optional — see the CLI corpus notes §11's follow-on note. Only the CLI/shim
  translation path (``cli_translate._classify_add_unit``) currently
  populates these; RPC-sourced ``Application.AddUnits`` events never set
  them, so this is a pure addition for RPC-sourced events (``args.get()``
  returns ``None``, nothing forwarded, unchanged output).
* ``"absolute"`` → jubilant has no client method for "set scale to N", so
  this falls to ``juju.cli("scale-application", ...)``, the same
  escape-hatch pattern already used by ``set_charm``, ``expose``, and the
  other emitters with no jubilant client-method equivalent. `juju
  scale-application` (K8s-only) has no `--to`/`--attach-storage` flags, so
  this branch never looks for them.
"""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit an ``add_unit()``/``juju.cli("scale-application")`` call."""
    args = event["args"]
    app = args["app"]
    units = args["units"]
    pad = " " * indent
    if args.get("mode") == "absolute":
        return pad + f'juju.cli("scale-application", {app!r}, {str(units)!r})'
    parts = [repr(app), f"num_units={units}"]
    to = args.get("to")
    if to:
        parts.append(f"to={to!r}")
    attach_storage = args.get("attach_storage")
    if attach_storage:
        parts.append(f"attach_storage={attach_storage!r}")
    return pad + f"juju.add_unit({', '.join(parts)})"
