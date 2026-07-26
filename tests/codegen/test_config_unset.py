from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import config_unset


def test_config_unset_basic(config_unset_event: dict[str, Any]) -> None:
    line = config_unset.emit(config_unset_event, indent=8)
    assert line == "        juju.cli(\"config\", 'my-charm', \"--reset\", 'log-level,debug')"


def test_config_unset_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        config_unset.emit({"args": {"options": ["log-level"]}}, indent=0)


def test_config_unset_missing_options_raises() -> None:
    with pytest.raises(ValueError, match="options"):
        config_unset.emit({"args": {"app": "my-charm", "options": []}}, indent=0)


def test_config_unset_no_assertion_emitted(config_unset_event: dict[str, Any]) -> None:
    log = {"events": [config_unset_event]}
    src = generate(log)
    assert 'juju.cli("config"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
