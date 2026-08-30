"""Smoke test: ``quiet_window.synthesize()`` output round-trips through codegen.

Mirrors ``extensions/libjuju/tests/test_codegen_smoke.py::
test_codegen_renders_synthesised_wait_for_idle`` — that test proves the libjuju
extension's synthesised events render unmodified through the existing codegen
pipeline; this proves the same for the core recorder's quiet-window synthesis
(PLAN.md open question 7's core-path half).
"""

from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder import quiet_window, tagger
from jubilant_recorder.codegen import generate

_EMPTY: dict[str, Any] = {
    "schema_version": 1,
    "captured_at": "2026-05-30T09:00:00.000Z",
    "apps": {},
    "relations": [],
}


def _snapshot(ts: str, *, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": ts,
        "apps": {
            "my-charm": {
                "units": {
                    "my-charm/0": {
                        "workload_status": status,
                        "workload_message": "",
                        "agent_status": "idle" if status in ("active", "blocked") else "executing",
                    }
                }
            }
        },
        "relations": [],
    }


def _log() -> dict[str, Any]:
    transitional = _snapshot("2026-05-30T09:00:01.000Z", status="maintenance")
    settled = _snapshot("2026-05-30T09:00:10.000Z", status="active")
    return {
        "schema_version": 1,
        "session_id": "test-session",
        "recorded_at": "2026-05-30T09:05:00.000Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.10.0",
        "model": "test-model",
        "events": [
            {
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
                "model_snapshot_before": _EMPTY,
                "model_snapshot_after": transitional,
                "assertions": [],
                "gesture": None,
                "duration_ms": 1000.0,
            },
            {
                "seq": 2,
                "op": "run",
                "ts": "2026-05-30T09:00:10.000Z",
                "args": {"unit": "my-charm/0", "action": "do-thing", "params": {}},
                "result": {"success": True, "results": {}, "message": None},
                "model_snapshot_before": settled,
                "model_snapshot_after": settled,
                "assertions": [],
                "gesture": None,
                "duration_ms": 0.0,
            },
        ],
    }


def test_codegen_renders_synthesised_wait_for_idle() -> None:
    log = _log()
    synthesized = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

    ops = [e["op"] for e in synthesized["events"]]
    assert ops == ["deploy", "wait_for_idle", "run"]

    annotated = tagger.tag(synthesized)
    src = generate(annotated)

    # Generated Python must be syntactically valid.
    ast.parse(src)

    # The canonical wait call must appear in the output.
    assert "juju.wait(jubilant.all_active)" in src, src
    # The surrounding ops must also render — synthesis must not break them.
    assert "juju.deploy('my-charm', channel='edge')" in src, src
    assert "juju.run(" in src, src

    # The status tagger's existing per-event rule (before != after on the
    # synthesised event) picks up the settle automatically — no changes
    # needed to tagger/rules/status.py for this.
    assert (
        "assert juju.status().apps['my-charm']"
        ".units['my-charm/0'].workload_status.current == 'active'"
    ) in src, src

    # Ops appear in order: deploy, then the wait, then run.
    deploy_idx = src.find("juju.deploy(")
    wait_idx = src.find("juju.wait(")
    run_idx = src.find("juju.run(")
    assert deploy_idx < wait_idx < run_idx, src
