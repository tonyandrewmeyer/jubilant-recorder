"""Golden-output regression tests over the recorded session logs.

``tests/fixtures/*.jsonl`` are real sessions captured against live Juju by
the scripts in ``examples/``. They are the only end-to-end evidence that the
whole pipeline — quiet-window synthesis, tagging, codegen — still produces
what it produced yesterday, so each one is run through that pipeline and
diffed against a committed expected file in ``tests/fixtures/golden/``.

To update a golden file after an intentional codegen change:

    JTR_UPDATE_GOLDEN=1 uv run pytest tests/codegen/test_recorded_sessions_golden.py

Then read the diff before committing it. An unexplained change here means
codegen moved under you.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from jubilant_recorder import codegen, quiet_window, tagger

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden"

# Recorded sessions, with the test name each should generate.
RECORDED = [
    "deliberate_failures",
    "deploy_ubuntu",
    "deploy_ubuntu_with_gesture",
    "k8s_wait_timeout",
    "postgresql_config_action",
    "postgresql_integrate",
]


def _generate(name: str) -> str:
    """Run the full offline pipeline, exactly as `generate` does without --ai."""
    log = json.loads((FIXTURES / f"{name}.jsonl").read_text())
    log = quiet_window.synthesize(log)
    annotated = tagger.tag(log, proposer=None)
    return codegen.generate(annotated, test_name=f"test_{name}")


@pytest.mark.parametrize("name", RECORDED)
def test_recorded_session_matches_golden(name: str):
    actual = _generate(name)
    golden_path = GOLDEN / f"{name}.py"

    if os.environ.get("JTR_UPDATE_GOLDEN"):
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual)
        pytest.skip(f"updated golden file {golden_path.name}")

    assert golden_path.exists(), (
        f"missing golden file {golden_path}. Generate it with "
        f"JTR_UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}"
    )
    assert actual == golden_path.read_text(), (
        f"codegen output for {name}.jsonl no longer matches "
        f"{golden_path.name}. If the change is intended, regenerate with "
        f"JTR_UPDATE_GOLDEN=1 and review the diff."
    )


@pytest.mark.parametrize("name", RECORDED)
def test_recorded_session_output_is_valid_python(name: str):
    """A generated test that does not parse is useless regardless of content."""
    ast.parse(_generate(name))
