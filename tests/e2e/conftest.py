"""Shared machinery for the end-to-end suite.

These tests need a real Juju controller. They are deselected by default —
see ``pytest_collection_modifyitems`` — so the unit suite stays offline and
fast. Run them with:

    uv run pytest tests/e2e --e2e

or set ``JTR_E2E=1``. CI provisions the controller with concierge; see
``.github/workflows/e2e.yaml``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# In CI a missing controller means provisioning broke, and skipping would
# report that as a green, empty run. Set JTR_E2E_REQUIRE=1 to turn every
# "no controller" skip into a failure.
REQUIRE_CONTROLLER = bool(os.environ.get("JTR_E2E_REQUIRE"))

# charm-ubuntu is the smallest thing that actually reaches active on a machine
# cloud, and it is what examples/ has always used.
TEST_CHARM = "ubuntu"


def _no_controller(reason: str) -> NoReturn:
    """Skip, or fail if the environment says a controller must be there."""
    if REQUIRE_CONTROLLER:
        pytest.fail(f"JTR_E2E_REQUIRE is set but {reason}")
    pytest.skip(reason)


def _juju(*args: str, timeout: int = 600) -> str:
    """Run a juju command, raising with its stderr if it fails."""
    proc = subprocess.run(
        ["juju", *args],
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"juju {' '.join(args)} failed:\n{proc.stderr}")
    return proc.stdout


@pytest.fixture(scope="session")
def juju_controller() -> str:
    """Name of the controller under test, skipping if there is not one."""
    if shutil.which("juju") is None:
        _no_controller("juju is not on PATH")
    try:
        out = _juju("controllers", "--format", "json", timeout=60)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        _no_controller(f"no reachable juju controller: {exc}")
    data = json.loads(out)
    current = data.get("current-controller")
    if current:
        return current
    # A controller bootstrapped with --no-switch leaves current-controller
    # empty. One unambiguous controller is still a usable answer.
    names = list(data.get("controllers") or {})
    if len(names) == 1:
        return names[0]
    if not names:
        _no_controller("no juju controller is bootstrapped")
    _no_controller(f"no current controller and {len(names)} to choose from: {names}")


@pytest.fixture
def model(juju_controller: str):
    """An empty model, torn down afterwards.

    Named per-test so a failed run leaves something identifiable behind, and
    destroyed with --force so a stuck unit cannot wedge the whole suite.
    """
    name = f"jtr-e2e-{uuid.uuid4().hex[:8]}"
    # -c explicitly: there may be no current controller (see juju_controller).
    _juju("add-model", "--no-switch", "-c", juju_controller, name)
    try:
        yield name
    finally:
        subprocess.run(
            [
                "juju",
                "destroy-model",
                "--no-prompt",
                "--force",
                "--no-wait",
                f"{juju_controller}:{name}",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=600,
        )


@pytest.fixture
def recorder_env() -> dict[str, str]:
    """Environment for running the recorder as a subprocess from the checkout."""
    env = dict(os.environ)
    env.pop("JTR_SESSION", None)
    env.pop("JTR_LOG", None)
    env.pop("JTR_PAUSED", None)
    return env
