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
import warnings
from pathlib import Path
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# In CI a missing controller means provisioning broke, and skipping would
# report that as a green, empty run. Set JTR_E2E_REQUIRE=1 to turn every
# "no controller" skip into a failure.
REQUIRE_CONTROLLER = bool(os.environ.get("JTR_E2E_REQUIRE"))

# charm-ubuntu is the smallest thing that actually reaches active on a machine
# cloud, and it is what examples/ has always used. It has no Kubernetes
# build, so a k8s run needs a different one — see the `test_charm` fixture.
TEST_CHARM = "ubuntu"
K8S_TEST_CHARM = "snappass-test"

# The workload container `snappass-test` declares, for the `--container`
# flags that only mean anything on Kubernetes.
K8S_WORKLOAD_CONTAINER = "snappass"


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
def cloud_type(juju_controller: str) -> str:
    """``"caas"`` for a Kubernetes controller, ``"iaas"`` for a machine one.

    Juju's behaviour forks on this in ways the recorder has to follow —
    `add-unit` versus `scale-application`, `remove-unit`'s `-n`, the
    `--container` flags, `trust --scope cluster`, and the shape of
    `juju status --format json` itself. Running the suite against only one
    of the two leaves the other's translations unexercised.
    """
    controllers = json.loads(_juju("controllers", "--format", "json", timeout=120))
    cloud = (controllers.get("controllers") or {}).get(juju_controller, {}).get("cloud", "")
    clouds = json.loads(_juju("clouds", "--format", "json", "--all", timeout=120))
    for name, details in (clouds or {}).items():
        # `juju clouds` prefixes some entries (`localhost` vs `lxd`), so
        # match on the tail rather than the whole key.
        if name == cloud or name.endswith(f"/{cloud}"):
            return "caas" if (details or {}).get("type") in ("k8s", "kubernetes") else "iaas"
    # An unknown cloud is a controller we cannot characterise, and guessing
    # wrong means deploying a machine charm to Kubernetes and waiting for a
    # timeout to explain it.
    _no_controller(f"could not determine the cloud type of controller {juju_controller!r}")


@pytest.fixture(scope="session")
def test_charm(cloud_type: str) -> str:
    """The smallest charm that reaches active on the controller under test."""
    return K8S_TEST_CHARM if cloud_type == "caas" else TEST_CHARM


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
    # `juju controllers` answers from the local cache, so it succeeds against a
    # controller that is half-bootstrapped or gone — it reported a healthy
    # controller here while every API call failed with "no controller API
    # addresses". Only an actual API call proves reachability.
    try:
        _juju("models", "--format", "json", timeout=120)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        _no_controller(f"controller is registered but not reachable: {exc}")
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

    Teardown is best-effort and never fails the test. `--no-wait` means
    "do not wait for each step", not "return immediately": juju still polls
    until the model is gone, and on Kubernetes an empty model has been seen
    take longer than ten minutes to finish (namespace finalisers, not
    anything the test did). Turning that into an ERROR on a test that
    passed reports a controller's mood as a product failure.
    """
    name = f"jtr-e2e-{uuid.uuid4().hex[:8]}"
    # -c explicitly: there may be no current controller (see juju_controller).
    _juju("add-model", "--no-switch", "-c", juju_controller, name)
    try:
        yield name
    finally:
        _destroy_model_best_effort(f"{juju_controller}:{name}")


def _destroy_model_best_effort(qualified_name: str) -> None:
    """Ask juju to destroy a model, and carry on regardless of the answer."""
    try:
        proc = subprocess.run(
            ["juju", "destroy-model", "--no-prompt", "--force", "--no-wait", qualified_name],
            capture_output=True,
            encoding="utf-8",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        warnings.warn(
            f"{qualified_name} did not finish destroying in 180s; it is still going "
            f"in the background and the next run's `juju models` will show it",
            stacklevel=2,
        )
        return
    if proc.returncode != 0:
        warnings.warn(
            f"could not destroy {qualified_name}: {proc.stderr.strip()}",
            stacklevel=2,
        )


@pytest.fixture
def recorder_env() -> dict[str, str]:
    """Environment for running the recorder as a subprocess from the checkout."""
    env = dict(os.environ)
    env.pop("JTR_SESSION", None)
    env.pop("JTR_LOG", None)
    env.pop("JTR_PAUSED", None)
    return env
