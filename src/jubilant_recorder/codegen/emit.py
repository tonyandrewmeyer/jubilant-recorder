from __future__ import annotations

from typing import Any, TypeAlias

from jubilant_recorder.codegen import assertions, fallback, preamble, unrepresentable
from jubilant_recorder.codegen.operations import EMITTERS

SessionLog: TypeAlias = dict[str, Any]

_DEFAULT_TEST_NAME = "test_recorded_session"
_SKIP_OPS = frozenset({"checkpoint"})


def generate(log: SessionLog, *, test_name: str | None = None) -> str:
    indent = preamble.BODY_INDENT

    body_lines: list[str] = []
    needs_pytest = False
    already_skipped = False
    for event in log.get("events", []) or []:
        # Step 10: operations codegen can't honestly represent (failed ops,
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

        op = event.get("op", "")
        run_var: str | None = None
        if op in _SKIP_OPS:
            pass
        elif op == "run":
            run_var = f"result_{event.get('seq')}"
            body_lines.append(EMITTERS["run"](event, indent, var_name=run_var))
        elif op in EMITTERS:
            body_lines.append(EMITTERS[op](event, indent))
        else:
            body_lines.append(fallback.emit(event, indent))

        for tag in _collected_tags(event):
            rendered = assertions.emit(tag, indent, run_var=run_var)
            if rendered:
                body_lines.append(rendered)

    if not _has_statement(body_lines):
        body_lines.append(preamble.empty_body_filler())

    pre = preamble.Preamble(test_name=test_name or _DEFAULT_TEST_NAME, needs_pytest=needs_pytest)
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
