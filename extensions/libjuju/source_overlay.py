"""Source-aware overlay — Step 4 of the libjuju extension sketch.

**Decorative only, gated behind ``--source-aware <path>``.** The recording
alone (``RecordingLibjuju`` + ``correlate.py``, Step 3) must always be enough
to produce a correct, if blandly-named, jubilant test — nothing here may
become load-bearing. This module's entire job is: given the path to the
libjuju test file that was actually run, AST-walk it for call sites that
look like the libjuju operations the correlator already classifies, line
them up against the recorded events in source order, and hand
``jubilant_recorder.codegen.generate`` an optional ``overlay`` map it uses
purely to pick nicer variable names and carry source comments through.
Passing no overlay (or a source file with no correlatable call sites)
produces exactly the same output as not using this module at all.

What this recovers, per the plan's "Awareness of the existing test" section:

* The test function's own name, so the generated test isn't stuck at the
  generic ``test_recorded_session``.
* Local variable names assigned from a recognised call
  (``postgres = await model.deploy(...)``) — reused for the corresponding
  ``run``/``config_get`` result variable in the generated test, instead of
  the generic ``result_N``/``config_N``.
* A comment adjacent to the call (same line trailing, or a standalone
  comment line immediately above) — carried through verbatim above the
  matching generated line.

What it deliberately does not attempt (stated plainly rather than oversold,
matching this project's own convention — see the drift notes):

* **No execution-order guarantee beyond straight-line, sequential code.**
  Call sites are ordered by source position (line, then column) and matched
  to events by a single forward-only two-pointer walk. A test that branches
  (``if``/``for``), fires concurrent awaits (``asyncio.gather``), or calls
  libjuju through a helper function defined elsewhere in the file will not
  align cleanly — the mismatched call sites simply produce no annotation
  (silently skipped), never a wrong one. This is the same "decorative, not
  load-bearing" contract the plan asks for: a missed match degrades naming,
  it never corrupts the recorded operation sequence.
* **No fixture wiring.** The test function's own parameter names are not
  otherwise used (a future pass could map them to jubilant fixture
  suggestions per the plan, but that is speculative beyond what step 4 asks
  for and is left for a later session rather than half-built here).
* **Only a fixed method-name → op vocabulary is recognised**
  (``_METHOD_TO_OP`` below), mirroring the same buckets as
  ``correlate.py``'s ``_BUCKET1_MAP``. A call to a method not in this table
  (or a bucket-2/3 op, which the correlator doesn't name either) is not a
  call site at all and cannot be annotated — again: silently skipped, not
  guessed at.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

# Mirrors correlate.py's _BUCKET1_MAP op names (the wire-level op the
# correlator would emit), keyed by the libjuju/jubilant-idiomatic Python
# method name a human would actually write in a test. Deliberately a
# best-effort vocabulary, not a generated one: unlike the RPC facade/method
# pairs (which come straight off the wire and are exhaustively enumerable),
# there is no single canonical Python spelling for "the call that becomes
# an Application.Deploy RPC" — libjuju exposes `model.deploy(...)`, some
# helper wrappers spell it `deploy_charm(...)`, and jubilant itself uses
# `juju.deploy(...)`. Covering the common spellings from both libraries is
# enough for a decorative aid; an unrecognised spelling just means that one
# call site goes unannotated, which is the documented, safe failure mode.
_METHOD_TO_OP: dict[str, str] = {
    "deploy": "deploy",
    "add_relation": "integrate",
    "integrate": "integrate",
    "remove_relation": "remove_integration",
    "destroy_relation": "remove_integration",
    "set_config": "config",
    "config": "config",
    "get_config": "config_get",
    "add_units": "scale",
    "add_unit": "scale",
    "scale": "scale",
    "scale_application": "scale",
    "remove_application": "remove_application",
    "destroy": "remove_application",
    "destroy_application": "remove_application",
    "run_action": "run",
    "run": "run",
    "wait_for_idle": "wait_for_idle",
    "wait": "wait_for_idle",
    "get_status": "status",
    "status": "status",
    "add_secret": "secret_add",
    "update_secret": "secret_update",
    "remove_secret": "secret_remove",
    "grant_secret": "secret_grant",
    "revoke_secret": "secret_revoke",
    "secrets": "secret_list",
    "list_secrets": "secret_list",
    "offer": "create_offer",
    "list_offers": "list_offers",
    "find_offers": "find_offers",
    "remove_offer": "remove_offer",
    "get_consume_details": "get_consume_details",
    "consume": "consume",
    "remove_saas": "remove_saas",
}

# Only these ops carry a codegen-visible result variable today
# (``EMITTERS["run"]``/``EMITTERS["config_get"]`` both accept ``var_name``).
# A matched call site for any other op still contributes its comment, just
# not a variable-name override.
_VAR_CAPABLE_OPS = frozenset({"run", "config_get"})


@dataclass(frozen=True)
class CallSite:
    """One recognised libjuju call, in source order."""

    lineno: int
    method_name: str
    op: str
    var_name: str | None
    comment: str | None


@dataclass(frozen=True)
class SourceOverlay:
    """Everything ``extract_call_sites`` recovered from one source file."""

    call_sites: list[CallSite]
    test_name: str | None


def _line_comments(source: str) -> dict[int, str]:
    """Map line number -> comment text.

    Uses ``tokenize`` rather than a naive ``#``-split, so a ``#`` inside a
    string literal is never mistaken for a comment.
    """
    comments: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                text = tok.string.lstrip("#").strip()
                if text:
                    comments[tok.start[0]] = text
    except (tokenize.TokenizeError, SyntaxError, IndentationError):
        # Best-effort: a file that fails to tokenize (e.g. a syntax error
        # introduced after the recorded run) yields no comments rather than
        # raising — this module is decorative, never load-bearing.
        pass
    return comments


def _comment_for_line(line_comments: dict[int, str], lineno: int) -> str | None:
    if lineno in line_comments:
        return line_comments[lineno]
    if (lineno - 1) in line_comments:
        return line_comments[lineno - 1]
    return None


def _find_test_function(
    tree: ast.Module,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the first ``test_*`` function definition, if any."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            return node
    return None


def _unwrap_await(value: ast.expr) -> ast.expr:
    return value.value if isinstance(value, ast.Await) else value


def _extract_from_scope(scope: ast.AST, line_comments: dict[int, str]) -> list[CallSite]:
    call_sites: list[CallSite] = []
    for node in ast.walk(scope):
        var_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                var_name = target.id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                var_name = node.target.id
            value = node.value
        elif isinstance(node, ast.Expr):
            value = node.value
        else:
            continue

        call = _unwrap_await(value)
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue

        method_name = call.func.attr
        op = _METHOD_TO_OP.get(method_name)
        if op is None:
            continue

        call_sites.append(
            CallSite(
                lineno=node.lineno,
                method_name=method_name,
                op=op,
                var_name=var_name,
                comment=_comment_for_line(line_comments, node.lineno),
            )
        )

    call_sites.sort(key=lambda cs: cs.lineno)
    return call_sites


def extract_call_sites(source_path: Path) -> SourceOverlay:
    """AST-walk ``source_path`` for recognised libjuju call sites.

    Returns an empty ``SourceOverlay`` (no call sites, no test name) if the
    file can't be read or doesn't parse — this is a best-effort aid, and a
    stale or unreadable source path must never break codegen.
    """
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return SourceOverlay(call_sites=[], test_name=None)

    line_comments = _line_comments(source)
    test_fn = _find_test_function(tree)
    scope: ast.AST = test_fn if test_fn is not None else tree
    call_sites = _extract_from_scope(scope, line_comments)
    test_name = test_fn.name if test_fn is not None else None
    return SourceOverlay(call_sites=call_sites, test_name=test_name)


def align_events(
    call_sites: list[CallSite], events: list[dict[str, Any]]
) -> dict[int, dict[str, str]]:
    """Sequentially align call sites to recorded events by op name.

    A single forward-only two-pointer walk: for each event (in recorded
    order), check whether it matches the *next unclaimed* call site's op. If
    so, claim it and advance the call-site pointer; the event pointer always
    advances. This means a run of events with no matching call site (a
    synthesised ``wait_for_idle`` the source never called explicitly, an
    internal/diagnostic event, a bucket-2/3 op with no name mapping) is
    simply skipped rather than mis-paired — correctness only degrades to
    "no annotation for this event", never to a wrong pairing, as long as
    both streams are in the same relative order (true for straight-line,
    sequential test code; see the module docstring for what isn't covered).

    Returns a map of ``event["seq"] -> {"var_name": ..., "comment": ...}``
    (only including entries with at least one non-empty value).
    """
    overlay: dict[int, dict[str, str]] = {}
    cs_idx = 0
    for event in events:
        if cs_idx >= len(call_sites):
            break
        op = event.get("op")
        if not op or op.startswith("_libjuju"):
            continue
        cs = call_sites[cs_idx]
        if cs.op != op:
            continue
        entry: dict[str, str] = {}
        if cs.var_name and op in _VAR_CAPABLE_OPS:
            entry["var_name"] = cs.var_name
        if cs.comment:
            entry["comment"] = cs.comment
        if entry:
            seq = event.get("seq")
            if isinstance(seq, int):
                overlay[seq] = entry
        cs_idx += 1
    return overlay
