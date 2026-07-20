from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import get_consume_details


def test_get_consume_details_single_url(get_consume_details_event: dict[str, Any]) -> None:
    line = get_consume_details.emit(get_consume_details_event, indent=8)
    assert line == '        juju.cli("show-offer", "--format=json", \'admin/mymodel.postgresql\')'


def test_get_consume_details_multiple_urls() -> None:
    event = {
        "args": {
            "offer_urls": ["admin/mymodel.postgresql", "admin/mymodel.mysql"],
            "user_tag": None,
        },
    }
    line = get_consume_details.emit(event, indent=4)
    assert line == (
        '    juju.cli("show-offer", "--format=json", \'admin/mymodel.postgresql\')\n'
        '    juju.cli("show-offer", "--format=json", \'admin/mymodel.mysql\')'
    )


def test_get_consume_details_no_urls_falls_back() -> None:
    event = {"args": {"offer_urls": [], "user_tag": None}}
    line = get_consume_details.emit(event, indent=4)
    assert line == "    # TODO: manual step: get_consume_details with no offer_urls"


def test_get_consume_details_no_assertion_emitted(
    get_consume_details_event: dict[str, Any],
) -> None:
    log = {"events": [get_consume_details_event]}
    src = generate(log)
    assert 'juju.cli("show-offer", "--format=json"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
