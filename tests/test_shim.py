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
