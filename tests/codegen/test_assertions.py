from __future__ import annotations

from jubilant_recorder.codegen import assertions


def test_unit_status_specific_unit() -> None:
    tag = {
        "kind": "unit_status",
        "app": "my-charm",
        "unit": "my-charm/0",
        "expected": "active",
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert line == (
        "        assert juju.status().apps['my-charm']"
        ".units['my-charm/0'].workload_status.current == 'active'"
    )


def test_unit_status_all_units() -> None:
    tag = {
        "kind": "unit_status",
        "app": "my-charm",
        "unit": None,
        "expected": "active",
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert line == (
        "        for _u in juju.status().apps['my-charm'].units.values():\n"
        "            assert _u.workload_status.current == 'active'"
    )


def test_unit_count() -> None:
    tag = {
        "kind": "unit_count",
        "app": "my-charm",
        "expected": 3,
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert line == "        assert len(juju.status().apps['my-charm'].units) == 3"


def test_action_result_with_run_var() -> None:
    tag = {
        "kind": "action_result",
        "unit": "my-charm/0",
        "action": "do-thing",
        "expected_success": True,
        "expected_results": {"output": "done"},
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8, run_var="result_3")
    assert line == (
        "        assert result_3.success\n        assert result_3.results['output'] == 'done'"
    )


def test_action_result_failure() -> None:
    tag = {
        "kind": "action_result",
        "unit": "my-charm/0",
        "action": "do-thing",
        "expected_success": False,
        "expected_results": {},
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8, run_var="result_3")
    assert line == "        assert not result_3.success"


def test_config_value() -> None:
    tag = {
        "kind": "config_value",
        "app": "my-charm",
        "key": "log-level",
        "expected": "info",
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert line == (
        "        assert juju.config('my-charm', keys=['log-level'])['log-level'] == 'info'"
    )


def test_relation_exists() -> None:
    tag = {
        "kind": "relation_exists",
        "endpoint_a": "my-charm:db",
        "endpoint_b": "postgresql:database",
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert "any(" in line
    # jubilant 1.10's API: walk apps[a_app].relations.get(a_ep) and match
    # on related_app — there's no related_endpoint to assert.
    assert "juju.status().apps['my-charm'].relations.get('db', [])" in line
    assert "r.related_app == 'postgresql'" in line
    assert "not any" not in line


def test_relation_absent() -> None:
    tag = {
        "kind": "relation_absent",
        "endpoint_a": "my-charm:db",
        "endpoint_b": "postgresql:database",
        "strict": False,
        "source": "delta",
    }
    line = assertions.emit(tag, indent=8)
    assert "assert not any(" in line
    assert "juju.status().apps['my-charm'].relations.get('db', [])" in line
    assert "r.related_app == 'postgresql'" in line


def test_user_checkpoint() -> None:
    tag = {
        "kind": "user_checkpoint",
        "label": "all done",
        "strict": False,
        "source": "gesture",
    }
    line = assertions.emit(tag, indent=8)
    assert line == "        # checkpoint: all done"


def test_unknown_kind_emits_nothing() -> None:
    tag = {"kind": "made-up-kind", "strict": False, "source": "delta"}
    line = assertions.emit(tag, indent=8)
    assert line == ""
