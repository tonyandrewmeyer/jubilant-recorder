"""``RecordingLibjuju`` — the libjuju → SessionLog driver.

This is the libjuju-side counterpart to ``RecordingJuju`` (the wrapper that
subclasses ``jubilant.Juju._cli()``). It wires the Step 1 PoC together:

* enter the context: install ``LibjujuTap`` and open a ``SessionLog``;
* user code runs its libjuju test against a live model (or a mocked
  connection in tests);
* exit the context: tear down the tap, run ``correlate()`` over the
  captured RPCs + AllWatcher deltas, convert each correlator event into
  an ``EventEnvelope`` and append it to the session log, then close the
  log.

The output session log is byte-compatible with the canonical SCHEMA the
existing tagger and codegen already consume — the libjuju path is an
alternate *producer* of the same log shape, not a parallel pipeline.

Usage
-----

::

    from pathlib import Path
    from extensions.libjuju.recording import RecordingLibjuju

    with RecordingLibjuju.start(
        log_path=Path("session.json"),
        model="my-model",
    ):
        # run the libjuju test body here
        await model.deploy("my-charm")
        await model.wait_for_idle()

The recorded log can then be fed through ``jubilant_recorder.codegen.generate``
to emit a jubilant test, the same as a ``RecordingJuju``-produced log.

Bucket handling
---------------

``correlate()`` already classifies every captured user-facing RPC into one
of three buckets:

* Bucket 1 (~89% of the sampled corpus): a clean jubilant op (``deploy``,
  ``integrate``, ``run``, ...). The event carries SCHEMA-shaped args and
  result; codegen renders it via the existing op emitters.
* Bucket 2: lossy ops (for example ``Secrets.RevokeSecret``). Emitted as
  ``op: "shell"`` so codegen's fallback path renders a manual-step stub
  with the original facade/method recorded for the human reviewer.
* Bucket 3: facade calls with no jubilant equivalent. Emitted as
  ``op: "_todo"`` with the raw facade/method/params; codegen's fallback
  path emits a ``# TODO: manual step`` comment block.

Bucket 2 and Bucket 3 events flow through unchanged: they are not dropped,
they are surfaced — the same way the canonical recorder surfaces ops it
cannot replay automatically.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from extensions.libjuju.correlate import correlate as _default_correlate
from extensions.libjuju.tap import LibjujuTap
from jubilant_recorder.events import EventEnvelope
from jubilant_recorder.session_log import SessionLog

if TYPE_CHECKING:
    import types
    from pathlib import Path

# Keys that ``correlate()`` may attach to an event for debugging / provenance
# but which are not part of the canonical EventEnvelope. They are stripped
# during conversion so the on-disk log matches the SCHEMA the tagger and
# codegen consume.
_PROVENANCE_KEYS: frozenset[str] = frozenset({"_libjuju_source", "note"})


Correlator = Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]]


class RecordingLibjuju:
    """Context manager that records a libjuju test session.

    Parameters
    ----------
    output_log_path:
        Path to write the SessionLog JSON file. The file is overwritten on
        each session.
    model:
        Juju model name to record in the SessionLog header. Used for the
        generated test's fixture context; does not affect correlation.
    tap:
        Optional ``LibjujuTap`` instance. Defaults to a fresh
        ``LibjujuTap()``. Inject in tests to wire a ``FakeConnection``.
    correlator:
        Optional callable matching ``correlate(rpcs, deltas) ->
        list[event_dict]``. Defaults to ``extensions.libjuju.correlate.
        correlate``. Inject in tests to assert exactly which RPCs and
        deltas flowed through.
    """

    def __init__(
        self,
        *,
        output_log_path: Path,
        model: str = "",
        tap: LibjujuTap | None = None,
        correlator: Correlator | None = None,
        idle_threshold_seconds: float | None = None,
    ) -> None:
        self._output_log_path = output_log_path
        self._model = model
        self._tap: LibjujuTap = tap if tap is not None else LibjujuTap()
        if correlator is not None:
            self._correlator: Correlator = correlator
        elif idle_threshold_seconds is not None:
            self._correlator = functools.partial(
                _default_correlate, idle_threshold_seconds=idle_threshold_seconds
            )
        else:
            self._correlator = _default_correlate
        self._session_log: SessionLog | None = None

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------

    @property
    def tap(self) -> LibjujuTap:
        return self._tap

    @property
    def session_log(self) -> SessionLog:
        if self._session_log is None:
            raise RuntimeError("session_log only available inside the context manager")
        return self._session_log

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> RecordingLibjuju:
        self._session_log = SessionLog(self._output_log_path, model=self._model)
        self._tap.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        # Always tear down the tap first so the original Connection.rpc is
        # restored even if correlation or log writing raises below.
        try:
            self._tap.__exit__(exc_type, exc_val, exc_tb)
        finally:
            log = self._session_log
            if log is None:
                raise RuntimeError("context manager not entered")
            try:
                self._flush_to_log(log, exc_val)
            finally:
                log.close()
        return False  # never suppress exceptions from the recorded body

    def _flush_to_log(self, log: SessionLog, exc: BaseException | None) -> None:
        """Correlate captured RPCs+deltas and append the resulting events.

        If the recorded body raised, a ``session.error`` event is appended
        AFTER the correlated events so the log preserves both what ran and
        why it stopped.
        """
        rpcs = self._tap.rpcs
        deltas = self._tap.deltas
        events = self._correlator(rpcs, deltas)
        for raw_event in events:
            envelope = _event_to_envelope(raw_event, log.next_seq())
            log.append_event(envelope)
        if exc is not None and isinstance(exc, Exception):
            log.record_session_error(exc)

    # ------------------------------------------------------------------
    # Convenience entry point that mirrors ``RecordingJuju.start``.
    # ------------------------------------------------------------------

    @classmethod
    @contextlib.contextmanager
    def start(
        cls,
        log_path: Path,
        *,
        model: str = "",
        tap: LibjujuTap | None = None,
        correlator: Correlator | None = None,
        idle_threshold_seconds: float | None = None,
    ) -> Generator[RecordingLibjuju, None, None]:
        recorder = cls(
            output_log_path=log_path,
            model=model,
            tap=tap,
            correlator=correlator,
            idle_threshold_seconds=idle_threshold_seconds,
        )
        with recorder as ctx:
            yield ctx


def _event_to_envelope(raw_event: dict[str, Any], seq: int) -> EventEnvelope:
    """Convert a ``correlate()`` event dict into an ``EventEnvelope``.

    ``correlate()`` assigns its own ``seq`` starting at 1 for each call;
    we override it with the SessionLog's seq counter so the on-disk log's
    seq numbers are gap-free under the canonical contract.

    Provenance-only keys (for example ``_libjuju_source``, ``note``) are
    not part of the EventEnvelope and are dropped here.

    ``duration_ms`` is read directly from the event dict.  ``correlate()``
    computes it from ``ts_start_iso``/``ts_end_iso`` on each RPC and from
    the quiet-window span for synthesised ``wait_for_idle`` events.
    """
    args = dict(raw_event.get("args") or {})
    for k in list(args):
        if k in _PROVENANCE_KEYS:
            args.pop(k, None)
    return EventEnvelope(
        seq=seq,
        op=raw_event.get("op", ""),
        ts=raw_event.get("ts", ""),
        args=args,
        result=dict(raw_event.get("result") or {}),
        model_snapshot_before=raw_event.get("model_snapshot_before"),
        model_snapshot_after=raw_event.get("model_snapshot_after"),
        assertions=list(raw_event.get("assertions") or []),
        gesture=raw_event.get("gesture"),
        duration_ms=float(raw_event.get("duration_ms") or 0.0),
    )
