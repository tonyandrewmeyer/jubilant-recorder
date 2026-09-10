"""Snapshot synthesis from shim-captured `juju status` output.

This is what lets a shell-capture session produce a test with assertions
in it, rather than a bare list of calls: the shim records the model as it
stood each time the operator looked, and the tagger turns the difference
between two looks into an assertion.
"""

from __future__ import annotations

import json
from typing import Any

from jubilant_recorder import shim_snapshots, tagger
from jubilant_recorder.codegen import generate


def _status_json(*, app: str, status: str, units: int = 1) -> str:
    """A `juju status --format=json` payload, in the shape juju 3.6 emits.

    Trimmed from a real capture rather than invented: `jubilant.Status`
    requires several keys (`charm-origin`, `model.controller`, …) that an
    approximate fixture omits, and a fixture that is not what juju actually
    prints would not test the thing this module does.
    """
    return json.dumps(
        {
            "model": {
                "name": "demo",
                "type": "iaas",
                "controller": "concierge-lxd",
                "cloud": "localhost",
                "region": "localhost",
                "version": "3.6.28",
                "model-status": {"current": "available"},
                "sla": "unsupported",
            },
            "machines": {},
            "applications": {
                app: {
                    "charm": app,
                    "series": "noble",
                    "os": "ubuntu",
                    "charm-origin": "charm-hub",
                    "charm-name": app,
                    "charm-rev": 79,
                    "charm-channel": "latest/stable",
                    "exposed": False,
                    "application-status": {"current": status},
                    "units": {
                        f"{app}/{i}": {
                            "workload-status": {"current": status},
                            "juju-status": {"current": "idle"},
                            "machine": str(i),
                        }
                        for i in range(units)
                    },
                }
            },
            "storage": {},
            "controller": {"timestamp": "10:00:00"},
        }
    )


def _status_event(seq: int, raw: str | None) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell",
        "ts": f"2026-09-10T10:00:0{seq}.000Z",
        "args": {"argv": ["status"], "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0, "status_json": raw},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _log(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "session_id": "s", "events": events}


def test_snapshot_is_attached_to_a_shim_status() -> None:
    log = shim_snapshots.attach_status_snapshots(
        _log([_status_event(1, _status_json(app="ubuntu", status="active"))])
    )
    after = log["events"][0]["model_snapshot_after"]
    assert after["apps"]["ubuntu"]["units"]["ubuntu/0"]["workload_status"] == "active"


def test_each_snapshot_becomes_the_next_one_s_before() -> None:
    """Consecutive looks are a delta, not the model appearing from nothing."""
    log = shim_snapshots.attach_status_snapshots(
        _log(
            [
                _status_event(1, _status_json(app="ubuntu", status="waiting")),
                _status_event(2, _status_json(app="ubuntu", status="active")),
            ]
        )
    )
    second = log["events"][1]
    assert (
        second["model_snapshot_before"]["apps"]["ubuntu"]["units"]["ubuntu/0"]["workload_status"]
        == "waiting"
    )
    assert (
        second["model_snapshot_after"]["apps"]["ubuntu"]["units"]["ubuntu/0"]["workload_status"]
        == "active"
    )


def test_a_shell_session_produces_an_assertion() -> None:
    """The end-to-end point of all of this."""
    log = shim_snapshots.attach_status_snapshots(
        _log(
            [
                _status_event(1, _status_json(app="ubuntu", status="waiting")),
                _status_event(2, _status_json(app="ubuntu", status="active")),
            ]
        )
    )
    src = generate(tagger.tag(log))
    assert "juju.status()" in src
    assert "workload_status.current == 'active'" in src


def test_a_malformed_capture_costs_assertions_not_the_test() -> None:
    log = shim_snapshots.attach_status_snapshots(_log([_status_event(1, "not json at all")]))
    assert log["events"][0]["model_snapshot_after"] is None
    assert "juju.status()" in generate(log)


def test_a_missing_capture_is_left_alone() -> None:
    log = shim_snapshots.attach_status_snapshots(_log([_status_event(1, None)]))
    assert log["events"][0]["model_snapshot_after"] is None


def _k8s_status_json(*, status: str) -> str:
    """A `juju status --format=json` payload from a Kubernetes model.

    Trimmed from a real microk8s capture on juju 3.6.28. Its unit entries
    have `address`/`provider-id`/`leader` and no `machine`, and `machines`
    is empty — the shape a machine-cloud capture never produces, and the one
    the shim's snapshot path had never been run against.
    """
    return json.dumps(
        {
            "model": {
                "name": "k8sdemo",
                "type": "caas",
                "controller": "concierge-microk8s",
                "cloud": "microk8s",
                "region": "localhost",
                "version": "3.6.28",
                "model-status": {"current": "available"},
                "sla": "unsupported",
            },
            "machines": {},
            "applications": {
                "snappass-test": {
                    "charm": "snappass-test",
                    "base": {"name": "ubuntu", "channel": "20.04"},
                    "charm-origin": "charmhub",
                    "charm-name": "snappass-test",
                    "charm-rev": 9,
                    "charm-channel": "latest/stable",
                    "scale": 1,
                    "provider-id": "a0623269-f9e5-4719-aaf9-76cd9e003c56",
                    "address": "10.152.183.96",
                    "exposed": False,
                    "application-status": {"current": status},
                    "units": {
                        "snappass-test/0": {
                            "workload-status": {"current": status, "message": "redis started"},
                            "juju-status": {"current": "idle"},
                            "leader": True,
                            "address": "10.1.241.74",
                            "provider-id": "snappass-test-0",
                        }
                    },
                }
            },
            "storage": {},
            "controller": {"timestamp": "18:01:07+12:00"},
        }
    )


def test_a_kubernetes_status_snapshots_the_same_way() -> None:
    """The shape differs; what the tagger needs out of it does not."""
    log = shim_snapshots.attach_status_snapshots(
        _log(
            [
                _status_event(1, _k8s_status_json(status="waiting")),
                _status_event(2, _k8s_status_json(status="active")),
            ]
        )
    )
    unit = log["events"][1]["model_snapshot_after"]["apps"]["snappass-test"]["units"]
    assert unit["snappass-test/0"]["workload_status"] == "active"
    assert unit["snappass-test/0"]["workload_message"] == "redis started"

    src = generate(tagger.tag(log))
    assert "juju.status()" in src
    assert "workload_status.current == 'active'" in src


def test_scripted_events_are_not_touched() -> None:
    """A mixed log must be safe to pass through."""
    event = _status_event(1, _status_json(app="ubuntu", status="active"))
    event["op"] = "status"
    event["args"] = {}
    event["model_snapshot_after"] = {"apps": {}, "relations": []}
    log = shim_snapshots.attach_status_snapshots(_log([event]))
    assert log["events"][0]["model_snapshot_after"] == {"apps": {}, "relations": []}
