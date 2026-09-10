"""Turn shim-captured ``juju status`` output into model snapshots.

`RecordingJuju` snapshots the model before and after every operation, and
the tagger derives its assertions from the difference between the two. A
shell-capture session has no such wrapper — the PATH shim sees argv and an
exit code, not a model — so before this existed, a session recorded at a
real prompt produced a test with no assertions in it at all, however much
the operator had actually checked.

The shim now records the raw ``juju status --format=json`` output next to
every recorded ``juju status`` (see `shim/juju_shim.py`). This module turns
those into the same ``model_snapshot_after`` shape the scripted front-end
records, and threads each one forward as the *next* status's
``model_snapshot_before``, so what the tagger sees is a real delta —
"between these two times the operator looked, ubuntu went from waiting to
active" — rather than the whole model appearing from nothing every time.

Statuses are the only sampling points available, so the delta is attributed
to the status event rather than to the command that caused it. That is a
coarser attribution than the scripted front-end's, and it is the honest one:
the shim genuinely does not know which of the commands between two looks
moved the model.
"""

from __future__ import annotations

import json
from typing import Any

from jubilant_recorder.recording_juju import _parse_snapshot


def attach_status_snapshots(log: dict[str, Any]) -> dict[str, Any]:
    """Populate snapshots on shim ``juju status`` events, in place.

    Events that already carry a ``model_snapshot_after`` (a scripted or
    libjuju recording) are left alone, so a mixed log is safe to pass
    through. Returns the same log for convenient chaining.
    """
    previous: dict[str, Any] | None = None
    for event in log.get("events") or []:
        if not _is_shim_status(event):
            continue
        if event.get("model_snapshot_after") is not None:
            previous = event["model_snapshot_after"]
            continue
        raw = (event.get("result") or {}).get("status_json")
        snapshot = _snapshot_from_json(raw, event.get("ts") or "")
        if snapshot is None:
            continue
        event["model_snapshot_before"] = previous
        event["model_snapshot_after"] = snapshot
        previous = snapshot
    return log


def _is_shim_status(event: dict[str, Any]) -> bool:
    args = event.get("args") or {}
    if event.get("op") != "shell" or args.get("source") != "shim":
        return False
    argv = args.get("argv") or []
    return bool(argv) and argv[0] == "status"


def _snapshot_from_json(raw: Any, captured_at: str) -> dict[str, Any] | None:
    """Parse captured status JSON, or return None if it is unusable.

    Never raises: a truncated or malformed capture costs the generated test
    some assertions, which is a much smaller failure than `jtr generate`
    refusing to produce a test at all.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _parse_snapshot(json.loads(raw), captured_at)
    except Exception:
        return None
