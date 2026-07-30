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

from extensions.libjuju.correlate import (
    _BUCKET1_MAP,
    _classify,
    _extract_args,
    _ModelState,
    _placement_to_cli_str,
    _storage_tag_to_id,
    _unit_tag_to_name,
    correlate,
)

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
                "Secrets",
                "RevokeSecret",
                {"uri": "secret:abc123", "scope-tag": "model-mymodel", "applications": ["myapp"]},
            )
        ]
        events = correlate(rpcs, [])

        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "shell"  # bucket-2 maps to shell with note
        assert "RevokeSecret" in ev["note"]
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
                "Secrets", "RevokeSecret", {"uri": "secret:abc"}, start=1.0, end=1.1, request_id=2
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


class TestStorageTagConversion:
    """``storage-foo-0`` ↔ ``foo/0`` — same trailing-``-N``-segment encoding as
    unit tags (``names.NewStorageTag`` replaces only the last ``/``)."""

    def test_single_word_name(self):
        assert _storage_tag_to_id("storage-foo-0") == "foo/0"

    def test_multi_word_name_preserves_hyphens(self):
        assert _storage_tag_to_id("storage-my-disk-1") == "my-disk/1"

    def test_no_prefix(self):
        assert _storage_tag_to_id("foo-0") == "foo/0"

    def test_empty(self):
        assert _storage_tag_to_id("") == ""


class TestPlacementConversion:
    """Inverse of Juju's ``ParsePlacement`` (core/instance/placement.go), confirmed
    against upstream source — see STEP7-RPC-ADDUNITS-PLACEMENT-RESULTS.md."""

    def test_machine_scope_is_bare_directive(self):
        assert _placement_to_cli_str({"scope": "#", "directive": "0"}) == "0"

    def test_container_with_directive(self):
        assert _placement_to_cli_str({"scope": "lxd", "directive": "0"}) == "lxd:0"

    def test_container_type_with_no_directive(self):
        """Bare ``lxd`` (no machine id) means "new container of this type"."""
        assert _placement_to_cli_str({"scope": "lxd", "directive": ""}) == "lxd"

    def test_missing_fields(self):
        assert _placement_to_cli_str({}) == ""


# ---------------------------------------------------------------------------
# Test: Application.AddUnits → op: scale (mode: relative), `to`/`attach_storage`
# ---------------------------------------------------------------------------


class TestScaleCorrelation:
    """RPC-sourced ``Application.AddUnits`` must carry `to`/`attach_storage` the
    same as the CLI/shim translation path, so `scale.py`'s emitter produces
    identical output regardless of source (see STEP7-FOLLOWONS-RESULTS.md's
    "still leaves open" list in the staging tree, closed by this session)."""

    def test_no_placement_or_storage(self):
        args = _extract_args(
            "Application", "AddUnits", {"application": "my-charm", "num-units": 3}
        )
        assert args == {"app": "my-charm", "units": 3, "mode": "relative"}
        assert "to" not in args
        assert "attach_storage" not in args

    def test_single_machine_placement(self):
        args = _extract_args(
            "Application",
            "AddUnits",
            {
                "application": "my-charm",
                "num-units": 1,
                "placement": [{"scope": "#", "directive": "0"}],
            },
        )
        assert args["to"] == "0"

    def test_multiple_placements_comma_joined(self):
        args = _extract_args(
            "Application",
            "AddUnits",
            {
                "application": "my-charm",
                "num-units": 2,
                "placement": [
                    {"scope": "#", "directive": "0"},
                    {"scope": "lxd", "directive": "1"},
                ],
            },
        )
        assert args["to"] == "0,lxd:1"

    def test_attach_storage_tag_converted_to_id(self):
        args = _extract_args(
            "Application",
            "AddUnits",
            {
                "application": "my-charm",
                "num-units": 1,
                "attach-storage": ["storage-foo-0"],
            },
        )
        assert args["attach_storage"] == "foo/0"

    def test_placement_and_attach_storage_together(self):
        args = _extract_args(
            "Application",
            "AddUnits",
            {
                "application": "my-charm",
                "num-units": 1,
                "placement": [{"scope": "#", "directive": "0"}],
                "attach-storage": ["storage-foo-0"],
            },
        )
        assert args == {
            "app": "my-charm",
            "units": 1,
            "mode": "relative",
            "to": "0",
            "attach_storage": "foo/0",
        }

    def test_full_correlate_emits_to_and_attach_storage(self):
        rpcs = [
            _rpc(
                "Application",
                "AddUnits",
                {
                    "application": "my-charm",
                    "num-units": 1,
                    "placement": [{"scope": "lxd", "directive": "7"}],
                    "attach-storage": ["storage-mydisk-1"],
                },
            )
        ]
        events = correlate(rpcs, [])
        assert events[0]["op"] == "scale"
        assert events[0]["args"]["to"] == "lxd:7"
        assert events[0]["args"]["attach_storage"] == "mydisk/1"

    def test_scale_applications_absolute_never_sets_to_or_attach_storage(self):
        """`scale-application` (K8s, absolute) has no `--to`/`--attach-storage`
        on the wire at all — confirm `_extract_args` never invents them."""
        args = _extract_args(
            "Application",
            "ScaleApplications",
            {"applications": [{"application-tag": "application-my-charm", "scale": 5}]},
        )
        assert "to" not in args
        assert "attach_storage" not in args
        assert args["mode"] == "absolute"


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
        rpcs = [_rpc("Secrets", "RevokeSecret", {"uri": "secret:abc"}, start=0.0, end=0.5)]
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


# ---------------------------------------------------------------------------
# Test: Secrets.* bucket-1 promotions (carry c)
# ---------------------------------------------------------------------------


class TestSecretsCorrelation:
    """Secrets.* facade methods promoted to bucket-1 in carry (c)."""

    def test_create_secrets_emits_secret_add(self):
        rpcs = [
            _rpc(
                "Secrets",
                "CreateSecrets",
                {
                    "secrets": [
                        {
                            "owner-tag": "application-myapp",
                            "label": "my-db-password",
                            "content": {"data": {"password": "hunter2", "username": "admin"}},
                            "description": "database credentials",
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "secret_add"
        assert ev["args"]["name"] == "my-db-password"
        assert ev["args"]["info"] == "database credentials"
        # Content values must be redacted; keys are preserved as a structure hint.
        assert ev["args"]["content"] == {"password": "<REDACTED>", "username": "<REDACTED>"}

    def test_create_secrets_redacts_all_content_values(self):
        """Every value in content.data is replaced with the REDACTED sentinel."""
        rpcs = [
            _rpc(
                "Secrets",
                "CreateSecrets",
                {
                    "secrets": [
                        {
                            "label": "s",
                            "content": {"data": {"k1": "v1", "k2": "v2", "k3": "v3"}},
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        content = events[0]["args"]["content"]
        assert set(content.keys()) == {"k1", "k2", "k3"}
        assert all(v == "<REDACTED>" for v in content.values())

    def test_create_secrets_no_description(self):
        rpcs = [
            _rpc(
                "Secrets",
                "CreateSecrets",
                {"secrets": [{"label": "x", "content": {"data": {"key": "val"}}}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["info"] is None

    def test_create_secrets_result_has_uri_field(self):
        """secret_add result carries a uri field (empty: tap does not capture responses)."""
        rpcs = [
            _rpc(
                "Secrets",
                "CreateSecrets",
                {"secrets": [{"label": "x", "content": {"data": {"k": "v"}}}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert "uri" in events[0]["result"]

    def test_update_secrets_emits_secret_update(self):
        rpcs = [
            _rpc(
                "Secrets",
                "UpdateSecrets",
                {
                    "secrets": [
                        {
                            "existing-id": "secret:abc123",
                            "content": {"data": {"password": "new-pass"}},
                            "description": "updated desc",
                            "label": "new-name",
                            "auto-prune": True,
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "secret_update"
        assert ev["args"]["identifier"] == "secret:abc123"
        assert ev["args"]["content"] == {"password": "<REDACTED>"}
        assert ev["args"]["info"] == "updated desc"
        assert ev["args"]["name"] == "new-name"
        assert ev["args"]["auto_prune"] is True

    def test_update_secrets_empty_content(self):
        """Metadata-only update: content.data absent produces empty content dict."""
        rpcs = [
            _rpc(
                "Secrets",
                "UpdateSecrets",
                {
                    "secrets": [
                        {
                            "existing-id": "secret:abc123",
                            "description": "new desc",
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["content"] == {}
        assert events[0]["args"]["info"] == "new desc"

    def test_remove_secrets_emits_secret_remove(self):
        rpcs = [
            _rpc(
                "Secrets",
                "RemoveSecrets",
                {"secrets": [{"uri": "secret:abc123", "revisions": []}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "secret_remove"
        assert ev["args"]["identifier"] == "secret:abc123"
        assert ev["args"]["revision"] is None

    def test_remove_secrets_with_revision(self):
        rpcs = [
            _rpc(
                "Secrets",
                "RemoveSecrets",
                {"secrets": [{"uri": "secret:abc123", "revisions": [3]}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["revision"] == 3

    def test_grant_secret_emits_secret_grant(self):
        rpcs = [
            _rpc(
                "Secrets",
                "GrantSecret",
                {
                    "uri": "secret:abc123",
                    "scope-tag": "model-mymodel",
                    "applications": ["myapp"],
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "secret_grant"
        assert ev["args"]["identifier"] == "secret:abc123"
        assert ev["args"]["app"] == "myapp"

    def test_list_secrets_emits_secret_list(self):
        rpcs = [
            _rpc(
                "Secrets",
                "ListSecrets",
                {"show-secrets": False, "filter": {}},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "secret_list"
        assert ev["args"]["owner"] is None

    def test_list_secrets_with_owner_filter(self):
        rpcs = [
            _rpc(
                "Secrets",
                "ListSecrets",
                {
                    "show-secrets": False,
                    "filter": {"owner-tag": "application-myapp"},
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["owner"] == "myapp"

    def test_revoke_secret_stays_bucket2(self):
        """Secrets.RevokeSecret has no jubilant equivalent; remains op: 'shell'."""
        rpcs = [
            _rpc(
                "Secrets",
                "RevokeSecret",
                {
                    "uri": "secret:abc123",
                    "scope-tag": "model-mymodel",
                    "applications": ["myapp"],
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "shell"
        assert "RevokeSecret" in ev["args"]["command"][0]

    def test_revoke_secret_stays_bucket2_via_classify(self):
        assert _classify("Secrets", "RevokeSecret") == ("2", None)

    def test_secrets_event_has_all_envelope_keys(self):
        """All bucket-1 Secrets events have the canonical EventEnvelope key set."""
        rpcs = [
            _rpc(
                "Secrets",
                "CreateSecrets",
                {"secrets": [{"label": "x", "content": {"data": {"k": "v"}}}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        ev = events[0]
        expected_keys = {
            "seq",
            "op",
            "ts",
            "args",
            "result",
            "model_snapshot_before",
            "model_snapshot_after",
            "assertions",
            "gesture",
            "duration_ms",
            "_libjuju_source",
        }
        assert set(ev.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test: cross-model (CMR) facades — bucket-1/2 promotions per
# CMR-FACADE-RECON.md (2026-07-09 recon).
# ---------------------------------------------------------------------------


class TestCrossModelClassification:
    """Direct ``_classify`` checks for every row in CMR-FACADE-RECON.md §1."""

    def test_create_offer_classifies_bucket1(self):
        assert _classify("ApplicationOffers", "Offer") == ("1", "create_offer")

    def test_list_offers_classifies_bucket1(self):
        assert _classify("ApplicationOffers", "ListApplicationOffers") == ("1", "list_offers")

    def test_remove_offer_classifies_bucket1(self):
        assert _classify("ApplicationOffers", "DestroyOffers") == ("1", "remove_offer")

    def test_get_consume_details_classifies_bucket1(self):
        assert _classify("ApplicationOffers", "GetConsumeDetails") == (
            "1",
            "get_consume_details",
        )

    def test_consume_classifies_bucket1(self):
        assert _classify("Application", "Consume") == ("1", "consume")

    def test_remove_saas_classifies_bucket1(self):
        assert _classify("Application", "DestroyConsumedApplications") == ("1", "remove_saas")

    def test_find_application_offers_classifies_bucket2(self):
        """No client method calls this RPC (recon §2.3) — bucket-2, not bucket-3."""
        assert _classify("ApplicationOffers", "FindApplicationOffers") == ("2", None)

    def test_consume_offer_misnomer_does_not_resolve(self):
        """There is no ``Model.consume_offer``; only ``Model.consume`` (recon §2.2).

        A wire call literally named ``ConsumeOffer`` was never real, and must
        never be added to ``_BUCKET1_MAP`` — it should fall through to the
        bucket-3 catch-all like any other unrecognised RPC, not resolve to
        the real ``consume`` op.
        """
        assert _classify("ApplicationOffers", "ConsumeOffer") == ("3", None)
        assert _classify("Application", "ConsumeOffer") == ("3", None)

    def test_no_bucket1_entry_is_named_consume_offer(self):
        """Guard against ever reintroducing the corpus's misnomer as an op name."""
        assert "consume_offer" not in _BUCKET1_MAP.values()


class TestCrossModelCorrelation:
    """``correlate()``-level checks mirroring ``TestSecretsCorrelation``'s shape."""

    def test_create_offer_emits_create_offer_event(self):
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "Offer",
                {
                    "Offers": [
                        {
                            "application-name": "ubuntu",
                            "endpoints": {"ubuntu": "ubuntu"},
                            "offer-name": "ubuntu",
                            "model-tag": "model-abc123",
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "create_offer"
        assert ev["args"]["app"] == "ubuntu"
        assert ev["args"]["endpoints"] == {"ubuntu": "ubuntu"}
        assert ev["args"]["offer_name"] == "ubuntu"
        assert ev["args"]["model_tag"] == "model-abc123"

    def test_list_offers_emits_list_offers_event(self):
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "ListApplicationOffers",
                {"filters": [{"model-name": "mymodel"}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        assert events[0]["op"] == "list_offers"
        assert events[0]["args"]["model_name"] == "mymodel"

    def test_remove_offer_emits_remove_offer_event(self):
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "DestroyOffers",
                {"force": True, "offer-urls": ["admin/mymodel.ubuntu"]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "remove_offer"
        assert ev["args"]["force"] is True
        assert ev["args"]["offer_urls"] == ["admin/mymodel.ubuntu"]

    def test_get_consume_details_emits_get_consume_details_event(self):
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "GetConsumeDetails",
                {"offer-urls": ["admin/mymodel.ubuntu"], "user-tag": "user-admin"},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "get_consume_details"
        assert ev["args"]["offer_urls"] == ["admin/mymodel.ubuntu"]
        assert ev["args"]["user_tag"] == "user-admin"

    def test_consume_emits_consume_event_not_consume_offer(self):
        """The real ``Model.consume()`` call → ``Application.Consume`` → op ``consume``."""
        rpcs = [
            _rpc(
                "Application",
                "Consume",
                {
                    "args": [
                        {
                            "offer-url": "admin/mymodel.ubuntu",
                            "application-alias": "my-ubuntu",
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "consume"
        assert ev["op"] != "consume_offer"
        assert ev["args"]["offer_url"] == "admin/mymodel.ubuntu"
        assert ev["args"]["application_alias"] == "my-ubuntu"

    def test_consume_without_alias(self):
        rpcs = [
            _rpc(
                "Application",
                "Consume",
                {"args": [{"offer-url": "admin/mymodel.ubuntu"}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["application_alias"] is None

    def test_remove_saas_emits_remove_saas_event(self):
        rpcs = [
            _rpc(
                "Application",
                "DestroyConsumedApplications",
                {"applications": [{"application-tag": "application-my-ubuntu"}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "remove_saas"
        assert ev["args"]["app"] == "my-ubuntu"

    def test_find_application_offers_stays_bucket2_shell(self):
        """No jubilant/client-method equivalent — stubs like other bucket-2 facades."""
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "FindApplicationOffers",
                {"filters": [{"model-name": "mymodel"}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "shell"
        assert "FindApplicationOffers" in ev["note"]

    def test_cmr_events_have_all_envelope_keys(self):
        """Bucket-1 CMR events carry the same canonical EventEnvelope key set."""
        rpcs = [
            _rpc(
                "ApplicationOffers",
                "Offer",
                {"Offers": [{"application-name": "ubuntu", "endpoints": {"ubuntu": "ubuntu"}}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        ev = events[0]
        expected_keys = {
            "seq",
            "op",
            "ts",
            "args",
            "result",
            "model_snapshot_before",
            "model_snapshot_after",
            "assertions",
            "gesture",
            "duration_ms",
            "_libjuju_source",
        }
        assert set(ev.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test: Application.* bucket-2 → bucket-1 promotion
# (LIBJUJU-CORPUS-AUDIT-2026-07-20.md §5 "Natural extension")
# ---------------------------------------------------------------------------


class TestApplicationCliClassification:
    """Direct ``_classify`` checks for the 8 promoted ``Application.*`` facades."""

    def test_set_charm_classifies_bucket1(self):
        assert _classify("Application", "SetCharm") == ("1", "set_charm")

    def test_expose_classifies_bucket1(self):
        assert _classify("Application", "Expose") == ("1", "expose")

    def test_unexpose_classifies_bucket1(self):
        assert _classify("Application", "Unexpose") == ("1", "unexpose")

    def test_set_constraints_classifies_bucket1(self):
        assert _classify("Application", "SetConstraints") == ("1", "set_constraints")

    def test_merge_bindings_classifies_bucket1(self):
        assert _classify("Application", "MergeBindings") == ("1", "merge_bindings")

    def test_set_relations_suspended_classifies_bucket1(self):
        assert _classify("Application", "SetRelationsSuspended") == (
            "1",
            "set_relations_suspended",
        )

    def test_unset_applications_config_classifies_bucket1(self):
        assert _classify("Application", "UnsetApplicationsConfig") == ("1", "config_unset")

    def test_update_application_base_classifies_bucket1(self):
        assert _classify("Application", "UpdateApplicationBase") == (
            "1",
            "update_application_base",
        )


class TestApplicationCliCorrelation:
    """``correlate()``-level checks mirroring ``TestCrossModelCorrelation``'s shape."""

    def test_set_charm_emits_set_charm_event(self):
        rpcs = [
            _rpc(
                "Application",
                "SetCharm",
                {"application": "my-charm", "charm-url": "ch:my-charm-2", "channel": "edge"},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "set_charm"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["charm_url"] == "ch:my-charm-2"
        assert ev["args"]["channel"] == "edge"
        assert ev["args"]["force"] is False

    def test_set_charm_captures_unrepresentable_config(self):
        rpcs = [
            _rpc(
                "Application",
                "SetCharm",
                {"application": "my-charm", "config-settings": {"log-level": "debug"}},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert events[0]["args"]["config_settings"] == {"log-level": "debug"}

    def test_expose_emits_expose_event(self):
        rpcs = [_rpc("Application", "Expose", {"application": "my-charm"})]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "expose"
        assert ev["args"]["app"] == "my-charm"

    def test_unexpose_emits_unexpose_event(self):
        rpcs = [
            _rpc(
                "Application",
                "Unexpose",
                {"application": "my-charm", "exposed-endpoints": ["db"]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "unexpose"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["exposed_endpoints"] == ["db"]

    def test_set_constraints_emits_set_constraints_event(self):
        rpcs = [
            _rpc(
                "Application",
                "SetConstraints",
                {"application": "my-charm", "constraints": {"mem": "4G", "cores": 2}},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "set_constraints"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["constraints"] == {"mem": "4G", "cores": 2}

    def test_merge_bindings_emits_merge_bindings_event(self):
        rpcs = [
            _rpc(
                "Application",
                "MergeBindings",
                {
                    "args": [
                        {
                            "application-tag": "application-my-charm",
                            "bindings": {"db": "space1"},
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "merge_bindings"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["bindings"] == {"db": "space1"}
        assert ev["args"]["force"] is False

    def test_set_relations_suspended_emits_event(self):
        rpcs = [
            _rpc(
                "Application",
                "SetRelationsSuspended",
                {"args": [{"relation-id": 3, "suspended": True, "message": "maintenance"}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "set_relations_suspended"
        assert ev["args"]["relation_ids"] == [3]
        assert ev["args"]["suspended"] is True
        assert ev["args"]["message"] == "maintenance"

    def test_unset_applications_config_emits_config_unset_event(self):
        rpcs = [
            _rpc(
                "Application",
                "UnsetApplicationsConfig",
                {"args": [{"application": "my-charm", "options": ["log-level", "debug"]}]},
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "config_unset"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["options"] == ["log-level", "debug"]

    def test_update_application_base_emits_event(self):
        rpcs = [
            _rpc(
                "Application",
                "UpdateApplicationBase",
                {
                    "args": [
                        {
                            "application-tag": "application-my-charm",
                            "base": {"name": "ubuntu", "channel": "24.04"},
                        }
                    ]
                },
            )
        ]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        assert len(events) == 1
        ev = events[0]
        assert ev["op"] == "update_application_base"
        assert ev["args"]["app"] == "my-charm"
        assert ev["args"]["base_name"] == "ubuntu"
        assert ev["args"]["base_channel"] == "24.04"
        assert ev["args"]["force"] is False

    def test_application_cli_events_have_all_envelope_keys(self):
        rpcs = [_rpc("Application", "Expose", {"application": "my-charm"})]
        events = correlate(rpcs, [], idle_threshold_seconds=5.0)
        ev = events[0]
        expected_keys = {
            "seq",
            "op",
            "ts",
            "args",
            "result",
            "model_snapshot_before",
            "model_snapshot_after",
            "assertions",
            "gesture",
            "duration_ms",
            "_libjuju_source",
        }
        assert set(ev.keys()) == expected_keys
