"""Optional, flag-gated AI polish pass over deterministic codegen output.

the plan §(C) describes an LLM pass that improves *readability* of the
generated test — a meaningful test name, per-step docstrings, collapsing
noisy repeated `wait_for_idle` polls — without touching *correctness*.
the plan §3 (assertion inference) and the work breakdown both stress that
this layer is "optional but low-risk: it only affects readability, not
correctness", and must be gated behind `--ai`, never on by default.

This module provides:

* `Polisher` — a one-method Protocol (`polish(code, session_log) -> str`).
* `StubPolisher` — a deterministic, network-free implementation used by
  tests. Adds a module docstring with the event count.
* `AnthropicPolisher` — real LLM polisher using claude-sonnet-4-6. Requires
  an anthropic.Anthropic() client injected at construction time (shared with
  the tagger's AnthropicProposer — one client per run).
* `polish()` — the orchestrator. Runs the polisher then *verifies* the
  result: the polished code must still parse, and the sequence of
  behaviour-bearing jubilant calls must be unchanged. Falls back to the
  deterministic output on any violation.
"""

from __future__ import annotations

import ast
import json
import warnings
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


_POLISH_PROMPT = """\
You are a Python test code refactoring assistant. Improve the readability of \
the jubilant integration test below.

You MAY:
- Rename the test function to be more descriptive (snake_case, starts with test_)
- Add a one-line docstring inside the test function explaining what it validates
- Remove consecutive duplicate juju.status() or juju.wait(...) calls

You MUST NOT:
- Add, remove, or reorder juju operation calls \
(deploy, integrate, config, scale, run, add_unit, remove_unit)
- Change any assert statements
- Add new imports
- Wrap code in markdown fences

Return ONLY the modified Python code with no additional commentary.

Session log (for naming context):
{session_log_json}

Test to improve:
{code}
"""


class AnthropicPolisher:
    """LLM polisher using the Anthropic API (claude-sonnet-4-6).

    Requires an anthropic.Anthropic() client injected at construction.
    The same client instance should be shared with AnthropicProposer in the
    tagger so only one anthropic.Anthropic() is created per run.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def polish(self, code: str, session_log: SessionLog) -> str:
        log_json = json.dumps(session_log, indent=2, sort_keys=True)
        prompt = _POLISH_PROMPT.format(session_log_json=log_json, code=code)
        try:
            message = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            warnings.warn(
                f"LLM polish API call failed: {exc} — using deterministic output",
                stacklevel=2,
            )
            return code

        if not message.content:
            return code
        return message.content[0].text.strip()


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
