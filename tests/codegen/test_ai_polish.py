"""Optional, flag-gated AI polish over deterministic codegen."""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from jubilant_recorder import codegen, tagger
from jubilant_recorder.codegen import ai_polish
from jubilant_recorder.codegen.ai_polish import AnthropicPolisher, Polisher, StubPolisher, polish

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "minimal_session.json"


def _annotated() -> dict[str, Any]:
    return tagger.tag(json.loads(FIXTURE.read_text()))


def test_stub_polisher_adds_event_count_docstring() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    polished = StubPolisher().polish(deterministic, log)
    n = len(log["events"])
    assert polished.startswith(f'"""<recorded session: {n} events>"""\n')
    ast.parse(polished)


def test_polished_output_is_valid_python_and_keeps_calls() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    polished = polish(deterministic, log)
    ast.parse(polished)
    # Every behaviour-bearing juju call survives the polish pass.
    for call in ("juju.deploy(", "juju.run("):
        assert call in polished


def test_stub_polisher_satisfies_protocol() -> None:
    assert isinstance(StubPolisher(), Polisher)


def test_polish_is_byte_identical_to_deterministic_without_docstring() -> None:
    # Round-trip: deterministic codegen + StubPolisher == prepended docstring,
    # and stripping the docstring line yields the deterministic output back.
    log = _annotated()
    deterministic = codegen.generate(log)
    polished = polish(deterministic, log)
    assert polished != deterministic
    stripped = polished.split("\n", 1)[1]
    assert stripped == deterministic


def test_polish_idempotent_when_run_twice() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    once = polish(deterministic, log)
    twice = polish(once, log)
    ast.parse(twice)
    # Re-polishing replaces the docstring rather than stacking a second one.
    assert twice.count("<recorded session:") == 1


class _DroppingPolisher:
    """A misbehaving polisher that deletes a deploy call."""

    def polish(self, code: str, session_log: dict[str, Any]) -> str:
        return "\n".join(line for line in code.splitlines() if "juju.deploy(" not in line)


class _SyntaxBreakingPolisher:
    def polish(self, code: str, session_log: dict[str, Any]) -> str:
        return code + "\n    this is not valid python ((("


def test_polish_rejects_polisher_that_drops_a_call() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    out = polish(deterministic, log, polisher=_DroppingPolisher())
    # The guard discards the polished version and returns deterministic code.
    assert out == deterministic


def test_polish_rejects_polisher_that_breaks_syntax() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    out = polish(deterministic, log, polisher=_SyntaxBreakingPolisher())
    assert out == deterministic


def test_behaviour_preserved_allows_wait_for_idle_collapse() -> None:
    original = (
        "import jubilant\n\n\ndef t():\n    with jubilant.temp_model() as juju:\n"
        "        juju.deploy('a')\n"
        "        juju.wait_for_idle()\n"
        "        juju.wait_for_idle()\n"
    )
    collapsed = (
        "import jubilant\n\n\ndef t():\n    with jubilant.temp_model() as juju:\n"
        "        juju.deploy('a')\n"
        "        juju.wait_for_idle()\n"
    )
    assert ai_polish.behaviour_preserved(original, collapsed)


def test_behaviour_preserved_rejects_dropped_deploy() -> None:
    original = (
        "import jubilant\n\n\ndef t():\n    with jubilant.temp_model() as juju:\n"
        "        juju.deploy('a')\n"
    )
    without = (
        "import jubilant\n\n\ndef t():\n    with jubilant.temp_model() as juju:\n        pass\n"
    )
    assert not ai_polish.behaviour_preserved(original, without)


# ── AnthropicPolisher ─────────────────────────────────────────────────────────


def _make_mock_client(response_text: str) -> Any:
    message = MagicMock()
    message.content = [MagicMock(text=response_text)]
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def test_anthropic_polisher_satisfies_protocol() -> None:
    assert isinstance(AnthropicPolisher(MagicMock()), Polisher)


def test_anthropic_polisher_returns_improved_code_when_valid() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    # The "polished" version renames the test function but keeps all juju calls.
    improved = deterministic.replace("def test_recorded_session(", "def test_deploy_my_charm(")
    polisher = AnthropicPolisher(_make_mock_client(improved))
    result = polish(deterministic, log, polisher=polisher)
    # behaviour_preserved passes → polished version is used
    assert "test_deploy_my_charm" in result
    ast.parse(result)


def test_anthropic_polisher_falls_back_on_behaviour_violation() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    # Mock returns code that drops juju.deploy — behaviour_preserved will reject it
    bad_code = "\n".join(line for line in deterministic.splitlines() if "juju.deploy(" not in line)
    polisher = AnthropicPolisher(_make_mock_client(bad_code))
    result = polish(deterministic, log, polisher=polisher)
    assert result == deterministic


def test_anthropic_polisher_api_error_warns_and_returns_original() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("connection refused")
    polisher = AnthropicPolisher(client)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = polisher.polish(deterministic, log)

    assert result == deterministic
    assert any("API call failed" in str(warning.message) for warning in w)


def test_anthropic_polisher_empty_response_returns_original() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    message = MagicMock()
    message.content = []
    client = MagicMock()
    client.messages.create.return_value = message
    polisher = AnthropicPolisher(client)
    result = polisher.polish(deterministic, log)
    # empty content → returns the original code unchanged (polish() will keep it)
    assert result == deterministic
