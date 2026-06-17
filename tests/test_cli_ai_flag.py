"""The `--ai` flag gates the polish pass; default off, deterministic otherwise."""

from __future__ import annotations

import ast
from pathlib import Path

from jubilant_recorder.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_session.json"


def test_generate_without_ai_is_unpolished(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out)])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    assert "<recorded session:" not in source
    assert source.startswith("import jubilant\n")


def test_generate_with_ai_invokes_stub_polisher(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out), "--ai"])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    # The StubPolisher's deterministic transformation: a module docstring
    # recording the event count.
    assert source.startswith('"""<recorded session:')


def test_ai_flag_only_adds_docstring(tmp_path: Path) -> None:
    plain = tmp_path / "plain.py"
    polished = tmp_path / "polished.py"
    main(["generate", str(FIXTURE), "--out", str(plain)])
    main(["generate", str(FIXTURE), "--out", str(polished), "--ai"])
    plain_src = plain.read_text()
    polished_src = polished.read_text()
    # Without --ai the output is byte-identical to deterministic codegen;
    # with --ai the only difference is the prepended docstring line.
    assert polished_src.split("\n", 1)[1] == plain_src
