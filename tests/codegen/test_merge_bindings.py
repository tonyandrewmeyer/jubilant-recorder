from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import merge_bindings


def test_merge_bindings_basic(merge_bindings_event: dict[str, Any]) -> None:
    line = merge_bindings.emit(merge_bindings_event, indent=8)
    assert line == "        juju.cli(\"bind\", 'my-charm', 'db=space1')"


def test_merge_bindings_default_space() -> None:
    event = {"args": {"app": "my-charm", "bindings": {"": "space1", "db": "space2"}}}
    line = merge_bindings.emit(event, indent=0)
    assert line == "juju.cli(\"bind\", 'my-charm', 'space1', 'db=space2')"


def test_merge_bindings_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        merge_bindings.emit({"args": {"bindings": {}}}, indent=0)


def test_merge_bindings_force_gets_todo() -> None:
    event = {"args": {"app": "my-charm", "bindings": {"db": "space1"}, "force": True}}
    line = merge_bindings.emit(event, indent=0)
    assert line.startswith("# TODO: MergeBindings also carried force=True")
    assert "juju.cli(\"bind\", 'my-charm', 'db=space1')" in line


def test_merge_bindings_no_assertion_emitted(merge_bindings_event: dict[str, Any]) -> None:
    log = {"events": [merge_bindings_event]}
    src = generate(log)
    assert 'juju.cli("bind"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
