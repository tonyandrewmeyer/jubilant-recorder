from __future__ import annotations

from typing import Any

import pytest

EMPTY_SNAPSHOT: dict[str, Any] = {
    "schema_version": 1,
    "captured_at": "2026-05-30T09:00:00.000Z",
    "apps": {},
    "relations": [],
}


def _event(
    seq: int,
    op: str,
    args: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    assertions: list[dict[str, Any]] | None = None,
    gesture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": "2026-05-30T09:00:00.000Z",
        "args": args,
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
        "session_id": "01935b00-0000-7000-8000-000000000000",
        "recorded_at": "2026-05-30T09:05:00.000Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.10.0",
        "model": "test-model",
        "events": events,
    }


@pytest.fixture
def deploy_event() -> dict[str, Any]:
    return _event(
        1,
        "deploy",
        {
            "charm": "my-charm",
            "app": None,
            "channel": "edge",
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        {"app_name": "my-charm"},
    )


@pytest.fixture
def integrate_event() -> dict[str, Any]:
    return _event(
        2,
        "integrate",
        {"app1_endpoint": "my-charm:db", "app2_endpoint": "postgresql:database"},
    )


@pytest.fixture
def config_event() -> dict[str, Any]:
    return _event(
        3,
        "config",
        {"app": "my-charm", "values": {"log-level": "info"}},
    )


@pytest.fixture
def scale_event() -> dict[str, Any]:
    return _event(
        4,
        "scale",
        {"app": "my-charm", "units": 3},
    )


@pytest.fixture
def run_event() -> dict[str, Any]:
    return _event(
        5,
        "run",
        {"unit": "my-charm/0", "action": "do-thing", "params": {"key": "val"}},
        {"success": True, "results": {"output": "done"}, "message": None},
    )


@pytest.fixture
def wait_for_idle_event() -> dict[str, Any]:
    return _event(
        6,
        "wait_for_idle",
        {"apps": ["my-charm"], "timeout": 300},
        {"settled_at": "2026-05-30T09:01:47.230Z"},
    )


@pytest.fixture
def status_event() -> dict[str, Any]:
    return _event(7, "status", {}, {"snapshot": EMPTY_SNAPSHOT})


@pytest.fixture
def deploy_log(deploy_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([deploy_event])


@pytest.fixture
def integrate_log(integrate_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([integrate_event])


@pytest.fixture
def config_log(config_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([config_event])


@pytest.fixture
def scale_log(scale_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([scale_event])


@pytest.fixture
def run_log(run_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([run_event])


@pytest.fixture
def wait_for_idle_log(wait_for_idle_event: dict[str, Any]) -> dict[str, Any]:
    return _wrap([wait_for_idle_event])


@pytest.fixture
def all_ops_log(
    deploy_event: dict[str, Any],
    wait_for_idle_event: dict[str, Any],
    integrate_event: dict[str, Any],
    config_event: dict[str, Any],
    scale_event: dict[str, Any],
    run_event: dict[str, Any],
) -> dict[str, Any]:
    annotated_wait = dict(wait_for_idle_event)
    annotated_wait["assertions"] = [
        {
            "kind": "unit_status",
            "app": "my-charm",
            "unit": "my-charm/0",
            "expected": "active",
            "strict": False,
            "source": "delta",
        }
    ]
    annotated_run = dict(run_event)
    annotated_run["assertions"] = [
        {
            "kind": "action_result",
            "unit": "my-charm/0",
            "action": "do-thing",
            "expected_success": True,
            "expected_results": {"output": "done"},
            "strict": False,
            "source": "delta",
        }
    ]
    return _wrap(
        [
            deploy_event,
            annotated_wait,
            integrate_event,
            config_event,
            scale_event,
            annotated_run,
        ]
    )


@pytest.fixture
def unknown_op_log() -> dict[str, Any]:
    return _wrap(
        [
            _event(
                1,
                "remove_application",
                {"app": "my-charm"},
            )
        ]
    )
