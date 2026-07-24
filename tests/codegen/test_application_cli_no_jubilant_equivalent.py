"""
`set_charm`, `expose`, `unexpose`, `set_constraints`, `merge_bindings`,
`set_relations_suspended`, `config_unset`, and `update_application_base` are
the 8 `Application.*` bucket-2 → bucket-1 promotions from
`LIBJUJU-CORPUS-AUDIT-2026-07-20.md` §5 "Natural extension". jubilant 1.10
has no dedicated client method for any of them, but each has an
``EMITTERS`` entry that renders a ``juju.cli(...)`` call — see
``operations/__init__.py``. They must not fall through to the
``# TODO: manual step`` fallback path bucket-3 ops use.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import EMITTERS

_OPS = (
    "set_charm",
    "expose",
    "unexpose",
    "set_constraints",
    "merge_bindings",
    "set_relations_suspended",
    "config_unset",
    "update_application_base",
)


def test_emitters_registered_for_application_cli_ops() -> None:
    for op in _OPS:
        assert op in EMITTERS


def test_set_charm_emits_cli(set_charm_event: dict[str, Any]) -> None:
    src = generate({"events": [set_charm_event]})
    assert 'juju.cli("refresh"' in src
    assert "# TODO: manual step" not in src


def test_expose_emits_cli(expose_event: dict[str, Any]) -> None:
    src = generate({"events": [expose_event]})
    assert 'juju.cli("expose"' in src
    assert "# TODO: manual step" not in src


def test_unexpose_emits_cli(unexpose_event: dict[str, Any]) -> None:
    src = generate({"events": [unexpose_event]})
    assert 'juju.cli("unexpose"' in src
    assert "# TODO: manual step" not in src


def test_set_constraints_emits_cli(set_constraints_event: dict[str, Any]) -> None:
    src = generate({"events": [set_constraints_event]})
    assert 'juju.cli("set-constraints"' in src
    assert "# TODO: manual step" not in src


def test_merge_bindings_emits_cli(merge_bindings_event: dict[str, Any]) -> None:
    src = generate({"events": [merge_bindings_event]})
    assert 'juju.cli("bind"' in src
    assert "# TODO: manual step" not in src


def test_set_relations_suspended_emits_cli(
    set_relations_suspended_event: dict[str, Any],
) -> None:
    src = generate({"events": [set_relations_suspended_event]})
    assert 'juju.cli("suspend-relation"' in src
    assert "# TODO: manual step" not in src


def test_config_unset_emits_cli(config_unset_event: dict[str, Any]) -> None:
    src = generate({"events": [config_unset_event]})
    assert 'juju.cli("config"' in src
    assert "# TODO: manual step" not in src


def test_update_application_base_emits_cli(
    update_application_base_event: dict[str, Any],
) -> None:
    src = generate({"events": [update_application_base_event]})
    assert 'juju.cli("set-application-base"' in src
    assert "# TODO: manual step" not in src
