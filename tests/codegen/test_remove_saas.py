from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_saas


def test_remove_saas_single_app(remove_saas_event: dict[str, Any]) -> None:
    line = remove_saas.emit(remove_saas_event, indent=8)
    assert line == "        juju.cli('remove-saas', 'postgresql')"


def test_remove_saas_forced() -> None:
    event = {"args": {"app": "postgresql", "force": True}}
    line = remove_saas.emit(event, indent=4)
    assert line == "    juju.cli('remove-saas', '--force', 'postgresql')"


def test_remove_saas_multi_app_list() -> None:
    event = {"args": {"app": ["postgresql", "mysql"]}}
    line = remove_saas.emit(event, indent=4)
    assert line == "    juju.cli('remove-saas', 'postgresql', 'mysql')"


def test_remove_saas_no_app_falls_back() -> None:
    event = {"args": {"app": None}}
    line = remove_saas.emit(event, indent=4)
    assert line == "    # TODO: manual step: remove_saas with no app"


def test_remove_saas_no_assertion_emitted(remove_saas_event: dict[str, Any]) -> None:
    log = {"events": [remove_saas_event]}
    src = generate(log)
    assert "juju.cli('remove-saas'" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
