"""``find_offers`` emitter — twin of ``list_offers``.

``ApplicationOffers.FindApplicationOffers`` was the other of the two last
bucket-2 members. It follows ``ListApplicationOffers``' precedent exactly: a
read, no jubilant client method, and correlator filter fields that do not
map onto the CLI's flags, so the filters are dropped and the emitted call
finds everything.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import find_offers


def test_find_offers_basic(find_offers_event: dict[str, Any]) -> None:
    line = find_offers.emit(find_offers_event, indent=8)
    assert line == '        juju.cli("find-offers", "--format=json")'


def test_find_offers_with_var_name(find_offers_event: dict[str, Any]) -> None:
    line = find_offers.emit(find_offers_event, indent=4, var_name="found")
    assert line == '    found = juju.cli("find-offers", "--format=json")'


def test_find_offers_filters_are_dropped() -> None:
    """``juju find-offers``' flags don't correspond to the captured
    ``OfferFilter`` fields, so forwarding them would fabricate a mapping.

    Same decision as ``list_offers``; asserted here so a future change that
    starts forwarding them has to justify itself against a failing test
    rather than quietly narrowing what a recorded session reproduces.
    """
    event = {
        "args": {
            "model_name": "othermodel",
            "application_name": "postgresql",
            "offer_name": "myoffer",
        },
    }
    line = find_offers.emit(event, indent=0)
    assert line == 'juju.cli("find-offers", "--format=json")'
    assert "postgresql" not in line


def test_find_offers_renders_without_fallback(
    find_offers_event: dict[str, Any],
) -> None:
    src = generate({"events": [find_offers_event]})
    assert '"find-offers"' in src
    assert "# TODO: manual step" not in src
