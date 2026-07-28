"""Emit jubilant code for recorded ``add-unit``/``scale-application`` calls.

jubilant 1.10 has no ``Juju.scale()`` method — only ``add_unit()`` (relative:
"add N more units") and ``remove_unit()``. There is no absolute "set to N"
primitive at all. See CLI-CORPUS.md F1/F2.

The "scale" op is shared by two sources that don't have a common jubilant
primitive: ``Application.AddUnits`` (relative) and
``Application.ScaleApplications`` (absolute, K8s-only). ``args["mode"]``
disambiguates them:

* ``"relative"`` (default, for events recorded before this field existed —
  ``AddUnits`` is the more common source) → ``juju.add_unit(app,
  num_units=units)``.
* ``"absolute"`` → jubilant has no client method for "set scale to N", so
  this falls to ``juju.cli("scale-application", ...)``, the same
  escape-hatch pattern already used by ``set_charm``, ``expose``, and the
  other emitters with no jubilant client-method equivalent.
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
    return pad + f"juju.add_unit({app!r}, num_units={units})"
