"""End-to-end: shell capture, against a real controller.

Shell capture has two independent lanes:

* the **PATH shim**, which intercepts `juju` itself, and
* the **preexec/precmd hook**, which records surrounding context commands.

Only the shim lane is exercised here, and that is deliberate rather than an
oversight: bash-preexec fires from the DEBUG trap and PROMPT_COMMAND, both of
which need a real prompt cycle. A script body does not have one, and driving
`bash -i` over a pipe does not reliably produce one either, so a scripted
harness records zero events whether the hook works or not — which is
indistinguishable from it being broken. `scripts/verify-shell-hook.sh` exists
because that lane has to be checked by a person at a terminal.

The shim lane has no such problem: it is an exec wrapper that only reads
JTR_SESSION and JTR_LOG from the environment, so it records identically
whether a human or a script invoked juju. Since juju is what the shim lane is
for, this covers the part that matters for recording.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import uuid
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e


def _jtr(*args: str, env: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "jubilant_recorder.jtr_cli", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
    )
    assert proc.returncode == 0, f"jtr {' '.join(args)} failed:\n{proc.stderr}"
    return proc


def test_shim_records_real_juju_commands(model: str, tmp_path: Path, recorder_env: dict[str, str]):
    """Install the shim, run real juju through it, and read back the log."""
    shim_dir = tmp_path / "shims"
    real_juju = shutil.which("juju")
    assert real_juju, "juju not on PATH"

    _jtr(
        "shim",
        "install",
        "--target",
        str(shim_dir),
        "--real-juju",
        real_juju,
        env=recorder_env,
    )
    shim = shim_dir / "juju"
    assert shim.is_file() and os.access(shim, os.X_OK), "shim was not installed executable"

    log_path = tmp_path / "session.jsonl"
    session_id = str(uuid.uuid4())
    env = dict(recorder_env)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["JTR_SESSION"] = session_id
    env["JTR_LOG"] = str(log_path)

    # Resolve through PATH, so this genuinely goes via the shim rather than
    # calling the shim by its own path.
    for args in (["status", "-m", model], ["models"]):
        proc = subprocess.run(
            ["juju", *args], env=env, capture_output=True, encoding="utf-8", timeout=300
        )
        assert proc.returncode == 0, f"juju {' '.join(args)} failed:\n{proc.stderr}"

    events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    shell = [e for e in events if e["op"] in ("shell", "shell_context")]
    assert len(shell) == 2, f"expected 2 recorded juju commands, got {len(shell)}: {events}"
    for event in shell:
        assert event["args"]["basename"] == "juju"
        assert event["args"]["source"] == "shim"
        assert event["args"]["session_id"] == session_id
    assert shell[0]["args"]["argv"][0] == "status"
    assert shell[1]["args"]["argv"][0] == "models"


def test_shim_is_transparent_when_no_session(tmp_path: Path, recorder_env: dict[str, str]):
    """With JTR_SESSION unset the shim must exec juju and record nothing.

    This is the property that makes it safe to leave the shim on PATH.
    """
    shim_dir = tmp_path / "shims"
    real_juju = shutil.which("juju")
    assert real_juju
    _jtr("shim", "install", "--target", str(shim_dir), "--real-juju", real_juju, env=recorder_env)

    log_path = tmp_path / "session.jsonl"
    env = dict(recorder_env)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["JTR_LOG"] = str(log_path)  # set, but no JTR_SESSION

    proc = subprocess.run(
        ["juju", "version"], env=env, capture_output=True, encoding="utf-8", timeout=120
    )
    assert proc.returncode == 0
    assert proc.stdout.strip(), "shim did not pass juju's output through"
    assert not log_path.exists(), "shim recorded despite no active session"


def test_shell_session_generates_a_test(model: str, tmp_path: Path, recorder_env: dict[str, str]):
    """A shell-captured session must reach codegen, not just the log."""
    shim_dir = tmp_path / "shims"
    real_juju = shutil.which("juju")
    assert real_juju
    _jtr("shim", "install", "--target", str(shim_dir), "--real-juju", real_juju, env=recorder_env)

    log_path = tmp_path / "session.jsonl"
    env = dict(recorder_env)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["JTR_SESSION"] = str(uuid.uuid4())
    env["JTR_LOG"] = str(log_path)

    subprocess.run(
        ["juju", "deploy", "ubuntu", "-m", model],
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=600,
        check=True,
    )

    out = tmp_path / "test_from_shell.py"
    # `jtr generate` takes --session-log, unlike `jubilant-recorder generate`,
    # which takes the log positionally.
    _jtr("generate", "--session-log", str(log_path), "--out", str(out), env=recorder_env)
    source = out.read_text()
    ast.parse(source)
    assert "deploy" in source, source
