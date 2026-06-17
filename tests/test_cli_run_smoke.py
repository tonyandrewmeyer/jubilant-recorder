"""`recorder run -- /bin/true` round-trips through start, run, stop, generate."""

from __future__ import annotations

import ast
from pathlib import Path

from jubilant_recorder.cli import main


def test_run_round_trips(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    out = tmp_path / "test_recorded.py"
    rc = main(
        [
            "run",
            "--session-log",
            str(session_log),
            "--out",
            str(out),
            "--",
            "/bin/true",
        ]
    )
    assert rc == 0
    assert session_log.exists()
    assert out.exists()
    ast.parse(out.read_text())
    state_file = cache_dir / "jubilant-recorder" / "active.json"
    assert not state_file.exists()


def test_run_emits_valid_test_for_empty_session(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    session_log = tmp_path / "session.json"
    out = tmp_path / "test_empty.py"
    main(
        [
            "run",
            "--session-log",
            str(session_log),
            "--out",
            str(out),
            "--",
            "/bin/true",
        ]
    )
    src = out.read_text()
    assert "import jubilant" in src
    assert "def test_recorded_session" in src
