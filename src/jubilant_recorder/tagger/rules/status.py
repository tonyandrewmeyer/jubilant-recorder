"""Assertion-tag rules for recorded status checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jubilant_recorder.tagger.types import AssertionTag

if TYPE_CHECKING:
    from collections.abc import Iterable

_STABLE_STATUSES = frozenset({"active", "blocked"})


def evaluate(events: list[dict[str, Any]], index: int) -> Iterable[AssertionTag]:
    """Yield assertion tags for a status change at this point in the session."""
    event = events[index]
    before = event.get("model_snapshot_before") or {}
    after = event.get("model_snapshot_after") or {}
    before_apps = (before.get("apps") or {}) if isinstance(before, dict) else {}
    after_apps = (after.get("apps") or {}) if isinstance(after, dict) else {}

    for app_name, app_data in after_apps.items():
        units = (app_data or {}).get("units") or {}
        for unit_name, unit_data in units.items():
            after_status = (unit_data or {}).get("workload_status")
            if after_status not in _STABLE_STATUSES:
                continue
            before_unit = ((before_apps.get(app_name) or {}).get("units") or {}).get(unit_name)
            before_status = (before_unit or {}).get("workload_status") if before_unit else None
            if before_status == after_status:
                continue
            yield AssertionTag(
                kind="unit_status",
                strict=False,
                source="delta",
                payload={
                    "app": app_name,
                    "unit": unit_name,
                    "expected": after_status,
                },
            )
