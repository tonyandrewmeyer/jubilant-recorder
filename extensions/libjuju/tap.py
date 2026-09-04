"""Monkeypatch tap for libjuju's Connection.rpc + AllWatcher delta stream.

``LibjujuTap`` is a synchronous context manager that:

1. Monkeypatches ``juju.client.connection.Connection.rpc`` to capture every
   outgoing facade RPC with its request-id, timestamp, facade, method, and
   params.
2. Detects AllWatcher.Next responses inside the same monkeypatch and extracts
   the delta stream (entity_kind, change_kind, payload, timestamp) from them.

The tap operates entirely at the ``Connection.rpc`` level — the single choke-
point through which all libjuju → Juju I/O passes — so it catches calls from
helper modules, factory fixtures, and any layer of the call stack, not just
direct ``model.deploy()`` calls.

----

**Request-ID finding (how async correlation is resolved):**

``Connection.rpc()`` assigns a monotonically-increasing integer request-id to
every outgoing JSON-RPC message. It stamps this id on the ``msg`` dict in-place
as ``msg["request-id"]`` before the websocket send, then uses it to correlate
the eventual response from the controller (via ``Connection._recv``).

Because ``msg`` is a plain dict passed by reference, our wrapper can read
``msg["request-id"]`` *after* the original ``rpc()`` returns and see the exact
id that was used for that call.

AllWatcher delta bursts are a separate push mechanism: the controller sends them
as responses to ``AllWatcher.Next`` RPC calls; each delta carries no reference
to the request-id of the user operation that triggered the state change.

**Conclusion:** request-ids ARE available on outgoing RPCs (and are recorded by
the tap).  They are NOT available on individual deltas.  The ``correlate.py``
module must therefore use a time-window heuristic to pair each user-facing RPC
with the delta burst that followed it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import types


def _format_ts(dt: datetime) -> str:
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def _normalise(obj: Any) -> Any:
    """Recursively convert libjuju-typed objects to JSON-serialisable Python.

    libjuju leaves typed dataclasses (for example ``juju.client._definitions.Base``)
    in outgoing ``msg["params"]`` and in AllWatcher delta payloads; the WebSocket
    encoder only sees the wire form. Since the tap captures the pre-send Python
    view of both, everything downstream (SessionLog JSON serialisation, correlator,
    tests) requires plain ``dict``/``list``/scalar shapes. This is the single
    chokepoint that guarantees that.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _normalise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_normalise(v) for v in obj]
    to_json = getattr(obj, "to_json", None)
    if callable(to_json):
        try:
            return _normalise(to_json())
        except Exception:
            pass
    serialize = getattr(obj, "serialize", None)
    if callable(serialize):
        try:
            return _normalise(serialize())
        except Exception:
            pass
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict) and d:
        return {str(k): _normalise(v) for k, v in d.items() if not str(k).startswith("_")}
    return repr(obj)


class LibjujuTap:
    """Context manager that intercepts all libjuju ``Connection.rpc`` calls.

    Inside the ``with`` block every call to
    ``juju.client.connection.Connection.rpc()`` is wrapped so the tap can:

    - Record user-facing facade RPCs to ``self.rpcs``.
    - Extract AllWatcher delta bursts from ``AllWatcher.Next`` responses and
      record them to ``self.deltas``.

    On exit the original ``Connection.rpc`` is unconditionally restored, even
    if the body of the ``with`` block raises.

    Usage::

        with LibjujuTap() as tap:
            await model.deploy("my-charm")
            await model.wait_for_idle()

        events = correlate(tap.rpcs, tap.deltas)

    Parameters
    ----------
    _connection_class:
        Override the ``Connection`` class to patch. Used in tests to avoid
        importing ``juju.client.connection`` (which has heavy optional
        dependencies).  Production callers leave this as ``None``.
    """

    def __init__(self, *, _connection_class: type | None = None) -> None:
        self._rpcs: list[dict[str, Any]] = []
        self._deltas: list[dict[str, Any]] = []
        self._original_rpc: Any = None
        self._connection_class = _connection_class

    # ------------------------------------------------------------------
    # Public read-only views
    # ------------------------------------------------------------------

    @property
    def rpcs(self) -> list[dict[str, Any]]:
        """Captured RPC calls in arrival order.

        Each entry is a dict with keys:
        ``request_id``, ``ts_start_iso``, ``ts_end_iso``,
        ``facade``, ``version``, ``method``, ``params``.
        """
        return list(self._rpcs)

    @property
    def deltas(self) -> list[dict[str, Any]]:
        """Captured AllWatcher deltas in arrival order.

        Each entry is a dict with keys:
        ``ts_iso``, ``entity_kind``, ``change_kind``, ``payload``.
        """
        return list(self._deltas)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def _get_connection_class(self) -> type:
        if self._connection_class is not None:
            return self._connection_class
        from juju.client.connection import Connection  # type: ignore[import]

        return Connection

    def __enter__(self) -> LibjujuTap:
        Connection = self._get_connection_class()  # noqa: N806  # Holds a class.

        tap = self
        original_rpc = Connection.rpc
        self._original_rpc = original_rpc

        async def _patched_rpc(
            conn_self: Any,
            msg: dict[str, Any],
            encoder: Any = None,
        ) -> dict[str, Any]:
            ts_start = datetime.now(UTC)
            result = await original_rpc(conn_self, msg, encoder)
            ts_end = datetime.now(UTC)

            # msg["request-id"] is set by the original rpc() before sending.
            request_id: int | None = msg.get("request-id")
            facade: str = msg.get("type", "")
            method: str = msg.get("request", "")
            params: dict[str, Any] = msg.get("params") or {}

            if facade == "AllWatcher":
                if method == "Next":
                    # Extract delta burst from the AllWatcher.Next response.
                    # Raw result shape: {"request-id": N, "response": {"deltas": [[ek, ck,
                    # payload], ...]}}
                    response_body = (result or {}).get("response") or {}
                    raw_deltas = response_body.get("deltas") or []
                    for raw_delta in raw_deltas:
                        if isinstance(raw_delta, (list, tuple)) and len(raw_delta) == 3:
                            entity_kind, change_kind, payload = raw_delta
                            tap._deltas.append(
                                {
                                    "ts_iso": _format_ts(ts_end),
                                    "entity_kind": str(entity_kind),
                                    "change_kind": str(change_kind),
                                    "payload": _normalise(payload)
                                    if isinstance(payload, dict)
                                    else {},
                                }
                            )
                # All AllWatcher.* calls (Next, Stop, etc.) are internal — never add to _rpcs.
            else:
                tap._rpcs.append(
                    {
                        "request_id": request_id,
                        "ts_start_iso": _format_ts(ts_start),
                        "ts_end_iso": _format_ts(ts_end),
                        "facade": facade,
                        "version": msg.get("version"),
                        "method": method,
                        "params": _normalise(params),
                    }
                )

            return result

        # Assigning the plain async function to Connection.rpc lets Python's
        # descriptor machinery supply self when called as an instance method.
        Connection.rpc = _patched_rpc  # type: ignore[method-assign]
        self._patched_on = Connection
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        self._patched_on.rpc = self._original_rpc  # type: ignore[method-assign]
        return False  # do not suppress exceptions
