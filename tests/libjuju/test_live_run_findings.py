"""Regressions from the first live `pytest --jtr-out` run against a charm.

Three things the fixture corpus never produced, because a hand-built
`FakeConnection` sends what the correlator expects rather than what libjuju
actually sends.
"""

from __future__ import annotations

from jubilant_recorder.extensions.libjuju.correlate import _classify, _extract_args, correlate

_BASE = "2026-09-10T00:00:"


def _ts(second: float) -> str:
    s = int(second)
    ms = round((second - s) * 1000)
    return f"{_BASE}{s:02d}.{ms:03d}Z"


def _rpc(facade: str, method: str, params: dict, *, start: float = 0.0, end: float = 0.1) -> dict:
    return {
        "request_id": 1,
        "ts_start_iso": _ts(start),
        "ts_end_iso": _ts(end),
        "facade": facade,
        "version": 20,
        "method": method,
        "params": params,
    }


def _unit_delta(name: str, app: str, status: str, *, ts: float) -> dict:
    return {
        "ts_iso": _ts(ts),
        "entity_kind": "unit",
        "change_kind": "change",
        "payload": {
            "name": name,
            "application": app,
            "workload-status": {"current": status, "message": "", "since": ""},
            "agent-status": {"current": "idle", "message": "", "since": ""},
        },
    }


# --- DestroyApplication's real wire shape ---


def test_destroy_application_accepts_bare_application_names() -> None:
    """What libjuju 3.6 sends for `Model.remove_application()`.

    The correlator assumed a list of `{application-tag: …}` entities and
    raised `AttributeError` on a list of plain strings — which, before the
    plugin isolated recorder failures, failed the test being recorded.
    """
    assert _extract_args(
        "Application", "DestroyApplication", {"applications": ["ubuntu-peer"]}
    ) == {"app": "ubuntu-peer"}


def test_destroy_application_still_accepts_the_entity_shape() -> None:
    args = _extract_args(
        "Application",
        "DestroyApplication",
        {"applications": [{"application-tag": "application-ubuntu"}]},
    )
    assert args == {"app": "ubuntu"}


def test_destroy_application_with_no_applications_does_not_raise() -> None:
    assert _extract_args("Application", "DestroyApplication", {}) == {"app": ""}


# --- DestroyUnit ---


def test_destroy_unit_is_bucket_one() -> None:
    """`Application.DestroyUnit` was bucket 3, though jubilant has remove_unit()."""
    bucket, op = _classify("Application", "DestroyUnit")
    assert (bucket, op) == ("1", "remove_unit")


def test_destroy_unit_args() -> None:
    args = _extract_args(
        "Application",
        "DestroyUnit",
        {
            "units": [
                {"unit-tag": "unit-ubuntu-1", "destroy-storage": False, "force": False},
                {"unit-tag": "unit-ubuntu-2", "destroy-storage": True, "force": True},
            ]
        },
    )
    assert args == {
        "app_or_unit": ["ubuntu/1", "ubuntu/2"],
        "force": True,
        "destroy_storage": True,
    }


# --- the trailing wait ---


def test_a_session_ending_on_a_wait_gets_a_wait_for_idle() -> None:
    """Nearly every pytest-operator test ends on `wait_for_idle`.

    Synthesis only looked at gaps *between* RPCs, so the last wait was lost,
    its deltas became orphans, and the final snapshot never advanced past
    "waiting" — leaving the generated test with no assertion on the thing
    the test existed to check.
    """
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [
        _unit_delta("ubuntu/0", "ubuntu", "waiting", ts=0.2),
        _unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0),
    ]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    ops = [e["op"] for e in events]
    assert ops == ["deploy", "wait_for_idle"]

    wait = events[-1]
    before = wait["model_snapshot_before"]["apps"]["ubuntu"]["units"]["ubuntu/0"]
    after = wait["model_snapshot_after"]["apps"]["ubuntu"]["units"]["ubuntu/0"]
    assert before["workload_status"] == "waiting"
    assert after["workload_status"] == "active"


def test_the_trailing_deltas_are_no_longer_orphans() -> None:
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [_unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0)]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    assert "_libjuju_orphan_deltas" not in [e["op"] for e in events]


def test_a_short_trailing_gap_is_not_a_wait() -> None:
    """Deltas landing right after the call are the call's own, not a wait."""
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [_unit_delta("ubuntu/0", "ubuntu", "waiting", ts=3.0)]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    assert "wait_for_idle" not in [e["op"] for e in events]


def test_no_rpcs_at_all_synthesises_nothing() -> None:
    events = correlate([], [_unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0)])
    assert [e["op"] for e in events] == ["_libjuju_orphan_deltas"]
