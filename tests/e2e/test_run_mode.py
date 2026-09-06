"""End-to-end: `jubilant-recorder run`, the all-in-one path.

`run` starts a session, executes a command under it, stops, and generates a
test — the entry point a first-time user is most likely to reach for. It also
exports JTR/JUBILANT_RECORDER_SESSION_LOG into the child, which nothing else
exercises against a real controller.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import REPO_ROOT, TEST_CHARM

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e


def test_run_records_a_child_script_and_generates(
    model: str, tmp_path: Path, recorder_env: dict[str, str]
):
    script = tmp_path / "recording_script.py"
    script.write_text(
        textwrap.dedent(f"""
        import os
        from jubilant_recorder.recording_juju import RecordingJuju

        log = os.environ["JUBILANT_RECORDER_SESSION_LOG"]
        with RecordingJuju.start(log, model={model!r}) as juju:
            juju.deploy({TEST_CHARM!r})
            juju.status()
        """)
    )

    log_path = tmp_path / "session.json"
    out_path = tmp_path / "test_out.py"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jubilant_recorder.cli",
            "run",
            "--session-log",
            str(log_path),
            "--out",
            str(out_path),
            # `run` has no --model of its own; the child script targets the
            # model itself, via RecordingJuju.start(model=...).
            "--",
            sys.executable,
            str(script),
        ],
        cwd=REPO_ROOT,
        env=recorder_env,
        capture_output=True,
        encoding="utf-8",
        timeout=900,
    )
    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"

    log = json.loads(log_path.read_text())
    ops = [e["op"] for e in log["events"]]
    assert "deploy" in ops, ops

    source = out_path.read_text()
    ast.parse(source)
    assert f"juju.deploy('{TEST_CHARM}'" in source, source
