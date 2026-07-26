"""`recorder stop` finalises the log and removes the state file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jubilant_recorder.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def test_stop_removes_state_file_and_log_is_well_formed(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    main(["start", "--session-log", str(session_log)])
    state_file = cache_dir / "jubilant-recorder" / "active.json"
    assert state_file.exists()
    rc = main(["stop"])
    assert rc == 0
    assert not state_file.exists()
    assert session_log.exists()
    doc = json.loads(session_log.read_text())
    assert doc["schema_version"] == 1
    assert isinstance(doc["events"], list)


def test_stop_with_no_state_file_returns_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    rc = main(["stop"])
    assert rc == 1


def test_stop_finalises_a_missing_log(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    main(["start", "--session-log", str(session_log)])
    session_log.unlink()
    rc = main(["stop"])
    assert rc == 0
    assert session_log.exists()
    doc = json.loads(session_log.read_text())
    assert doc["schema_version"] == 1
