"""The recorded session event types."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class ModelSnapshot:
    """A point-in-time view of the model, captured alongside an event."""

    schema_version: int
    captured_at: str
    apps: dict[str, Any]
    relations: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "apps": self.apps,
            "relations": self.relations,
        }


@dataclasses.dataclass
class EventEnvelope:
    """One recorded event and the metadata surrounding it."""

    seq: int
    op: str
    ts: str
    args: dict[str, Any]
    result: dict[str, Any]
    model_snapshot_before: dict[str, Any] | None
    model_snapshot_after: dict[str, Any] | None
    assertions: list[Any]
    gesture: dict[str, Any] | None
    duration_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "assertions": self.assertions,
            "args": self.args,
            "duration_ms": self.duration_ms,
            "gesture": self.gesture,
            "model_snapshot_after": self.model_snapshot_after,
            "model_snapshot_before": self.model_snapshot_before,
            "op": self.op,
            "result": self.result,
            "seq": self.seq,
            "ts": self.ts,
        }
