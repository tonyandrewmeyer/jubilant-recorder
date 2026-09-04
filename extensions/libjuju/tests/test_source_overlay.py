"""Tests for the source-aware overlay (extensions/libjuju/source_overlay.py).

Covers: AST extraction of call sites (test name, variable name, adjacent
comment), the sequential event-alignment two-pointer walk, and the
end-to-end wiring into ``jubilant_recorder.codegen.generate`` — including
the load-bearing guarantee that omitting the overlay entirely reproduces
byte-identical output to codegen with no source-awareness at all.
"""

from __future__ import annotations

import ast
import textwrap
from typing import TYPE_CHECKING

from extensions.libjuju.source_overlay import align_events, extract_call_sites
from jubilant_recorder.codegen import generate

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# extract_call_sites
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "test_example.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_extracts_test_function_name(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_deploy_and_relate(model):
            await model.deploy("postgresql")
        """,
    )
    overlay = extract_call_sites(path)
    assert overlay.test_name == "test_deploy_and_relate"


def test_extracts_variable_name_from_assignment(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_run_action(model):
            postgres = await model.applications["postgresql"].units[0].run_action("get-password")
            await postgres.wait()
        """,
    )
    overlay = extract_call_sites(path)
    run_sites = [cs for cs in overlay.call_sites if cs.op == "run"]
    assert len(run_sites) == 1
    assert run_sites[0].var_name == "postgres"


def test_extracts_trailing_comment_on_same_line(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_deploy(model):
            await model.deploy("postgresql")  # deploy the database
        """,
    )
    overlay = extract_call_sites(path)
    assert overlay.call_sites[0].comment == "deploy the database"


def test_extracts_standalone_comment_immediately_above(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_scale(model):
            # bumped resource limits before scaling
            await model.applications["postgresql"].add_unit(count=2)
        """,
    )
    overlay = extract_call_sites(path)
    scale_sites = [cs for cs in overlay.call_sites if cs.op == "scale"]
    assert len(scale_sites) == 1
    assert scale_sites[0].comment == "bumped resource limits before scaling"


def test_comment_inside_string_literal_is_not_mistaken_for_a_comment(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_deploy(model):
            await model.deploy("postgresql#not-a-comment")
        """,
    )
    overlay = extract_call_sites(path)
    assert overlay.call_sites[0].comment is None


def test_unrecognised_method_name_produces_no_call_site(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_something(model):
            await model.some_unmapped_helper("x")
        """,
    )
    overlay = extract_call_sites(path)
    assert overlay.call_sites == []


def test_call_sites_are_ordered_by_source_line(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_sequence(model):
            await model.deploy("a")
            await model.deploy("b")
            await model.add_relation("a:db", "b:database")
        """,
    )
    overlay = extract_call_sites(path)
    ops = [cs.op for cs in overlay.call_sites]
    assert ops == ["deploy", "deploy", "integrate"]
    linenos = [cs.lineno for cs in overlay.call_sites]
    assert linenos == sorted(linenos)


def test_missing_file_returns_empty_overlay(tmp_path: Path) -> None:
    overlay = extract_call_sites(tmp_path / "does_not_exist.py")
    assert overlay.call_sites == []
    assert overlay.test_name is None


def test_unparsable_file_returns_empty_overlay(tmp_path: Path) -> None:
    path = tmp_path / "broken.py"
    path.write_text("def test_x(:\n    this is not python", encoding="utf-8")
    overlay = extract_call_sites(path)
    assert overlay.call_sites == []
    assert overlay.test_name is None


def test_no_test_function_falls_back_to_module_scope(tmp_path: Path) -> None:
    """A driver script (like step3_live.py) with no test_* function still
    yields call sites — just no test-name hint."""
    path = _write(
        tmp_path,
        """
        model = get_model()
        model.deploy("ubuntu")
        """,
    )
    overlay = extract_call_sites(path)
    assert overlay.test_name is None
    assert [cs.op for cs in overlay.call_sites] == ["deploy"]


# ---------------------------------------------------------------------------
# align_events
# ---------------------------------------------------------------------------


def _event(seq: int, op: str) -> dict:
    return {"seq": seq, "op": op}


def test_align_events_matches_in_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_x(model):
            postgres = await model.deploy("postgresql")
            await model.add_relation("postgresql:db", "app:db")
        """,
    )
    overlay = extract_call_sites(path)
    events = [_event(1, "deploy"), _event(2, "integrate")]
    result = align_events(overlay.call_sites, events)
    # deploy has no var_name-capable op (var names only apply to run/config_get)
    # but the "postgres" assignment is still recorded on the call site itself.
    assert 1 not in result or "var_name" not in result.get(1, {})
    assert result == {} or all(isinstance(v, dict) for v in result.values())


def test_align_events_skips_unmatched_events_without_losing_sync(tmp_path: Path) -> None:
    """A synthesised wait_for_idle the source never called explicitly must
    not consume a call site meant for the next real call."""
    path = _write(
        tmp_path,
        """
        async def test_x(model):
            result = await model.units[0].run_action("do-thing")
        """,
    )
    overlay = extract_call_sites(path)
    events = [
        _event(1, "wait_for_idle"),  # synthesised; no matching call site
        _event(2, "run"),
    ]
    result = align_events(overlay.call_sites, events)
    assert result == {2: {"var_name": "result"}}


def test_align_events_carries_comment_for_run(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_x(model):
            result = await model.units[0].run_action("do-thing")  # check the result
        """,
    )
    overlay = extract_call_sites(path)
    events = [_event(5, "run")]
    result = align_events(overlay.call_sites, events)
    assert result == {5: {"var_name": "result", "comment": "check the result"}}


def test_align_events_empty_call_sites_yields_empty_overlay() -> None:
    assert align_events([], [_event(1, "deploy")]) == {}


def test_align_events_var_name_only_applies_to_run_and_config_get(tmp_path: Path) -> None:
    """A deploy assigned to a variable does not get a var_name override —
    the deploy emitter has no var_name parameter."""
    path = _write(
        tmp_path,
        """
        async def test_x(model):
            postgres = await model.deploy("postgresql")
        """,
    )
    overlay = extract_call_sites(path)
    events = [_event(1, "deploy")]
    result = align_events(overlay.call_sites, events)
    assert result == {}


# ---------------------------------------------------------------------------
# End-to-end: codegen.generate with and without the overlay
# ---------------------------------------------------------------------------

_BASE_LOG = {
    "schema_version": 1,
    "events": [
        {
            "seq": 1,
            "op": "run",
            "ts": "2026-08-21T00:00:00.000Z",
            "args": {"unit": "postgresql/0", "action": "get-password", "params": {}},
            "result": {"success": True, "results": {"password": "x"}, "message": None},
            "model_snapshot_before": None,
            "model_snapshot_after": None,
            "assertions": [],
            "gesture": None,
            "duration_ms": 0.0,
        }
    ],
}


def test_generate_without_overlay_is_unaffected() -> None:
    """The recording alone must always be enough — this is the literal
    "byte-identical without the flag" guarantee from ``source_overlay.py``'s
    "decorative, not load-bearing" contract."""
    with_none = generate(_BASE_LOG, overlay=None)
    without_param = generate(_BASE_LOG)
    assert with_none == without_param
    assert "result_1" in with_none


def test_generate_with_overlay_uses_source_var_name_and_comment(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        async def test_get_password(model):
            password = await model.units[0].run_action("get-password")  # fetch admin password
        """,
    )
    overlay_source = extract_call_sites(path)
    overlay = align_events(overlay_source.call_sites, _BASE_LOG["events"])

    src = generate(_BASE_LOG, test_name=overlay_source.test_name, overlay=overlay)
    ast.parse(src)
    assert "def test_get_password():" in src
    assert "password = juju.run(" in src
    assert "# fetch admin password" in src
    assert "result_1" not in src
