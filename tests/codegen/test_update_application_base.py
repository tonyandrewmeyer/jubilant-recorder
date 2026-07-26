from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import update_application_base


def test_update_application_base_basic(update_application_base_event: dict[str, Any]) -> None:
    line = update_application_base.emit(update_application_base_event, indent=8)
    assert line == "        juju.cli(\"set-application-base\", 'my-charm', 'ubuntu@24.04')"


def test_update_application_base_force() -> None:
    event = {
        "args": {
            "app": "my-charm",
            "base_name": "ubuntu",
            "base_channel": "24.04",
            "force": True,
        }
    }
    line = update_application_base.emit(event, indent=0)
    assert line == "juju.cli(\"set-application-base\", 'my-charm', 'ubuntu@24.04', \"--force\")"


def test_update_application_base_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        update_application_base.emit(
            {"args": {"base_name": "ubuntu", "base_channel": "24.04"}}, indent=0
        )


def test_update_application_base_missing_base_raises() -> None:
    with pytest.raises(ValueError, match="base"):
        update_application_base.emit({"args": {"app": "my-charm"}}, indent=0)


def test_update_application_base_no_assertion_emitted(
    update_application_base_event: dict[str, Any],
) -> None:
    log = {"events": [update_application_base_event]}
    src = generate(log)
    assert 'juju.cli("set-application-base"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
