"""End-to-end: the libjuju recording front-end, against a real controller.

The unit suite drives `LibjujuTap` through a fake `Connection` that replays
canned RPC responses. That proves the correlation logic, but it cannot prove
the tap still attaches to python-libjuju's real `Connection.rpc`, or that a
live AllWatcher delta burst looks like what `correlate.py` expects. Both are
things libjuju can change under us, and both are invisible until someone
records a real session.

Needs the `libjuju` extra: `uv sync --extra dev --extra libjuju`.
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e

pytest.importorskip("juju", reason="needs the libjuju extra")


def test_records_a_live_libjuju_session(model: str, tmp_path: Path, test_charm: str):
    """Tap a real libjuju deployment and generate a test from it."""
    from juju.model import Model

    from jubilant_recorder.extensions.libjuju.recording import RecordingLibjuju

    log_path = tmp_path / "session.json"

    async def run() -> None:
        m = Model()
        await m.connect(model_name=model)
        try:
            with RecordingLibjuju(output_log_path=log_path, model=model):
                await m.deploy(test_charm, application_name=test_charm)
                await m.wait_for_idle(apps=[test_charm], timeout=900, status="active")
        finally:
            await m.disconnect()

    asyncio.run(run())

    log = json.loads(log_path.read_text())
    ops = [e["op"] for e in log["events"]]
    assert "deploy" in ops, ops

    # The tap's whole point is that a libjuju session lands in the same schema
    # as a jubilant one, so the shared tagger and codegen can consume it.
    assert log["schema_version"] >= 1
    deploy = next(e for e in log["events"] if e["op"] == "deploy")
    assert deploy["args"].get("charm"), deploy

    out = tmp_path / "test_from_libjuju.py"
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
    # libjuju's DeployFromRepository reports the *resolved* charm URL
    # (`ch:amd64/noble/ubuntu`), not the name the caller passed, so match on
    # the application rather than the charm string.
    assert "juju.deploy(" in source, source
    assert f"app='{test_charm}'" in source, source
