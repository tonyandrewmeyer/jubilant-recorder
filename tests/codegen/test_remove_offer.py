from __future__ import annotations

from typing import Any

import pytest

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_offer


def test_remove_offer_basic(remove_offer_event: dict[str, Any]) -> None:
    line = remove_offer.emit(remove_offer_event, indent=8)
    assert line == '        juju.cli("remove-offer", "--force", \'admin/mymodel.postgresql\')'


def test_remove_offer_not_forced() -> None:
    event = {"args": {"force": False, "offer_urls": ["admin/mymodel.postgresql"]}}
    line = remove_offer.emit(event, indent=0)
    assert line == "juju.cli(\"remove-offer\", 'admin/mymodel.postgresql')"


def test_remove_offer_multiple_urls() -> None:
    event = {
        "args": {"force": True, "offer_urls": ["admin/mymodel.postgresql", "admin/mymodel.mysql"]},
    }
    line = remove_offer.emit(event, indent=4)
    assert line == (
        '    juju.cli("remove-offer", "--force", '
        "'admin/mymodel.postgresql', 'admin/mymodel.mysql')"
    )


def test_remove_offer_missing_urls_raises() -> None:
    event = {"args": {"force": True, "offer_urls": []}}
    with pytest.raises(ValueError, match="offer_urls"):
        remove_offer.emit(event, indent=0)


def test_remove_offer_empty_url_raises() -> None:
    event = {"args": {"force": True, "offer_urls": [""]}}
    with pytest.raises(ValueError, match="offer_urls"):
        remove_offer.emit(event, indent=0)


def test_remove_offer_no_assertion_emitted(remove_offer_event: dict[str, Any]) -> None:
    log = {"events": [remove_offer_event]}
    src = generate(log)
    assert 'juju.cli("remove-offer"' in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
