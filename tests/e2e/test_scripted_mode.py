"""End-to-end: the scripted recording path, against a real controller.

This is the mode the README documents — wrap `jubilant.Juju` in
`RecordingJuju`, drive a real deployment, and generate a test from what was
recorded. It is the only mode where the whole pipeline (recording, snapshots,
tagging, codegen) runs against live Juju output rather than a fixture.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e


def test_record_deploy_and_generate(model: str, tmp_path: Path, test_charm: str):
    """Record a deploy, then generate a test that reflects it."""
    from jubilant_recorder import gestures
    from jubilant_recorder.recording_juju import RecordingJuju

    log_path = tmp_path / "session.json"

    with RecordingJuju.start(log_path, model=model) as juju:
        juju.deploy(test_charm)
        juju.wait(lambda s: all(u.is_active for u in s.apps[test_charm].units.values()))
        gestures.assert_status(test_charm, "active")
        gestures.checkpoint("deployed")

    log = json.loads(log_path.read_text())
    ops = [e["op"] for e in log["events"]]
    assert "deploy" in ops, ops
    assert "checkpoint" in ops, ops

    # Snapshots are the part that only a live controller can exercise: the
    # fixtures cannot prove `juju status` still parses into what codegen wants.
    deploy_event = next(e for e in log["events"] if e["op"] == "deploy")
    assert deploy_event["model_snapshot_after"] is not None
    assert test_charm in deploy_event["model_snapshot_after"]["apps"]

    out = tmp_path / "test_generated.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "jubilant_recorder.cli",
            "generate",
            str(log_path),
            "--out",
            str(out),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    source = out.read_text()
    ast.parse(source)
    assert f"juju.deploy('{test_charm}'" in source, source
    assert "# checkpoint: deployed" in source, source
    assert "# TODO: manual step" not in source, source


def test_generated_test_replays_green(model: str, tmp_path: Path, test_charm: str):
    """The generated test is the product. Run it, and require it to pass.

    Everything else here checks that codegen *emits* something plausible.
    This checks that what it emits actually works, which is the only claim
    the project really makes.
    """
    from jubilant_recorder.recording_juju import RecordingJuju

    log_path = tmp_path / "session.json"
    with RecordingJuju.start(log_path, model=model) as juju:
        juju.deploy(test_charm)
        juju.wait(lambda s: all(u.is_active for u in s.apps[test_charm].units.values()))

    generated = tmp_path / "test_replay.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "jubilant_recorder.cli",
            "generate",
            str(log_path),
            "--out",
            str(generated),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )

    # The generated test uses jubilant.temp_model(), so it builds its own
    # model and needs nothing from the fixture beyond a working controller.
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
