from __future__ import annotations

import argparse
import os
import stat
from typing import TYPE_CHECKING

from jubilant_recorder.jtr_cli import cmd_shim_install

if TYPE_CHECKING:
    from pathlib import Path


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_shim_install_writes_executable_shim(tmp_path: Path) -> None:
    target = tmp_path / "shims"
    rc = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc == 0

    shim_path = target / "juju"
    assert shim_path.exists()
    mode = stat.S_IMODE(os.stat(shim_path).st_mode)
    assert mode & stat.S_IXUSR

    content = shim_path.read_text()
    assert "/usr/bin/true" in content
    assert "__REAL_JUJU__" not in content


def test_shim_install_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "shims"
    rc1 = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc1 == 0
    first_content = (target / "juju").read_text()

    rc2 = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc2 == 0
    second_content = (target / "juju").read_text()

    assert first_content == second_content


def test_shim_install_no_real_juju_error(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    target = tmp_path / "shims"
    rc = cmd_shim_install(_ns(target=str(target), real_juju=None))
    assert rc != 0
    assert "--real-juju" in capsys.readouterr().err


def test_shim_install_adds_an_interpreter_line(tmp_path: Path) -> None:
    """Without a shebang the kernel hands the shim to sh and juju stops working."""
    target = tmp_path / "shims"
    assert cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true")) == 0

    first_line = (target / "juju").read_text().splitlines()[0]
    assert first_line.startswith("#!"), f"installed shim has no interpreter line: {first_line!r}"


def test_installed_shim_actually_runs_and_records(tmp_path: Path) -> None:
    """Execute the installed shim the way PATH resolution would.

    The pre-existing tests here check the executable bit and the REAL_JUJU
    substitution, both of which passed while the installed file was
    unrunnable -- it had no interpreter line, so every line was a shell
    syntax error and the real juju was never exec'd. This runs it.
    """
    import json
    import subprocess

    target = tmp_path / "shims"
    assert cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true")) == 0

    log = tmp_path / "session.jsonl"
    env = {
        **os.environ,
        "JTR_SESSION": "shim-exec-test",
        "JTR_LOG": str(log),
    }
    env.pop("JTR_PAUSED", None)
    env.pop("JTR_PYTHON_ACTIVE", None)

    proc = subprocess.run(  # noqa: S603
        [str(target / "juju"), "status", "-m", "somemodel"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"shim did not run: {proc.stderr!r}"

    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(events) == 1, f"expected one recorded event, got {events}"
    assert events[0]["op"] == "shell"
    assert events[0]["args"]["argv"] == ["status", "-m", "somemodel"]
    assert events[0]["args"]["source"] == "shim"


def test_installed_shim_is_a_passthrough_with_no_session(tmp_path: Path) -> None:
    """No JTR_SESSION means exec the real juju and record nothing."""
    import subprocess

    target = tmp_path / "shims"
    assert cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true")) == 0

    log = tmp_path / "session.jsonl"
    env = {**os.environ, "JTR_LOG": str(log)}
    for key in ("JTR_SESSION", "JTR_PAUSED", "JTR_PYTHON_ACTIVE"):
        env.pop(key, None)

    proc = subprocess.run([str(target / "juju"), "status"], env=env, capture_output=True, text=True)  # noqa: S603
    assert proc.returncode == 0, f"shim did not run: {proc.stderr!r}"
    assert not log.exists() or log.read_text().strip() == ""
