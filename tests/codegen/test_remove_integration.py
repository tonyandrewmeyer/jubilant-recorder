from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_integration


def test_remove_integration_basic(remove_integration_event: dict[str, Any]) -> None:
    line = remove_integration.emit(remove_integration_event, indent=8)
    assert line == "        juju.remove_relation('my-charm:db', 'postgresql:database')"


def test_remove_integration_different_endpoints() -> None:
    event = {
        "args": {"app1_endpoint": "mysql:db", "app2_endpoint": "app:database"},
    }
    line = remove_integration.emit(event, indent=4)
    assert line == "    juju.remove_relation('mysql:db', 'app:database')"


def test_remove_integration_no_assertion_emitted(
    remove_integration_event: dict[str, Any],
) -> None:
    log = {"events": [remove_integration_event]}
    src = generate(log)
    assert "juju.remove_relation(" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
