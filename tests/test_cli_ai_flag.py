"""The `--ai` flag gates the polish pass; default off, deterministic otherwise."""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

from jubilant_recorder.cli import _make_ai_components, main
from jubilant_recorder.codegen.ai_polish import LLMPolisher, StubPolisher
from jubilant_recorder.tagger.llm import LLMProposer, StubProposer

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_session.json"


def test_generate_without_ai_is_unpolished(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out)])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    assert "<recorded session:" not in source
    assert source.startswith("import jubilant\n")


def test_generate_with_ai_invokes_stub_polisher(tmp_path: Path, monkeypatch: object) -> None:
    # No OPENROUTER_API_KEY → --ai falls back to StubPolisher regardless of
    # what's in the ambient environment.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # type: ignore[attr-defined]
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out), "--ai"])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    # The StubPolisher's deterministic transformation: a module docstring
    # recording the event count.
    assert source.startswith('"""<recorded session:')


def test_ai_flag_only_adds_docstring(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # type: ignore[attr-defined]
    plain = tmp_path / "plain.py"
    polished = tmp_path / "polished.py"
    main(["generate", str(FIXTURE), "--out", str(plain)])
    main(["generate", str(FIXTURE), "--out", str(polished), "--ai"])
    plain_src = plain.read_text()
    polished_src = polished.read_text()
    # Without --ai the output is byte-identical to deterministic codegen;
    # with --ai the only difference is the prepended docstring line.
    assert polished_src.split("\n", 1)[1] == plain_src


def test_make_ai_components_no_api_key_returns_stubs(monkeypatch: object) -> None:
    """Without OPENROUTER_API_KEY, _make_ai_components returns offline stubs."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # type: ignore[attr-defined]

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        proposer, polisher = _make_ai_components(True)

    assert isinstance(proposer, StubProposer)
    assert isinstance(polisher, StubPolisher)
    assert any("OPENROUTER_API_KEY" in str(warning.message) for warning in w)


def test_make_ai_components_with_api_key_returns_real_clients(monkeypatch: object) -> None:
    """With OPENROUTER_API_KEY set, _make_ai_components returns OpenRouter-backed objects."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")  # type: ignore[attr-defined]

    proposer, polisher = _make_ai_components(True)

    assert isinstance(proposer, LLMProposer)
    assert isinstance(polisher, LLMPolisher)


def test_make_ai_components_use_ai_false_returns_stubs() -> None:
    proposer, polisher = _make_ai_components(False)
    assert isinstance(proposer, StubProposer)
    assert isinstance(polisher, StubPolisher)
