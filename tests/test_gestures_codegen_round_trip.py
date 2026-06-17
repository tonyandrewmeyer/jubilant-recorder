"""Feed a synthetic log with each gesture event into codegen and verify the
generated test contains the matching explicit assertion (not an implicit delta).
"""

from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder import codegen

EMPTY_SNAPSHOT = {
    "schema_version": 1,
    "captured_at": "2026-06-07T00:00:00.000Z",
    "apps": {},
    "relations": [],
}


def _event(
    seq: int,
    op: str,
    *,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    gesture: dict[str, Any] | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": "2026-06-07T00:00:00.000Z",
        "args": args or {},
        "result": result or {},
        "model_snapshot_before": EMPTY_SNAPSHOT,
        "model_snapshot_after": EMPTY_SNAPSHOT,
        "assertions": assertions or [],
        "gesture": gesture,
        "duration_ms": 0.0,
    }


def _wrap(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "0193fc4e-9c3d-7000-8000-1a2b3c4d5e6f",
        "recorded_at": "2026-06-07T00:00:00Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.10.0",
        "model": "test-model",
        "events": events,
    }


def test_checkpoint_gesture_renders_comment() -> None:
    log = _wrap(
        [
            _event(
                1,
                "checkpoint",
                gesture={"kind": "checkpoint", "label": "phase one", "params": {}},
            )
        ]
    )
    src = codegen.generate(log)
    ast.parse(src)
    assert "# checkpoint: phase one" in src


def test_assert_status_gesture_emits_explicit_assert_not_delta() -> None:
    log = _wrap(
        [
            _event(
                1,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": None},
                result={"settled_at": None},
                gesture={
                    "kind": "assert_status",
                    "label": None,
                    "params": {"app": "my-charm", "unit": "my-charm/0", "status": "active"},
                },
            )
        ]
    )
    src = codegen.generate(log)
    ast.parse(src)
    assert "juju.wait(lambda s: jubilant.all_active(s, *['my-charm']))" in src
    assert (
        "assert juju.status().apps['my-charm']"
        ".units['my-charm/0'].workload_status.current == 'active'"
    ) in src
    # No delta-source comment.
    assert "source: 'delta'" not in src


def test_assert_status_no_unit_renders_loop() -> None:
    log = _wrap(
        [
            _event(
                1,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": None},
                result={"settled_at": None},
                gesture={
                    "kind": "assert_status",
                    "label": None,
                    "params": {"app": "my-charm", "unit": None, "status": "active"},
                },
            )
        ]
    )
    src = codegen.generate(log)
    ast.parse(src)
    assert "for _u in juju.status().apps['my-charm'].units.values():" in src
    assert "_u.workload_status.current == 'active'" in src


def test_assert_action_result_gesture_on_run_event_uses_run_var() -> None:
    log = _wrap(
        [
            _event(
                5,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {}},
                result={"success": True, "results": {"output": "done"}, "message": None},
                gesture={
                    "kind": "assert_action_result",
                    "label": None,
                    "params": {
                        "unit": "my-charm/0",
                        "action": "do-thing",
                        "success": True,
                        "expected_results": {"output": "done"},
                    },
                },
            )
        ]
    )
    src = codegen.generate(log)
    ast.parse(src)
    assert "result_5 = juju.run('my-charm/0', 'do-thing')" in src
    assert "assert result_5.success" in src
    assert "assert result_5.results['output'] == 'done'" in src
