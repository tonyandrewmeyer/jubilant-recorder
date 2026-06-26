"""
Tap tests — fixture-driven, no live Juju controller required.

Strategy: create a ``FakeConnection`` class with a scripted async ``rpc``
method, pass it to ``LibjujuTap(_connection_class=FakeConnection)``, fire
synthetic RPC calls via the patched ``FakeConnection.rpc``, and assert the
tap captured the right records.

Because ``Connection.rpc`` is async, tests use ``asyncio.run()`` to drive
the async calls from synchronous pytest functions.

No import of ``juju.client.connection`` happens here — that module has
heavy optional dependencies (websockets, macaroonbakery) not available in
the CI/test sandbox.  The ``_connection_class`` parameter on ``LibjujuTap``
exists precisely for this pattern.
"""

from __future__ import annotations

import asyncio

from extensions.libjuju.tap import LibjujuTap

# ---------------------------------------------------------------------------
# Fake Connection class + helper factories
# ---------------------------------------------------------------------------


class FakeConnection:
    """Minimal stand-in for juju.client.connection.Connection.

    Tests replace ``FakeConnection.rpc`` per test via the ``_make_stub`` helper.
    """

    rpc = None  # replaced per-test by _make_stub


def _make_stub(responses: list[dict]) -> object:
    """Return an async callable that returns ``responses`` in order.

    Also stamps ``msg["request-id"]`` as the original ``Connection.rpc`` does.
    """
    counter = [0]

    async def _stub(conn_self: FakeConnection, msg: dict, encoder: object = None) -> dict:
        counter[0] += 1
        msg["request-id"] = counter[0]
        if not responses:
            return {"request-id": counter[0], "response": {}}
        idx = min(counter[0] - 1, len(responses) - 1)
        return responses[idx]

    return _stub


def _make_tap(stub) -> LibjujuTap:
    """Return a ``LibjujuTap`` wired to ``FakeConnection`` with ``stub`` as rpc."""
    FakeConnection.rpc = stub
    return LibjujuTap(_connection_class=FakeConnection)


def _run_rpc(msg: dict) -> dict:
    """Synchronously invoke the (patched) ``FakeConnection.rpc`` via asyncio.run."""
    conn = FakeConnection()
    return asyncio.run(FakeConnection.rpc(conn, msg))


# ---------------------------------------------------------------------------
# Test: basic RPC capture
# ---------------------------------------------------------------------------


class TestTapCapturesRPCs:
    def test_deploy_rpc_is_captured(self):
        stub = _make_stub(
            [{"request-id": 1, "response": {"results": [{"tag": "application-my-charm"}]}}]
        )
        with _make_tap(stub) as tap:
            _run_rpc(
                {
                    "type": "Application",
                    "request": "Deploy",
                    "version": 20,
                    "params": {
                        "applications": [
                            {"charm-url": "ch:my-charm", "application-name": "my-charm"}
                        ]
                    },
                }
            )

        assert len(tap.rpcs) == 1
        rpc = tap.rpcs[0]
        assert rpc["facade"] == "Application"
        assert rpc["method"] == "Deploy"
        assert rpc["request_id"] == 1
        assert rpc["version"] == 20
        assert "ts_start_iso" in rpc
        assert "ts_end_iso" in rpc

    def test_add_relation_rpc_is_captured(self):
        stub = _make_stub([{"request-id": 1, "response": {}}])
        with _make_tap(stub) as tap:
            _run_rpc(
                {
                    "type": "Application",
                    "request": "AddRelation",
                    "version": 20,
                    "params": {"endpoints": ["my-charm:db", "postgresql:database"]},
                }
            )

        assert len(tap.rpcs) == 1
        assert tap.rpcs[0]["facade"] == "Application"
        assert tap.rpcs[0]["method"] == "AddRelation"
        assert tap.rpcs[0]["params"]["endpoints"] == ["my-charm:db", "postgresql:database"]

    def test_multiple_rpcs_captured_in_order(self):
        stub = _make_stub(
            [
                {"request-id": 1, "response": {}},
                {"request-id": 2, "response": {}},
                {"request-id": 3, "response": {}},
            ]
        )
        with _make_tap(stub) as tap:
            _run_rpc({"type": "Application", "request": "Deploy", "version": 20, "params": {}})
            _run_rpc(
                {"type": "Application", "request": "AddRelation", "version": 20, "params": {}}
            )
            _run_rpc({"type": "Client", "request": "Status", "version": 6, "params": {}})

        assert len(tap.rpcs) == 3
        assert [r["method"] for r in tap.rpcs] == ["Deploy", "AddRelation", "Status"]
        assert [r["request_id"] for r in tap.rpcs] == [1, 2, 3]

    def test_params_are_deep_copied(self):
        """Params captured by the tap must not be affected by later mutation of msg."""
        stub = _make_stub([{"request-id": 1, "response": {}}])
        original_params = {"applications": [{"application-name": "my-charm"}]}
        with _make_tap(stub) as tap:
            msg = {
                "type": "Application",
                "request": "Deploy",
                "version": 20,
                "params": original_params,
            }
            _run_rpc(msg)
            # Mutate params after the RPC — the captured copy must be unchanged.
            original_params["applications"][0]["application-name"] = "mutated"

        assert tap.rpcs[0]["params"]["applications"][0]["application-name"] == "my-charm"


# ---------------------------------------------------------------------------
# Test: AllWatcher filtering
# ---------------------------------------------------------------------------


class TestTapFiltersInternalRPCs:
    def test_allwatcher_next_not_in_rpcs(self):
        deltas_response = {
            "request-id": 1,
            "response": {
                "deltas": [
                    ["application", "change", {"name": "my-charm"}],
                ]
            },
        }
        stub = _make_stub([deltas_response])
        with _make_tap(stub) as tap:
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        assert tap.rpcs == []  # AllWatcher.Next must NOT appear in rpcs

    def test_allwatcher_next_populates_deltas(self):
        deltas_response = {
            "request-id": 1,
            "response": {
                "deltas": [
                    [
                        "application",
                        "change",
                        {"name": "my-charm", "status": {"current": "waiting"}},
                    ],
                    [
                        "unit",
                        "change",
                        {
                            "name": "my-charm/0",
                            "application": "my-charm",
                            "workload-status": {"current": "maintenance", "message": "installing"},
                            "agent-status": {"current": "executing", "message": ""},
                        },
                    ],
                ]
            },
        }
        stub = _make_stub([deltas_response])
        with _make_tap(stub) as tap:
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        assert len(tap.deltas) == 2
        assert tap.deltas[0]["entity_kind"] == "application"
        assert tap.deltas[0]["change_kind"] == "change"
        assert tap.deltas[0]["payload"]["name"] == "my-charm"
        assert tap.deltas[1]["entity_kind"] == "unit"
        assert tap.deltas[1]["payload"]["name"] == "my-charm/0"

    def test_allwatcher_stop_not_captured(self):
        stub = _make_stub([{"request-id": 1, "response": {}}])
        with _make_tap(stub) as tap:
            _run_rpc({"type": "AllWatcher", "request": "Stop", "version": 3, "params": {}})

        assert tap.rpcs == []
        assert tap.deltas == []

    def test_mixed_allwatcher_and_user_rpcs(self):
        """AllWatcher.Next entries must be filtered from rpcs but deltas extracted."""
        stub = _make_stub(
            [
                {"request-id": 1, "response": {}},  # Application.Deploy
                {
                    "request-id": 2,
                    "response": {
                        "deltas": [
                            [
                                "unit",
                                "change",
                                {
                                    "name": "x/0",
                                    "application": "x",
                                    "workload-status": {"current": "maintenance", "message": ""},
                                    "agent-status": {"current": "executing", "message": ""},
                                },
                            ]
                        ]
                    },
                },  # AllWatcher.Next
                {"request-id": 3, "response": {}},  # Client.Status
            ]
        )
        with _make_tap(stub) as tap:
            _run_rpc({"type": "Application", "request": "Deploy", "version": 20, "params": {}})
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})
            _run_rpc({"type": "Client", "request": "Status", "version": 6, "params": {}})

        assert len(tap.rpcs) == 2
        assert [r["method"] for r in tap.rpcs] == ["Deploy", "Status"]
        assert len(tap.deltas) == 1
        assert tap.deltas[0]["entity_kind"] == "unit"


# ---------------------------------------------------------------------------
# Test: context-manager safety
# ---------------------------------------------------------------------------


class TestTapContextManager:
    def test_patch_is_reverted_on_exit(self):
        stub = _make_stub([{"request-id": 1, "response": {}}])
        FakeConnection.rpc = stub

        with LibjujuTap(_connection_class=FakeConnection):
            assert FakeConnection.rpc is not stub  # tap replaced it

        assert FakeConnection.rpc is stub  # restored after context exit

    def test_patch_reverted_even_when_body_raises(self):
        stub = _make_stub([])
        FakeConnection.rpc = stub

        try:
            with LibjujuTap(_connection_class=FakeConnection):
                raise RuntimeError("deliberate failure")
        except RuntimeError:
            pass

        assert FakeConnection.rpc is stub  # restored even after the exception

    def test_rpcs_property_returns_snapshot(self):
        stub = _make_stub([{"request-id": 1, "response": {}}])
        with _make_tap(stub) as tap:
            _run_rpc({"type": "Application", "request": "Deploy", "version": 20, "params": {}})
            snapshot1 = tap.rpcs

        snapshot2 = tap.rpcs
        assert snapshot1 == snapshot2
        assert snapshot1 is not snapshot2  # different list objects (defensive copy)

    def test_empty_tap_produces_empty_lists(self):
        stub = _make_stub([])
        with _make_tap(stub) as tap:
            pass

        assert tap.rpcs == []
        assert tap.deltas == []


# ---------------------------------------------------------------------------
# Test: delta timestamps are recorded
# ---------------------------------------------------------------------------


class TestDeltaTimestamps:
    def test_delta_has_ts_iso(self):
        stub = _make_stub(
            [
                {
                    "request-id": 1,
                    "response": {
                        "deltas": [
                            [
                                "unit",
                                "change",
                                {
                                    "name": "x/0",
                                    "application": "x",
                                    "workload-status": {"current": "active", "message": ""},
                                    "agent-status": {"current": "idle", "message": ""},
                                },
                            ]
                        ]
                    },
                }
            ]
        )
        with _make_tap(stub) as tap:
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        assert len(tap.deltas) == 1
        ts = tap.deltas[0]["ts_iso"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_rpc_has_start_and_end_ts(self):
        stub = _make_stub([{"request-id": 1, "response": {}}])
        with _make_tap(stub) as tap:
            _run_rpc({"type": "Client", "request": "Status", "version": 6, "params": {}})

        rpc = tap.rpcs[0]
        assert rpc["ts_start_iso"] <= rpc["ts_end_iso"]

    def test_delta_ts_records_arrival_time(self):
        """Delta timestamps reflect when the AllWatcher.Next response arrived."""
        stub = _make_stub(
            [
                {
                    "request-id": 1,
                    "response": {"deltas": [["application", "change", {"name": "x"}]]},
                },
                {
                    "request-id": 2,
                    "response": {"deltas": [["application", "change", {"name": "y"}]]},
                },
            ]
        )
        with _make_tap(stub) as tap:
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})
            _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})

        assert len(tap.deltas) == 2
        # Both deltas have valid ISO timestamps
        for d in tap.deltas:
            assert d["ts_iso"].endswith("Z")
