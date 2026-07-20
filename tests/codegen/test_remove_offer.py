from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import remove_offer


def test_remove_offer_forced(remove_offer_event: dict[str, Any]) -> None:
    line = remove_offer.emit(remove_offer_event, indent=8)
    assert line == "        juju.cli('remove-offer', '--force', 'admin/mymodel.postgresql')"


def test_remove_offer_no_force() -> None:
    event = {"args": {"force": False, "offer_urls": ["admin/mymodel.myoffer"]}}
    line = remove_offer.emit(event, indent=4)
    assert line == "    juju.cli('remove-offer', 'admin/mymodel.myoffer')"


def test_remove_offer_multiple_urls() -> None:
    event = {
        "args": {
            "force": True,
            "offer_urls": ["admin/mymodel.offer1", "admin/mymodel.offer2"],
        },
    }
    line = remove_offer.emit(event, indent=4)
    assert line == (
        "    juju.cli('remove-offer', '--force', 'admin/mymodel.offer1', 'admin/mymodel.offer2')"
    )


def test_remove_offer_no_urls_falls_back() -> None:
    event = {"args": {"force": False, "offer_urls": []}}
    line = remove_offer.emit(event, indent=4)
    assert line == "    # TODO: manual step: remove_offer with no offer_urls"


def test_remove_offer_no_assertion_emitted(remove_offer_event: dict[str, Any]) -> None:
    log = {"events": [remove_offer_event]}
    src = generate(log)
    assert "juju.cli('remove-offer'" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
