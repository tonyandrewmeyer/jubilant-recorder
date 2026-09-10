"""Multi-test module generation — the shape a migrated suite needs."""

from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder.codegen import generate_module


def _log(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "session_id": "s", "events": events}


def _deploy(seq: int, charm: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "deploy",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"charm": charm},
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def test_tests_share_one_module_scoped_model() -> None:
    """A pytest-operator suite's tests build on each other, so these must too.

    Giving each recorded test its own `temp_model()` would hand every test
    after the first an empty model and fail on state it never created.
    """
    src = generate_module(
        [
            ("test_deploy", _log([_deploy(1, "ubuntu")])),
            ("test_scale", _log([_deploy(2, "postgresql")])),
        ]
    )
    ast.parse(src)
    assert '@pytest.fixture(scope="module")' in src
    assert "with jubilant.temp_model() as juju:" in src
    assert src.count("temp_model") == 1
    assert "def test_deploy(juju: jubilant.Juju):" in src
    assert "def test_scale(juju: jubilant.Juju):" in src


def test_bodies_are_indented_for_the_fixture_form() -> None:
    src = generate_module([("test_deploy", _log([_deploy(1, "ubuntu")]))])
    assert "\n    juju.deploy('ubuntu')\n" in src


def test_test_order_is_preserved() -> None:
    """pytest-operator tests are order-dependent, so the file must keep it."""
    src = generate_module(
        [
            ("test_c", _log([_deploy(1, "c")])),
            ("test_a", _log([_deploy(2, "a")])),
            ("test_b", _log([_deploy(3, "b")])),
        ]
    )
    assert src.index("def test_c") < src.index("def test_a") < src.index("def test_b")


def test_a_test_that_recorded_nothing_still_has_a_body() -> None:
    """Some tests only assert; the file still has to parse."""
    src = generate_module([("test_nothing", _log([]))])
    ast.parse(src)
    assert "def test_nothing(juju: jubilant.Juju):\n    pass" in src


def test_empty_input_produces_an_importable_module() -> None:
    src = generate_module([])
    ast.parse(src)
    assert "import jubilant" in src


def _deploy_with_prior_state(seq: int, charm: str) -> dict[str, Any]:
    event = _deploy(seq, charm)
    event["model_snapshot_before"] = {
        "schema_version": 1,
        "captured_at": "2026-09-10T10:00:00.000Z",
        "apps": {
            "ubuntu": {
                "units": {
                    "ubuntu/0": {
                        "workload_status": "active",
                        "workload_message": "",
                        "agent_status": "idle",
                    }
                }
            }
        },
        "relations": [],
    }
    return event


def test_only_the_first_test_warns_about_a_non_empty_starting_model() -> None:
    """For the rest, that state is what the tests before them deployed.

    Every test after the first started from a model the earlier ones had
    filled, so warning on each buried the real steps under a five-line note
    that was also wrong.
    """
    src = generate_module(
        [
            ("test_first", _log([_deploy_with_prior_state(1, "ubuntu")])),
            ("test_second", _log([_deploy_with_prior_state(2, "postgresql")])),
            ("test_third", _log([_deploy_with_prior_state(3, "redis")])),
        ]
    )
    assert src.count("# NOTE: this session was recorded") == 1
    assert src.index("# NOTE:") < src.index("def test_second")
