"""`recorder start` writes a state file with the documented shape."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jubilant_recorder.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def test_start_writes_state(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    rc = main(["start", "--session-log", str(session_log), "--model", "test-model"])
    assert rc == 0
    state_file = cache_dir / "jubilant-recorder" / "active.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["session_log_path"] == str(session_log)
    assert state["model"] == "test-model"
    assert isinstance(state["pid"], int)
    assert "started_at" in state


def test_start_creates_empty_session_log(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    main(["start", "--session-log", str(session_log)])
    assert session_log.exists()
    doc = json.loads(session_log.read_text())
    assert doc["schema_version"] == 1
    assert doc["events"] == []
