"""Step 10 (fixture branch): codegen marks ops it can't represent.

The regression bar (PLAN.md step 10) is: codegen MUST NOT crash on failed
operations, partial deploys, or multi-unit applications with mixed
statuses. Each generated file must be syntactically valid Python and carry
a skip/TODO marker for the unrepresentable step. Representable ops in the
same log must still be emitted normally.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from jubilant_recorder import codegen, tagger
from jubilant_recorder.codegen import unrepresentable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "step10"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _generate(name: str) -> str:
    return codegen.generate(tagger.tag(_load(name)), test_name=f"test_{name}")


@pytest.mark.parametrize(
    "name", ["failed_deploy", "partial_deploy", "multi_unit_mixed", "multiple_failures"]
)
def test_fixture_generates_valid_python(name: str) -> None:
    src = _generate(name)
    ast.parse(src)  # the regression bar: never crash, always valid Python.


def test_failed_deploy_skips_on_error_state_and_failed_wait() -> None:
    src = _generate("failed_deploy")
    ast.parse(src)
    # The deploy CLI call succeeded, so it is still replayed...
    assert "juju.deploy('my-charm'" in src
    # ...the error-state model emits the first (and only) pytest.skip...
    assert "import pytest" in src
    assert src.count("pytest.skip(reason=") == 1
    assert "codegen can't represent units in error state: my-charm/0" in src
    # ...and the timed-out wait that follows is marked unreachable, not re-skipped.
    assert "codegen can't represent failed wait_for_idle" in src
    assert "unreachable" in src


def test_multiple_failures_collapse_trailing_skips() -> None:
    src = _generate("multiple_failures")
    ast.parse(src)
    # The successful deploy is emitted normally.
    assert "juju.deploy('good-charm'" in src
    # Only the first failing step emits pytest.skip.
    assert "import pytest" in src
    assert src.count("pytest.skip(reason=") == 1
    # The second failure is marked unreachable rather than adding a dead skip.
    assert src.count("unreachable") == 1
    assert "codegen can't represent failed wait_for_idle: timed out" in src


def test_partial_deploy_keeps_representable_ops_and_skips_timeout() -> None:
    src = _generate("partial_deploy")
    ast.parse(src)
    # Representable ops are emitted normally.
    assert "juju.deploy('my-charm'" in src
    assert "juju.deploy('postgresql'" in src
    assert "juju.integrate('my-charm:db', 'postgresql:database')" in src
    # The wait_for_idle that never settled is skipped.
    assert "pytest.skip(reason=" in src
    assert "codegen can't represent failed wait_for_idle" in src


def test_multi_unit_mixed_emits_comment_not_skip() -> None:
    src = _generate("multi_unit_mixed")
    ast.parse(src)
    # The scale call is replayed; only its mixed end-state is unrepresentable.
    assert "juju.add_unit('my-charm', num_units=3)" in src
    assert "codegen can't represent mixed unit statuses for my-charm" in src
    # A mixed status is a comment-only marker — the test keeps running.
    assert "pytest.skip" not in src
    assert "import pytest" not in src


def test_classify_returns_none_for_representable_event() -> None:
    event = {
        "op": "deploy",
        "args": {"charm": "my-charm"},
        "result": {"app_name": "my-charm"},
        "model_snapshot_after": {
            "apps": {"my-charm": {"units": {"my-charm/0": {"workload_status": "active"}}}},
            "relations": [],
        },
    }
    assert unrepresentable.classify(event) is None


def test_classify_failed_op_takes_priority() -> None:
    event = {
        "op": "deploy",
        "args": {"charm": "my-charm"},
        "result": {"app_name": "my-charm", "error": "boom"},
        "model_snapshot_after": None,
    }
    finding = unrepresentable.classify(event)
    assert finding is not None
    assert finding.kind == "failed"
    assert finding.needs_skip


def test_classify_ignores_mixed_for_non_multi_unit_ops() -> None:
    # A `run` op never triggers the multi-unit-mixed branch even if the
    # model happens to hold mixed statuses.
    event = {
        "op": "run",
        "args": {"unit": "my-charm/0", "action": "noop"},
        "result": {"success": True, "results": {}},
        "model_snapshot_after": {
            "apps": {
                "my-charm": {
                    "units": {
                        "my-charm/0": {"workload_status": "active"},
                        "my-charm/1": {"workload_status": "blocked"},
                    }
                }
            },
            "relations": [],
        },
    }
    assert unrepresentable.classify(event) is None
