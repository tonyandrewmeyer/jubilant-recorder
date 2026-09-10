"""End-to-end: what the PATH shim actually captures, against a real controller.

`test_shell_capture_mode.py` covers that the shim records *something*. This
covers the three things it records beyond the argv — the exit code, the
status snapshot, and the redaction — because each one is the difference
between a generated test that runs and one that lies, and none of them can
be checked without a real juju to run against.
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


@pytest.fixture
def shim_env(tmp_path: Path, recorder_env: dict[str, str]) -> dict[str, str]:
    """A shell environment with the shim installed and a session running."""
    shim_dir = tmp_path / "shims"
    real_juju = shutil.which("juju")
    assert real_juju, "juju not on PATH"
    _jtr("shim", "install", "--target", str(shim_dir), "--real-juju", real_juju, env=recorder_env)

    env = dict(recorder_env)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["JTR_SESSION"] = str(uuid.uuid4())
    env["JTR_LOG"] = str(tmp_path / "session.jsonl")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    return env


def _events(env: dict[str, str]) -> list[dict]:
    from pathlib import Path as _Path

    text = _Path(env["JTR_LOG"]).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _juju(env: dict[str, str], *args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["juju", *args], env=env, capture_output=True, encoding="utf-8", timeout=timeout
    )


def test_a_failed_command_records_its_exit_code(model: str, shim_env: dict[str, str]):
    """Otherwise the generated test asserts a command worked when it did not."""
    proc = _juju(shim_env, "deploy", "no-such-charm-exists-zzz", "-m", model)
    assert proc.returncode != 0, "expected juju to reject the charm"

    (event,) = _events(shim_env)
    assert event["result"]["exit_code"] == proc.returncode


def test_a_failed_command_is_commented_out_of_the_generated_test(
    model: str, shim_env: dict[str, str], tmp_path: Path
):
    _juju(shim_env, "deploy", "no-such-charm-exists-zzz", "-m", model)

    out = tmp_path / "test_failed.py"
    _jtr("generate", "--session-log", shim_env["JTR_LOG"], "--out", str(out), env=shim_env)
    source = out.read_text()
    ast.parse(source)
    assert "# juju.deploy('no-such-charm-exists-zzz')" in source
    assert "\n        juju.deploy(" not in source


def test_status_captures_a_snapshot(model: str, shim_env: dict[str, str]):
    """The only sampling point a shell session has."""
    assert _juju(shim_env, "status", "-m", model).returncode == 0

    (event,) = _events(shim_env)
    snapshot = json.loads(event["result"]["status_json"])
    assert snapshot["model"]["name"] == model


def test_two_statuses_around_a_deploy_produce_an_assertion(
    model: str, shim_env: dict[str, str], tmp_path: Path
):
    """The whole point of capturing status: a shell session that asserts.

    Before the snapshot capture existed, a test generated from a shell
    session had no assertions in it at all, whatever the operator checked.
    """
    assert _juju(shim_env, "status", "-m", model).returncode == 0
    assert _juju(shim_env, "deploy", "ubuntu", "-m", model).returncode == 0
    assert (
        _juju(
            shim_env, "wait-for", "application", "ubuntu", "-m", model, "--timeout", "20m"
        ).returncode
        == 0
    )
    assert _juju(shim_env, "status", "-m", model).returncode == 0

    out = tmp_path / "test_asserts.py"
    _jtr("generate", "--session-log", shim_env["JTR_LOG"], "--out", str(out), env=shim_env)
    source = out.read_text()
    ast.parse(source)
    assert "juju.deploy('ubuntu')" in source
    assert "workload_status.current == 'active'" in source, source


def test_a_secret_on_the_command_line_is_not_written_to_the_log(
    model: str, shim_env: dict[str, str]
):
    assert (
        _juju(shim_env, "add-secret", "e2e-secret", "token=hunter2", "-m", model).returncode == 0
    )

    (event,) = _events(shim_env)
    assert "hunter2" not in json.dumps(event)
    assert "token=<redacted:token>" in event["args"]["argv"]


def test_the_model_flag_does_not_reach_the_generated_test(
    model: str, shim_env: dict[str, str], tmp_path: Path
):
    """The recording's model does not exist when the test runs."""
    assert _juju(shim_env, "status", "-m", model).returncode == 0

    out = tmp_path / "test_model_flag.py"
    _jtr("generate", "--session-log", shim_env["JTR_LOG"], "--out", str(out), env=shim_env)
    source = out.read_text()
    assert model not in source
    assert "juju.status()" in source


def test_the_generated_test_replays_green(model: str, shim_env: dict[str, str], tmp_path: Path):
    """The generated test is the product. Run it, and require it to pass.

    Everything else here checks the log holds the right thing. This is the
    only check that the jubilant calls the log turns into are ones jubilant
    will actually accept — a plausible-looking kwarg that does not exist
    reads fine and raises TypeError.
    """
    assert _juju(shim_env, "status", "-m", model).returncode == 0
    assert _juju(shim_env, "deploy", "ubuntu", "-m", model).returncode == 0
    assert (
        _juju(
            shim_env, "wait-for", "application", "ubuntu", "-m", model, "--timeout", "20m"
        ).returncode
        == 0
    )
    assert _juju(shim_env, "status", "-m", model).returncode == 0
    assert _juju(shim_env, "config", "ubuntu", "-m", model).returncode == 0
    assert _juju(shim_env, "exec", "--unit", "ubuntu/0", "-m", model, "--", "true").returncode == 0

    generated = tmp_path / "test_replay_from_shell.py"
    _jtr("generate", "--session-log", shim_env["JTR_LOG"], "--out", str(generated), env=shim_env)

    # The generated test opens its own `temp_model()`, so it needs nothing
    # from the fixture model beyond a working controller.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(generated), "-v", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=2400,
    )
    assert proc.returncode == 0, (
        f"the generated test did not pass:\n{proc.stdout}\n{proc.stderr}\n"
        f"--- generated source ---\n{generated.read_text()}"
    )
