"""End-to-end: shim-recorded `juju <subcommand>` events through
`generate()` — confirms real integration (not just the pure classifier).

Every `juju` command a shell session records becomes a runnable jubilant
call: a typed one where `jubilant.Juju` has a matching method, and
`juju.cli(...)` otherwise. A `# shell:` comment survives only for a bare
`juju` with no arguments, which is not a step at all.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap


def _shim_event(seq: int, argv: list[str]) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell",
        "ts": "2026-07-28T10:00:00.000Z",
        "args": {"argv": argv, "basename": "juju", "source": "shim", "session_id": "sess"},
        "result": {"captured": False, "exit_code": None},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def test_bucket1_deploy_argv_emits_real_call() -> None:
    src = generate(_wrap([_shim_event(1, ["deploy", "my-charm", "--channel", "edge"])]))
    assert "juju.deploy('my-charm', channel='edge')" in src
    assert "# shell:" not in src


def test_bucket1_config_set_argv_emits_real_call() -> None:
    src = generate(_wrap([_shim_event(1, ["config", "my-charm", "log-level=debug"])]))
    assert "juju.config('my-charm', values={'log-level': 'debug'})" in src
    assert "# shell:" not in src


def test_bucket1_add_unit_emits_add_unit_not_broken_scale() -> None:
    """Regression: a translated add-unit must not resurrect `juju.scale()`."""
    src = generate(_wrap([_shim_event(1, ["add-unit", "my-charm", "-n", "2"])]))
    assert "juju.add_unit('my-charm', num_units=2)" in src
    assert "juju.scale(" not in src


def test_bucket1_scale_application_emits_cli_escape_hatch() -> None:
    src = generate(_wrap([_shim_event(1, ["scale-application", "my-charm", "5"])]))
    assert "juju.cli(\"scale-application\", 'my-charm', '5')" in src


def test_bucket1_run_single_unit() -> None:
    src = generate(_wrap([_shim_event(1, ["run", "my-charm/0", "backup"])]))
    assert "juju.run('my-charm/0', 'backup')" in src


def test_untyped_deploy_flag_falls_through_to_cli() -> None:
    """`deploy --attach-storage` has no representable kwarg, so the whole
    command is emitted as `juju.cli(...)` — nothing is dropped, and the
    reader has a runnable line rather than a comment to retype."""
    src = generate(_wrap([_shim_event(1, ["deploy", "my-charm", "--attach-storage", "foo/0"])]))
    assert "juju.cli('deploy', 'my-charm', '--attach-storage', 'foo/0')" in src
    assert "juju.deploy(" not in src
    assert "# shell:" not in src


def test_multi_unit_run_falls_through_to_cli() -> None:
    src = generate(_wrap([_shim_event(1, ["run", "my-charm/0", "my-charm/1", "backup"])]))
    assert "juju.cli('run', 'my-charm/0', 'my-charm/1', 'backup')" in src
    assert "juju.run(" not in src


def test_unknown_subcommand_falls_through_to_cli() -> None:
    src = generate(_wrap([_shim_event(1, ["no-such-command", "arg"])]))
    assert "juju.cli('no-such-command', 'arg')" in src
    assert "# shell:" not in src


def test_controller_scoped_subcommand_disables_model_injection() -> None:
    """`juju.cli()` inserts `--model` by default; `juju whoami` rejects it."""
    src = generate(_wrap([_shim_event(1, ["whoami"])]))
    assert "juju.cli('whoami', include_model=False)" in src


def test_prompting_subcommand_gains_no_prompt() -> None:
    """An unattended test cannot answer a confirmation prompt."""
    src = generate(_wrap([_shim_event(1, ["remove-machine", "0"])]))
    assert "juju.cli('remove-machine', '--no-prompt', '0')" in src


def test_ssh_translates_to_typed_call() -> None:
    src = generate(_wrap([_shim_event(1, ["ssh", "my-charm/0", "ls"])]))
    assert "juju.ssh('my-charm/0', 'ls')" in src


def test_add_secret_translates_to_typed_call() -> None:
    """`add-secret` is translated; the shim redacts the content on the way in.

    Redaction happens at record time (`jubilant_recorder.redaction`, applied
    by `shim/juju_shim.py`), so what reaches codegen is already a
    `<redacted:…>` marker for anything that looked like a credential.
    """
    src = generate(_wrap([_shim_event(1, ["add-secret", "my-secret", "key=value"])]))
    assert "juju.add_secret('my-secret', {'key': 'value'})" in src


def test_mixed_session_dispatches_per_event() -> None:
    """A typed event and a passthrough event in the same log — dispatch
    is per-event, not per-session."""
    events = [
        _shim_event(1, ["deploy", "my-charm", "--channel", "edge"]),
        _shim_event(2, ["export-bundle", "--filename", "b.yaml"]),
    ]
    src = generate(_wrap(events))
    assert "juju.deploy('my-charm', channel='edge')" in src
    assert "juju.cli('export-bundle', '--filename', 'b.yaml')" in src


def test_shell_context_python_wrapper_path_untouched() -> None:
    """`shell_context` (JTR_PYTHON_ACTIVE double-recording guard) must never
    be fed into the bucket-1 dispatch — it's narration, not a step."""
    event = _shim_event(1, ["deploy", "my-charm"])
    event["op"] = "shell_context"
    event["result"] = {"exit_code": 0, "stdout": None, "stderr": None, "stdout_truncated": False}
    src = generate(_wrap([event]))
    assert "# context: deploy my-charm" in src
    assert "juju.deploy(" not in src


def test_wait_for_idle_never_captured_from_shim() -> None:
    """There is no `juju` subcommand for wait_for_idle — the classifier
    must never invent a match (27, not 28, of the ops are argv-reachable)."""
    from jubilant_recorder.codegen import cli_translate

    assert "wait-for-idle" not in cli_translate._SUBCOMMANDS
    assert cli_translate.classify_argv(["wait-for-idle", "my-charm"]) == (
        "cli_passthrough",
        {"argv": ["wait-for-idle", "my-charm"]},
    )
