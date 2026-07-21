from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import list_offers


def test_list_offers_basic(list_offers_event: dict[str, Any]) -> None:
    line = list_offers.emit(list_offers_event, indent=8)
    assert line == '        juju.cli("offers", "--format=json")'


def test_list_offers_with_var_name(list_offers_event: dict[str, Any]) -> None:
    line = list_offers.emit(list_offers_event, indent=4, var_name="offers")
    assert line == '    offers = juju.cli("offers", "--format=json")'


def test_list_offers_filters_ignored() -> None:
    """The correlator's filter fields don't map onto ``juju offers`` flags —
    they must never leak into the rendered call."""
    event = {
        "args": {
            "model_name": "othermodel",
            "application_name": "postgresql",
            "offer_name": "myoffer",
        },
    }
    line = list_offers.emit(event, indent=0)
    assert line == 'juju.cli("offers", "--format=json")'


def test_list_offers_no_assertion_emitted(list_offers_event: dict[str, Any]) -> None:
    log = {"events": [list_offers_event]}
    src = generate(log)
    assert 'juju.cli("offers", "--format=json")' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
