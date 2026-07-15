from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import consume


def test_consume_basic(consume_event: dict[str, Any]) -> None:
    line = consume.emit(consume_event, indent=8)
    assert line == "        juju.consume('admin/othermodel.postgresql')"


def test_consume_with_alias() -> None:
    event = {
        "args": {"offer_url": "othermodel.mysql", "application_alias": "sql"},
    }
    line = consume.emit(event, indent=4)
    assert line == "    juju.consume('othermodel.mysql', 'sql')"


def test_consume_alias_none_omitted() -> None:
    event = {
        "args": {"offer_url": "othermodel.mysql", "application_alias": None},
    }
    line = consume.emit(event, indent=0)
    assert line == "juju.consume('othermodel.mysql')"


def test_consume_no_assertion_emitted(consume_event: dict[str, Any]) -> None:
    log = {"events": [consume_event]}
    src = generate(log)
    assert "juju.consume(" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
