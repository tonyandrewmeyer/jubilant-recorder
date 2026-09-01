"""Synthesise ``wait_for_idle`` events for the core recorder's quiet windows.

WHY (the plan open question 7): ``extensions/libjuju/correlate.py`` already solves
this for the libjuju-tap path, using the gap between the last AllWatcher delta
and the next user RPC as its quiet-window signal. The core recorder
(``RecordingJuju``) has no delta stream, so it needs a different signal built from
what it does have: the ``model_snapshot_before``/``model_snapshot_after`` pair every
recorded event already carries (see SCHEMA.md). A "quiet window" here is a gap
between two adjacent recorded events where the earlier event leaves some unit in a
transitional workload status (anything outside ``tagger.rules.status``'s
``_STABLE_STATUSES``) and the next event's own pre-op snapshot shows that same unit
already settled — the only way that can happen is if the user watched the terminal
until it settled before issuing their next command.

The wall-clock gap between the two events (their timestamps, plus the first
event's own ``duration_ms``) is used as a corroborating signal, gated by
``idle_threshold_seconds`` — mirroring ``LIBJUJU_IDLE_THRESHOLD_S``'s env-var/default
convention (``JUBILANT_RECORDER_IDLE_THRESHOLD_S``, default 5.0s). The
transitional -> settled transition is the primary signal (it is the one that
actually means "the user waited"); the timing threshold exists so a settle that
happens to land in a very short gap — arguably not something the user was waiting
on at all — doesn't get turned into a synthesised wait the user never experienced.

Synthesis runs once, over the full recorded event list, at test-generation time —
the same point ``tagger.tag()`` already post-processes the log at (see ``cli.py``),
rather than inline during recording: unlike the libjuju extension, the core
recorder has no separate "correlation" pass today, and slotting in here needs no
changes to ``RecordingJuju`` or the on-disk session log format.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from typing import Any, TypeAlias

from jubilant_recorder.tagger.rules.status import _STABLE_STATUSES

SessionLog: TypeAlias = dict[str, Any]

_DEFAULT_IDLE_THRESHOLD_S = 5.0
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _resolve_threshold(idle_threshold_seconds: float | None) -> float:
    if idle_threshold_seconds is not None:
        return idle_threshold_seconds
    try:
        return float(
            os.environ.get("JUBILANT_RECORDER_IDLE_THRESHOLD_S", str(_DEFAULT_IDLE_THRESHOLD_S))
        )
    except ValueError:
        return _DEFAULT_IDLE_THRESHOLD_S


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, _TS_FORMAT)


def _unit_statuses(snapshot: dict[str, Any] | None) -> dict[tuple[str, str], str | None]:
    """Map ``(app, unit)`` to workload status for every unit in a model snapshot."""
    if not snapshot:
        return {}
    statuses: dict[tuple[str, str], str | None] = {}
    for app_name, app_data in (snapshot.get("apps") or {}).items():
        units = (app_data or {}).get("units") or {}
        for unit_name, unit_data in units.items():
            statuses[(app_name, unit_name)] = (unit_data or {}).get("workload_status")
    return statuses


def _settled_during_gap(
    after_snapshot: dict[str, Any] | None, next_before_snapshot: dict[str, Any] | None
) -> bool:
    """Return whether some unit went from transitional to settled across the gap."""
    if after_snapshot is None or next_before_snapshot is None:
        return False
    after_statuses = _unit_statuses(after_snapshot)
    next_statuses = _unit_statuses(next_before_snapshot)
    return any(
        status not in _STABLE_STATUSES and next_statuses.get(key) in _STABLE_STATUSES
        for key, status in after_statuses.items()
    )


def _gap_seconds(event: dict[str, Any], next_event: dict[str, Any]) -> float | None:
    try:
        end_of_event = _parse_ts(event["ts"])
        start_of_next = _parse_ts(next_event["ts"])
    except (KeyError, ValueError, TypeError):
        return None
    duration_ms = event.get("duration_ms") or 0.0
    end_of_event += timedelta(milliseconds=duration_ms)
    return max(0.0, (start_of_next - end_of_event).total_seconds())


def synthesize(log: SessionLog, *, idle_threshold_seconds: float | None = None) -> SessionLog:
    """Return a copy of ``log`` with synthesised ``wait_for_idle`` events inserted.

    An event is inserted between two adjacent recorded events whenever the quiet
    window between them (see module docstring) both shows a unit settling and
    lasts at least ``idle_threshold_seconds`` (env ``JUBILANT_RECORDER_IDLE_THRESHOLD_S``,
    default 5.0s, when not given explicitly). ``seq`` is renumbered from 1 across
    the whole result so it stays monotonically increasing, mirroring
    ``extensions/libjuju/correlate.py``'s own synthesised-event convention.
    """
    threshold = _resolve_threshold(idle_threshold_seconds)
    out = copy.deepcopy(log)
    events: list[dict[str, Any]] = out.get("events", []) or []
    if not events:
        return out

    result: list[dict[str, Any]] = []
    seq = 0
    for i, event in enumerate(events):
        seq += 1
        event = {**event, "seq": seq}
        result.append(event)

        if i + 1 >= len(events):
            continue
        next_event = events[i + 1]
        after_snapshot = event.get("model_snapshot_after")
        next_before_snapshot = next_event.get("model_snapshot_before")
        if not _settled_during_gap(after_snapshot, next_before_snapshot):
            continue

        gap = _gap_seconds(event, next_event)
        if gap is None or gap < threshold:
            continue

        seq += 1
        result.append(
            {
                "seq": seq,
                "op": "wait_for_idle",
                "ts": event["ts"],
                "args": {"apps": None, "timeout": None},
                "result": {"settled_at": next_event["ts"]},
                "model_snapshot_before": after_snapshot,
                "model_snapshot_after": next_before_snapshot,
                "assertions": [],
                "gesture": None,
                "duration_ms": gap * 1000,
                "_quiet_window_source": "synthesised from inter-event quiet window",
            }
        )

    out["events"] = result
    return out
