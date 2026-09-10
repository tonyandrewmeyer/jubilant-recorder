"""Shared state threaded through code generation."""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import assertions as assertions_mod
from jubilant_recorder.codegen import cli_translate, fallback, unrepresentable
from jubilant_recorder.codegen.operations import EMITTERS


def render_shell_context(event: dict[str, Any], indent: int = 8) -> str:
    """Produce `# context: <argv>` plus optional exit and stdout lines."""
    return _render_shell_like(event, indent, prefix="context")


def render_shell(event: dict[str, Any], indent: int = 8) -> str:
    """Produce `# shell: <basename> <argv>` for PATH-shim intercepts.

    Shim events are ``op: "shell"`` (`shim/juju_shim.py`) — a `juju` invocation
    captured by the PATH shim. Rendered as a context comment so the generated
    test carries an audit trail of what the user did without codegen having to
    translate raw juju CLI to jubilant (that's the RecordingJuju wrapper's
    job).
    """
    args = event.get("args") or {}
    basename = args.get("basename") or ""
    argv = args.get("argv") or []
    cmd_parts = [basename, *list(argv)] if basename else list(argv)
    pad = " " * indent
    lines = [f"{pad}# shell: {' '.join(str(p) for p in cmd_parts).strip()}"]
    result = event.get("result") or {}
    exit_code = result.get("exit_code")
    if exit_code is not None and exit_code != 0:
        lines.append(f"{pad}# exit {exit_code}")
    return "\n".join(lines)


def comment_out_failed(event: dict[str, Any], block: str, indent: int) -> str:
    """Comment out a translated shim call whose recorded run failed.

    A shell-capture session is a person exploring, so it routinely contains
    commands that did not work — a typo, a charm name that does not exist,
    a `juju status` run before the model was made. Emitting those as live
    jubilant calls would produce a test that fails for reasons the recorded
    session already knew about, and the reader would have to work out which
    of the failures were meaningful.

    So they are kept, commented out, with the exit code that was recorded.
    Nothing is lost, the test runs, and the one thing the reader needs to
    decide — "did I mean to do that?" — is the thing put in front of them.

    This is deliberately gentler than the `pytest.skip` that
    `codegen.unrepresentable` gives a failed *scripted* operation: there,
    the recording script itself raised, so the session stopped meaning what
    it says from that point on. Here the operator saw the error, shrugged,
    and typed the next thing.
    """
    exit_code = (event.get("result") or {}).get("exit_code")
    if not isinstance(exit_code, int) or exit_code == 0:
        return block
    argv = (event.get("_shim_argv") or []) or (event.get("args") or {}).get("argv") or []
    pad = " " * indent
    typed = " ".join(str(a) for a in argv)
    header = f"{pad}# `juju {typed}` exited {exit_code} when recorded — left commented out:"
    body = "\n".join(f"{pad}# {line.strip()}" for line in block.splitlines() if line.strip())
    return f"{header}\n{body}" if body else header


def _render_shell_like(event: dict[str, Any], indent: int, *, prefix: str) -> str:
    pad = " " * indent
    args = event.get("args") or {}
    argv = args.get("argv") or []
    cmd_str = " ".join(argv) if isinstance(argv, list) else str(argv)
    lines = [f"{pad}# {prefix}: {cmd_str}"]
    result = event.get("result") or {}
    exit_code = result.get("exit_code")
    if exit_code is not None and exit_code != 0:
        lines.append(f"{pad}# exit {exit_code}")
    stdout = result.get("stdout")
    if stdout is not None:
        stdout_lines = stdout.splitlines()
        shown = stdout_lines[:5]
        lines.extend(f"{pad}# | {line}" for line in shown)
        remaining = len(stdout_lines) - len(shown)
        if remaining > 0:
            lines.append(f"{pad}# | ... ({remaining} more)")
    return "\n".join(lines)


def render_note(event: dict[str, Any], indent: int = 8) -> str:
    """Produce `# note: <text>`."""
    pad = " " * indent
    text = (event.get("args") or {}).get("text", "")
    return f"{pad}# note: {text}"


def render_cap_reached(event: dict[str, Any], indent: int = 8) -> str:
    """Produce the marker for a session that hit the shell hook's event cap.

    Rendering it through the fallback emitter printed an empty JSON payload
    under a `# TODO: manual step` heading, which says neither what happened
    nor what to do about it.
    """
    del event
    pad = " " * indent
    return (
        f"{pad}# NOTE: the recording hit its event cap here — anything the operator did\n"
        f"{pad}# after this point was not recorded, and is not in this test."
    )


def render_status_comment(event: dict[str, Any], indent: int = 8) -> str | None:
    """Produce `# juju status: ...` summary from status op's model_snapshot_after.

    Returns None if all units are active with empty messages.
    Returns error comment if model_snapshot_after is None.
    """
    pad = " " * indent
    snapshot = event.get("model_snapshot_after")
    if snapshot is None:
        return f"{pad}# juju status: error (snapshot unavailable)"
    apps = snapshot.get("apps") or {}
    if not apps:
        return None
    unit_entries: list[tuple[str, str, str]] = []
    for app_obj in apps.values():
        for unit, unit_obj in (app_obj.get("units") or {}).items():
            status = unit_obj.get("workload_status", "")
            message = unit_obj.get("workload_message", "")
            unit_entries.append((unit, status, message))
    if all(s == "active" and m == "" for _, s, m in unit_entries):
        return None
    non_active = [(u, s, m) for u, s, m in unit_entries if s != "active"]
    active = [(u, s, m) for u, s, m in unit_entries if s == "active"]
    ordered = sorted(non_active) + sorted(active)
    parts = []
    for unit, status, message in ordered:
        if message:
            parts.append(f'{unit} {status} ("{message}")')
        else:
            parts.append(f"{unit} {status}")
    return f"{pad}# juju status: {', '.join(parts)}"


def render_config_result(event: dict[str, Any], indent: int = 8) -> str | None:
    """Produce `# result: ...` from config op's before/after delta."""
    pad = " " * indent
    before = event.get("model_snapshot_before") or {}
    after = event.get("model_snapshot_after") or {}
    if before == after:
        return None
    before_units: dict[str, tuple[str, str]] = {}
    for app_obj in (before.get("apps") or {}).values():
        for unit, unit_obj in (app_obj.get("units") or {}).items():
            before_units[unit] = (
                unit_obj.get("workload_status", ""),
                unit_obj.get("workload_message", ""),
            )
    parts = []
    for app_obj in (after.get("apps") or {}).values():
        for unit, unit_obj in (app_obj.get("units") or {}).items():
            new_status = unit_obj.get("workload_status", "")
            new_msg = unit_obj.get("workload_message", "")
            old_status, _ = before_units.get(unit, ("", ""))
            if new_status != old_status:
                if new_msg:
                    parts.append(f'{unit} {new_status} ("{new_msg}") — was {old_status}')
                else:
                    parts.append(f"{unit} {new_status} — was {old_status}")
    if not parts:
        return None
    return f"{pad}# result: {', '.join(parts)}"


def interleave_context(events: list[dict[str, Any]], indent: int = 8) -> tuple[list[str], bool]:
    """Iterate events in seq order; emit jubilant calls and context comments.

    Returns (body_lines, needs_pytest).
    """
    from jubilant_recorder.codegen.emit import _SKIP_OPS, _collected_tags

    model = cli_translate.session_model(events)

    body_lines: list[str] = []
    needs_pytest = False
    already_skipped = False
    pending_tag: str | None = None
    pad = " " * indent

    for event in events:
        op = event.get("op", "")

        # See emit.generate() for why this is scoped to `_libjuju*` rather
        # than a bare `_` (bucket-3's `_todo` must still render).
        if op.startswith("_libjuju"):
            continue

        if op == "shell_context":
            body_lines.append(render_shell_context(event, indent))
            continue
        # See emit.generate() for the full comment; mirrored here because
        # both dispatchers need the same per-event bucket-1 translation.
        if op == "shell" and (event.get("args") or {}).get("source") == "shim":
            translated = cli_translate.classify(event, session_model=model)
            if translated is None:
                body_lines.append(render_shell(event, indent))
                continue
            op, translated_args = translated
            event = {
                **event,
                "op": op,
                "args": translated_args,
                "_shim_argv": (event.get("args") or {}).get("argv") or [],
            }
        if op == "note":
            body_lines.append(render_note(event, indent))
            continue
        if op == "cap_reached":
            body_lines.append(render_cap_reached(event, indent))
            continue
        if op == "tag":
            pending_tag = event.get("args", {}).get("label")
            continue

        if pending_tag is not None and op not in _SKIP_OPS:
            body_lines.append(f"{pad}# step: {pending_tag}")
            pending_tag = None

        finding = unrepresentable.classify(event)
        if finding is not None:
            block, used_pytest = unrepresentable.emit(
                event, indent, finding, suppress_skip=already_skipped
            )
            body_lines.append(block)
            if used_pytest:
                needs_pytest = True
                already_skipped = True
            continue

        if op == "status" and not event.get("assertions") and not event.get("gesture"):
            comment = render_status_comment(event, indent)
            if comment is not None:
                body_lines.append(comment)
            continue

        run_var: str | None = None
        block_start = len(body_lines)
        if op in _SKIP_OPS:
            pass
        elif op == "run":
            run_var = f"result_{event.get('seq')}"
            body_lines.append(EMITTERS["run"](event, indent, var_name=run_var))
        elif op in EMITTERS:
            body_lines.append(EMITTERS[op](event, indent))
            if op == "config":
                comment = render_config_result(event, indent)
                if comment is not None:
                    body_lines.append(comment)
        else:
            body_lines.append(fallback.emit(event, indent))

        for tag in _collected_tags(event):
            rendered = assertions_mod.emit(tag, indent, run_var=run_var)
            if rendered:
                body_lines.append(rendered)

        # See emit.generate(); mirrored here for the same reason.
        if "_shim_argv" in event:
            for i in range(block_start, len(body_lines)):
                body_lines[i] = comment_out_failed(event, body_lines[i], indent)

    return body_lines, needs_pytest
