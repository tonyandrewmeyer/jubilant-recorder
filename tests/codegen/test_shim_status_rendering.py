"""How a shell-recorded `juju status` renders.

The call is emitted because the operator really ran it and the generated
test should run it too. The summary comment is emitted only when the model
was not healthy, because a comment saying "everything is active" adds
nothing to the assertion immediately below it that says the same.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap


def _snapshot(**units: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": "2026-09-10T10:00:00.000Z",
        "apps": {
            unit.split("_")[0]: {
                "units": {
                    unit.replace("_", "/"): {
                        "workload_status": status,
                        "workload_message": "",
                        "agent_status": "idle",
                    }
                }
            }
            for unit, status in units.items()
        },
        "relations": [],
    }


def _status_event(after: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "seq": 1,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": ["status"], "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0},
        "model_snapshot_before": None,
        "model_snapshot_after": after,
        "assertions": [],
        "gesture": None,
    }


def test_a_healthy_status_is_just_the_call() -> None:
    src = generate(_wrap([_status_event(_snapshot(ubuntu_0="active"))]))
    assert "juju.status()" in src
    assert "# juju status:" not in src


def test_an_unhealthy_status_carries_a_summary() -> None:
    src = generate(_wrap([_status_event(_snapshot(ubuntu_0="blocked"))]))
    assert "juju.status()" in src
    assert "# juju status: ubuntu/0 blocked" in src


def test_a_status_with_no_snapshot_is_just_the_call() -> None:
    """`JTR_NO_SNAPSHOT=1`, or a capture that failed. No summary to give."""
    src = generate(_wrap([_status_event(None)]))
    assert "juju.status()" in src
    assert "# juju status:" not in src
