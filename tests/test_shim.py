from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SHIM_PATH = Path(__file__).parent.parent / "src" / "jubilant_recorder" / "shim" / "juju_shim.py"


def test_no_session_no_event(tmp_path: Path) -> None:
    """With no JTR_SESSION, the shim just execs real juju (here /usr/bin/true)."""
    env = {"_JTR_REAL_JUJU": "/usr/bin/true"}
    result = subprocess.run(
        [sys.executable, str(SHIM_PATH), "version"],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0


def test_session_appends_event(tmp_path: Path) -> None:
    """With JTR_SESSION set, the shim appends an event to JTR_LOG."""
    log_file = tmp_path / "test.jsonl"
    env = {
        "JTR_SESSION": "test-session",
        "JTR_LOG": str(log_file),
        "_JTR_REAL_JUJU": "/usr/bin/true",
    }
    result = subprocess.run(
        [sys.executable, str(SHIM_PATH), "version"],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["op"] == "shell"
    assert event["args"]["source"] == "shim"
    assert event["args"]["session_id"] == "test-session"
    assert event["args"]["argv"] == ["version"]


def _fake_juju(tmp_path: Path, *, script: str) -> str:
    """Write an executable stand-in for the real juju binary."""
    path = tmp_path / "fake-juju"
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(0o755)
    return str(path)


def _run(tmp_path: Path, argv: list[str], *, real_juju: str, **env_extra: str):
    log_file = tmp_path / "test.jsonl"
    env = {
        "JTR_SESSION": "test-session",
        "JTR_LOG": str(log_file),
        "_JTR_REAL_JUJU": real_juju,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        **env_extra,
    }
    result = subprocess.run(
        [sys.executable, str(SHIM_PATH), *argv], env=env, capture_output=True, text=True
    )
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    return result, [json.loads(line) for line in lines]


def test_exit_code_is_recorded(tmp_path: Path) -> None:
    """Codegen comments out a failed command, which needs the real status.

    The shim `execv`-ed before, so every recorded command looked like it had
    succeeded and the generated test asserted so.
    """
    juju = _fake_juju(tmp_path, script="exit 3")
    result, events = _run(tmp_path, ["deploy", "nope"], real_juju=juju)
    assert result.returncode == 3
    assert events[0]["result"]["exit_code"] == 3


def test_stdout_is_forwarded_and_captured_for_read_only_commands(tmp_path: Path) -> None:
    juju = _fake_juju(tmp_path, script="echo hello-from-juju")
    result, events = _run(tmp_path, ["whoami"], real_juju=juju)
    assert result.stdout == "hello-from-juju\n"  # the operator still sees it
    assert events[0]["result"]["captured"] is True
    assert events[0]["result"]["stdout"] == "hello-from-juju\n"


def test_stdout_is_not_captured_for_other_commands(tmp_path: Path) -> None:
    """Capturing `juju deploy` would hold its progress output back."""
    juju = _fake_juju(tmp_path, script="echo deploying")
    result, events = _run(tmp_path, ["deploy", "ubuntu"], real_juju=juju)
    assert result.stdout == "deploying\n"
    assert events[0]["result"]["captured"] is False
    assert events[0]["result"]["stdout"] is None


def test_status_captures_a_json_snapshot(tmp_path: Path) -> None:
    """`juju status` is the only sampling point a shell session has."""
    juju = _fake_juju(
        tmp_path,
        script='if [ "$2" = "--format" ]; then echo \'{"model":{}}\'; else echo TABULAR; fi',
    )
    result, events = _run(tmp_path, ["status"], real_juju=juju)
    assert result.stdout == "TABULAR\n"  # the operator's own view is untouched
    assert events[0]["result"]["status_json"] == '{"model":{}}\n'


def test_status_snapshot_can_be_turned_off(tmp_path: Path) -> None:
    juju = _fake_juju(tmp_path, script="echo TABULAR")
    _, events = _run(tmp_path, ["status"], real_juju=juju, JTR_NO_SNAPSHOT="1")
    assert events[0]["result"]["status_json"] is None


def test_secret_content_on_the_command_line_is_redacted(tmp_path: Path) -> None:
    """`juju add-secret` puts a live credential in argv, and argv is recorded."""
    juju = _fake_juju(tmp_path, script="exit 0")
    _, events = _run(tmp_path, ["add-secret", "mine", "token=hunter2"], real_juju=juju)
    argv = events[0]["args"]["argv"]
    assert argv == ["add-secret", "mine", "token=<redacted:token>"]


def test_url_credentials_in_argv_are_redacted(tmp_path: Path) -> None:
    juju = _fake_juju(tmp_path, script="exit 0")
    _, events = _run(
        tmp_path,
        ["config", "app", "uri=postgresql://user:pw@host/db"],
        real_juju=juju,
    )
    assert "user:pw@host" not in json.dumps(events[0])


def test_session_redact_patterns_are_applied(tmp_path: Path) -> None:
    """`jtr redact PATTERN` is documented for shell capture, so the shim honours it."""
    cache = tmp_path / "cache" / "jtr"
    cache.mkdir(parents=True)
    (cache / "test-session.json").write_text(json.dumps({"overrides": {"redact": [r"cust-\d+"]}}))
    juju = _fake_juju(tmp_path, script="exit 0")
    _, events = _run(tmp_path, ["deploy", "ubuntu", "cust-4711"], real_juju=juju)
    assert events[0]["args"]["argv"] == ["deploy", "ubuntu", "<redacted>"]


def test_paused_session_records_nothing(tmp_path: Path) -> None:
    juju = _fake_juju(tmp_path, script="exit 0")
    log_file = tmp_path / "test.jsonl"
    log_file.write_text("")
    subprocess.run(
        [sys.executable, str(SHIM_PATH), "status"],
        env={
            "JTR_SESSION": "s",
            "JTR_LOG": str(log_file),
            "JTR_PAUSED": "1",
            "_JTR_REAL_JUJU": juju,
        },
        capture_output=True,
    )
    assert log_file.read_text() == ""
