"""Optional, flag-gated AI polish over deterministic codegen."""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from jubilant_recorder import codegen, tagger
from jubilant_recorder.codegen import ai_polish
from jubilant_recorder.codegen.ai_polish import LLMPolisher, Polisher, StubPolisher, polish

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


# ── LLMPolisher ────────────────────────────────────────────────────────────────


def _make_mock_client(response_text: str) -> Any:
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": response_text}}]}
    client = MagicMock()
    client.post.return_value = response
    return client


def test_llm_polisher_satisfies_protocol() -> None:
    assert isinstance(LLMPolisher(MagicMock(), model="test/model"), Polisher)


def test_llm_polisher_returns_improved_code_when_valid() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    # The "polished" version renames the test function but keeps all juju calls.
    improved = deterministic.replace("def test_recorded_session(", "def test_deploy_my_charm(")
    polisher = LLMPolisher(_make_mock_client(improved), model="test/model")
    result = polish(deterministic, log, polisher=polisher)
    # behaviour_preserved passes → polished version is used
    assert "test_deploy_my_charm" in result
    ast.parse(result)


def test_llm_polisher_falls_back_on_behaviour_violation() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    # Mock returns code that drops juju.deploy — behaviour_preserved will reject it
    bad_code = "\n".join(line for line in deterministic.splitlines() if "juju.deploy(" not in line)
    polisher = LLMPolisher(_make_mock_client(bad_code), model="test/model")
    result = polish(deterministic, log, polisher=polisher)
    assert result == deterministic


def test_llm_polisher_api_error_warns_and_returns_original() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    client = MagicMock()
    client.post.side_effect = RuntimeError("connection refused")
    polisher = LLMPolisher(client, model="test/model")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = polisher.polish(deterministic, log)

    assert result == deterministic
    assert any("API call failed" in str(warning.message) for warning in w)


def test_llm_polisher_empty_response_returns_original() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    response = MagicMock()
    response.json.return_value = {"choices": []}
    client = MagicMock()
    client.post.return_value = response
    polisher = LLMPolisher(client, model="test/model")
    result = polisher.polish(deterministic, log)
    # empty choices → returns the original code unchanged (polish() will keep it)
    assert result == deterministic


class _ReturningPolisher:
    """Returns whatever it was constructed with, whatever it was given."""

    def __init__(self, out: str) -> None:
        self._out = out

    def polish(self, code: str, session_log: dict[str, Any]) -> str:
        return self._out


class _AssertRewritingPolisher:
    """Stands in for the live model, which rewrote assertions despite the prompt."""

    def __init__(self, replacement: str) -> None:
        self._replacement = replacement

    def polish(self, code: str, session_log) -> str:
        return self._replacement


_ORIGINAL = """import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu')
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
"""

_REWRITTEN = """import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu')
        assert juju.status().apps['ubuntu'].units['ubuntu/1'].workload_status.current == 'active'
"""

_RENAMED_ONLY = """import jubilant


def test_deploys_ubuntu():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu')
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
"""


def test_polish_rejects_rewritten_assertions():
    polisher = _AssertRewritingPolisher(_REWRITTEN)

    with pytest.warns(UserWarning, match="changed the test's assertions"):
        result = polish(_ORIGINAL, {}, polisher=polisher)

    assert result == _ORIGINAL


def test_polish_keeps_a_rename_that_leaves_assertions_alone():
    polisher = _AssertRewritingPolisher(_RENAMED_ONLY)

    assert polish(_ORIGINAL, {}, polisher=polisher) == _RENAMED_ONLY


@pytest.mark.parametrize(
    "fence",
    ["```python\n{body}```\n", "```\n{body}```\n", "  ```py\n{body}```  \n"],
    ids=["language", "bare", "surrounding-whitespace"],
)
def test_llm_polisher_strips_a_markdown_fence(fence: str) -> None:
    # The prompt says not to fence the code; models do it anyway, and an
    # unstripped fence makes a perfectly good polish a SyntaxError.
    log = _annotated()
    deterministic = codegen.generate(log)
    improved = deterministic.replace("def test_recorded_session(", "def test_deploy_my_charm(")
    polisher = LLMPolisher(_make_mock_client(fence.format(body=improved)), model="test/model")

    result = polish(deterministic, log, polisher=polisher)

    assert "test_deploy_my_charm" in result
    assert "```" not in result
    ast.parse(result)


def test_llm_polisher_leaves_unfenced_code_alone() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    improved = deterministic.replace("def test_recorded_session(", "def test_deploy_my_charm(")
    polisher = LLMPolisher(_make_mock_client(improved), model="test/model")
    assert polisher.polish(deterministic, log) == improved.strip()


def test_llm_polisher_does_not_strip_a_fence_inside_the_code() -> None:
    # Only a fence wrapping the whole response is a wrapper; one in a
    # docstring is content.
    log = _annotated()
    deterministic = codegen.generate(log)
    improved = deterministic.replace(
        "def test_recorded_session():",
        'def test_recorded_session():\n    """Recorded from:\n\n    ```\n    juju deploy\n    ```\n    """',
    )
    polisher = LLMPolisher(_make_mock_client(improved), model="test/model")
    assert "```" in polisher.polish(deterministic, log)


@pytest.mark.parametrize(
    ("polished", "expected"),
    [
        ("", "returned nothing"),
        ("{code}", "returned the test unchanged"),
        ("not python at all ((", "did not return parseable Python"),
        ("{dropped}", "changed the test's juju calls"),
    ],
    ids=["empty", "identical", "unparseable", "behaviour-changed"],
)
def test_every_discarded_polish_says_which_gate_rejected_it(polished: str, expected: str) -> None:
    # A discarded polish and a model with nothing to add both leave the
    # deterministic output in place; without a warning they are the same
    # observation from outside.
    log = _annotated()
    deterministic = codegen.generate(log)
    dropped = "\n".join(line for line in deterministic.splitlines() if "juju.deploy(" not in line)
    out = polished.format(code=deterministic, dropped=dropped)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = polish(deterministic, log, polisher=_ReturningPolisher(out))

    assert result == deterministic
    assert any(expected in str(warning.message) for warning in w), [
        str(warning.message) for warning in w
    ]


def test_an_accepted_polish_warns_about_nothing() -> None:
    log = _annotated()
    deterministic = codegen.generate(log)
    improved = deterministic.replace("def test_recorded_session(", "def test_deploy_my_charm(")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = polish(deterministic, log, polisher=_ReturningPolisher(improved))

    assert "test_deploy_my_charm" in result
    assert not w
