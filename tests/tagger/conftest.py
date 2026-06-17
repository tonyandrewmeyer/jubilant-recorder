from __future__ import annotations

from typing import Any

import pytest


def make_snapshot(
    *,
    apps: dict[str, Any] | None = None,
    relations: list[dict[str, Any]] | None = None,
    captured_at: str = "2026-05-30T09:00:00.000Z",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "apps": apps or {},
        "relations": list(relations) if relations else [],
    }


def make_unit(
    *,
    workload_status: str = "active",
    workload_message: str = "",
    agent_status: str = "idle",
) -> dict[str, Any]:
    return {
        "workload_status": workload_status,
        "workload_message": workload_message,
        "agent_status": agent_status,
    }


def make_event(
    seq: int,
    op: str,
    *,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    assertions: list[dict[str, Any]] | None = None,
    gesture: dict[str, Any] | None = None,
    ts: str = "2026-05-30T09:00:00.000Z",
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": ts,
        "args": args or {},
        "result": result or {},
        "model_snapshot_before": before,
        "model_snapshot_after": after,
        "assertions": list(assertions) if assertions else [],
        "gesture": gesture,
    }


def make_log(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "test-session",
        "recorded_at": "2026-05-30T09:05:00Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.0.0",
        "model": "test-model",
        "events": list(events),
    }


@pytest.fixture
def status_session() -> dict[str, Any]:
    before = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(
                        workload_status="maintenance",
                        workload_message="installing charm software",
                        agent_status="executing",
                    ),
                },
            },
        },
    )
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": 300},
                result={"settled_at": "2026-05-30T09:01:47.230Z"},
                before=before,
                after=after,
            ),
        ]
    )


@pytest.fixture
def status_no_delta_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": 300},
                result={"settled_at": "2026-05-30T09:01:47.230Z"},
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def action_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {"key": "val"}},
                result={
                    "success": True,
                    "results": {"output": "done"},
                    "message": None,
                },
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def action_failed_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {}},
                result={
                    "success": False,
                    "results": {},
                    "message": "permission denied",
                },
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def scale_session() -> dict[str, Any]:
    before = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(),
                    "my-charm/1": make_unit(),
                    "my-charm/2": make_unit(),
                },
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "scale",
                args={"app": "my-charm", "units": 3},
                before=before,
                after=after,
            ),
        ]
    )


@pytest.fixture
def config_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "config",
                args={"app": "my-charm", "values": {"log-level": "info", "debug": True}},
                before=snap,
                after=snap,
            ),
            make_event(
                2,
                "config_get",
                args={"app": "my-charm", "keys": None},
                result={"values": {"log-level": "info", "debug": True}},
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def config_no_verify_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "config",
                args={"app": "my-charm", "values": {"log-level": "info"}},
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def relation_session() -> dict[str, Any]:
    before = make_snapshot(
        apps={
            "my-charm": {"units": {"my-charm/0": make_unit()}},
            "postgresql": {"units": {"postgresql/0": make_unit()}},
        },
    )
    after = make_snapshot(
        apps={
            "my-charm": {"units": {"my-charm/0": make_unit()}},
            "postgresql": {"units": {"postgresql/0": make_unit()}},
        },
        relations=[{"endpoints": ["my-charm:db", "postgresql:database"]}],
    )
    return make_log(
        [
            make_event(
                1,
                "integrate",
                args={"app1_endpoint": "my-charm:db", "app2_endpoint": "postgresql:database"},
                before=before,
                after=after,
            ),
        ]
    )


@pytest.fixture
def relation_remove_session() -> dict[str, Any]:
    before = make_snapshot(
        apps={
            "my-charm": {"units": {"my-charm/0": make_unit()}},
            "postgresql": {"units": {"postgresql/0": make_unit()}},
        },
        relations=[{"endpoints": ["my-charm:db", "postgresql:database"]}],
    )
    after = make_snapshot(
        apps={
            "my-charm": {"units": {"my-charm/0": make_unit()}},
            "postgresql": {"units": {"postgresql/0": make_unit()}},
        },
    )
    return make_log(
        [
            make_event(
                1,
                "remove_integration",
                args={"app1_endpoint": "my-charm:db", "app2_endpoint": "postgresql:database"},
                before=before,
                after=after,
            ),
        ]
    )


@pytest.fixture
def happy_path_session() -> dict[str, Any]:
    empty = make_snapshot()
    deploying = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(
                        workload_status="maintenance",
                        workload_message="installing charm software",
                        agent_status="executing",
                    ),
                },
            },
        },
    )
    active = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(
                1,
                "deploy",
                args={
                    "charm": "my-charm",
                    "app": None,
                    "channel": "edge",
                    "num_units": 1,
                    "config": {},
                    "resources": {},
                },
                result={"app_name": "my-charm"},
                before=empty,
                after=deploying,
            ),
            make_event(
                2,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": 300},
                result={"settled_at": "2026-05-30T09:01:47.230Z"},
                before=deploying,
                after=active,
            ),
            make_event(
                3,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {"key": "val"}},
                result={"success": True, "results": {"output": "done"}, "message": None},
                before=active,
                after=active,
            ),
        ]
    )


@pytest.fixture
def negative_path_session() -> dict[str, Any]:
    snap = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    return make_log(
        [
            make_event(1, "status", args={}, result={"snapshot": snap}, before=snap, after=snap),
            make_event(
                2,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": 300},
                result={"settled_at": "2026-05-30T09:02:00.000Z"},
                before=snap,
                after=snap,
            ),
        ]
    )


@pytest.fixture
def gesture_already_tagged_session() -> dict[str, Any]:
    before = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(
                        workload_status="maintenance", agent_status="executing"
                    ),
                },
            },
        },
    )
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit()},
            },
        },
    )
    pre_existing_tag = {
        "kind": "unit_status",
        "app": "my-charm",
        "unit": "my-charm/0",
        "expected": "active",
        "strict": True,
        "source": "gesture",
    }
    return make_log(
        [
            make_event(
                1,
                "wait_for_idle",
                args={"apps": ["my-charm"], "timeout": 300},
                result={"settled_at": "2026-05-30T09:01:47.230Z"},
                before=before,
                after=after,
                assertions=[pre_existing_tag],
            ),
        ]
    )
