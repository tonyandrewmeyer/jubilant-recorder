from __future__ import annotations

import argparse
from pathlib import Path

from jubilant_recorder.jtr_cli import cmd_shell_install


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_shell_install_appends_markers_on_first_run(tmp_path: Path) -> None:
    rcfile = tmp_path / "bashrc"
    rcfile.write_text("# existing content\n")

    rc = cmd_shell_install(_ns(shell="bash", rcfile=str(rcfile), no_path_shim=False))
    assert rc == 0

    content = rcfile.read_text()
    assert content.startswith("# existing content\n")
    assert content.count("# BEGIN jtr shell-init") == 1
    assert content.count("# END jtr shell-init") == 1
    assert "preexec_functions+=(preexec)" in content
    assert "precmd_functions+=(precmd)" in content


def test_shell_install_updates_block_not_appended_twice(tmp_path: Path) -> None:
    rcfile = tmp_path / "bashrc"
    rcfile.write_text("# existing content\n")

    cmd_shell_install(_ns(shell="bash", rcfile=str(rcfile), no_path_shim=False))
    first_content = rcfile.read_text()

    rc = cmd_shell_install(_ns(shell="bash", rcfile=str(rcfile), no_path_shim=False))
    assert rc == 0
    second_content = rcfile.read_text()

    assert second_content.count("# BEGIN jtr shell-init") == 1
    assert second_content.count("# END jtr shell-init") == 1
    assert second_content == first_content


def test_shell_install_no_path_shim_propagates(tmp_path: Path) -> None:
    rcfile = tmp_path / "zshrc"

    rc = cmd_shell_install(_ns(shell="zsh", rcfile=str(rcfile), no_path_shim=True))
    assert rc == 0

    content = rcfile.read_text()
    assert "Add jtr shim directory to PATH" not in content
    assert "# BEGIN jtr shell-init" in content


def test_shell_install_creates_file_when_absent(tmp_path: Path) -> None:
    rcfile = tmp_path / "newrc" / "zshrc"

    rc = cmd_shell_install(_ns(shell="zsh", rcfile=str(rcfile), no_path_shim=False))
    assert rc == 0
    assert rcfile.exists()
    assert "# BEGIN jtr shell-init" in rcfile.read_text()
