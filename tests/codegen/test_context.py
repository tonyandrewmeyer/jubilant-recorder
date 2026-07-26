from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen.context import (
    interleave_context,
    render_config_result,
    render_note,
    render_shell,
    render_shell_context,
    render_status_comment,
)
from jubilant_recorder.codegen.emit import generate
from tests.codegen.conftest import EMPTY_SNAPSHOT, _event, _wrap

INDENT = 8
PAD = " " * INDENT


def _shell_context_event(
    seq: int,
    argv: list[str],
    basename: str,
    source: str = "hook",
    exit_code: int | None = 0,
    stdout: str | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell_context",
        "ts": "2026-06-28T10:00:00.000Z",
        "args": {
            "argv": argv,
            "basename": basename,
            "source": source,
            "session_id": "test-session",
        },
        "result": {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": None,
            "stdout_truncated": False,
        },
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _note_event(seq: int, text: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "note",
        "ts": "2026-06-28T10:00:00.000Z",
        "args": {"text": text},
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _tag_event(seq: int, label: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "tag",
        "ts": "2026-06-28T10:00:00.000Z",
        "args": {"label": label},
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _snapshot_with_units(units: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Build a minimal snapshot with a single app 'my-app' and given units.

    units: {unit_name: (workload_status, workload_message)}
    """
    return {
        "schema_version": 1,
        "captured_at": "2026-06-28T10:00:00.000Z",
        "apps": {
            "my-app": {
                "units": {
                    unit: {
                        "workload_status": status,
                        "workload_message": message,
                        "agent_status": "idle",
                    }
                    for unit, (status, message) in units.items()
                }
            }
        },
        "relations": [],
    }


# --- render_shell_context ---


def test_render_shell_context_basic() -> None:
    event = _shell_context_event(1, ["kubectl", "get", "pods"], "kubectl")
    result = render_shell_context(event, INDENT)
    assert result == f"{PAD}# context: kubectl get pods"


def test_render_shell_context_nonzero_exit() -> None:
    event = _shell_context_event(1, ["helm", "install", "foo"], "helm", exit_code=1)
    result = render_shell_context(event, INDENT)
    lines = result.splitlines()
    assert lines[0] == f"{PAD}# context: helm install foo"
    assert lines[1] == f"{PAD}# exit 1"


def test_render_shell_context_zero_exit_no_extra_line() -> None:
    event = _shell_context_event(1, ["kubectl", "get", "pods"], "kubectl", exit_code=0)
    result = render_shell_context(event, INDENT)
    assert "\n" not in result  # single line only


def test_render_shell_context_stdout_shown() -> None:
    event = _shell_context_event(
        1, ["kubectl", "get", "pods"], "kubectl", stdout="pod1\npod2\npod3"
    )
    result = render_shell_context(event, INDENT)
    assert f"{PAD}# | pod1" in result
    assert f"{PAD}# | pod2" in result
    assert f"{PAD}# | pod3" in result


def test_render_shell_context_stdout_truncated_at_5() -> None:
    lines = [f"line{i}" for i in range(7)]
    event = _shell_context_event(1, ["kubectl", "logs", "pod"], "kubectl", stdout="\n".join(lines))
    result = render_shell_context(event, INDENT)
    assert "line4" in result
    assert "line5" not in result
    assert "(2 more)" in result


# --- render_note ---


def test_render_note_basic() -> None:
    event = _note_event(1, "this is a note")
    result = render_note(event, INDENT)
    assert result == f"{PAD}# note: this is a note"


def test_render_note_empty_text() -> None:
    event = _note_event(1, "")
    result = render_note(event, INDENT)
    assert result == f"{PAD}# note: "


# --- render_status_comment ---


def test_render_status_comment_all_active_no_message_returns_none() -> None:
    event = _event(1, "status", {}, {"snapshot": EMPTY_SNAPSHOT})
    event["model_snapshot_after"] = _snapshot_with_units(
        {
            "my-app/0": ("active", ""),
            "my-app/1": ("active", ""),
        }
    )
    result = render_status_comment(event, INDENT)
    assert result is None


def test_render_status_comment_nonactive_unit() -> None:
    event = _event(1, "status", {}, {"snapshot": EMPTY_SNAPSHOT})
    event["model_snapshot_after"] = _snapshot_with_units(
        {
            "my-app/0": ("waiting", "waiting for db"),
        }
    )
    result = render_status_comment(event, INDENT)
    assert result is not None
    assert "waiting" in result
    assert "waiting for db" in result


def test_render_status_comment_none_snapshot() -> None:
    event = _event(1, "status", {}, {"snapshot": None})
    event["model_snapshot_after"] = None
    result = render_status_comment(event, INDENT)
    assert result is not None
    assert "error" in result


def test_render_status_comment_empty_apps() -> None:
    event = _event(1, "status", {}, {"snapshot": EMPTY_SNAPSHOT})
    event["model_snapshot_after"] = EMPTY_SNAPSHOT
    result = render_status_comment(event, INDENT)
    assert result is None


# --- render_config_result ---


def test_render_config_result_no_change_returns_none(config_event: dict[str, Any]) -> None:
    config_event["model_snapshot_before"] = EMPTY_SNAPSHOT
    config_event["model_snapshot_after"] = EMPTY_SNAPSHOT
    result = render_config_result(config_event, INDENT)
    assert result is None


def test_render_config_result_status_change() -> None:
    before = _snapshot_with_units({"my-app/0": ("waiting", "")})
    after = _snapshot_with_units({"my-app/0": ("active", "")})
    event = _event(1, "config", {"app": "my-app", "values": {"k": "v"}})
    event["model_snapshot_before"] = before
    event["model_snapshot_after"] = after
    result = render_config_result(event, INDENT)
    assert result is not None
    assert "active" in result
    assert "was waiting" in result


# --- generate() with shell-hook events ---


def test_generate_shell_context_renders_comment() -> None:
    ctx_event = _shell_context_event(1, ["kubectl", "get", "pods"], "kubectl")
    deploy_event = _event(
        2,
        "deploy",
        {
            "charm": "my-charm",
            "app": None,
            "channel": None,
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        {"app_name": "my-charm"},
    )
    log = _wrap([ctx_event, deploy_event])
    output = generate(log)
    assert "# context: kubectl get pods" in output
    assert "juju.deploy" in output


def test_generate_note_renders_comment() -> None:
    note_event = _note_event(1, "initial setup")
    deploy_event = _event(
        2,
        "deploy",
        {
            "charm": "my-charm",
            "app": None,
            "channel": None,
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        {"app_name": "my-charm"},
    )
    log = _wrap([note_event, deploy_event])
    output = generate(log)
    assert "# note: initial setup" in output
    assert "juju.deploy" in output


def test_generate_tag_emits_step_before_next_op() -> None:
    tag_event = _tag_event(1, "deploy phase")
    deploy_event = _event(
        2,
        "deploy",
        {
            "charm": "my-charm",
            "app": None,
            "channel": None,
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        {"app_name": "my-charm"},
    )
    log = _wrap([tag_event, deploy_event])
    output = generate(log)
    assert "# step: deploy phase" in output
    # step comment should appear before the deploy call
    step_pos = output.index("# step: deploy phase")
    deploy_pos = output.index("juju.deploy")
    assert step_pos < deploy_pos


def test_generate_tag_only_no_following_op() -> None:
    """A tag with no following jubilant op is silently dropped."""
    tag_event = _tag_event(1, "orphan tag")
    log = _wrap([tag_event])
    output = generate(log)
    # orphan tag is dropped; just the pass placeholder is emitted
    assert "# step: orphan tag" not in output


def test_generate_status_no_assertions_rendered_as_comment() -> None:
    """status with no assertions/gesture becomes a comment, not a jubilant call."""
    status_event = _event(1, "status", {}, {"snapshot": EMPTY_SNAPSHOT})
    status_event["model_snapshot_after"] = _snapshot_with_units(
        {
            "my-app/0": ("waiting", "initialising"),
        }
    )
    log = _wrap([status_event])
    output = generate(log)
    assert "juju.status()" not in output
    assert "# juju status:" in output


def test_generate_status_with_assertion_not_a_comment() -> None:
    """status with assertions goes through normal emitter path."""
    status_event = _event(
        1,
        "status",
        {},
        {"snapshot": EMPTY_SNAPSHOT},
        assertions=[
            {
                "kind": "unit_status",
                "app": "my-app",
                "unit": "my-app/0",
                "expected": "active",
                "strict": False,
                "source": "delta",
            }
        ],
    )
    log = _wrap([status_event])
    output = generate(log)
    assert "juju.status()" in output


def test_generate_status_with_gesture_not_a_comment() -> None:
    """status with gesture goes through normal emitter path."""
    status_event = _event(
        1,
        "status",
        {},
        {"snapshot": EMPTY_SNAPSHOT},
        gesture={"kind": "checkpoint", "label": "done", "params": {}},
    )
    log = _wrap([status_event])
    output = generate(log)
    # gesture produces a checkpoint comment via assertions path
    assert "checkpoint" in output


# --- interleave_context ---


def test_interleave_context_returns_correct_types() -> None:
    lines, needs_pytest = interleave_context([])
    assert isinstance(lines, list)
    assert isinstance(needs_pytest, bool)
    assert needs_pytest is False


def test_interleave_context_shell_context() -> None:
    events = [_shell_context_event(1, ["helm", "list"], "helm")]
    lines, _ = interleave_context(events, INDENT)
    assert any("# context: helm list" in line for line in lines)


def test_interleave_context_tag_flushed_before_op() -> None:
    deploy_event = _event(
        2,
        "deploy",
        {
            "charm": "c",
            "app": None,
            "channel": None,
            "num_units": 1,
            "config": {},
            "resources": {},
        },
        {"app_name": "c"},
    )
    events = [_tag_event(1, "my step"), deploy_event]
    lines, _ = interleave_context(events, INDENT)
    combined = "\n".join(lines)
    step_pos = combined.index("# step: my step")
    deploy_pos = combined.index("juju.deploy")
    assert step_pos < deploy_pos


# --- render_shell (PATH-shim juju intercepts) ---


def _shim_shell_event(
    seq: int, argv: list[str], *, exit_code: int | None = None
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell",
        "ts": "2026-06-28T10:00:00.000Z",
        "args": {
            "argv": argv,
            "basename": "juju",
            "source": "shim",
            "session_id": "sess",
        },
        "result": {"captured": False, "exit_code": exit_code},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def test_render_shell_shim_basic() -> None:
    event = _shim_shell_event(1, ["--version"])
    result = render_shell(event, INDENT)
    assert result == f"{PAD}# shell: juju --version"


def test_render_shell_shim_with_exit() -> None:
    event = _shim_shell_event(1, ["status"], exit_code=2)
    lines = render_shell(event, INDENT).splitlines()
    assert lines == [f"{PAD}# shell: juju status", f"{PAD}# exit 2"]


def test_render_shell_shim_no_argv() -> None:
    event = _shim_shell_event(1, [])
    result = render_shell(event, INDENT)
    assert result == f"{PAD}# shell: juju"


def test_generate_shim_shell_rendered_as_shell_comment() -> None:
    """C2 — shim `op: shell` events render as `# shell: <cmd>`, not raw JSON TODO."""
    events = [_shim_shell_event(1, ["status", "--format=json"])]
    src = generate(_wrap(events))
    assert "# shell: juju status --format=json" in src
    assert "TODO" not in src


def test_generate_bucket2_libjuju_shell_still_falls_through() -> None:
    """Regression: op=shell WITHOUT source=shim must still hit fallback TODO."""
    events = [
        {
            "seq": 1,
            "op": "shell",
            "ts": "2026-06-28T10:00:00.000Z",
            "args": {"note": "libjuju bucket-2 stub"},
            "result": {},
            "model_snapshot_before": None,
            "model_snapshot_after": None,
            "assertions": [],
            "gesture": None,
        }
    ]
    src = generate(_wrap(events))
    assert "# TODO: manual step" in src


def test_generate_session_end_dropped() -> None:
    """C1 — the `session_end` sentinel never appears in generated output."""
    events = [
        {
            "seq": 1,
            "op": "session_end",
            "ts": "2026-06-28T10:00:00.000Z",
            "args": {},
            "result": {},
            "model_snapshot_before": None,
            "model_snapshot_after": None,
            "assertions": [],
            "gesture": None,
        }
    ]
    src = generate(_wrap(events))
    assert "session_end" not in src
    assert "TODO" not in src
