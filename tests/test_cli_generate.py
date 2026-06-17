"""`recorder generate` produces a syntactically valid pytest test file."""

from __future__ import annotations

import ast
from pathlib import Path

from jubilant_recorder.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_session.json"


def test_generate_produces_valid_python(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out)])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    assert "import jubilant" in source
    assert "def test_recorded_session" in source


def test_generate_respects_name_arg(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out), "--name", "test_deploy_flow"])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    assert "def test_deploy_flow" in source


def test_generate_includes_recorded_operations(tmp_path: Path) -> None:
    out = tmp_path / "test_recorded.py"
    main(["generate", str(FIXTURE), "--out", str(out)])
    source = out.read_text()
    assert "juju.deploy(" in source
    assert "juju.wait(" in source
    assert "juju.run(" in source
