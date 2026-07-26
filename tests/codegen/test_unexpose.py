from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import unexpose


def test_unexpose_basic(unexpose_event: dict[str, Any]) -> None:
    line = unexpose.emit(unexpose_event, indent=8)
    assert line == "        juju.cli(\"unexpose\", 'my-charm')"


def test_unexpose_with_endpoints() -> None:
    event = {"args": {"app": "my-charm", "exposed_endpoints": ["db", "web"]}}
    line = unexpose.emit(event, indent=0)
    assert line == "juju.cli(\"unexpose\", 'my-charm', \"--endpoints\", 'db,web')"


def test_unexpose_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        unexpose.emit({"args": {}}, indent=0)


def test_unexpose_no_assertion_emitted(unexpose_event: dict[str, Any]) -> None:
    log = {"events": [unexpose_event]}
    src = generate(log)
    assert 'juju.cli("unexpose"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
