from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from jubilant_recorder.jtr_cli import _hook_event_impl

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run_jtr(*args: str, env: dict | None = None, **kwargs) -> subprocess.CompletedProcess:
    base_env = {k: v for k, v in os.environ.items()}
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "jubilant_recorder.jtr_cli", *args],
        env=base_env,
        capture_output=True,
        text=True,
        **kwargs,
    )


def test_hook_event_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    session_id = "test-session"
    # Write a minimal state file
    state_dir = tmp_path / "cache" / "jtr"
    state_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    state = {
        "session_id": session_id,
        "session_name": "test",
        "log_path": str(log_file),
        "started_at": "2026-06-28T10:00:00.000Z",
        "shared": False,
        "overrides": {"include": [], "exclude": [], "redact": []},
    }
    (state_dir / f"{session_id}.json").write_text(json.dumps(state))
    _hook_event_impl(session_id, "kubectl get pods", 0, 0, str(log_file))
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["op"] == "shell_context"
    assert event["args"]["basename"] == "kubectl"
    assert event["args"]["source"] == "hook"


def test_hook_event_paused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    monkeypatch.setenv("JTR_PAUSED", "1")
    _hook_event_impl("test-session", "kubectl get pods", 0, 0, str(log_file))
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 0


def test_hook_event_denied(tmp_path: Path) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    _hook_event_impl("test-session", "ls -la", 0, 0, str(log_file))
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 0


def test_hook_event_not_allowlisted(tmp_path: Path) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    _hook_event_impl("test-session", "git status", 0, 0, str(log_file))
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 0


def test_include_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    session_id = "test-session-inc"
    state_dir = tmp_path / "cache" / "jtr"
    state_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    state = {
        "session_id": session_id,
        "session_name": "test",
        "log_path": str(log_file),
        "started_at": "2026-06-28T10:00:00.000Z",
        "shared": False,
        "overrides": {"include": ["git"], "exclude": [], "redact": []},
    }
    (state_dir / f"{session_id}.json").write_text(json.dumps(state))
    _hook_event_impl(session_id, "git status", 0, 0, str(log_file))
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["op"] == "shell_context"
    assert event["args"]["basename"] == "git"


def test_note_event_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    monkeypatch.setenv("JTR_SESSION", "test-session")
    monkeypatch.setenv("JTR_LOG", str(log_file))
    result = _run_jtr(
        "note",
        "some important note",
        env={
            "JTR_SESSION": "test-session",
            "JTR_LOG": str(log_file),
        },
    )
    assert result.returncode == 0
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["op"] == "note"
    assert event["args"]["text"] == "some important note"
    assert event["seq"] == 1


def test_tag_event_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "test.jsonl"
    log_file.touch()
    result = _run_jtr(
        "tag",
        "scale up",
        env={
            "JTR_SESSION": "test-session",
            "JTR_LOG": str(log_file),
        },
    )
    assert result.returncode == 0
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["op"] == "tag"
    assert event["args"]["label"] == "scale up"
    assert event["seq"] == 1


def test_session_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    # Remove JTR_SESSION from env so start doesn't fail
    env_no_session = {k: v for k, v in os.environ.items() if k != "JTR_SESSION"}
    env_no_session["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        [sys.executable, "-m", "jubilant_recorder.jtr_cli", "start", "mytest"],
        env=env_no_session,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    stdout = result.stdout
    # Parse exports
    exports = {}
    for line in stdout.splitlines():
        if line.startswith("export "):
            rest = line[len("export ") :]
            if "=" in rest:
                k, v = rest.split("=", 1)
                exports[k] = v
    assert "JTR_SESSION" in exports
    assert "JTR_LOG" in exports
    session_id = exports["JTR_SESSION"]
    log_path = exports["JTR_LOG"]
    # Now stop
    env_with_session = dict(env_no_session)
    env_with_session["JTR_SESSION"] = session_id
    env_with_session["JTR_LOG"] = log_path
    result2 = subprocess.run(
        [sys.executable, "-m", "jubilant_recorder.jtr_cli", "stop"],
        env=env_with_session,
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0
    assert "unset JTR_SESSION" in result2.stdout
    assert "unset JTR_LOG" in result2.stdout


# --- shell-init snippet ---


def test_shell_init_bash_registers_functions_into_arrays() -> None:
    """B1 — bash-preexec iterates preexec_functions/precmd_functions arrays and
    ignores bare `preexec`/`precmd` names; the snippet must register them."""
    result = _run_jtr("shell-init", "--shell", "bash", "--no-path-shim")
    assert result.returncode == 0
    assert "preexec_functions+=(preexec)" in result.stdout
    assert "precmd_functions+=(precmd)" in result.stdout


def test_shell_init_zsh_omits_bash_preexec_note() -> None:
    """B2 — the `bash-preexec must be sourced BEFORE this block` header is
    bash-specific; zsh has native `preexec`/`precmd` and doesn't need it."""
    result = _run_jtr("shell-init", "--shell", "zsh", "--no-path-shim")
    assert result.returncode == 0
    assert "bash-preexec" not in result.stdout


def test_shell_init_zsh_does_not_register_into_arrays() -> None:
    """Zsh's native preexec/precmd are called by name; the bash-specific
    array-registration would be a no-op at best, confusing at worst."""
    result = _run_jtr("shell-init", "--shell", "zsh", "--no-path-shim")
    assert "preexec_functions" not in result.stdout
    assert "precmd_functions" not in result.stdout


# --- include / exclude / tail filters ---


def test_include_exclude_are_regexes_over_the_command_line(tmp_path, monkeypatch) -> None:
    """`jtr include 'terraform .*'` is the documented shape.

    Both lists were compared against the *basename* before, so every
    documented example (all of which are patterns, not bare words) silently
    did nothing.
    """
    from jubilant_recorder.jtr_cli import _hook_event_impl, _state_file

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    log = tmp_path / "s.jsonl"
    log.write_text("")
    state = _state_file("sess")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "overrides": {
                    "include": [r"terraform .*"],
                    "exclude": [r"kubectl logs .*"],
                    "redact": [],
                }
            }
        )
    )

    def record(cmd: str) -> None:
        _hook_event_impl("sess", cmd, 0, 0, str(log))

    record("terraform apply -auto-approve")  # included by pattern
    record("kubectl logs pod/x")  # excluded by pattern
    record("kubectl get pods")  # on the default allowlist
    record("cargo build")  # not allowlisted, not included

    recorded = [json.loads(line)["args"]["argv"][0] for line in log.read_text().splitlines()]
    assert recorded == ["terraform apply -auto-approve", "kubectl get pods"]


def test_tail_filters_select_lanes() -> None:
    """Both flags were on the parser but never read."""
    from jubilant_recorder.jtr_cli import _tail_wanted

    juju_event = {"op": "shell"}
    context_event = {"op": "shell_context"}
    note = {"op": "note"}

    assert _tail_wanted(juju_event, jubilant_only=True, context_only=False)
    assert not _tail_wanted(context_event, jubilant_only=True, context_only=False)
    assert not _tail_wanted(note, jubilant_only=True, context_only=False)

    assert not _tail_wanted(juju_event, jubilant_only=False, context_only=True)
    assert _tail_wanted(context_event, jubilant_only=False, context_only=True)

    # The end sentinel always gets through, or `jtr tail` never returns.
    assert _tail_wanted({"op": "session_end"}, jubilant_only=True, context_only=False)


def test_notes_are_redacted(tmp_path, monkeypatch) -> None:
    """A note is free text the operator typed, so it can carry a credential.

    It was the one thing in shell capture that redaction never touched.
    """
    import argparse

    from jubilant_recorder.jtr_cli import _state_file, cmd_note

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    log = tmp_path / "s.jsonl"
    log.write_text("")
    monkeypatch.setenv("JTR_SESSION", "sess")
    monkeypatch.setenv("JTR_LOG", str(log))
    state = _state_file("sess")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"overrides": {"redact": [r"cust-\d+"]}}))

    cmd_note(argparse.Namespace(text="token=hunter2 for cust-4711"))

    text = json.loads(log.read_text().strip())["args"]["text"]
    assert "hunter2" not in text
    assert "cust-4711" not in text
