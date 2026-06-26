"""
Smoke test: a ``RecordingLibjuju``-produced session log feeds the existing
``jubilant_recorder.codegen.generate`` pipeline unchanged.

The libjuju extension's value proposition is that it is an alternate
producer for the canonical SessionLog shape — so the existing codegen
must be able to ingest its output without modification. This test drives
a scripted libjuju session through ``RecordingLibjuju``, reads the
log back, hands it to ``codegen.generate``, asserts the emitted Python
parses (``ast.parse``), and that the rendered text contains the
operations the session performed.

A second test exercises a bucket-2 (``Application.SetCharm``) RPC too,
to prove the codegen fallback emits a ``# TODO`` comment rather than
crashing on the libjuju-extension's secondary buckets.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

from extensions.libjuju.recording import RecordingLibjuju
from extensions.libjuju.tap import LibjujuTap

from jubilant_recorder.codegen import generate

# ---------------------------------------------------------------------------
# Helpers — shared with the unit-test module's FakeConnection pattern.
# ---------------------------------------------------------------------------


class FakeConnection:
    rpc = None


def _make_stub(responses: list[dict[str, Any]]):
    counter = [0]

    async def _stub(conn_self: FakeConnection, msg: dict, encoder: object = None) -> dict:
        counter[0] += 1
        msg["request-id"] = counter[0]
        if not responses:
            return {"request-id": counter[0], "response": {}}
        idx = min(counter[0] - 1, len(responses) - 1)
        return responses[idx]

    return _stub


def _run_rpc(msg: dict[str, Any]) -> dict[str, Any]:
    conn = FakeConnection()
    return asyncio.run(FakeConnection.rpc(conn, msg))


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


def test_codegen_consumes_bucket1_libjuju_log(tmp_path: Path) -> None:
    """deploy + integrate + run → recorded log → codegen → parseable test."""

    FakeConnection.rpc = _make_stub(
        [
            # Application.Deploy
            {"request-id": 1, "response": {"results": [{"tag": "application-my-charm"}]}},
            # AllWatcher.Next — deltas attributed to the deploy
            {
                "request-id": 2,
                "response": {
                    "deltas": [
                        [
                            "unit",
                            "change",
                            {
                                "name": "my-charm/0",
                                "application": "my-charm",
                                "workload-status": {
                                    "current": "active",
                                    "message": "",
                                    "since": "",
                                },
                                "agent-status": {
                                    "current": "idle",
                                    "message": "",
                                    "since": "",
                                },
                            },
                        ]
                    ]
                },
            },
            # Application.AddRelation
            {"request-id": 3, "response": {}},
            # Action.EnqueueOperation
            {
                "request-id": 4,
                "response": {
                    "results": [
                        {
                            "operation": "operation-1",
                            "action": {"name": "do-thing", "receiver": "unit-my-charm-0"},
                        }
                    ]
                },
            },
        ]
    )

    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="smoke-model",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "Application",
                "request": "Deploy",
                "version": 20,
                "params": {
                    "applications": [
                        {
                            "charm-url": "ch:my-charm",
                            "application-name": "my-charm",
                            "num-units": 1,
                        }
                    ]
                },
            }
        )
        _run_rpc({"type": "AllWatcher", "request": "Next", "version": 3, "params": {}})
        _run_rpc(
            {
                "type": "Application",
                "request": "AddRelation",
                "version": 20,
                "params": {"endpoints": ["my-charm:db", "postgresql:database"]},
            }
        )
        _run_rpc(
            {
                "type": "Action",
                "request": "EnqueueOperation",
                "version": 7,
                "params": {
                    "actions": [
                        {
                            "receiver": "unit-my-charm-0",
                            "name": "do-thing",
                            "parameters": {},
                        }
                    ]
                },
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    ops = [e["op"] for e in log["events"]]
    assert ops == ["deploy", "integrate", "run"], log["events"]

    src = generate(log)

    # Emitted Python must be syntactically valid.
    module = ast.parse(src)
    func_defs = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    assert func_defs, "codegen must produce a test function"

    # Each bucket-1 op surfaces as the expected jubilant call.
    assert "juju.deploy('ch:my-charm', app='my-charm')" in src, src
    assert "juju.integrate('my-charm:db', 'postgresql:database')" in src, src
    assert "juju.run('my-charm/0', 'do-thing')" in src, src
    # Preamble + idiom are correct.
    assert src.startswith("import jubilant\n"), src
    assert "with jubilant.temp_model() as juju:" in src, src


def test_codegen_handles_bucket2_libjuju_log(tmp_path: Path) -> None:
    """A bucket-2 (lossy) RPC mixed in must not break codegen; it emits a
    ``# TODO`` comment via the fallback path and the rest of the test
    still parses cleanly."""

    FakeConnection.rpc = _make_stub(
        [
            # Application.Deploy — bucket 1
            {"request-id": 1, "response": {"results": [{"tag": "application-x"}]}},
            # Application.SetCharm — bucket 2 (no clean jubilant equivalent)
            {"request-id": 2, "response": {}},
        ]
    )

    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="m",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "Application",
                "request": "Deploy",
                "version": 20,
                "params": {
                    "applications": [
                        {"charm-url": "ch:x", "application-name": "x", "num-units": 1}
                    ]
                },
            }
        )
        _run_rpc(
            {
                "type": "Application",
                "request": "SetCharm",
                "version": 20,
                "params": {"application": "x", "charm-url": "ch:x-2"},
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert [e["op"] for e in log["events"]] == ["deploy", "shell"]

    src = generate(log)
    ast.parse(src)
    # Deploy renders normally.
    assert "juju.deploy('ch:x', app='x')" in src, src
    # The bucket-2 op renders as a TODO via the fallback emitter — codegen
    # does not crash on unknown ops.
    assert "# TODO: manual step" in src, src
    assert '"op": "shell"' in src, src
