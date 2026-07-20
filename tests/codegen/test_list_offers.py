from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import list_offers


def test_list_offers_empty_filter(list_offers_event: dict[str, Any]) -> None:
    line = list_offers.emit(list_offers_event, indent=8)
    assert line == '        juju.cli("offers", "--format=json")'


def test_list_offers_offer_name_filter() -> None:
    event = {
        "args": {"model_name": None, "application_name": None, "offer_name": "myoffer"},
    }
    line = list_offers.emit(event, indent=4)
    assert line == '    juju.cli("offers", "--format=json", \'myoffer\')'


def test_list_offers_complex_filter_falls_back() -> None:
    event = {
        "args": {"model_name": "mymodel", "application_name": None, "offer_name": None},
    }
    line = list_offers.emit(event, indent=4)
    assert line == "    # TODO: manual step: list_offers with complex filter"


def test_list_offers_no_assertion_emitted(list_offers_event: dict[str, Any]) -> None:
    log = {"events": [list_offers_event]}
    src = generate(log)
    assert 'juju.cli("offers", "--format=json")' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
