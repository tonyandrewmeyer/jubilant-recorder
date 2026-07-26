from __future__ import annotations

import argparse
import ast
from typing import TYPE_CHECKING

from jubilant_recorder.jtr_cli import cmd_generate

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

FIXTURE_LINES = [
    '{"seq": 1, "op": "shell_context", "ts": "2026-07-16T00:00:00.000Z", '
    '"args": {"argv": ["curl -s https://example.com/ -o /dev/null"], "basename": "curl", '
    '"source": "hook", "session_id": "abc123"}, "result": {"exit_code": 0, "stdout": null, '
    '"stderr": null, "stdout_truncated": false}, "model_snapshot_before": null, '
    '"model_snapshot_after": null, "assertions": [], "gesture": null}',
    '{"seq": 2, "op": "shell", "ts": "2026-07-16T00:00:01.000Z", '
    '"args": {"argv": ["--version"], "basename": "juju", "source": "shim", '
    '"session_id": "abc123"}, "result": {"captured": false, "exit_code": null}, '
    '"model_snapshot_before": null, "model_snapshot_after": null, "assertions": [], '
    '"gesture": null}',
    '{"seq": 3, "op": "note", "ts": "2026-07-16T00:00:02.000Z", '
    '"args": {"text": "this is a note"}, "result": {}, "model_snapshot_before": null, '
    '"model_snapshot_after": null, "assertions": [], "gesture": null}',
    '{"seq": 4, "op": "session_end", "ts": "2026-07-16T00:00:03.000Z", "args": {}, '
    '"result": {}, "model_snapshot_before": null, "model_snapshot_after": null, '
    '"assertions": [], "gesture": null}',
]


def _write_fixture(path: Path) -> None:
    path.write_text("\n".join(FIXTURE_LINES) + "\n")


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_generate_stdout_mode(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    log_path = tmp_path / "session.jsonl"
    _write_fixture(log_path)

    rc = cmd_generate(_ns(session_log=str(log_path), out=None, name=None))
    assert rc == 0

    source = capsys.readouterr().out
    ast.parse(source)
    assert "def test_recorded_session" in source
    assert "# context: curl -s https://example.com/ -o /dev/null" in source
    assert "# shell: juju --version" in source
    assert "# note: this is a note" in source
    # session_end is an in-band sentinel, not a step to translate.
    assert "session_end" not in source


def test_generate_out_file_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "session.jsonl"
    _write_fixture(log_path)
    out_path = tmp_path / "test_recorded.py"

    rc = cmd_generate(_ns(session_log=str(log_path), out=str(out_path), name="test_my_session"))
    assert rc == 0

    source = out_path.read_text()
    ast.parse(source)
    assert "def test_my_session" in source


def test_generate_empty_file_error(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    log_path = tmp_path / "empty.jsonl"
    log_path.write_text("")

    rc = cmd_generate(_ns(session_log=str(log_path), out=None, name=None))
    assert rc != 0
    assert "no events" in capsys.readouterr().err


def test_generate_missing_session_log_error(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JTR_LOG", raising=False)

    rc = cmd_generate(_ns(session_log=None, out=None, name=None))
    assert rc != 0
    assert "JTR_LOG" in capsys.readouterr().err


def test_generate_session_log_not_found_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    missing = tmp_path / "missing.jsonl"
    rc = cmd_generate(_ns(session_log=str(missing), out=None, name=None))
    assert rc != 0
    assert "not found" in capsys.readouterr().err
