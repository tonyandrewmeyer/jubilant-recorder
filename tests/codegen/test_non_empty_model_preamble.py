"""the plan open question 3: warn when the recording did not start from an
empty model.

`jubilant.temp_model()` always hands the generated test a fresh, empty
model. If the recorded session actually started against a model that
already had applications deployed, the test silently assumes state that
`temp_model()` never creates. Codegen detects this from the first event's
`model_snapshot_before` and emits an explanatory comment; the fresh-model
case (every other fixture in this test suite) must stay byte-identical.
"""

from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder.codegen import generate

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "schema_version": 1,
    "captured_at": "2026-05-30T09:00:00.000Z",
    "apps": {},
    "relations": [],
}


def _snapshot_with_apps(apps: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:00:00.000Z",
        "apps": apps,
        "relations": [],
    }


def _deploy_event(before: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "seq": 1,
        "op": "deploy",
        "ts": "2026-05-30T09:00:00.000Z",
        "args": {
            "charm": "my-charm",
            "app": None,
            "channel": "edge",
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        "result": {"app_name": "my-charm"},
        "model_snapshot_before": before,
        "model_snapshot_after": before,
        "assertions": [],
        "gesture": None,
        "duration_ms": 0.0,
    }


def _log(before: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "test-session",
        "recorded_at": "2026-05-30T09:05:00.000Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.10.0",
        "model": "test-model",
        "events": [_deploy_event(before)],
    }


def test_fresh_model_emits_no_comment() -> None:
    src = generate(_log(_EMPTY_SNAPSHOT))
    ast.parse(src)
    assert "NOTE" not in src
    assert "non-empty" not in src.lower()


def test_empty_log_emits_no_comment() -> None:
    src = generate({"events": []})
    ast.parse(src)
    assert "NOTE" not in src


def test_null_first_snapshot_emits_no_comment() -> None:
    """SCHEMA.md: `model_snapshot_before` may be null for the very first event
    if the pre-session snapshot fails — codegen must not crash or warn on it."""
    src = generate(_log(None))
    ast.parse(src)
    assert "NOTE" not in src


def test_non_empty_model_emits_comment() -> None:
    before = _snapshot_with_apps(
        {
            "postgresql": {"units": {"postgresql/0": {}}},
        }
    )
    src = generate(_log(before))
    ast.parse(src)
    assert "NOTE" in src
    assert "postgresql (1 unit)" in src
    assert "temp_model()" in src


def test_non_empty_model_names_multiple_apps_sorted_with_unit_counts() -> None:
    before = _snapshot_with_apps(
        {
            "zebra-charm": {"units": {"zebra-charm/0": {}, "zebra-charm/1": {}}},
            "my-charm": {"units": {"my-charm/0": {}}},
        }
    )
    src = generate(_log(before))
    ast.parse(src)
    assert "my-charm (1 unit), zebra-charm (2 units)" in src


def test_non_empty_model_comment_is_inside_the_with_block() -> None:
    before = _snapshot_with_apps({"postgresql": {"units": {"postgresql/0": {}}}})
    src = generate(_log(before))
    with_idx = src.find("with jubilant.temp_model() as juju:")
    note_idx = src.find("# NOTE:")
    assert with_idx != -1
    assert note_idx > with_idx


def test_app_with_no_units_still_flagged() -> None:
    """An app entry with an empty units dict is still pre-existing state —
    e.g. a subordinate not yet related, or a snapshot race."""
    before = _snapshot_with_apps({"my-charm": {"units": {}}})
    src = generate(_log(before))
    ast.parse(src)
    assert "my-charm (0 units)" in src
