"""Codegen for jubilant operations the deterministic emitter can't represent.

PLAN.md §"Work breakdown" step 10 names three categories the recorder can
capture but codegen cannot honestly turn into a passing assertion:

* **failed operations** — `_cli()` raised, so the event carries a
  `result.error` string and a null `model_snapshot_after` (SCHEMA.md Open
  Q#3). A `wait_for_idle` that times out (the "relation never settles"
  *partial deploy* case) lands here too: its `result.error` holds the
  timeout message.
* **error-state models** — the operation's CLI call succeeded but the
  recorded `model_snapshot_after` shows a unit in the `error` workload
  state (e.g. a deploy with bad config whose charm then errors). There is
  no sensible *target* status to assert for an errored unit.
* **multi-unit applications with mixed statuses** — a `deploy`/`scale`
  whose units settled into more than one distinct workload status. A
  single status assertion would be wrong for some unit; codegen can't pick
  one.

Rather than crash (the step-10 regression bar) or silently emit a test
that asserts a falsehood, codegen marks the step:

* failed op / error state  → `pytest.skip(reason=...)` plus a `# TODO`
  comment. The generated test stops at the unrepresentable step instead of
  running an assertion against a broken model.
* mixed statuses           → a `# TODO: manual step` comment only. The op
  call itself is fine to replay; only its assertion is unrepresentable, so
  the test keeps running.

This module is additive: `classify()` returns None for every representable
event, so logs without these cases generate byte-identical output to the
prior snapshots.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from jubilant_recorder.codegen import fallback
from jubilant_recorder.codegen.operations import EMITTERS, run_action

_ERROR_WORKLOAD_STATUS = "error"
_MULTI_UNIT_OPS = frozenset({"deploy", "scale"})


@dataclasses.dataclass(frozen=True)
class Finding:
    """Why an event can't be represented, and how to mark it."""

    kind: str  # "failed" | "error_state" | "mixed"
    reason: str  # human-readable detail for the TODO comment

    @property
    def needs_skip(self) -> bool:
        return self.kind in ("failed", "error_state")


def classify(event: dict[str, Any]) -> Finding | None:
    """Return a Finding if `event` can't be represented, else None."""
    op = event.get("op", "") or "<unknown>"
    result = event.get("result") or {}
    error = result.get("error")
    if error:
        first_line = str(error).splitlines()[0] if str(error) else ""
        reason = f"failed {op}" + (f": {first_line}" if first_line else "")
        return Finding(kind="failed", reason=reason)

    after = event.get("model_snapshot_after")
    if not isinstance(after, dict):
        return None

    errored = sorted(
        unit
        for unit, status in _all_unit_statuses(after).items()
        if status == _ERROR_WORKLOAD_STATUS
    )
    if errored:
        return Finding(
            kind="error_state",
            reason=f"units in error state: {', '.join(errored)}",
        )

    if op in _MULTI_UNIT_OPS:
        app = result.get("app_name") or (event.get("args") or {}).get("app")
        app_statuses = _app_unit_statuses(after, app)
        if len(app_statuses) > 1 and len(set(app_statuses.values())) > 1:
            rendered = ", ".join(
                f"{unit}={status}" for unit, status in sorted(app_statuses.items())
            )
            return Finding(
                kind="mixed",
                reason=f"mixed unit statuses for {app}: {rendered}",
            )

    return None


def emit(
    event: dict[str, Any],
    indent: int,
    finding: Finding,
    *,
    suppress_skip: bool = False,
) -> tuple[str, bool]:
    """Render the marker block for an unrepresentable event.

    Returns `(block, needs_pytest)` — `needs_pytest` is True when the block
    contains a `pytest.skip(...)` call, so the caller can arrange the
    `import pytest` in the preamble.

    When `suppress_skip` is True the `pytest.skip(...)` line is replaced with
    a short comment. Use this for failures that follow the first skip — they
    are unreachable at runtime and would only add noise.
    """
    pad = " " * indent
    op = event.get("op", "") or "<unknown>"
    lines: list[str] = []

    if finding.kind == "failed":
        # The CLI call raised, so we must not replay it as a success.
        lines.append(f"{pad}# TODO: manual step — codegen can't represent {finding.reason}")
        lines.append(f"{pad}# attempted: {_describe_op(event)}")
        if suppress_skip:
            lines.append(f"{pad}# (unreachable — an earlier step already skipped this test)")
            return "\n".join(lines), False
        lines.append(f"{pad}pytest.skip(reason={_skip_reason(op, finding)!r})")
        return "\n".join(lines), True

    # error_state / mixed: the operation's CLI call succeeded, so replay it,
    # then mark the unrepresentable end-state in place of an assertion.
    lines.append(_op_call(event, indent))
    lines.append(f"{pad}# TODO: manual step — codegen can't represent {finding.reason}")
    if finding.needs_skip:
        if suppress_skip:
            lines.append(f"{pad}# (unreachable — an earlier step already skipped this test)")
            return "\n".join(lines), False
        lines.append(f"{pad}pytest.skip(reason={_skip_reason(op, finding)!r})")
        return "\n".join(lines), True
    return "\n".join(lines), False


def _skip_reason(op: str, finding: Finding) -> str:
    if finding.kind == "failed":
        return f"recorded session: {op} failed — review and replace this step"
    return "recorded session left the model in an error state — review before running this test"


def _op_call(event: dict[str, Any], indent: int) -> str:
    op = event.get("op", "")
    if op == "run":
        return run_action.emit(event, indent)
    emitter = EMITTERS.get(op)
    if emitter is not None:
        return emitter(event, indent)
    return fallback.emit(event, indent)


def _describe_op(event: dict[str, Any]) -> str:
    """A one-line, comment-safe description of the attempted op."""
    op = event.get("op", "") or "<unknown>"
    args = event.get("args") or {}
    rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(args.items()))
    line = f"{op}({rendered})"
    return line.replace("\n", " ")


def _all_unit_statuses(snapshot: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for app_obj in (snapshot.get("apps") or {}).values():
        for unit, unit_obj in (app_obj.get("units") or {}).items():
            statuses[unit] = unit_obj.get("workload_status", "")
    return statuses


def _app_unit_statuses(snapshot: dict[str, Any], app: str | None) -> dict[str, str]:
    if not app:
        return {}
    app_obj = (snapshot.get("apps") or {}).get(app) or {}
    return {
        unit: unit_obj.get("workload_status", "")
        for unit, unit_obj in (app_obj.get("units") or {}).items()
    }
