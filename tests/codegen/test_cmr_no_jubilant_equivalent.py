"""
`list_offers`, `remove_offer`, `get_consume_details`, and `remove_saas` are
correlator-classified bucket-1. jubilant 1.10 (the installed version,
confirmed by grepping ``jubilant/_juju.py``) still has no dedicated client
method for any of them, but each has an ``EMITTERS`` entry that renders a
``juju.cli(...)`` call — see ``operations/__init__.py``. They must not fall
through to the ``# TODO: manual step`` fallback path bucket-3 ops use.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import EMITTERS


def test_emitters_registered_for_cmr_ops_without_client_methods() -> None:
    for op in ("list_offers", "remove_offer", "get_consume_details", "remove_saas"):
        assert op in EMITTERS


def test_list_offers_emits_cli(list_offers_event: dict[str, Any]) -> None:
    src = generate({"events": [list_offers_event]})
    assert 'juju.cli("offers", "--format=json")' in src
    assert "# TODO: manual step" not in src


def test_remove_offer_emits_cli(remove_offer_event: dict[str, Any]) -> None:
    src = generate({"events": [remove_offer_event]})
    assert 'juju.cli("remove-offer"' in src
    assert "# TODO: manual step" not in src


def test_get_consume_details_emits_cli(get_consume_details_event: dict[str, Any]) -> None:
    src = generate({"events": [get_consume_details_event]})
    assert 'juju.cli("show-offer"' in src
    assert "# TODO: manual step" not in src


def test_remove_saas_emits_cli(remove_saas_event: dict[str, Any]) -> None:
    src = generate({"events": [remove_saas_event]})
    assert 'juju.cli("remove-saas"' in src
    assert "# TODO: manual step" not in src
