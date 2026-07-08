from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_application


def test_remove_application_single_app(remove_application_event: dict[str, Any]) -> None:
    line = remove_application.emit(remove_application_event, indent=8)
    assert line == "        juju.remove_application('my-charm')"


def test_remove_application_multi_app() -> None:
    event = {"args": {"app": ["my-charm", "postgresql"]}}
    line = remove_application.emit(event, indent=4)
    assert line == "    juju.remove_application('my-charm', 'postgresql')"


def test_remove_application_no_assertion_emitted(
    remove_application_event: dict[str, Any],
) -> None:
    log = {"events": [remove_application_event]}
    src = generate(log)
    assert "juju.remove_application(" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
