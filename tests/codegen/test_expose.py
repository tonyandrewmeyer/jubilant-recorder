from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import expose


def test_expose_basic(expose_event: dict[str, Any]) -> None:
    line = expose.emit(expose_event, indent=8)
    assert line == '        juju.cli("expose", \'my-charm\')'


def test_expose_missing_app_raises() -> None:
    with pytest.raises(ValueError, match="app"):
        expose.emit({"args": {}}, indent=0)


def test_expose_restricted_endpoints_gets_todo() -> None:
    event = {"args": {"app": "my-charm", "exposed_endpoints": {"db": {"expose-to-spaces": ["s1"]}}}}
    line = expose.emit(event, indent=0)
    assert line.startswith("# TODO: Expose restricted to specific spaces/CIDRs on endpoint(s) db")
    assert 'juju.cli("expose", \'my-charm\')' in line


def test_expose_no_assertion_emitted(expose_event: dict[str, Any]) -> None:
    log = {"events": [expose_event]}
    src = generate(log)
    assert 'juju.cli("expose"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
