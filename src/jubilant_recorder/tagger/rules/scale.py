from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jubilant_recorder.tagger.types import AssertionTag


def _app_unit_count(snapshot_apps: dict[str, Any], app_name: str) -> int | None:
    app = snapshot_apps.get(app_name)
    if app is None:
        return None
    units = app.get("units") or {}
    return len(units)


def evaluate(events: list[dict[str, Any]], index: int) -> Iterable[AssertionTag]:
    event = events[index]
    before = event.get("model_snapshot_before") or {}
    after = event.get("model_snapshot_after") or {}
    before_apps = (before.get("apps") or {}) if isinstance(before, dict) else {}
    after_apps = (after.get("apps") or {}) if isinstance(after, dict) else {}

    app_names = set(before_apps) | set(after_apps)
    for app_name in app_names:
        before_count = _app_unit_count(before_apps, app_name)
        after_count = _app_unit_count(after_apps, app_name)
        if after_count is None:
            continue
        if before_count == after_count:
            continue
        yield AssertionTag(
            kind="unit_count",
            strict=False,
            source="delta",
            payload={"app": app_name, "expected": after_count},
        )
