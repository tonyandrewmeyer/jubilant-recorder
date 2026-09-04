"""Read and write the recorded session log format."""

from __future__ import annotations

import contextlib
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jubilant

if TYPE_CHECKING:
    from collections.abc import Generator

    from jubilant_recorder.events import EventEnvelope


def _format_ts(dt: datetime) -> str:
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


class SessionLog:
    """A recorded session: its events, metadata and tags."""

    def __init__(self, log_path: Path | str, model: str = "") -> None:
        # The README's gesture-API example passes a plain string, and so will
        # anyone following it. Coerce here rather than at every call site:
        # close() writes through Path.write_text, so a str would only fail at
        # the very end of a session, after the work was already done.
        self._log_path = Path(log_path)
        self._model = model
        self._session_id = str(uuid.uuid4())
        self._recorded_at: str | None = None
        self._events: list[dict[str, Any]] = []
        self._seq = 0

        try:
            result = subprocess.run(
                ["juju", "version"],
                capture_output=True,
                encoding="utf-8",
                timeout=10,
            )
            self._juju_version = result.stdout.strip()
        except Exception:
            self._juju_version = "unknown"

        try:
            self._jubilant_version = jubilant.__version__
        except Exception:
            self._jubilant_version = "unknown"

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def append_event(self, event: EventEnvelope) -> None:
        self._events.append(event.as_dict())

    def record_session_error(self, exc: Exception) -> None:
        now = datetime.now(UTC)
        ts = _format_ts(now)
        seq = self.next_seq()
        self._events.append(
            {
                "assertions": [],
                "args": {},
                "duration_ms": 0.0,
                "gesture": None,
                "model_snapshot_after": None,
                "model_snapshot_before": None,
                "op": "session.error",
                "result": {"error": str(exc)},
                "seq": seq,
                "ts": ts,
            }
        )

    def close(self) -> None:
        now = datetime.now(UTC)
        self._recorded_at = _format_ts(now)
        document = {
            "events": self._events,
            "jubilant_version": self._jubilant_version,
            "juju_version": self._juju_version,
            "model": self._model,
            "recorded_at": self._recorded_at,
            "schema_version": 1,
            "session_id": self._session_id,
        }
        self._log_path.write_text(
            json.dumps(document, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    @contextlib.contextmanager
    def open(cls, log_path: Path, model: str = "") -> Generator[SessionLog, None, None]:
        instance = cls(log_path, model=model)
        try:
            yield instance
        finally:
            instance.close()
