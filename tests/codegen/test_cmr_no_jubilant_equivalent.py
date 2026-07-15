"""
`list_offers`, `remove_offer`, `get_consume_details`, and `remove_saas` are
correlator-classified bucket-1 (CMR-FACADE-RECON.md), but jubilant 1.10 (the
installed version, confirmed by grepping ``jubilant/_juju.py``) has no client
method for any of them. They have no ``EMITTERS`` entry — see
``operations/__init__.py`` — and so must fall through to the same
``# TODO: manual step`` fallback path bucket-3 ops use, rather than crash or
silently drop the step.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import EMITTERS


def test_no_emitters_registered_for_unsupported_cmr_ops() -> None:
    for op in ("list_offers", "remove_offer", "get_consume_details", "remove_saas"):
        assert op not in EMITTERS


def test_list_offers_falls_back_to_todo(list_offers_event: dict[str, Any]) -> None:
    src = generate({"events": [list_offers_event]})
    assert "# TODO: manual step — list_offers" in src
    assert "juju.list_offers(" not in src


def test_remove_offer_falls_back_to_todo(remove_offer_event: dict[str, Any]) -> None:
    src = generate({"events": [remove_offer_event]})
    assert "# TODO: manual step — remove_offer" in src
    assert "juju.remove_offer(" not in src


def test_get_consume_details_falls_back_to_todo(
    get_consume_details_event: dict[str, Any],
) -> None:
    src = generate({"events": [get_consume_details_event]})
    assert "# TODO: manual step — get_consume_details" in src
    assert "juju.get_consume_details(" not in src


def test_remove_saas_falls_back_to_todo(remove_saas_event: dict[str, Any]) -> None:
    src = generate({"events": [remove_saas_event]})
    assert "# TODO: manual step — remove_saas" in src
    assert "juju.remove_saas(" not in src
