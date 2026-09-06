from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from jubilant_recorder.events import EventEnvelope
from jubilant_recorder.session_log import SessionLog, _format_ts


def _make_event(seq: int) -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        seq=seq,
        op="deploy",
        ts=_format_ts(now),
        args={"charm": "test-charm", "channel": None},
        result={"app_name": "test-charm"},
        model_snapshot_before=None,
        model_snapshot_after=None,
        assertions=[],
        gesture=None,
        duration_ms=123.0,
    )


class TestRoundTripJson:
    def test_round_trip_json(self, tmp_path):
        log_path = tmp_path / "session.json"
        log = SessionLog(log_path)
        log.append_event(_make_event(log.next_seq()))
        log.append_event(_make_event(log.next_seq()))
        log.close()

        doc = json.loads(log_path.read_text())
        assert doc["schema_version"] == 1
        assert len(doc["events"]) == 2


def _without_recorded_at(text: str) -> str:
    return re.sub(r'"recorded_at": "[^"]*"', '"recorded_at": "<normalised>"', text)


class TestKeyOrderingStable:
    def test_key_ordering_stable(self, tmp_path):
        log_path_a = tmp_path / "a.json"
        log_path_b = tmp_path / "b.json"

        # Build the event once and reuse it for both logs: the property under
        # test is that identical logical content yields byte-identical files.
        # Re-deriving the event per file would otherwise race on the `ts`
        # millisecond timestamp captured in `_make_event`.
        event = _make_event(1)
        for path in (log_path_a, log_path_b):
            log = SessionLog.__new__(SessionLog)
            log._log_path = path
            log._model = "test"
            log._session_id = "fixed-uuid"
            log._juju_version = "3.6.0"
            log._jubilant_version = "1.10.0"
            log._events = []
            log._seq = 0
            log.append_event(event)
            log.close()

        # close() stamps recorded_at from the wall clock, so the two writes
        # differ whenever they straddle a millisecond boundary. That is the
        # one field that is legitimately time-dependent; normalise it out
        # rather than leaving a test that fails a few runs in a thousand.
        assert _without_recorded_at(log_path_a.read_text()) == _without_recorded_at(
            log_path_b.read_text()
        )


class TestSortKeysInOutput:
    def test_sort_keys_in_output(self, tmp_path):
        log_path = tmp_path / "session.json"
        log = SessionLog(log_path)
        log.append_event(_make_event(log.next_seq()))
        log.close()

        raw = log_path.read_text()
        assert raw.index('"assertions"') < raw.index('"duration_ms"')


class TestSessionErrorRecorded:
    def test_session_error_recorded(self, tmp_path):
        log_path = tmp_path / "session.json"
        log = SessionLog(log_path)
        log.record_session_error(ValueError("oops"))
        log.close()

        doc = json.loads(log_path.read_text())
        assert len(doc["events"]) == 1
        assert doc["events"][0]["op"] == "session.error"
        assert doc["events"][0]["result"]["error"] == "oops"


class TestSeqIncrements:
    def test_seq_increments(self, tmp_path):
        log_path = tmp_path / "session.json"
        log = SessionLog(log_path)
        for _ in range(3):
            log.append_event(_make_event(log.next_seq()))
        log.close()

        doc = json.loads(log_path.read_text())
        seqs = [e["seq"] for e in doc["events"]]
        assert seqs == [1, 2, 3]


class TestContextManagerClosesOnException:
    def test_context_manager_closes_on_exception(self, tmp_path):
        log_path = tmp_path / "session.json"
        with pytest.raises(RuntimeError), SessionLog.open(log_path) as log:
            log.append_event(_make_event(log.next_seq()))
            raise RuntimeError("test error")

        assert log_path.exists()
        doc = json.loads(log_path.read_text())
        assert doc["schema_version"] == 1
        assert len(doc["events"]) == 1


def test_open_accepts_a_string_path(tmp_path):
    """The README's gesture-API example passes a str, so str has to work.

    Regression: close() wrote through Path.write_text, so a str path raised
    AttributeError at the end of a session, after the recording was done.
    """
    log_path = tmp_path / "session.json"

    with SessionLog.open(str(log_path)) as log:
        assert log is not None

    assert log_path.is_file()
