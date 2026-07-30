"""Step 7 end-to-end: shim-recorded `juju <subcommand>` events through
`generate()` — confirms real integration (not just the pure classifier),
and covers the CLI corpus notes §7's golden-output regression scope: existing
shim-`shell` behaviour must be unchanged for anything that stays bucket 2/3,
and mixed bucket-1/bucket-2 sessions must dispatch per-event.
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
    """F1 regression: a translated add-unit must not resurrect `juju.scale()`."""
    src = generate(_wrap([_shim_event(1, ["add-unit", "my-charm", "-n", "2"])]))
    assert "juju.add_unit('my-charm', num_units=2)" in src
    assert "juju.scale(" not in src


def test_bucket1_scale_application_emits_cli_escape_hatch() -> None:
    src = generate(_wrap([_shim_event(1, ["scale-application", "my-charm", "5"])]))
    assert "juju.cli(\"scale-application\", 'my-charm', '5')" in src


def test_bucket1_run_single_unit() -> None:
    src = generate(_wrap([_shim_event(1, ["run", "my-charm/0", "backup"])]))
    assert "juju.run('my-charm/0', 'backup')" in src


def test_bucket2_excepted_flag_still_renders_shell_comment() -> None:
    """deploy --attach-storage has no representable kwarg — stays the
    existing `# shell:` rendering, unchanged by step 7 (§7 golden-output
    regression scope)."""
    src = generate(_wrap([_shim_event(1, ["deploy", "my-charm", "--attach-storage", "foo/0"])]))
    assert "# shell: juju deploy my-charm --attach-storage foo/0" in src
    assert "juju.deploy(" not in src


def test_bucket2_multi_unit_run_still_renders_shell_comment() -> None:
    src = generate(_wrap([_shim_event(1, ["run", "my-charm/0", "my-charm/1", "backup"])]))
    assert "# shell: juju run my-charm/0 my-charm/1 backup" in src
    assert "juju.run(" not in src


def test_bucket3_unhandled_subcommand_still_renders_shell_comment() -> None:
    src = generate(_wrap([_shim_event(1, ["ssh", "my-charm/0", "ls"])]))
    assert "# shell: juju ssh my-charm/0 ls" in src


def test_add_secret_never_translated_stays_shell_comment() -> None:
    """F5: PATH shim has no redaction — add-secret argv must never become a
    typed `juju.add_secret(...)` call. It still renders as the existing
    `# shell:` comment (which — pre-existing F5 gap, unchanged here — does
    carry the plaintext argv; that gap is the shim's, not step 7's, to fix).
    """
    src = generate(_wrap([_shim_event(1, ["add-secret", "my-secret", "token=hunter2"])]))
    assert "# shell: juju add-secret my-secret token=hunter2" in src
    assert "juju.add_secret(" not in src


def test_mixed_session_dispatches_per_event() -> None:
    """One bucket-1 event and one bucket-3 event in the same log — dispatch
    is per-event, not per-session (§7)."""
    events = [
        _shim_event(1, ["deploy", "my-charm", "--channel", "edge"]),
        _shim_event(2, ["ssh", "my-charm/0", "ls"]),
    ]
    src = generate(_wrap(events))
    assert "juju.deploy('my-charm', channel='edge')" in src
    assert "# shell: juju ssh my-charm/0 ls" in src


def test_shell_context_python_wrapper_path_untouched() -> None:
    """`shell_context` (JTR_PYTHON_ACTIVE double-recording guard) must never
    be fed into the bucket-1 dispatch — it's narration, not a step (§7)."""
    event = _shim_event(1, ["deploy", "my-charm"])
    event["op"] = "shell_context"
    event["result"] = {"exit_code": 0, "stdout": None, "stderr": None, "stdout_truncated": False}
    src = generate(_wrap([event]))
    assert "# context: deploy my-charm" in src
    assert "juju.deploy(" not in src


def test_wait_for_idle_never_captured_from_shim() -> None:
    """§7: there is no `juju` subcommand for wait_for_idle — the classifier
    must never invent a match (27, not 28, of the ops are argv-reachable)."""
    from jubilant_recorder.codegen import cli_translate

    assert "wait-for-idle" not in cli_translate._SUBCOMMANDS
    assert cli_translate.classify_argv(["wait-for-idle", "my-charm"]) is None
