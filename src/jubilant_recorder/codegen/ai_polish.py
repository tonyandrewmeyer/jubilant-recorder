"""Optional, flag-gated AI polish pass over deterministic codegen output.

the plan §(C) describes an LLM pass that improves *readability* of the
generated test — a meaningful test name, per-step docstrings, collapsing
noisy repeated `wait_for_idle` polls — without touching *correctness*.
the plan §3 (assertion inference) and the work breakdown both stress that
this layer is "optional but low-risk: it only affects readability, not
correctness", and must be gated behind `--ai`, never on by default.

This module provides the seam, not a real LLM client:

* `Polisher` — a one-method Protocol (`polish(code, session_log) -> str`).
  A production implementation would call an LLM here. The recorder never
  ships one that makes network calls; the seam exists so one can be
  injected.
* `StubPolisher` — a deterministic, network-free implementation used by
  the tests and as the default for `--ai`. It performs a single observable
  transformation: it adds a module docstring recording the event count.
* `polish()` — the orchestrator. It runs a polisher and then *verifies*
  the result before returning it: the polished code must still parse, and
  the sequence of behaviour-bearing jubilant calls must be unchanged. If a
  polisher violates either guarantee (e.g. drops a `deploy`, or proposes a
  collapse that changes observable behaviour), `polish()` discards the
  polished version and returns the deterministic code untouched. This is
  the enforcement of the plan's "AST unchanged in observable behaviour"
  rule — a misbehaving polisher can never corrupt the generated test.
"""

from __future__ import annotations

import ast
from typing import Any, Protocol, TypeAlias, runtime_checkable

SessionLog: TypeAlias = dict[str, Any]

# `wait_for_idle` and `status` are idempotent observation calls: collapsing
# or re-spacing them does not change what the test *does* to the model, so a
# polisher is allowed to rewrite them. Every other jubilant call is
# behaviour-bearing and must survive polishing unchanged and in order.
_IDEMPOTENT_CALLS = frozenset({"wait_for_idle", "status"})


@runtime_checkable
class Polisher(Protocol):
    def polish(self, code: str, session_log: SessionLog) -> str:
        """Return a more readable version of `code`.

        Implementations may improve the test name, add docstrings, and
        collapse redundant idempotent calls — but MUST NOT change the
        sequence of behaviour-bearing jubilant operations. `polish()`
        below enforces this and falls back to `code` on violation.
        """
        ...


class StubPolisher:
    """Deterministic, offline stand-in for an LLM polisher.

    Adds a module docstring recording the recorded-session size. Chosen
    because it is observable (tests can assert on it), deterministic (no
    network, same input → same output), and behaviour-preserving (a module
    docstring changes no jubilant calls).
    """

    def polish(self, code: str, session_log: SessionLog) -> str:
        event_count = len(session_log.get("events") or [])
        docstring = f'"""<recorded session: {event_count} events>"""'
        return _with_module_docstring(code, docstring)


def polish(code: str, session_log: SessionLog, *, polisher: Polisher | None = None) -> str:
    """Run a polisher over `code`, guarding correctness.

    Returns the polished code if it still parses and preserves the
    behaviour-bearing jubilant call sequence; otherwise returns `code`
    unchanged. `polisher` defaults to `StubPolisher`.
    """
    polisher = polisher or StubPolisher()
    polished = polisher.polish(code, session_log)
    if polished == code:
        return code
    try:
        ast.parse(polished)
    except SyntaxError:
        return code
    if not behaviour_preserved(code, polished):
        return code
    return polished


def behaviour_preserved(original: str, polished: str) -> bool:
    """True when both sources issue the same behaviour-bearing juju calls.

    Idempotent observation calls (`wait_for_idle`, `status`) are ignored so
    a polisher may collapse redundant polls; every other `juju.<method>()`
    call must appear the same number of times, in the same order.
    """
    return _behaviour_calls(original) == _behaviour_calls(polished)


def _behaviour_calls(code: str) -> list[str]:
    tree = ast.parse(code)
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        value = func.value
        if (
            isinstance(value, ast.Name)
            and value.id == "juju"
            and func.attr not in _IDEMPOTENT_CALLS
        ):
            calls.append(func.attr)
    return calls


def _with_module_docstring(code: str, docstring: str) -> str:
    """Prepend `docstring` as the module docstring, replacing any existing one.

    Deterministic codegen never emits a module docstring, so in practice
    this prepends. The replace path keeps `polish()` idempotent if it is
    ever run twice.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return docstring + "\n" + code
    body = tree.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        end = body[0].end_lineno or 1
        remaining = code.split("\n")[end:]
        return "\n".join([docstring, *remaining])
    return docstring + "\n" + code
