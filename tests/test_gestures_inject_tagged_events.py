"""Each gesture call appends the documented event shape into the session log."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from jubilant_recorder import RecordingJuju, assert_action_result, assert_status, checkpoint


def _open(tmp_path: Path):
    log_path = tmp_path / "session.json"
    return RecordingJuju.start(log_path), log_path


def test_checkpoint_appends_checkpoint_event(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        ctx as _juju,
    ):
        checkpoint("phase one")
    doc = json.loads(log_path.read_text())
    assert len(doc["events"]) == 1
    ev = doc["events"][0]
    assert ev["op"] == "checkpoint"
    assert ev["gesture"]["kind"] == "checkpoint"
    assert ev["gesture"]["label"] == "phase one"
    assert ev["gesture"]["params"] == {}
    assert ev["seq"] == 1


def test_checkpoint_with_comment(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        ctx,
    ):
        checkpoint("phase", comment="deploy done")
    doc = json.loads(log_path.read_text())
    ev = doc["events"][0]
    assert "deploy done" in ev["gesture"]["label"]


def test_assert_status_appends_wait_for_idle_with_gesture(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        ctx,
    ):
        assert_status("my-charm", "active")
    doc = json.loads(log_path.read_text())
    assert len(doc["events"]) == 1
    ev = doc["events"][0]
    assert ev["op"] == "wait_for_idle"
    assert ev["gesture"]["kind"] == "assert_status"
    assert ev["gesture"]["params"]["app"] == "my-charm"
    assert ev["gesture"]["params"]["status"] == "active"


def test_assert_status_no_args_emits_todo(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        ctx,
    ):
        assert_status()
    doc = json.loads(log_path.read_text())
    ev = doc["events"][0]
    assert ev["op"] == "checkpoint"
    assert "TODO" in ev["gesture"]["label"]


def test_assert_action_result_attaches_to_recent_run(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    minimal_run = json.dumps(
        {
            "my-charm/0": {
                "id": "1",
                "status": "completed",
                "return-code": 0,
                "results": {"output": "done"},
                "message": "",
            }
        }
    )
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        patch("jubilant.Juju._cli", return_value=(minimal_run, "")),
        ctx as juju,
    ):
        juju.run("my-charm/0", "do-thing")
        assert_action_result("latest", key="output", value="done")
    doc = json.loads(log_path.read_text())
    run_events = [e for e in doc["events"] if e["op"] == "run"]
    assert len(run_events) == 1
    gesture = run_events[0]["gesture"]
    assert gesture["kind"] == "assert_action_result"
    assert gesture["params"]["unit"] == "my-charm/0"
    assert gesture["params"]["action"] == "do-thing"
    assert gesture["params"]["expected_results"] == {"output": "done"}


def test_seq_monotonic_with_gestures(tmp_path: Path) -> None:
    ctx, log_path = _open(tmp_path)
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        ctx,
    ):
        checkpoint("a")
        checkpoint("b")
        checkpoint("c")
    doc = json.loads(log_path.read_text())
    seqs = [e["seq"] for e in doc["events"]]
    assert seqs == [1, 2, 3]
