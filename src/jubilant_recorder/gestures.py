"""Explicit gesture API for marking checkpoints and assertions in a session.

Gestures inject tagged events into the active RecordingJuju's session log.
They are not jubilant operations and never call the juju CLI — they only
annotate the log so the codegen can render explicit assertion lines.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jubilant_recorder.recording_juju import RecordingJuju

_active_session: contextvars.ContextVar[RecordingJuju | None] = contextvars.ContextVar(
    "recorder_active_session", default=None
)


def _require_session() -> RecordingJuju:
    session = _active_session.get()
    if session is None:
        raise RuntimeError(
            "no active recording session; gesture API requires recorder.RecordingJuju().start()"
        )
    return session


def checkpoint(name: str, *, comment: str | None = None) -> None:
    """Mark a logical step boundary in the recorded session."""
    session = _require_session()
    label = name if not comment else f"{name} — {comment}"
    session._inject_gesture_event(
        op="checkpoint",
        gesture={"kind": "checkpoint", "label": label, "params": {}},
        args={},
    )


def assert_status(
    app: str | None = None,
    status: str | None = None,
    message: str | None = None,
    *,
    unit: str | None = None,
) -> None:
    """Snapshot model status and inject an explicit status assertion."""
    session = _require_session()
    if app is None and status is None and message is None and unit is None:
        session._inject_gesture_event(
            op="checkpoint",
            gesture={
                "kind": "checkpoint",
                "label": "TODO: tighten this assertion",
                "params": {},
            },
            args={},
        )
        return
    if status is None:
        # Message-only or unit-only without an enum: best we can do is a TODO,
        # since the codegen has no workload_message assertion path.
        label = "TODO: tighten this assertion"
        if message is not None:
            label = f"TODO: assert workload_message == {message!r}"
        session._inject_gesture_event(
            op="checkpoint",
            gesture={"kind": "checkpoint", "label": label, "params": {}},
            args={},
        )
        return
    # The wait_for_idle op below renders as `juju.wait_for_idle(...)`; the
    # gesture's unit_status tag renders the explicit assert on the next line.
    wait_args: dict[str, Any] = {"apps": [app] if app else None, "timeout": None}
    session._inject_gesture_event(
        op="wait_for_idle",
        gesture={
            "kind": "assert_status",
            "label": None,
            "params": {"app": app, "unit": unit, "status": status},
        },
        args=wait_args,
        result={"settled_at": None},
    )


def assert_action_result(
    action_id: str,
    *,
    key: str | None = None,
    value: Any = None,
) -> None:
    """Attach an action_result gesture to the most recent run event."""
    session = _require_session()
    events = session._session_log._events
    target = None
    for ev in reversed(events):
        if ev.get("op") == "run":
            target = ev
            break
    if target is None:
        session._inject_gesture_event(
            op="checkpoint",
            gesture={
                "kind": "checkpoint",
                "label": f"TODO: no run event found for action_id={action_id!r}",
                "params": {},
            },
            args={},
        )
        return
    expected_results: dict[str, Any] = {}
    if key is not None:
        expected_results[key] = value
    target["gesture"] = {
        "kind": "assert_action_result",
        "label": None,
        "params": {
            "unit": target["args"].get("unit"),
            "action": target["args"].get("action"),
            "success": True,
            "expected_results": expected_results,
        },
    }


def assert_config(app: str, *, key: str, value: Any) -> None:
    """Read an application's config and assert one key's value.

    The deterministic tagger only proposes a config assertion when it sees a
    value *change* between two reads, which misses the common case: you set
    something once and want the test to check it stayed set. This says so
    explicitly.

    Renders as a `juju.config(...)` read followed by an assert on the key::

        assert_config("my-charm", key="log-level", value="debug")

    The session log's `config_value` tag shape and its codegen path already
    existed — `docs/schema.md` has documented this gesture since the schema
    was written — but nothing user-facing produced one.
    """
    session = _require_session()
    session._inject_gesture_event(
        op="config_get",
        gesture={
            "kind": "assert_config",
            "label": None,
            "params": {"app": app, "key": key, "value": value},
        },
        args={"app": app, "keys": [key]},
        result={"values": {key: value}},
    )
