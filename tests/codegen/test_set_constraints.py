from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import set_constraints


def test_set_constraints_basic(set_constraints_event: dict[str, Any]) -> None:
    line = set_constraints.emit(set_constraints_event, indent=8)
    assert line == "        juju.cli(\"set-constraints\", 'my-charm', 'cores=2', 'mem=4G')"


def test_set_constraints_list_value_joins_with_commas() -> None:
    event = {"args": {"app": "my-charm", "constraints": {"tags": ["foo", "bar"]}}}
    line = set_constraints.emit(event, indent=0)
    assert line == "juju.cli(\"set-constraints\", 'my-charm', 'tags=foo,bar')"


def test_set_constraints_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        set_constraints.emit({"args": {"constraints": {}}}, indent=0)


def test_set_constraints_no_assertion_emitted(set_constraints_event: dict[str, Any]) -> None:
    log = {"events": [set_constraints_event]}
    src = generate(log)
    assert 'juju.cli("set-constraints"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
