"""Assertion-tag rules for recorded configuration changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jubilant_recorder.tagger.types import AssertionTag

if TYPE_CHECKING:
    from collections.abc import Iterable

_STATE_CHANGING_OPS = frozenset(
    {
        "deploy",
        "integrate",
        "remove_integration",
        "scale",
        "remove_application",
        "run",
        "config",
    }
)


def evaluate(events: list[dict[str, Any]], index: int) -> Iterable[AssertionTag]:
    """Yield assertion tags for a configuration change at this point in the session."""
    event = events[index]
    if event.get("op") != "config_get":
        return
    args = event.get("args") or {}
    result = event.get("result") or {}
    app = args.get("app")
    values = result.get("values") or {}
    if not app or not isinstance(values, dict) or not values:
        return

    set_values: dict[str, Any] | None = None
    for j in range(index - 1, -1, -1):
        prev = events[j]
        prev_op = prev.get("op")
        if prev_op == "config":
            prev_args = prev.get("args") or {}
            if prev_args.get("app") == app:
                set_values = prev_args.get("values") or {}
                break
            continue
        if prev_op in _STATE_CHANGING_OPS:
            return
    if set_values is None:
        return

    for key, expected in set_values.items():
        if key not in values:
            continue
        if values[key] != expected:
            continue
        yield AssertionTag(
            kind="config_value",
            strict=False,
            source="delta",
            payload={"app": app, "key": key, "expected": expected},
        )
