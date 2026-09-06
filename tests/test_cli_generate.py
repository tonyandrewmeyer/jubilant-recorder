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


def test_generate_source_aware_picks_up_test_name_var_name_and_comment(
    tmp_path: Path,
) -> None:
    """`--source-aware` is decorative (src/jubilant_recorder/extensions/libjuju/source_overlay.py):
    it must not be required for correct output, but when given a matching
    source file it should improve the test name, the `run` result variable
    name, and carry the adjacent comment through."""
    source_file = tmp_path / "test_my_charm.py"
    source_file.write_text(
        "async def test_deploy_and_run(juju):\n"
        '    await juju.deploy("my-charm")\n'
        "    await juju.wait_for_idle(apps=['my-charm'])\n"
        "    output = await juju.run_action('my-charm/0', 'do-thing')  # confirm it worked\n",
        encoding="utf-8",
    )
    out = tmp_path / "test_recorded.py"
    rc = main(["generate", str(FIXTURE), "--out", str(out), "--source-aware", str(source_file)])
    assert rc == 0
    source = out.read_text()
    ast.parse(source)
    assert "def test_deploy_and_run():" in source
    assert "output = juju.run(" in source
    assert "# confirm it worked" in source


def test_generate_source_aware_with_unrelated_file_is_a_no_op(tmp_path: Path) -> None:
    """A `--source-aware` path with no correlatable call sites must not
    change the output at all — the recording alone is always sufficient."""
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("x = 1\n", encoding="utf-8")

    plain_out = tmp_path / "plain.py"
    main(["generate", str(FIXTURE), "--out", str(plain_out)])

    aware_out = tmp_path / "aware.py"
    main(["generate", str(FIXTURE), "--out", str(aware_out), "--source-aware", str(unrelated)])

    assert plain_out.read_text() == aware_out.read_text()
