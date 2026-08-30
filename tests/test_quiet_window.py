"""Tests for the core recorder's quiet-window ``wait_for_idle`` synthesis.

Mirrors ``extensions/libjuju/tests/test_correlate.py::TestWaitForIdleSynthesis`` in
shape (same op sequence assertions, same "no synthesis" edge cases), but drives
``quiet_window.synthesize()`` over already-recorded core-style events instead of
raw RPCs/deltas — see the module docstring in ``quiet_window.py`` for why the
signal is different.
"""

from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder import quiet_window

_EMPTY: dict[str, Any] = {
    "schema_version": 1,
    "captured_at": "2026-05-30T09:00:00.000Z",
    "apps": {},
    "relations": [],
}


def _snapshot(ts: str, *, status: str = "active", unit: str = "my-charm/0") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": ts,
        "apps": {
            "my-charm": {
                "units": {
                    unit: {
                        "workload_status": status,
                        "workload_message": "",
                        "agent_status": "idle" if status in ("active", "blocked") else "executing",
                    }
                }
            }
        },
        "relations": [],
    }


def _event(
    seq: int,
    op: str,
    ts: str,
    *,
    duration_ms: float = 0.0,
    before: dict[str, Any] | None = _EMPTY,
    after: dict[str, Any] | None = _EMPTY,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": ts,
        "args": {},
        "result": {},
        "model_snapshot_before": before,
        "model_snapshot_after": after,
        "assertions": [],
        "gesture": None,
        "duration_ms": duration_ms,
    }


def _log(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "test-session",
        "recorded_at": "2026-05-30T09:05:00.000Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.10.0",
        "model": "test-model",
        "events": events,
    }


def _deploy_then_run(gap_seconds: float) -> dict[str, Any]:
    """deploy (ends transitional, 1s duration) --gap_seconds from its start-- run (starts settled).

    The true quiet window (post-op-completion) is ``gap_seconds - 1.0`` seconds,
    since ``deploy`` itself takes 1s (``duration_ms=1000``).
    """
    transitional = _snapshot("2026-05-30T09:00:01.000Z", status="maintenance")
    run_ts = f"2026-05-30T09:00:{gap_seconds:06.3f}Z"
    settled = _snapshot(run_ts, status="active")
    events = [
        _event(
            1,
            "deploy",
            "2026-05-30T09:00:00.000Z",
            duration_ms=1000,
            before=_EMPTY,
            after=transitional,
        ),
        _event(2, "run", run_ts, before=settled, after=settled),
    ]
    return _log(events)


class TestQuietWindowSynthesis:
    def test_quiet_window_synthesises_wait_for_idle(self) -> None:
        """Gap of 7s with threshold=5s -> one synthesised wait_for_idle."""
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" in ops

    def test_synthesised_event_inserted_between_events(self) -> None:
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert ops == ["deploy", "wait_for_idle", "run"]

    def test_seq_is_monotonically_increasing_with_synthesised_event(self) -> None:
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        seqs = [e["seq"] for e in out["events"]]
        assert seqs == list(range(1, len(seqs) + 1))

    def test_wait_for_idle_args_shape(self) -> None:
        """synthesised wait_for_idle has apps=null, timeout=null per SCHEMA.md."""
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        wfi = next(e for e in out["events"] if e["op"] == "wait_for_idle")
        assert wfi["args"] == {"apps": None, "timeout": None}

    def test_wait_for_idle_result_has_settled_at(self) -> None:
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        wfi = next(e for e in out["events"] if e["op"] == "wait_for_idle")
        assert wfi["result"]["settled_at"] == log["events"][1]["ts"]

    def test_duration_ms_equals_quiet_window(self) -> None:
        """The deploy op runs 1000ms; the raw ts gap is 7s, so the true quiet
        window (post-op-completion) is 6s -> 6000ms."""
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        wfi = next(e for e in out["events"] if e["op"] == "wait_for_idle")
        assert wfi["duration_ms"] == pytest.approx(6000.0)

    def test_model_snapshot_before_after_differ(self) -> None:
        """Unlike the libjuju synthesis (single delta-derived snapshot for both
        sides), the core synthesis has two genuinely different data points —
        the transitional state right after the earlier op, and the settled
        state right before the next one — and deliberately keeps them distinct
        so the existing status tagger rule can tag the transition."""
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        wfi = next(e for e in out["events"] if e["op"] == "wait_for_idle")
        assert wfi["model_snapshot_before"] != wfi["model_snapshot_after"]
        before_status = wfi["model_snapshot_before"]["apps"]["my-charm"]["units"]["my-charm/0"][
            "workload_status"
        ]
        after_status = wfi["model_snapshot_after"]["apps"]["my-charm"]["units"]["my-charm/0"][
            "workload_status"
        ]
        assert before_status == "maintenance"
        assert after_status == "active"

    def test_short_gap_below_threshold_no_synthesis(self) -> None:
        """Same transition, but the gap is only 2s < the 5s threshold."""
        log = _deploy_then_run(2.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_custom_threshold_via_kwarg(self) -> None:
        """idle_threshold_seconds=15 suppresses synthesis for a ~6s true gap."""
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log, idle_threshold_seconds=15.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_env_var_threshold_override(self, monkeypatch) -> None:
        monkeypatch.setenv("JUBILANT_RECORDER_IDLE_THRESHOLD_S", "15.0")
        log = _deploy_then_run(7.0)
        out = quiet_window.synthesize(log)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_env_var_threshold_permits_synthesis(self, monkeypatch) -> None:
        monkeypatch.setenv("JUBILANT_RECORDER_IDLE_THRESHOLD_S", "1.0")
        log = _deploy_then_run(2.0)
        out = quiet_window.synthesize(log)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" in ops

    def test_no_settle_no_synthesis(self) -> None:
        """Unit still transitional in the next event's own before -> no wait, no
        matter how long the gap: the primary signal (settling) never fired."""
        still_transitional = _snapshot("2026-05-30T09:00:01.000Z", status="maintenance")
        events = [
            _event(
                1,
                "deploy",
                "2026-05-30T09:00:00.000Z",
                duration_ms=1000,
                before=_EMPTY,
                after=still_transitional,
            ),
            _event(
                2,
                "run",
                "2026-05-30T09:00:30.000Z",
                before=still_transitional,
                after=still_transitional,
            ),
        ]
        out = quiet_window.synthesize(_log(events), idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_already_stable_no_synthesis(self) -> None:
        """Both snapshots already stable (e.g. 'active') -> nothing transitioned."""
        stable = _snapshot("2026-05-30T09:00:00.000Z", status="active")
        events = [
            _event(
                1, "config", "2026-05-30T09:00:00.000Z", duration_ms=0, before=stable, after=stable
            ),
            _event(2, "run", "2026-05-30T09:01:00.000Z", before=stable, after=stable),
        ]
        out = quiet_window.synthesize(_log(events), idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_multiple_quiet_windows_produce_multiple_wait_for_idle(self) -> None:
        transitional = _snapshot("2026-05-30T09:00:01.000Z", status="maintenance")
        settled = _snapshot("2026-05-30T09:00:10.000Z", status="active")
        blocked_transitional = _snapshot("2026-05-30T09:00:11.000Z", status="waiting")
        resolved = _snapshot("2026-05-30T09:00:20.000Z", status="blocked")
        events = [
            _event(1, "deploy", "2026-05-30T09:00:00.000Z", before=_EMPTY, after=transitional),
            _event(
                2,
                "integrate",
                "2026-05-30T09:00:10.000Z",
                before=settled,
                after=blocked_transitional,
            ),
            _event(3, "status", "2026-05-30T09:00:20.000Z", before=resolved, after=resolved),
        ]
        out = quiet_window.synthesize(_log(events), idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert ops == ["deploy", "wait_for_idle", "integrate", "wait_for_idle", "status"]

    def test_missing_snapshot_no_crash(self) -> None:
        """A null model_snapshot (SCHEMA.md: allowed for the very first event) must
        not raise — just skip that pair for synthesis purposes."""
        events = [
            _event(1, "deploy", "2026-05-30T09:00:00.000Z", before=None, after=None),
            _event(2, "run", "2026-05-30T09:01:00.000Z", before=_EMPTY, after=_EMPTY),
        ]
        out = quiet_window.synthesize(_log(events), idle_threshold_seconds=5.0)

        ops = [e["op"] for e in out["events"]]
        assert "wait_for_idle" not in ops

    def test_empty_log_no_crash(self) -> None:
        out = quiet_window.synthesize(_log([]))
        assert out["events"] == []

    def test_single_event_no_crash(self) -> None:
        log = _log([_event(1, "deploy", "2026-05-30T09:00:00.000Z")])
        out = quiet_window.synthesize(log, idle_threshold_seconds=5.0)
        assert [e["op"] for e in out["events"]] == ["deploy"]

    def test_default_threshold_is_five_seconds(self, monkeypatch) -> None:
        """True quiet window = raw gap - deploy's 1s duration; threshold is 5s."""
        monkeypatch.delenv("JUBILANT_RECORDER_IDLE_THRESHOLD_S", raising=False)
        below = quiet_window.synthesize(_deploy_then_run(5.9))  # quiet window 4.9s
        above = quiet_window.synthesize(_deploy_then_run(6.1))  # quiet window 5.1s

        assert "wait_for_idle" not in [e["op"] for e in below["events"]]
        assert "wait_for_idle" in [e["op"] for e in above["events"]]

    def test_input_log_not_mutated(self) -> None:
        log = _deploy_then_run(7.0)
        original_events = len(log["events"])
        quiet_window.synthesize(log, idle_threshold_seconds=5.0)
        assert len(log["events"]) == original_events
