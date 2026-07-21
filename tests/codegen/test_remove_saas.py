from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_saas


def test_remove_saas_basic(remove_saas_event: dict[str, Any]) -> None:
    line = remove_saas.emit(remove_saas_event, indent=8)
    assert line == "        juju.cli(\"remove-saas\", 'postgresql')"


def test_remove_saas_different_app() -> None:
    event = {"args": {"app": "mysql-remote"}}
    line = remove_saas.emit(event, indent=4)
    assert line == "    juju.cli(\"remove-saas\", 'mysql-remote')"


def test_remove_saas_missing_app_raises() -> None:
    event = {"args": {}}
    with pytest.raises(ValueError, match="app"):
        remove_saas.emit(event, indent=0)


def test_remove_saas_empty_app_raises() -> None:
    event = {"args": {"app": ""}}
    with pytest.raises(ValueError, match="app"):
        remove_saas.emit(event, indent=0)


def test_remove_saas_no_assertion_emitted(remove_saas_event: dict[str, Any]) -> None:
    log = {"events": [remove_saas_event]}
    src = generate(log)
    assert 'juju.cli("remove-saas"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
