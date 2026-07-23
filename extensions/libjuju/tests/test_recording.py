"""
``RecordingLibjuju`` driver tests — fixture-driven, no live Juju controller.

The strategy mirrors ``test_tap.py``: build a ``FakeConnection`` with a
scripted async ``rpc`` method, hand it to a ``LibjujuTap``, fire the
synthetic RPCs from inside the recorder's context, and assert the
on-disk session log is SCHEMA-compliant and renderable by the canonical
codegen.

Where the test drives correlation directly (rather than through the
tap), it injects a stub ``correlator`` callable so the test can be
explicit about which events the log must contain.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from extensions.libjuju.recording import RecordingLibjuju
from extensions.libjuju.tap import LibjujuTap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeConnection:
    """Minimal stand-in for ``juju.client.connection.Connection``."""

    rpc = None  # replaced per-test


def _make_stub(responses: list[dict[str, Any]]):
    counter = [0]

    async def _stub(conn_self: FakeConnection, msg: dict, encoder: object = None) -> dict:
        counter[0] += 1
        msg["request-id"] = counter[0]
        if not responses:
            return {"request-id": counter[0], "response": {}}
        idx = min(counter[0] - 1, len(responses) - 1)
        return responses[idx]

    return _stub


def _run_rpc(msg: dict[str, Any]) -> dict[str, Any]:
    conn = FakeConnection()
    return asyncio.run(FakeConnection.rpc(conn, msg))


def _read_log(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test: end-to-end through the real correlator
# ---------------------------------------------------------------------------


class TestRecordingEndToEnd:
    def test_deploy_session_writes_schema_compliant_log(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {"results": [{"tag": "application-my-charm"}]}},
                {
                    "request-id": 2,
                    "response": {
                        "deltas": [
                            [
                                "unit",
                                "change",
                                {
                                    "name": "my-charm/0",
                                    "application": "my-charm",
                                    "workload-status": {
                                        "current": "active",
                                        "message": "",
                                        "since": "",
                                    },
                                    "agent-status": {
                                        "current": "idle",
                                        "message": "",
                                        "since": "",
                                    },
                                },
                            ]
                        ]
                    },
                },
            ]
        )
        log_path = tmp_path / "session.json"
        tap = LibjujuTap(_connection_class=FakeConnection)
        with RecordingLibjuju.start(
            log_path=log_path,
            model="test-model",
            tap=tap,
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {
                                "charm-url": "ch:my-charm",
                                "application-name": "my-charm",
                                "num-units": 1,
                            }
                        ]
                    },
                }
            )
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        doc = _read_log(log_path)
        # SCHEMA-level top-level fields are present.
        assert doc["schema_version"] == 1
        assert doc["model"] == "test-model"
        assert doc["session_id"]
        assert doc["recorded_at"]
        assert isinstance(doc["events"], list)
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "deploy"
        assert ev["seq"] == 1  # SessionLog seq, not correlate seq
        assert ev["args"]["charm"] == "ch:my-charm"
        assert ev["args"]["app"] == "my-charm"
        # EventEnvelope keys are the only top-level keys per event.
        assert set(ev.keys()) == {
            "assertions",
            "args",
            "duration_ms",
            "gesture",
            "model_snapshot_after",
            "model_snapshot_before",
            "op",
            "result",
            "seq",
            "ts",
        }

    def test_seq_is_assigned_by_session_log_not_correlator(self, tmp_path: Path):
        """``correlate()`` assigns its own seq counter; the recorder must
        ignore that and use the SessionLog's seq so the on-disk log meets
        the canonical "no gaps" guarantee."""
        log_path = tmp_path / "session.json"

        def fake_correlator(rpcs, deltas):
            # correlate-shaped events but with deliberately wrong seq values.
            return [
                {
                    "seq": 99,
                    "op": "integrate",
                    "ts": "2026-06-25T00:00:00.000Z",
                    "args": {"app1_endpoint": "a:db", "app2_endpoint": "b:database"},
                    "result": {},
                    "model_snapshot_before": None,
                    "model_snapshot_after": None,
                    "assertions": [],
                    "gesture": None,
                },
                {
                    "seq": 99,
                    "op": "integrate",
                    "ts": "2026-06-25T00:00:01.000Z",
                    "args": {"app1_endpoint": "c:db", "app2_endpoint": "d:database"},
                    "result": {},
                    "model_snapshot_before": None,
                    "model_snapshot_after": None,
                    "assertions": [],
                    "gesture": None,
                },
            ]

        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
            correlator=fake_correlator,
        ):
            pass

        doc = _read_log(log_path)
        assert [e["seq"] for e in doc["events"]] == [1, 2]

    def test_provenance_fields_are_stripped(self, tmp_path: Path):
        """``correlate`` may attach ``_libjuju_source`` / ``note`` keys for
        debugging; the on-disk log must contain only canonical EventEnvelope
        keys so the tagger and codegen never trip over unexpected fields."""
        log_path = tmp_path / "session.json"

        def fake_correlator(rpcs, deltas):
            return [
                {
                    "seq": 1,
                    "op": "_todo",
                    "ts": "2026-06-25T00:00:00.000Z",
                    "args": {
                        "_raw_facade": "Foo",
                        "_raw_method": "Bar",
                        "_raw_params": {},
                        "_libjuju_source": "libjuju Foo.Bar",
                    },
                    "result": {},
                    "model_snapshot_before": None,
                    "model_snapshot_after": None,
                    "assertions": [],
                    "gesture": None,
                    "_libjuju_source": "libjuju Foo.Bar",
                    "note": "# TODO: manual step — libjuju Foo.Bar",
                }
            ]

        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
            correlator=fake_correlator,
        ):
            pass

        ev = _read_log(log_path)["events"][0]
        assert "_libjuju_source" not in ev
        assert "note" not in ev
        assert "_libjuju_source" not in ev["args"]
        # _raw_* fields ARE part of the bucket-3 args contract — keep them.
        assert ev["args"]["_raw_facade"] == "Foo"


# ---------------------------------------------------------------------------
# Test: model_snapshot_before/after propagate through to the log
# ---------------------------------------------------------------------------


class TestSnapshotsPropagate:
    def test_snapshot_before_and_after_present_for_bucket1(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {"results": [{"tag": "application-x"}]}},
                {
                    "request-id": 2,
                    "response": {
                        "deltas": [
                            [
                                "unit",
                                "change",
                                {
                                    "name": "x/0",
                                    "application": "x",
                                    "workload-status": {
                                        "current": "maintenance",
                                        "message": "installing",
                                        "since": "",
                                    },
                                    "agent-status": {
                                        "current": "executing",
                                        "message": "",
                                        "since": "",
                                    },
                                },
                            ]
                        ]
                    },
                },
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:x", "application-name": "x", "num-units": 1}
                        ]
                    },
                }
            )
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        ev = _read_log(log_path)["events"][0]
        # before-snapshot exists, is well-formed, and shows no apps yet.
        assert ev["model_snapshot_before"]["schema_version"] == 1
        assert ev["model_snapshot_before"]["apps"] == {}
        # after-snapshot exists and shows the new unit.
        after = ev["model_snapshot_after"]
        assert after["schema_version"] == 1
        assert "x" in after["apps"]
        assert "x/0" in after["apps"]["x"]["units"]
        assert after["apps"]["x"]["units"]["x/0"]["workload_status"] == "maintenance"


# ---------------------------------------------------------------------------
# Test: bucket-2 / bucket-3 surface in the log without breaking it
# ---------------------------------------------------------------------------


class TestBucketTwoAndThree:
    def test_bucket2_emits_shell_op(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "RevokeSecret",
                    "version": 1,
                    "params": {"uri": "secret:abc123"},
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "shell"
        # bucket-2 args.command has the original facade/method captured for the human.
        assert "RevokeSecret" in ev["args"]["command"][0]

    def test_bucket3_emits_todo_op(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "CharmRelations",
                    "version": 20,
                    "params": {"application": "my-charm"},
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "_todo"
        assert ev["args"]["_raw_facade"] == "Application"
        assert ev["args"]["_raw_method"] == "CharmRelations"


# ---------------------------------------------------------------------------
# Test: error handling and tap restoration
# ---------------------------------------------------------------------------


class TestContextManagerSafety:
    def test_session_error_recorded_when_body_raises(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with (
            pytest.raises(RuntimeError, match="boom"),
            RecordingLibjuju.start(
                log_path=log_path,
                model="m",
                tap=LibjujuTap(_connection_class=FakeConnection),
            ),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {"applications": [{"charm-url": "ch:x", "application-name": "x"}]},
                }
            )
            raise RuntimeError("boom")

        doc = _read_log(log_path)
        ops = [e["op"] for e in doc["events"]]
        # The deploy was captured before the failure; the error is recorded after.
        assert ops[-1] == "session.error"
        assert "boom" in doc["events"][-1]["result"]["error"]
        assert "deploy" in ops

    def test_tap_is_unpatched_after_exit(self, tmp_path: Path):
        original_rpc = _make_stub([])
        FakeConnection.rpc = original_rpc
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            pass
        assert FakeConnection.rpc is original_rpc

    def test_tap_is_unpatched_even_when_body_raises(self, tmp_path: Path):
        original_rpc = _make_stub([])
        FakeConnection.rpc = original_rpc
        log_path = tmp_path / "session.json"
        with (
            pytest.raises(ValueError),
            RecordingLibjuju.start(
                log_path=log_path,
                model="m",
                tap=LibjujuTap(_connection_class=FakeConnection),
            ),
        ):
            raise ValueError("kaboom")
        assert FakeConnection.rpc is original_rpc

    def test_empty_session_writes_empty_events_list(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            pass
        doc = _read_log(log_path)
        assert doc["events"] == []

    def test_session_log_accessor_outside_context_raises(self, tmp_path: Path):
        rec = RecordingLibjuju(
            output_log_path=tmp_path / "session.json",
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        )
        with pytest.raises(RuntimeError, match="session_log only available"):
            _ = rec.session_log


# ---------------------------------------------------------------------------
# Test: multi-RPC ordering and seq monotonicity
# ---------------------------------------------------------------------------


class TestSequenceOrdering:
    def test_three_rpcs_produce_three_events_with_monotonic_seq(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {}},
                {"request-id": 2, "response": {}},
                {"request-id": 3, "response": {}},
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {"applications": [{"charm-url": "ch:a", "application-name": "a"}]},
                }
            )
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["a:ep", "b:ep"]},
                }
            )
            _run_rpc(
                {
                    "type": "Client",
                    "request": "Status",
                    "version": 6,
                    "params": {},
                }
            )

        ops = [e["op"] for e in _read_log(log_path)["events"]]
        seqs = [e["seq"] for e in _read_log(log_path)["events"]]
        assert ops == ["deploy", "integrate", "status"]
        assert seqs == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test: duration_ms in the written log — carry (a) from step-3
# ---------------------------------------------------------------------------


class TestDurationMsInLog:
    def test_duration_ms_present_on_every_event_in_log(self, tmp_path: Path):
        """Every emitted event must carry a numeric duration_ms field."""
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {"results": [{"tag": "application-my-charm"}]}},
                {"request-id": 2, "response": {}},
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:my-charm", "application-name": "my-charm"}
                        ]
                    },
                }
            )
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["my-charm:db", "pg:database"]},
                }
            )

        doc = _read_log(log_path)
        for ev in doc["events"]:
            assert "duration_ms" in ev, f"missing duration_ms on op={ev['op']}"
            assert isinstance(ev["duration_ms"], (int, float))
            assert ev["duration_ms"] >= 0

    def test_duration_ms_round_trips_through_json(self, tmp_path: Path):
        """Parsing the log back produces a float duration_ms, not a string."""
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "SetCharm",
                    "version": 20,
                    "params": {"application": "x"},
                }
            )

        doc = _read_log(log_path)
        assert len(doc["events"]) == 1
        raw_duration = doc["events"][0]["duration_ms"]
        assert isinstance(raw_duration, (int, float)), f"expected float, got {type(raw_duration)}"


# ---------------------------------------------------------------------------
# Test: wait_for_idle synthesis plumbed through RecordingLibjuju — carry (b)
# ---------------------------------------------------------------------------


class TestWaitForIdleSynthesisInRecording:
    def test_idle_threshold_seconds_kwarg_triggers_synthesis(self, tmp_path: Path):
        """idle_threshold_seconds=0 forces synthesis between every pair of RPCs."""
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {"results": [{"tag": "application-x"}]}},
                {"request-id": 2, "response": {}},
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
            idle_threshold_seconds=0.0,
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:x", "application-name": "x", "num-units": 1}
                        ]
                    },
                }
            )
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["x:db", "y:database"]},
                }
            )

        doc = _read_log(log_path)
        ops = [e["op"] for e in doc["events"]]
        assert "wait_for_idle" in ops
        # wait_for_idle appears between deploy and integrate
        wfi_idx = ops.index("wait_for_idle")
        assert ops[wfi_idx - 1] == "deploy"
        assert ops[wfi_idx + 1] == "integrate"

    def test_synthesised_wait_for_idle_has_duration_ms(self, tmp_path: Path):
        """The synthesised wait_for_idle event carries a non-negative duration_ms."""
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {}},
                {"request-id": 2, "response": {}},
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
            idle_threshold_seconds=0.0,
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:x", "application-name": "x"}
                        ]
                    },
                }
            )
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["x:db", "y:database"]},
                }
            )

        doc = _read_log(log_path)
        wfi = next(e for e in doc["events"] if e["op"] == "wait_for_idle")
        assert isinstance(wfi["duration_ms"], (int, float))
        assert wfi["duration_ms"] >= 0

    def test_default_threshold_suppresses_synthesis_for_fast_rpcs(self, tmp_path: Path):
        """Default 5-second threshold should not synthesise for instantaneous fake RPCs."""
        FakeConnection.rpc = _make_stub(
            [
                {"request-id": 1, "response": {}},
                {"request-id": 2, "response": {}},
            ]
        )
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:x", "application-name": "x"}
                        ]
                    },
                }
            )
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["x:db", "y:database"]},
                }
            )

        doc = _read_log(log_path)
        ops = [e["op"] for e in doc["events"]]
        assert "wait_for_idle" not in ops


# ---------------------------------------------------------------------------
# Test: Secrets.* bucket-1 round-trip through RecordingLibjuju (carry c)
# ---------------------------------------------------------------------------


class TestSecretsRecording:
    """Secrets.* RPCs promoted to bucket-1 write correct events to the log."""

    def test_create_secrets_writes_secret_add_event(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "CreateSecrets",
                    "version": 2,
                    "params": {
                        "secrets": [
                            {
                                "owner-tag": "application-myapp",
                                "label": "my-secret",
                                "content": {"data": {"password": "s3cr3t"}},
                                "description": "test cred",
                            }
                        ]
                    },
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "secret_add"
        assert ev["args"]["name"] == "my-secret"
        assert ev["args"]["content"] == {"password": "<REDACTED>"}
        assert ev["args"]["info"] == "test cred"
        # Content values must never appear in plaintext.
        assert "s3cr3t" not in json.dumps(ev)

    def test_update_secrets_writes_secret_update_event(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "UpdateSecrets",
                    "version": 2,
                    "params": {
                        "secrets": [
                            {
                                "existing-id": "secret:xyz789",
                                "content": {"data": {"token": "abc"}},
                                "auto-prune": False,
                            }
                        ]
                    },
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "secret_update"
        assert ev["args"]["identifier"] == "secret:xyz789"
        assert ev["args"]["content"] == {"token": "<REDACTED>"}
        assert "abc" not in json.dumps(ev)

    def test_remove_secrets_writes_secret_remove_event(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "RemoveSecrets",
                    "version": 2,
                    "params": {"secrets": [{"uri": "secret:abc123", "revisions": []}]},
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "secret_remove"
        assert ev["args"]["identifier"] == "secret:abc123"
        assert ev["args"]["revision"] is None

    def test_grant_secret_writes_secret_grant_event(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "GrantSecret",
                    "version": 2,
                    "params": {
                        "uri": "secret:abc123",
                        "scope-tag": "model-mymodel",
                        "applications": ["consumer-app"],
                    },
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "secret_grant"
        assert ev["args"]["identifier"] == "secret:abc123"
        assert ev["args"]["app"] == "consumer-app"

    def test_list_secrets_writes_secret_list_event(self, tmp_path: Path):
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "ListSecrets",
                    "version": 2,
                    "params": {"show-secrets": False, "filter": {}},
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "secret_list"
        assert ev["args"]["owner"] is None

    def test_revoke_secret_stays_shell_op(self, tmp_path: Path):
        """Secrets.RevokeSecret has no jubilant equivalent; must remain bucket-2."""
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "RevokeSecret",
                    "version": 2,
                    "params": {
                        "uri": "secret:abc123",
                        "scope-tag": "model-mymodel",
                        "applications": ["consumer-app"],
                    },
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert ev["op"] == "shell"
        assert "RevokeSecret" in ev["args"]["command"][0]

    def test_secret_add_event_has_canonical_envelope_keys(self, tmp_path: Path):
        """On-disk event must have exactly the canonical EventEnvelope key set."""
        FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
        log_path = tmp_path / "session.json"
        with RecordingLibjuju.start(
            log_path=log_path,
            model="m",
            tap=LibjujuTap(_connection_class=FakeConnection),
        ):
            _run_rpc(
                {
                    "type": "Secrets",
                    "request": "CreateSecrets",
                    "version": 2,
                    "params": {
                        "secrets": [{"label": "x", "content": {"data": {"k": "v"}}}]
                    },
                }
            )

        ev = _read_log(log_path)["events"][0]
        assert set(ev.keys()) == {
            "assertions",
            "args",
            "duration_ms",
            "gesture",
            "model_snapshot_after",
            "model_snapshot_before",
            "op",
            "result",
            "seq",
            "ts",
        }
