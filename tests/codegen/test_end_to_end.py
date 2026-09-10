from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder.codegen import generate


def _parses(source: str) -> ast.Module:
    return ast.parse(source)


def test_empty_log_parses() -> None:
    src = generate({"events": []})
    module = _parses(src)
    assert "def test_recorded_session" in src
    assert any(isinstance(n, ast.FunctionDef) for n in module.body)


def test_custom_test_name() -> None:
    src = generate({"events": []}, test_name="test_my_charm")
    _parses(src)
    assert "def test_my_charm()" in src


def test_import_jubilant_present() -> None:
    src = generate({"events": []})
    assert src.startswith("import jubilant\n")


def test_temp_model_used() -> None:
    src = generate({"events": []})
    assert "with jubilant.temp_model() as juju:" in src


def test_deploy_only(deploy_log: dict[str, Any]) -> None:
    src = generate(deploy_log)
    _parses(src)
    assert "juju.deploy('my-charm', channel='edge')" in src


def test_config_get_appears(config_get_log: dict[str, Any]) -> None:
    """With no assertion reading it, the read is a call, not a binding.

    Binding it unconditionally left an unused local in a file the user did
    not write, which every linter they run then flags.
    """
    src = generate(config_get_log)
    _parses(src)
    assert "juju.config('my-charm')" in src
    assert "config_10 = " not in src
    assert "# TODO: manual step" not in src


def test_libjuju_orphan_deltas_dropped_silently(orphan_deltas_log: dict[str, Any]) -> None:
    src = generate(orphan_deltas_log)
    _parses(src)
    assert "juju.config('my-charm')" in src
    assert "_libjuju_orphan_deltas" not in src
    assert "# TODO: manual step" not in src


def test_all_operations_in_order(all_ops_log: dict[str, Any]) -> None:
    src = generate(all_ops_log)
    _parses(src)
    expected_calls = [
        "juju.deploy(",
        "juju.wait(",
        "juju.integrate(",
        "juju.config(",
        "juju.add_unit(",
        "juju.run(",
    ]
    last = -1
    for needle in expected_calls:
        idx = src.find(needle)
        assert idx > last, f"{needle!r} not found in order"
        last = idx


def test_assertions_appear(all_ops_log: dict[str, Any]) -> None:
    src = generate(all_ops_log)
    assert (
        "assert juju.status().apps['my-charm']"
        ".units['my-charm/0'].workload_status.current == 'active'"
    ) in src
    assert "result_5 = juju.run(" in src
    assert "assert result_5.success" in src
    assert "assert result_5.results['output'] == 'done'" in src


def test_run_var_naming_follows_seq(run_log: dict[str, Any]) -> None:
    annotated = dict(run_log)
    events = [dict(e) for e in annotated["events"]]
    events[0]["assertions"] = [
        {
            "kind": "action_result",
            "unit": "my-charm/0",
            "action": "do-thing",
            "expected_success": True,
            "expected_results": {"output": "done"},
            "strict": False,
            "source": "delta",
        }
    ]
    annotated["events"] = events
    src = generate(annotated)
    _parses(src)
    assert "result_5 = juju.run(" in src
    assert "assert result_5.success" in src


def test_checkpoint_only_event_skipped_op_but_assertion_emitted() -> None:
    log = {
        "events": [
            {
                "seq": 1,
                "op": "checkpoint",
                "ts": "2026-05-30T09:00:00.000Z",
                "args": {},
                "result": {},
                "model_snapshot_before": None,
                "model_snapshot_after": None,
                "assertions": [
                    {
                        "kind": "user_checkpoint",
                        "label": "ready",
                        "strict": False,
                        "source": "gesture",
                    }
                ],
                "gesture": {"kind": "checkpoint", "label": "ready", "params": {}},
            }
        ]
    }
    src = generate(log)
    _parses(src)
    assert "# checkpoint: ready" in src
    assert "# TODO: manual step" not in src


def test_minimal_session_fixture_parses() -> None:
    import json
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "minimal_session.json"
    log = json.loads(fixture_path.read_text())
    src = generate(log)
    _parses(src)
    assert "juju.deploy(" in src
    assert "juju.wait(" in src
    assert "juju.run(" in src
    assert "# checkpoint: all done" in src


def test_config_get_and_orphan_session_fixture_parses() -> None:
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "config_get_and_orphan_session.json"
    )
    log = json.loads(fixture_path.read_text())
    src = generate(log)
    _parses(src)
    assert "juju.deploy(" in src
    assert "juju.config('my-charm')" in src
    assert "_libjuju_orphan_deltas" not in src
    assert "# TODO: manual step" not in src


def test_config_get_binds_a_variable_when_an_assertion_reads_it() -> None:
    """The binding is emitted exactly when something needs the value."""
    event = {
        "seq": 3,
        "op": "config_get",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"app": "my-charm"},
        "result": {"values": {"log-level": "debug"}},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [
            {
                "kind": "config_value",
                "app": "my-charm",
                "key": "log-level",
                "expected": "debug",
                "strict": False,
                "source": "delta",
            }
        ],
        "gesture": None,
    }
    src = generate({"schema_version": 1, "session_id": "s", "events": [event]})
    _parses(src)
    assert "config_3 = juju.config('my-charm')" in src
    assert "assert config_3['log-level'] == 'debug'" in src
