"""End-to-end: cross-model relations, against a real controller.

CMR is where the translation surface is thinnest and where a live run found
the most: `juju offer`'s dotted `model.app` form (the only way to offer from
a model you are not switched to) was refused by the classifier, and the
libjuju path wrote the controller password to the session log.

These do not replay what they generate, and that is the finding rather than
a gap: a cross-model relation needs two models and a generated test opens
one, so its offer URLs name a model the test does not create. The generated
source says so, and this checks that it does.
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

from tests.e2e.conftest import CMR_CHARM, CMR_ENDPOINT, REPO_ROOT, _juju, wait_for_unit

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


def _shim_juju(env: dict[str, str], *args: str, timeout: int = 600) -> None:
    proc = subprocess.run(
        ["juju", *args], env=env, capture_output=True, encoding="utf-8", timeout=timeout
    )
    assert proc.returncode == 0, f"juju {' '.join(args)} failed:\n{proc.stderr}"


def test_a_cross_model_session_translates(
    model: str, second_model: str, tmp_path: Path, shim_env: dict[str, str]
):
    """Offer in one model, consume in another, tear both down."""
    offer_name = "e2eoffer"
    offer_url = f"admin/{model}.{offer_name}"
    _juju("deploy", CMR_CHARM, "-m", model, timeout=900)
    wait_for_unit(model, CMR_CHARM)

    # `juju offer` takes no `--model`: the model goes in the app name.
    _shim_juju(shim_env, "offer", f"{model}.{CMR_CHARM}:{CMR_ENDPOINT}", offer_name)
    _shim_juju(shim_env, "offers", "-m", model)
    _shim_juju(shim_env, "show-offer", "-m", model, offer_url)
    _shim_juju(shim_env, "consume", "-m", second_model, offer_url, "remote")
    _shim_juju(shim_env, "remove-saas", "-m", second_model, "remote")
    _shim_juju(shim_env, "remove-offer", offer_url, "--force", "-y")

    out = tmp_path / "test_cmr.py"
    _jtr("generate", "--session-log", shim_env["JTR_LOG"], "--out", str(out), env=shim_env)
    source = out.read_text()
    ast.parse(source)

    # The dotted offer is the one a live run found being refused.
    assert f"juju.offer('{model}.{CMR_CHARM}', endpoint='{CMR_ENDPOINT}'" in source, source
    assert f"juju.consume('{offer_url}', 'remote')" in source, source
    assert 'juju.cli("offers"' in source, source
    assert 'juju.cli("show-offer"' in source, source
    assert "juju.cli(\"remove-saas\", 'remote')" in source, source
    assert 'juju.cli("remove-offer"' in source, source
    assert "# shell:" not in source, source

    # And the thing a generated CMR test cannot do for itself.
    assert f"reference offers in model {model}" in source, source


def test_a_libjuju_cross_model_session_records_no_credentials(
    model: str, second_model: str, tmp_path: Path
):
    """`Model.connect()` sends `Admin.Login`, whose params carry the password.

    It reached the session log in plaintext, and the generated test as a
    `# TODO: manual step` block. This is the regression test for that, and
    it needs a real connection — a fake one never sends a login.
    """
    juju_module = pytest.importorskip("juju", reason="needs the libjuju extra")
    del juju_module
    import asyncio

    from juju.model import Model

    from jubilant_recorder.extensions.libjuju.recording import RecordingLibjuju

    offer_name = "ljoffer"
    _juju("deploy", CMR_CHARM, "-m", model, timeout=900)
    wait_for_unit(model, CMR_CHARM)

    log_path = tmp_path / "session.json"

    async def run() -> None:
        offering = Model()
        await offering.connect(model_name=model)
        consuming = Model()
        await consuming.connect(model_name=second_model)
        try:
            with RecordingLibjuju(output_log_path=log_path, model=model):
                await offering.create_offer(f"{CMR_CHARM}:{CMR_ENDPOINT}", offer_name=offer_name)
                await consuming.consume(f"admin/{model}.{offer_name}", application_alias="remote")
                await consuming.remove_saas("remote")
                await offering.remove_offer(f"admin/{model}.{offer_name}", force=True)
        finally:
            await offering.disconnect()
            await consuming.disconnect()

    asyncio.run(run())

    raw = log_path.read_text()
    log = json.loads(raw)
    ops = [e["op"] for e in log["events"]]
    assert "create_offer" in ops, ops
    assert "consume" in ops, ops
    assert "remove_offer" in ops, ops

    # A login is not a step the user performed.
    assert "_todo" not in ops, ops
    assert "Admin" not in raw, "the connection handshake reached the log"
    # And nothing that looks like a credential, whatever facade carried it.
    for event in log["events"]:
        for key, value in (event.get("args") or {}).items():
            if "credential" in key.lower() or "password" in key.lower():
                assert str(value).startswith("<redacted:"), (key, value)
