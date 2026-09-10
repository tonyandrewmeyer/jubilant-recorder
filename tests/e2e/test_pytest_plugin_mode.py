"""End-to-end: recording an unmodified pytest-operator suite.

The unit suite drives the plugin through `pytester` with libjuju absent —
enough to prove the hook wiring and the module shape, not that the thing
works. This runs a real `pytest-operator` suite against a real controller
and reads what came out, which is the only way to find out whether the
correlator understands what libjuju actually sends.

Needs `pytest-operator` as well as the `libjuju` extra; both are skipped for
rather than assumed, since neither is a dependency of this package.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import REPO_ROOT, TEST_CHARM

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e

# Skipping here would report a green run that tested nothing, the same way a
# missing controller would — so `JTR_E2E_REQUIRE` (set in CI) makes a missing
# dependency a failure rather than a skip. See `tests/e2e/conftest.py`.
for _module, _hint in (
    ("juju", "needs the libjuju extra"),
    ("pytest_operator", "needs pytest-operator"),
):
    if importlib.util.find_spec(_module) is None:
        if os.environ.get("JTR_E2E_REQUIRE"):
            pytest.fail(f"JTR_E2E_REQUIRE is set but {_module} is not importable: {_hint}")
        pytest.skip(_hint, allow_module_level=True)

_SUITE = f'''
import pytest
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest):
    await ops_test.model.deploy("{TEST_CHARM}", application_name="{TEST_CHARM}")
    await ops_test.model.wait_for_idle(
        apps=["{TEST_CHARM}"], status="active", timeout=900
    )


async def test_read_config(ops_test: OpsTest):
    config = await ops_test.model.applications["{TEST_CHARM}"].get_config()
    assert isinstance(config, dict)


async def test_remove(ops_test: OpsTest):
    await ops_test.model.remove_application("{TEST_CHARM}", block_until_done=True)
'''

_CONFIG = """
[pytest]
asyncio_mode = auto
"""


def test_records_a_real_pytest_operator_suite(tmp_path: Path, juju_controller: str):
    suite_dir = tmp_path / "suite"
    (suite_dir / "tests" / "integration").mkdir(parents=True)
    (suite_dir / "tests" / "integration" / "test_charm.py").write_text(_SUITE)
    (suite_dir / "pytest.ini").write_text(_CONFIG)
    out = tmp_path / "test_migrated.py"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_charm.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--jtr-out={out}",
        ],
        cwd=suite_dir,
        capture_output=True,
        encoding="utf-8",
        timeout=2400,
        env={**_env(), "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert proc.returncode == 0, f"the recorded suite failed:\n{proc.stdout}\n{proc.stderr}"

    # The recorder must never fail the suite it is recording, and a warning
    # is how it says it could not record something.
    assert "recording failed and was discarded" not in proc.stdout, proc.stdout

    source = out.read_text()
    ast.parse(source)
    # One test per recorded test, sharing one model — the shape a
    # pytest-operator suite already has.
    assert '@pytest.fixture(scope="module")' in source
    assert source.count("temp_model") == 1
    for name in ("test_deploy", "test_read_config", "test_remove"):
        assert f"def {name}(juju: jubilant.Juju):" in source, source

    assert "juju.deploy(" in source
    # The wait each test ends on used to be lost, taking the assertion with it.
    assert "workload_status.current == 'active'" in source, source
    assert f"juju.remove_application('{TEST_CHARM}')" in source, source

    logs = sorted(p.name for p in (tmp_path / "test_migrated-sessions").glob("*.json"))
    assert logs == ["test_deploy.json", "test_read_config.json", "test_remove.json"]
    # Nothing should have been left unmapped that jubilant can express.
    for log_path in (tmp_path / "test_migrated-sessions").glob("*.json"):
        ops = [e["op"] for e in json.loads(log_path.read_text())["events"]]
        assert "_todo" not in ops, f"{log_path.name} has unmapped RPCs: {ops}"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("JTR_SESSION", None)
    env.pop("JTR_LOG", None)
    return env


def test_the_migrated_module_replays_green(tmp_path: Path, juju_controller: str):
    """Record a suite, then run what came out of it.

    The claim the migration path makes is "a decent starting point", and a
    starting point that does not run is not one. This does not check the
    module covers what the original covered — it cannot, the assertions the
    original made never reached the wire — only that everything it does
    contain works.
    """
    suite_dir = tmp_path / "suite"
    (suite_dir / "tests" / "integration").mkdir(parents=True)
    (suite_dir / "tests" / "integration" / "test_charm.py").write_text(_SUITE)
    (suite_dir / "pytest.ini").write_text(_CONFIG)
    out = tmp_path / "test_migrated.py"

    record = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_charm.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--jtr-out={out}",
        ],
        cwd=suite_dir,
        capture_output=True,
        encoding="utf-8",
        timeout=2400,
        env={**_env(), "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert record.returncode == 0, f"{record.stdout}\n{record.stderr}"

    replay = subprocess.run(
        [sys.executable, "-m", "pytest", str(out), "-v", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=2400,
    )
    assert replay.returncode == 0, (
        f"the migrated module did not pass:\n{replay.stdout}\n{replay.stderr}\n"
        f"--- generated source ---\n{out.read_text()}"
    )
