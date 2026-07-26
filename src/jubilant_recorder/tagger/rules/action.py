"""Assertion-tag rules for recorded actions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from jubilant_recorder.tagger.types import AssertionTag

if TYPE_CHECKING:
    from collections.abc import Iterable

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?$")
_MAX_STABLE_STRING = 200


def _stable_results(results: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in results.items():
        if isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, str):
            if _TIMESTAMP_RE.match(value):
                continue
            if _IP_RE.match(value):
                continue
            if len(value) > _MAX_STABLE_STRING:
                continue
            out[key] = value
    return out


def evaluate(events: list[dict[str, Any]], index: int) -> Iterable[AssertionTag]:
    """Yield assertion tags for an action result at this point in the session."""
    event = events[index]
    if event.get("op") != "run":
        return
    args = event.get("args") or {}
    result = event.get("result") or {}
    if "success" not in result:
        return
    unit = args.get("unit")
    action_name = args.get("action")
    if not unit or not action_name:
        return
    success = bool(result.get("success"))
    raw_results = result.get("results") or {}
    expected_results = _stable_results(raw_results) if success else {}
    yield AssertionTag(
        kind="action_result",
        strict=False,
        source="delta",
        payload={
            "unit": unit,
            "action": action_name,
            "expected_success": success,
            "expected_results": expected_results,
        },
    )
