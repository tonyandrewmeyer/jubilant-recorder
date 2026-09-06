"""Dispatch recorded events to their per-operation emitters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Mapping

from jubilant_recorder.codegen import (
    assertions,
    cli_translate,
    fallback,
    preamble,
    unrepresentable,
)
from jubilant_recorder.codegen import context as ctx
from jubilant_recorder.codegen.operations import EMITTERS

SessionLog: TypeAlias = dict[str, Any]

_DEFAULT_TEST_NAME = "test_recorded_session"
# `session_end` is an in-band sentinel appended by `jtr stop`; it marks the
# end of the log, not a step for the user to translate.
_SKIP_OPS = frozenset({"checkpoint", "session_end"})


def generate(
    log: SessionLog,
    *,
    test_name: str | None = None,
    overlay: Mapping[int, Mapping[str, str]] | None = None,
) -> str:
    """Generate the full jubilant test source for a recorded session.

    ``overlay`` is an optional, purely decorative annotation map keyed by
    event ``seq`` (see ``src/jubilant_recorder/extensions/libjuju/source_overlay.py``): an entry's
    ``"comment"`` is rendered as a ``#`` line immediately above that event's
    block, and its ``"var_name"`` overrides the auto-generated result
    variable name for ``run``/``config_get`` events. Omitting ``overlay``
    (the default) produces byte-identical output to before this parameter
    existed — nothing here is load-bearing for correctness.
    """
    indent = preamble.BODY_INDENT
    pad = " " * indent

    body_lines: list[str] = []
    needs_pytest = False
    already_skipped = False
    pending_tag: str | None = None
    for event in log.get("events", []) or []:
        op = event.get("op", "")
        annotation = (overlay or {}).get(event.get("seq"))
        if annotation and annotation.get("comment"):
            body_lines.append(f"{pad}# {annotation['comment']}")

        # Diagnostic-only markers synthesised by extension correlators (e.g.
        # libjuju's orphan-delta trailer) are never a step for the user to
        # translate — drop the event entirely. Scoped to the `_libjuju*`
        # prefix specifically, not a bare `_`: bucket-3's `_todo` op also
        # starts with an underscore but must still surface as a manual-step
        # TODO (see SCHEMA.md "Diagnostic-only ops").
        if op.startswith("_libjuju"):
            continue

        # New shell-hook ops: render as comments, never as jubilant calls.
        if op == "shell_context":
            body_lines.append(ctx.render_shell_context(event, indent))
            continue
        # Only the PATH-shim path uses `op: "shell"` with `args.source =
        # "shim"` — a plain `juju <argv>` invocation. Bucket-2/no-jubilant-
        # equivalent libjuju events (bucket-2, find_application_offers) also
        # use `op: "shell"` but without a shim source; those must still fall
        # through to fallback so they render as `# TODO: manual step`.
        if op == "shell" and (event.get("args") or {}).get("source") == "shim":
            # Bucket-1 argv is translated into the
            # matching typed op below instead of a raw `# shell:` comment.
            # Anything not a clean bucket-1 match keeps today's rendering.
            translated = cli_translate.classify(event)
            if translated is None:
                body_lines.append(ctx.render_shell(event, indent))
                continue
            op, translated_args = translated
            event = {**event, "op": op, "args": translated_args}
        if op == "note":
            body_lines.append(ctx.render_note(event, indent))
            continue
        if op == "tag":
            # Tag labels are buffered and emitted as "# step:" before the
            # next non-skipped jubilant op.
            pending_tag = event.get("args", {}).get("label")
            continue

        # Flush any pending tag before the next real (non-skip) op.
        if pending_tag is not None and op not in _SKIP_OPS:
            body_lines.append(f"{pad}# step: {pending_tag}")
            pending_tag = None

        # Operations codegen can't honestly represent (failed ops,
        # error-state models, mixed multi-unit statuses) get a skip/TODO
        # marker instead of an assertion — and never crash codegen.
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

        # Status with no assertions and no gesture: render as a comment.
        if op == "status" and not event.get("assertions") and not event.get("gesture"):
            comment = ctx.render_status_comment(event, indent)
            if comment is not None:
                body_lines.append(comment)
            continue

        run_var: str | None = None
        if op in _SKIP_OPS:
            pass
        elif op == "run":
            run_var = (annotation or {}).get("var_name") or f"result_{event.get('seq')}"
            body_lines.append(EMITTERS["run"](event, indent, var_name=run_var))
        elif op == "config_get":
            config_get_var = (annotation or {}).get("var_name") or f"config_{event.get('seq')}"
            body_lines.append(EMITTERS["config_get"](event, indent, var_name=config_get_var))
        elif op in EMITTERS:
            body_lines.append(EMITTERS[op](event, indent))
            if op == "config":
                comment = ctx.render_config_result(event, indent)
                if comment is not None:
                    body_lines.append(comment)
        else:
            body_lines.append(fallback.emit(event, indent))

        for tag in _collected_tags(event):
            rendered = assertions.emit(tag, indent, run_var=run_var)
            if rendered:
                body_lines.append(rendered)

    if not _has_statement(body_lines):
        body_lines.append(preamble.empty_body_filler())

    events_list = log.get("events", []) or []
    first_snapshot = events_list[0].get("model_snapshot_before") if events_list else None
    pre = preamble.Preamble(
        test_name=test_name or _DEFAULT_TEST_NAME,
        needs_pytest=needs_pytest,
        pre_existing_apps=preamble.pre_existing_apps(first_snapshot),
    )
    return "\n".join([*pre.lines(), *body_lines]) + "\n"


def _collected_tags(event: dict[str, Any]) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = list(event.get("assertions") or [])
    gesture_tag = _gesture_to_tag(event.get("gesture"))
    if gesture_tag is None:
        return tags
    existing_kinds = {t.get("kind") for t in tags if isinstance(t, dict)}
    if gesture_tag["kind"] in existing_kinds:
        return tags
    tags.append(gesture_tag)
    return tags


def _gesture_to_tag(gesture: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gesture:
        return None
    kind = gesture.get("kind")
    params = gesture.get("params") or {}
    label = gesture.get("label") or ""
    if kind == "checkpoint":
        return {
            "kind": "user_checkpoint",
            "label": label,
            "strict": False,
            "source": "gesture",
        }
    if kind == "assert_status":
        return {
            "kind": "unit_status",
            "app": params.get("app"),
            "unit": params.get("unit"),
            "expected": params.get("status"),
            "strict": False,
            "source": "gesture",
        }
    if kind == "assert_action_result":
        return {
            "kind": "action_result",
            "unit": params.get("unit"),
            "action": params.get("action"),
            "expected_success": params.get("success", True),
            "expected_results": params.get("expected_results") or {},
            "strict": False,
            "source": "gesture",
        }
    if kind == "assert_config":
        return {
            "kind": "config_value",
            "app": params.get("app"),
            "key": params.get("key"),
            "expected": params.get("value"),
            "strict": False,
            "source": "gesture",
        }
    return None


def _has_statement(body_lines: list[str]) -> bool:
    for block in body_lines:
        for line in block.splitlines():
            stripped = line.lstrip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            return True
    return False
