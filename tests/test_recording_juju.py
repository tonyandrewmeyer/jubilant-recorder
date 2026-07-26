from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from jubilant_recorder.recording_juju import RecordingJuju
from jubilant_recorder.session_log import SessionLog

if TYPE_CHECKING:
    from pathlib import Path

MINIMAL_STATUS_JSON = json.dumps(
    {
        "model": {
            "name": "test",
            "type": "iaas",
            "controller": "ctrl",
            "cloud": "lxd",
            "version": "3.6.0",
        },
        "machines": {},
        "applications": {},
    }
)

MINIMAL_RUN_JSON = json.dumps(
    {
        "my-charm/0": {
            "id": "1",
            "status": "completed",
            "return-code": 0,
            "results": {"output": "done", "return-code": 0},
            "message": "",
        }
    }
)


def _make_juju(tmp_path: Path) -> tuple[RecordingJuju, SessionLog, Path]:
    log_path = tmp_path / "session.json"
    log = SessionLog(log_path)
    juju = RecordingJuju(session_log=log)
    return juju, log, log_path


class TestDeployEmitsOneEvent:
    def test_deploy_emits_one_event(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
        ):
            juju.deploy("my-charm", channel="edge")
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "deploy"
        assert ev["seq"] == 1
        assert ev["args"]["charm"] == "my-charm"
        assert ev["args"]["channel"] == "edge"
        assert ev["ts"] != ""

    def test_deploy_captures_full_kwarg_surface(self, tmp_path):
        """Carry from step 3: the recorder previously dropped ``base``,
        ``revision``, ``trust``, ``constraints`` and friends. Make sure
        the full jubilant.deploy kwarg surface survives into the args
        dict so codegen can faithfully round-trip the invocation."""
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
        ):
            juju.deploy(
                "ubuntu",
                "ubuntu",
                base="ubuntu@24.04",
                channel="latest/stable",
                revision=42,
                trust=True,
                constraints={"mem": "2G"},
                to="0",
                force=True,
            )
        log.close()
        doc = json.loads(log_path.read_text())
        args = doc["events"][0]["args"]
        assert args["charm"] == "ubuntu"
        assert args["app"] == "ubuntu"
        assert args["base"] == "ubuntu@24.04"
        assert args["channel"] == "latest/stable"
        assert args["revision"] == 42
        assert args["trust"] is True
        assert args["constraints"] == {"mem": "2G"}
        assert args["to"] == "0"
        assert args["force"] is True


class TestRunEmitsEventWithResult:
    def test_run_emits_event_with_result(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=(MINIMAL_RUN_JSON, "")),
        ):
            juju.run("my-charm/0", "do-thing")
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "run"
        assert ev["result"]["success"] is True
        assert "output" in ev["result"]["results"]


class TestWaitEmitsWaitForIdleEvent:
    def test_wait_emits_wait_for_idle_event(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        from jubilant.statustypes import Status

        fake_status = Status._from_dict(json.loads(MINIMAL_STATUS_JSON))
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju.wait", return_value=fake_status),
        ):
            juju.wait(lambda s: True)
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "wait_for_idle"
        assert ev["result"]["settled_at"] is not None


class TestStatusEmitsStatusEvent:
    def test_status_emits_status_event(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=(MINIMAL_STATUS_JSON, "")),
        ):
            juju.status()
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "status"
        assert isinstance(ev["result"]["snapshot"], (dict, type(None)))


class TestIntegrateEmitsEvent:
    def test_integrate_emits_event(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
        ):
            juju.integrate("app1:rel", "app2:rel")
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        ev = doc["events"][0]
        assert ev["op"] == "integrate"
        assert ev["args"]["app1_endpoint"] == "app1:rel"
        assert ev["args"]["app2_endpoint"] == "app2:rel"


class TestSessionErrorRecordedOnException:
    def test_session_error_recorded_on_exception(self, tmp_path):
        log_path = tmp_path / "session.json"
        with (
            pytest.raises(RuntimeError, match="boom"),
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
            RecordingJuju.start(log_path) as juju,
        ):
            juju.deploy("my-charm")
            raise RuntimeError("boom")
        doc = json.loads(log_path.read_text())
        ops = [e["op"] for e in doc["events"]]
        assert "session.error" in ops
        error_event = next(e for e in doc["events"] if e["op"] == "session.error")
        assert "boom" in error_event["result"]["error"]


class TestTimingFieldsPopulated:
    def test_timing_fields_populated(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
        ):
            juju.deploy("my-charm")
        log.close()
        doc = json.loads(log_path.read_text())
        ev = doc["events"][0]
        assert ev["ts"] != ""
        assert "T" in ev["ts"]
        assert ev["duration_ms"] >= 0


class TestMultipleEventsSeqIncrements:
    def test_multiple_events_seq_increments(self, tmp_path):
        juju, log, log_path = _make_juju(tmp_path)
        with (
            patch.object(RecordingJuju, "_take_snapshot", return_value=None),
            patch("jubilant.Juju._cli", return_value=("", "")),
        ):
            juju.deploy("my-charm")
            juju.integrate("app1:rel", "app2:rel")
        log.close()
        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 2
        assert doc["events"][0]["seq"] == 1
        assert doc["events"][1]["seq"] == 2
