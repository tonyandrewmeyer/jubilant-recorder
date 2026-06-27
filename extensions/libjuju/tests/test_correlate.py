"""
Correlate tests — fixture-driven, no live Juju controller required.

Strategy: build synthetic RPC + delta records by hand (the same shape
``LibjujuTap`` produces), call ``correlate()``, and assert the SCHEMA.md-
shaped events are correct.

Timestamp convention used in these tests:
  RPC starts at T+0.000, ends at T+0.100.
  Delta bursts arrive at T+0.200 (within the default 2 s window).
"""

from __future__ import annotations

from extensions.libjuju.correlate import _ModelState, _unit_tag_to_name, correlate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "2026-06-22T00:00:"


def _ts(second: float, offset_seconds: float = 0.0) -> str:
    total = second + offset_seconds
    s = int(total)
    ms = int((total - s) * 1000)
    return f"{_BASE}{s:02d}.{ms:03d}Z"


def _rpc(
    facade: str,
    method: str,
    params: dict,
    *,
    start: float = 0.0,
    end: float = 0.1,
    request_id: int = 1,
    version: int = 20,
) -> dict:
    return {
        "request_id": request_id,
        "ts_start_iso": _ts(start),
        "ts_end_iso": _ts(end),
        "facade": facade,
        "version": version,
        "method": method,
        "params": params,
    }


def _delta(entity_kind: str, change_kind: str, payload: dict, *, ts_offset: float = 0.2) -> dict:
    return {
        "ts_iso": _ts(ts_offset),
        "entity_kind": entity_kind,
        "change_kind": change_kind,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Test: Application.Deploy → op: deploy
# ---------------------------------------------------------------------------


class TestDeployCorrelation:
    def test_deploy_emits_deploy_event(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {
                    "applications": [
                        {
                            "charm-url": "ch:my-charm",
                            "application-name": "my-charm",
                            "num-units": 1,
                            "config": {},
                        }
                    ]
                },
            )
        ]
        deltas = [
            _delta(
                "application",
                "change",
                {"name": "my-charm"},
            ),
            _delta(
                "unit",
                "change",
                {
                    "name": "my-charm/0",
                    "application": "my-charm",
                    "workload-status": {
                        "current": "maintenance",
                        "message": "installing",
                        "since": "",
                    },
                    "agent-status": {"current": "executing", "message": "", "since": ""},
                },
            ),
        ]
        events = correlate(rpcs, deltas)

        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "deploy"
        assert ev["seq"] == 1
        assert ev["args"]["charm"] == "ch:my-charm"
        assert ev["args"]["app"] == "my-charm"
        assert ev["result"]["app_name"] == "my-charm"

    def test_deploy_model_snapshot_after_shows_new_unit(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {
                    "applications": [
                        {"charm-url": "ch:postgres", "application-name": "pg", "num-units": 1}
                    ]
                },
            )
        ]
        deltas = [
            _delta(
                "unit",
                "change",
                {
                    "name": "pg/0",
                    "application": "pg",
                    "workload-status": {
                        "current": "maintenance",
                        "message": "installing",
                        "since": "",
                    },
                    "agent-status": {"current": "executing", "message": "", "since": ""},
                },
            ),
        ]
        events = correlate(rpcs, deltas)

        snap_after = events[0]["model_snapshot_after"]
        assert "pg" in snap_after["apps"]
        assert "pg/0" in snap_after["apps"]["pg"]["units"]
        unit = snap_after["apps"]["pg"]["units"]["pg/0"]
        assert unit["workload_status"] == "maintenance"
        assert unit["agent_status"] == "executing"

    def test_snap_before_is_empty_when_no_prior_state(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
            )
        ]
        events = correlate(rpcs, [])

        snap_before = events[0]["model_snapshot_before"]
        assert snap_before["apps"] == {}
        assert snap_before["relations"] == []


# ---------------------------------------------------------------------------
# Test: Application.AddRelation → op: integrate
# ---------------------------------------------------------------------------


class TestIntegrateCorrelation:
    def test_add_relation_emits_integrate_event(self):
        rpcs = [
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["my-charm:db", "postgresql:database"]},
                start=1.0,
                end=1.1,
                request_id=2,
            )
        ]
        deltas = [
            _delta(
                "relation",
                "change",
                {
                    "id": 1,
                    "key": "my-charm:db postgresql:database",
                    "endpoints": [
                        {"application-name": "my-charm", "name": "db", "role": "requirer"},
                        {"application-name": "postgresql", "name": "database", "role": "provider"},
                    ],
                },
                ts_offset=1.2,
            )
        ]
        events = correlate(rpcs, deltas)

        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "integrate"
        assert ev["args"]["app1_endpoint"] == "my-charm:db"
        assert ev["args"]["app2_endpoint"] == "postgresql:database"

    def test_integrate_model_snapshot_after_shows_relation(self):
        rpcs = [
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["app1:ep", "app2:ep2"]},
                start=1.0,
                end=1.1,
            )
        ]
        deltas = [
            _delta(
                "relation",
                "change",
                {
                    "endpoints": [
                        {"application-name": "app1", "name": "ep"},
                        {"application-name": "app2", "name": "ep2"},
                    ]
                },
                ts_offset=1.2,
            )
        ]
        events = correlate(rpcs, deltas)

        snap_after = events[0]["model_snapshot_after"]
        assert len(snap_after["relations"]) == 1
        endpoints = set(snap_after["relations"][0]["endpoints"])
        assert endpoints == {"app1:ep", "app2:ep2"}


# ---------------------------------------------------------------------------
# Test: Bucket-3 facade (no CLI equivalent)
# ---------------------------------------------------------------------------


class TestBucketThreeCorrelation:
    def test_unknown_facade_emits_todo_event(self):
        rpcs = [
            _rpc(
                "Application",
                "SetCharm",
                {"application": "my-charm", "charm-url": "ch:my-charm-2"},
            )
        ]
        events = correlate(rpcs, [])

        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "shell"  # bucket-2 maps to shell with note
        assert "SetCharm" in ev["note"]
        assert ev["args"]["cwd"] is None

    def test_raw_facade_call_with_no_equivalent_emits_todo(self):
        rpcs = [
            _rpc(
                "Application",
                "CharmRelations",
                {"application": "my-charm"},
            )
        ]
        events = correlate(rpcs, [])

        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "_todo"
        assert "# TODO: manual step" in ev["note"]
        assert "CharmRelations" in ev["note"]
        assert ev["args"]["_raw_facade"] == "Application"
        assert ev["args"]["_raw_method"] == "CharmRelations"

    def test_libjuju_source_field_present_on_all_events(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
            ),
            _rpc(
                "Application", "SetCharm", {"application": "x"}, start=1.0, end=1.1, request_id=2
            ),
            _rpc(
                "Application",
                "CharmRelations",
                {"application": "x"},
                start=2.0,
                end=2.1,
                request_id=3,
            ),
        ]
        events = correlate(rpcs, [])

        for ev in events:
            assert "_libjuju_source" in ev


# ---------------------------------------------------------------------------
# Test: out-of-order delta arrival
# ---------------------------------------------------------------------------


class TestOutOfOrderDeltas:
    def test_delta_before_rpc_end_is_still_attributed(self):
        """A delta that arrives slightly before the RPC's ts_end should still be attributed."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                end=0.5,
            )
        ]
        # Delta at 0.4 — before ts_end (0.5) but within the 0.5 s pre-window
        deltas = [
            _delta(
                "unit",
                "change",
                {
                    "name": "x/0",
                    "application": "x",
                    "workload-status": {"current": "active", "message": "", "since": ""},
                    "agent-status": {"current": "idle", "message": "", "since": ""},
                },
                ts_offset=0.4,
            )
        ]
        events = correlate(rpcs, deltas, window_seconds=2.0)

        snap_after = events[0]["model_snapshot_after"]
        assert "x" in snap_after["apps"]

    def test_orphan_deltas_not_attributed_to_any_rpc(self):
        """Deltas that arrive more than window_seconds after the last RPC become orphans."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                end=0.1,
            )
        ]
        deltas = [
            _delta(
                "unit",
                "change",
                {
                    "name": "x/0",
                    "application": "x",
                    "workload-status": {"current": "active", "message": "", "since": ""},
                    "agent-status": {"current": "idle", "message": "", "since": ""},
                },
                ts_offset=99.0,  # way after the window
            )
        ]
        events = correlate(rpcs, deltas, window_seconds=2.0)

        # Should have the deploy event + an orphan event
        assert len(events) == 2
        orphan_ev = events[-1]
        assert orphan_ev["op"] == "_libjuju_orphan_deltas"
        assert orphan_ev["result"]["orphan_delta_count"] == 1


# ---------------------------------------------------------------------------
# Test: _ModelState
# ---------------------------------------------------------------------------


class TestModelState:
    def test_unit_add_and_snapshot(self):
        state = _ModelState()
        state.apply_delta(
            _delta(
                "unit",
                "change",
                {
                    "name": "my-app/0",
                    "application": "my-app",
                    "workload-status": {"current": "active", "message": "ready", "since": ""},
                    "agent-status": {"current": "idle", "message": "", "since": ""},
                },
            )
        )
        snap = state.snapshot("2026-06-22T00:00:00.000Z")

        assert "my-app" in snap["apps"]
        unit = snap["apps"]["my-app"]["units"]["my-app/0"]
        assert unit["workload_status"] == "active"
        assert unit["workload_message"] == "ready"
        assert unit["agent_status"] == "idle"

    def test_unit_remove(self):
        state = _ModelState()
        state.apply_delta(
            _delta(
                "unit",
                "change",
                {
                    "name": "x/0",
                    "application": "x",
                    "workload-status": {"current": "active", "message": "", "since": ""},
                    "agent-status": {"current": "idle", "message": "", "since": ""},
                },
            )
        )
        state.apply_delta(_delta("unit", "remove", {"name": "x/0"}))

        snap = state.snapshot("2026-06-22T00:00:00.000Z")
        assert "x" not in snap["apps"]

    def test_relation_add(self):
        state = _ModelState()
        state.apply_delta(
            _delta(
                "relation",
                "change",
                {
                    "endpoints": [
                        {"application-name": "app1", "name": "rel1"},
                        {"application-name": "app2", "name": "rel2"},
                    ]
                },
            )
        )
        snap = state.snapshot("2026-06-22T00:00:00.000Z")

        assert len(snap["relations"]) == 1
        eps = set(snap["relations"][0]["endpoints"])
        assert eps == {"app1:rel1", "app2:rel2"}

    def test_relation_remove(self):
        state = _ModelState()
        ep_data = {
            "endpoints": [
                {"application-name": "a", "name": "ep1"},
                {"application-name": "b", "name": "ep2"},
            ]
        }
        state.apply_delta(_delta("relation", "change", ep_data))
        state.apply_delta(_delta("relation", "remove", ep_data))

        snap = state.snapshot("2026-06-22T00:00:00.000Z")
        assert snap["relations"] == []

    def test_snapshot_has_correct_schema_version(self):
        state = _ModelState()
        snap = state.snapshot("2026-06-22T00:00:00.000Z")
        assert snap["schema_version"] == 1
        assert snap["captured_at"] == "2026-06-22T00:00:00.000Z"

    def test_multiple_units_same_app(self):
        state = _ModelState()
        for i in range(3):
            state.apply_delta(
                _delta(
                    "unit",
                    "change",
                    {
                        "name": f"my-app/{i}",
                        "application": "my-app",
                        "workload-status": {"current": "active", "message": "", "since": ""},
                        "agent-status": {"current": "idle", "message": "", "since": ""},
                    },
                )
            )
        snap = state.snapshot("2026-06-22T00:00:00.000Z")
        assert len(snap["apps"]["my-app"]["units"]) == 3


# ---------------------------------------------------------------------------
# Test: internal RPCs filtered out
# ---------------------------------------------------------------------------


class TestInternalRPCFiltering:
    def test_allwatcher_next_skipped(self):
        rpcs = [
            _rpc("AllWatcher", "Next", {}, request_id=1),
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=1.0,
                end=1.1,
                request_id=2,
            ),
        ]
        events = correlate(rpcs, [])

        assert len(events) == 1
        assert events[0]["op"] == "deploy"

    def test_pinger_ping_skipped(self):
        rpcs = [
            _rpc("Pinger", "Ping", {}, request_id=1),
        ]
        events = correlate(rpcs, [])

        assert len(events) == 0

    def test_client_watchall_skipped(self):
        rpcs = [
            _rpc("Client", "WatchAll", {}, request_id=1),
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["a:ep", "b:ep2"]},
                start=1.0,
                end=1.1,
                request_id=2,
            ),
        ]
        events = correlate(rpcs, [])

        assert len(events) == 1
        assert events[0]["op"] == "integrate"


# ---------------------------------------------------------------------------
# Test: seq numbering
# ---------------------------------------------------------------------------


class TestUnitTagConversion:
    """``unit-my-charm-0`` ↔ ``my-charm/0`` — the unit number is the trailing
    ``-N`` segment, not the first one. Step 3 regression: Action.Enqueue
    args used to split on the FIRST hyphen and mangled multi-word app names."""

    def test_single_word_app(self):
        assert _unit_tag_to_name("unit-foo-0") == "foo/0"

    def test_multi_word_app_preserves_hyphens(self):
        assert _unit_tag_to_name("unit-my-charm-0") == "my-charm/0"

    def test_three_word_app(self):
        assert _unit_tag_to_name("unit-my-fancy-charm-12") == "my-fancy-charm/12"

    def test_no_prefix(self):
        assert _unit_tag_to_name("my-charm-0") == "my-charm/0"

    def test_empty(self):
        assert _unit_tag_to_name("") == ""

    def test_action_enqueue_emits_correct_unit_in_run_args(self):
        rpcs = [
            _rpc(
                "Action",
                "EnqueueOperation",
                {
                    "actions": [
                        {
                            "receiver": "unit-postgresql-k8s-2",
                            "name": "create-backup",
                            "parameters": {"prefix": "nightly"},
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [])
        assert events[0]["op"] == "run"
        assert events[0]["args"]["unit"] == "postgresql-k8s/2"
        assert events[0]["args"]["action"] == "create-backup"
        assert events[0]["args"]["params"] == {"prefix": "nightly"}


class TestSeqNumbering:
    def test_seq_starts_at_one(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
            )
        ]
        events = correlate(rpcs, [])

        assert events[0]["seq"] == 1

    def test_seq_is_monotonically_increasing(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                request_id=1,
            ),
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["x:ep", "y:ep"]},
                start=1.0,
                end=1.1,
                request_id=2,
            ),
            _rpc("Client", "Status", {}, start=2.0, end=2.1, request_id=3),
        ]
        events = correlate(rpcs, [])

        assert [e["seq"] for e in events] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test: duration_ms — carry (a) from step-3
# ---------------------------------------------------------------------------


class TestDurationMs:
    def test_duration_ms_present_on_bucket1_events(self):
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=0.0,
                end=0.1,
            )
        ]
        events = correlate(rpcs, [])

        assert "duration_ms" in events[0]
        assert isinstance(events[0]["duration_ms"], float)

    def test_duration_ms_reflects_rpc_wall_clock(self):
        """RPC from t=0.0 to t=1.0 → duration_ms ≈ 1000."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=0.0,
                end=1.0,
            )
        ]
        events = correlate(rpcs, [])

        # 1-second RPC → 1000 ms (allow 1 ms rounding from the ms-precision timestamps).
        assert abs(events[0]["duration_ms"] - 1000.0) <= 1.0

    def test_duration_ms_present_on_bucket2_shell_events(self):
        rpcs = [_rpc("Application", "SetCharm", {"application": "x"}, start=0.0, end=0.5)]
        events = correlate(rpcs, [])

        assert events[0]["op"] == "shell"
        assert "duration_ms" in events[0]
        assert isinstance(events[0]["duration_ms"], float)

    def test_duration_ms_present_on_bucket3_todo_events(self):
        rpcs = [_rpc("Application", "CharmRelations", {"application": "x"}, start=0.0, end=0.3)]
        events = correlate(rpcs, [])

        assert events[0]["op"] == "_todo"
        assert "duration_ms" in events[0]

    def test_duration_ms_zero_on_orphan_event(self):
        """Orphan events are synthetic — duration_ms is 0."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                end=0.1,
            )
        ]
        deltas = [
            _delta(
                "unit",
                "change",
                {
                    "name": "x/0",
                    "application": "x",
                    "workload-status": {"current": "active", "message": "", "since": ""},
                    "agent-status": {"current": "idle", "message": "", "since": ""},
                },
                ts_offset=99.0,
            )
        ]
        events = correlate(rpcs, deltas, window_seconds=2.0)

        orphan = events[-1]
        assert orphan["op"] == "_libjuju_orphan_deltas"
        assert orphan["duration_ms"] == 0.0

    def test_duration_ms_non_negative(self):
        """duration_ms is always >= 0 regardless of timestamp ordering."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=5.0,
                end=5.0,  # same start and end → 0 ms
            )
        ]
        events = correlate(rpcs, [])

        assert events[0]["duration_ms"] >= 0.0


# ---------------------------------------------------------------------------
# Test: wait_for_idle synthesis — carry (b) from step-3
# ---------------------------------------------------------------------------

# Timestamps for synthesis tests — keep seconds < 60 so the _ts helper stays valid.
# Scenario: RPC[0] ends at t=1, last delta at t=3, RPC[1] starts at t=10.
# Quiet window: t=3 → t=10 (7 s > 5 s threshold) → synthesis expected.
_DEPLOY_RPC_START = 0.0
_DEPLOY_RPC_END = 1.0
_UNIT_DELTA_TS = 3.0
_RELATE_RPC_START = 10.0
_RELATE_RPC_END = 10.1


def _synthesis_rpcs() -> list[dict]:
    return [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
            start=_DEPLOY_RPC_START,
            end=_DEPLOY_RPC_END,
            request_id=1,
        ),
        _rpc(
            "Application",
            "AddRelation",
            {"endpoints": ["x:db", "y:database"]},
            start=_RELATE_RPC_START,
            end=_RELATE_RPC_END,
            request_id=2,
        ),
    ]


def _active_unit_delta(ts_offset: float) -> dict:
    return _delta(
        "unit",
        "change",
        {
            "name": "x/0",
            "application": "x",
            "workload-status": {"current": "active", "message": "", "since": ""},
            "agent-status": {"current": "idle", "message": "", "since": ""},
        },
        ts_offset=ts_offset,
    )


class TestWaitForIdleSynthesis:
    def test_quiet_window_synthesises_wait_for_idle(self):
        """Gap of 7 s with threshold=5 s → one synthesised wait_for_idle."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        ops = [e["op"] for e in events]
        assert "wait_for_idle" in ops

    def test_synthesised_event_inserted_between_rpcs(self):
        """wait_for_idle appears between deploy and integrate, not before/after."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        ops = [e["op"] for e in events]
        assert ops == ["deploy", "wait_for_idle", "integrate"]

    def test_seq_is_monotonically_increasing_with_synthesised_event(self):
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        seqs = [e["seq"] for e in events]
        assert seqs == list(range(1, len(events) + 1))

    def test_wait_for_idle_args_shape(self):
        """synthesised wait_for_idle has apps=null, timeout=null per SCHEMA.md."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        wfi = next(e for e in events if e["op"] == "wait_for_idle")
        assert wfi["args"] == {"apps": None, "timeout": None}

    def test_wait_for_idle_result_has_settled_at(self):
        """settled_at in the result is the start of the next user RPC."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        wfi = next(e for e in events if e["op"] == "wait_for_idle")
        assert "settled_at" in wfi["result"]
        assert wfi["result"]["settled_at"] is not None

    def test_wait_for_idle_duration_ms_equals_quiet_window(self):
        """duration_ms = (next_rpc_start - last_delta_ts) * 1000."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        wfi = next(e for e in events if e["op"] == "wait_for_idle")
        # quiet window: _RELATE_RPC_START - _UNIT_DELTA_TS = 7.0 s → 7000 ms (±1 ms rounding)
        expected_ms = (_RELATE_RPC_START - _UNIT_DELTA_TS) * 1000
        assert abs(wfi["duration_ms"] - expected_ms) <= 1.0

    def test_quiet_window_below_threshold_not_synthesised(self):
        """Gap of 2 s with threshold=5 s → no synthesis."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=0.0,
                end=1.0,
                request_id=1,
            ),
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["x:db", "y:database"]},
                start=3.0,  # 2 s gap from last delta at t=1.0
                end=3.1,
                request_id=2,
            ),
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)

        ops = [e["op"] for e in events]
        assert "wait_for_idle" not in ops

    def test_stream_never_quiesces_no_synthesis(self):
        """Delta keeps arriving right up to the next RPC → no quiet window."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=0.0,
                end=1.0,
                request_id=1,
            ),
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["x:db", "y:database"]},
                start=10.0,
                end=10.1,
                request_id=2,
            ),
        ]
        # Delta arrives just before the next RPC → quiet window = 10.0 - 9.9 = 0.1 s < 5 s
        deltas = [_active_unit_delta(ts_offset=9.9)]
        events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)

        ops = [e["op"] for e in events]
        assert "wait_for_idle" not in ops

    def test_multiple_quiet_windows_produce_multiple_wait_for_idle(self):
        """Three RPCs with two long gaps → two synthesised wait_for_idles."""
        rpcs = [
            _rpc(
                "Application",
                "Deploy",
                {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                start=0.0,
                end=1.0,
                request_id=1,
            ),
            _rpc(
                "Application",
                "AddRelation",
                {"endpoints": ["x:db", "y:database"]},
                start=10.0,
                end=10.1,
                request_id=2,
            ),
            _rpc(
                "Client",
                "Status",
                {},
                start=20.0,
                end=20.1,
                request_id=3,
            ),
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)

        ops = [e["op"] for e in events]
        assert ops == ["deploy", "wait_for_idle", "integrate", "wait_for_idle", "status"]

    def test_custom_threshold_via_kwarg(self):
        """idle_threshold_seconds=15 suppresses synthesis for a 7-second gap."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=15.0,
        )

        ops = [e["op"] for e in events]
        assert "wait_for_idle" not in ops

    def test_wait_for_idle_model_snapshot_reflects_settled_state(self):
        """Snapshot for synthesised wait_for_idle shows the unit as active."""
        events = correlate(
            _synthesis_rpcs(),
            [_active_unit_delta(_UNIT_DELTA_TS)],
            idle_threshold_seconds=5.0,
        )

        wfi = next(e for e in events if e["op"] == "wait_for_idle")
        snap = wfi["model_snapshot_before"]
        assert "x" in snap["apps"]
        assert snap["apps"]["x"]["units"]["x/0"]["workload_status"] == "active"
        # before and after snapshots are the same (nothing changed during quiet window)
        assert wfi["model_snapshot_before"] == wfi["model_snapshot_after"]
