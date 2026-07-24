from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import set_charm


def test_set_charm_basic(set_charm_event: dict[str, Any]) -> None:
    line = set_charm.emit(set_charm_event, indent=8)
    assert line == (
        '        juju.cli("refresh", \'my-charm\', "--switch", \'ch:my-charm-2\', '
        '"--channel", \'edge\')'
    )


def test_set_charm_minimal() -> None:
    event = {"args": {"app": "my-charm"}}
    line = set_charm.emit(event, indent=0)
    assert line == 'juju.cli("refresh", \'my-charm\')'


def test_set_charm_force() -> None:
    event = {"args": {"app": "my-charm", "force": True}}
    line = set_charm.emit(event, indent=0)
    assert line == 'juju.cli("refresh", \'my-charm\', "--force")'


def test_set_charm_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        set_charm.emit({"args": {}}, indent=0)


def test_set_charm_unrepresentable_config_gets_todo() -> None:
    event = {"args": {"app": "my-charm", "config_settings": {"log-level": "debug"}}}
    line = set_charm.emit(event, indent=0)
    assert line.startswith("# TODO: SetCharm also carried config settings")
    assert 'juju.cli("refresh", \'my-charm\')' in line


def test_set_charm_no_assertion_emitted(set_charm_event: dict[str, Any]) -> None:
    log = {"events": [set_charm_event]}
    src = generate(log)
    assert 'juju.cli("refresh"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
