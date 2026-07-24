from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from jubilant_recorder.jtr_cli import cmd_shim_install


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_shim_install_writes_executable_shim(tmp_path: Path) -> None:
    target = tmp_path / "shims"
    rc = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc == 0

    shim_path = target / "juju"
    assert shim_path.exists()
    mode = stat.S_IMODE(os.stat(shim_path).st_mode)
    assert mode & stat.S_IXUSR

    content = shim_path.read_text()
    assert "/usr/bin/true" in content
    assert "__REAL_JUJU__" not in content


def test_shim_install_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "shims"
    rc1 = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc1 == 0
    first_content = (target / "juju").read_text()

    rc2 = cmd_shim_install(_ns(target=str(target), real_juju="/usr/bin/true"))
    assert rc2 == 0
    second_content = (target / "juju").read_text()

    assert first_content == second_content


def test_shim_install_no_real_juju_error(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    target = tmp_path / "shims"
    rc = cmd_shim_install(_ns(target=str(target), real_juju=None))
    assert rc != 0
    assert "--real-juju" in capsys.readouterr().err
