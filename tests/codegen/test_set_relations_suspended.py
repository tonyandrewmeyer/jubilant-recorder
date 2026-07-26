from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import set_relations_suspended


def test_set_relations_suspended_basic(set_relations_suspended_event: dict[str, Any]) -> None:
    line = set_relations_suspended.emit(set_relations_suspended_event, indent=8)
    assert line == ("        juju.cli(\"suspend-relation\", '3', \"--message\", 'maintenance')")


def test_set_relations_suspended_multiple_ids_no_message() -> None:
    event = {"args": {"relation_ids": [1, 2], "suspended": True, "message": None}}
    line = set_relations_suspended.emit(event, indent=0)
    assert line == "juju.cli(\"suspend-relation\", '1', '2')"


def test_resume_relation_drops_message() -> None:
    """``resume-relation`` has no ``--message`` flag — the message must not leak."""
    event = {"args": {"relation_ids": [3], "suspended": False, "message": "back online"}}
    line = set_relations_suspended.emit(event, indent=0)
    assert line == "juju.cli(\"resume-relation\", '3')"


def test_set_relations_suspended_missing_ids_raises() -> None:
    with pytest.raises(ValueError, match="relation_ids"):
        set_relations_suspended.emit({"args": {"relation_ids": []}}, indent=0)


def test_set_relations_suspended_no_assertion_emitted(
    set_relations_suspended_event: dict[str, Any],
) -> None:
    log = {"events": [set_relations_suspended_event]}
    src = generate(log)
    assert 'juju.cli("suspend-relation"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
