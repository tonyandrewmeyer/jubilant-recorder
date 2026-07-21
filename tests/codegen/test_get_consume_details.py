from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import get_consume_details


def test_get_consume_details_basic(get_consume_details_event: dict[str, Any]) -> None:
    line = get_consume_details.emit(get_consume_details_event, indent=8)
    assert line == (
        '        juju.cli("show-offer", "--format=json", \'admin/mymodel.postgresql\')'
    )


def test_get_consume_details_user_tag_dropped() -> None:
    """``user_tag`` has no ``juju show-offer`` flag equivalent — it must
    never leak into the rendered call."""
    event = {
        "args": {
            "offer_urls": ["admin/mymodel.postgresql"],
            "user_tag": "user-admin",
        },
    }
    line = get_consume_details.emit(event, indent=0)
    assert "user" not in line.split("show-offer")[1]


def test_get_consume_details_multiple_urls() -> None:
    event = {
        "args": {
            "offer_urls": ["admin/mymodel.postgresql", "admin/mymodel.mysql"],
            "user_tag": None,
        },
    }
    line = get_consume_details.emit(event, indent=4)
    assert line == (
        '    juju.cli("show-offer", "--format=json", '
        "'admin/mymodel.postgresql', 'admin/mymodel.mysql')"
    )


def test_get_consume_details_missing_urls_raises() -> None:
    event = {"args": {"offer_urls": [], "user_tag": None}}
    with pytest.raises(ValueError, match="offer_urls"):
        get_consume_details.emit(event, indent=0)


def test_get_consume_details_empty_url_raises() -> None:
    event = {"args": {"offer_urls": [""], "user_tag": None}}
    with pytest.raises(ValueError, match="offer_urls"):
        get_consume_details.emit(event, indent=0)


def test_get_consume_details_no_assertion_emitted(
    get_consume_details_event: dict[str, Any],
) -> None:
    log = {"events": [get_consume_details_event]}
    src = generate(log)
    assert 'juju.cli("show-offer"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
