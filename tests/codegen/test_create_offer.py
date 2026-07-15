from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import create_offer


def test_create_offer_single_endpoint(create_offer_event: dict[str, Any]) -> None:
    line = create_offer.emit(create_offer_event, indent=8)
    assert line == "        juju.offer('postgresql', endpoint='db')"


def test_create_offer_multiple_endpoints() -> None:
    event = {
        "args": {
            "app": "mysql",
            "endpoints": {"db": "db", "log": "log"},
            "offer_name": None,
            "model_tag": None,
        },
    }
    line = create_offer.emit(event, indent=4)
    assert line == "    juju.offer('mysql', endpoint=['db', 'log'])"


def test_create_offer_with_offer_name() -> None:
    event = {
        "args": {
            "app": "mysql",
            "endpoints": {"db": "db"},
            "offer_name": "altname",
            "model_tag": None,
        },
    }
    line = create_offer.emit(event, indent=0)
    assert line == "juju.offer('mysql', endpoint='db', name='altname')"


def test_create_offer_offer_name_same_as_app_dropped() -> None:
    """When the offer name equals the app name (jubilant's default), don't
    emit a redundant ``name=`` kwarg."""
    event = {
        "args": {
            "app": "mysql",
            "endpoints": {"db": "db"},
            "offer_name": "mysql",
            "model_tag": None,
        },
    }
    line = create_offer.emit(event, indent=0)
    assert line == "juju.offer('mysql', endpoint='db')"


def test_create_offer_model_tag_dropped_silently() -> None:
    """``model_tag`` is a UUID the recorder can't resolve to a model name —
    it must never leak into the emitted call."""
    event = {
        "args": {
            "app": "mysql",
            "endpoints": {"db": "db"},
            "offer_name": None,
            "model_tag": "model-deadbeef-0000-0000-0000-000000000000",
        },
    }
    line = create_offer.emit(event, indent=0)
    assert "model" not in line.split("juju.offer(")[1]


def test_create_offer_no_assertion_emitted(create_offer_event: dict[str, Any]) -> None:
    log = {"events": [create_offer_event]}
    src = generate(log)
    assert "juju.offer(" in src
    assert "assert " not in src
    assert "# TODO: manual step" not in src
