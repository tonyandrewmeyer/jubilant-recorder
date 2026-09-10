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

A second test exercises a bucket-2 RPC too, to prove the codegen fallback
emits a ``# TODO`` comment rather than crashing on the libjuju-extension's
secondary buckets.  It uses the synthetic member from ``conftest.py`` rather
than a real facade: ``_BUCKET2_FACADES`` is empty as of 2026-08-18, so no
real RPC classifies that way any more.
"""

from __future__ import annotations

import ast
import asyncio
import json
from typing import TYPE_CHECKING, Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.extensions.libjuju.recording import RecordingLibjuju
from jubilant_recorder.extensions.libjuju.tap import LibjujuTap

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers — shared with the unit-test module's FakeConnection pattern.
# ---------------------------------------------------------------------------


class FakeConnection:
    # Any, not a callable type: tests swap this for stubs with varying shapes.
    rpc: Any = None


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


def test_codegen_handles_bucket2_libjuju_log(tmp_path: Path, bucket2_facade) -> None:
    """A bucket-2 (lossy) RPC mixed in must not break codegen; it emits a
    ``# TODO`` comment via the fallback path and the rest of the test
    still parses cleanly."""

    FakeConnection.rpc = _make_stub(
        [
            # Application.Deploy — bucket 1
            {"request-id": 1, "response": {"results": [{"tag": "application-x"}]}},
            # synthetic bucket-2 member — see conftest.py
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
        facade, method = bucket2_facade
        _run_rpc(
            {
                "type": facade,
                "request": method,
                "version": 1,
                "params": {"uri": "secret:abc123"},
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


def test_codegen_renders_synthesised_wait_for_idle(tmp_path: Path) -> None:
    """Synthesised wait_for_idle events must render as ``juju.wait(jubilant.all_active)``.

    This verifies that carry (b) produces codegen-compatible events: the
    synthesised ``wait_for_idle`` op round-trips through the existing
    ``codegen.generate`` pipeline without modification and emits the same
    jubilant call that the canonical CLI-path recorder produces.
    """
    FakeConnection.rpc = _make_stub(
        [
            # Application.Deploy
            {"request-id": 1, "response": {"results": [{"tag": "application-my-charm"}]}},
            # Application.AddRelation (comes after a long wait)
            {"request-id": 2, "response": {}},
        ]
    )

    log_path = tmp_path / "session.json"
    # idle_threshold_seconds=0 forces synthesis for any inter-RPC gap,
    # even instantaneous ones in unit tests.
    with RecordingLibjuju.start(
        log_path=log_path,
        model="smoke-model",
        tap=LibjujuTap(_connection_class=FakeConnection),
        idle_threshold_seconds=0.0,
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
        _run_rpc(
            {
                "type": "Application",
                "request": "AddRelation",
                "version": 20,
                "params": {"endpoints": ["my-charm:db", "postgresql:database"]},
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    ops = [e["op"] for e in log["events"]]
    # wait_for_idle must have been synthesised between the two user ops.
    assert ops == ["deploy", "wait_for_idle", "integrate"], ops

    src = generate(log)
    # Generated Python must be syntactically valid.
    ast.parse(src)

    # The canonical wait call must appear in the output.
    assert "juju.wait(jubilant.all_active)" in src, src
    # The surrounding ops must also render — synthesis must not break them.
    assert "juju.deploy('ch:my-charm', app='my-charm')" in src, src
    assert "juju.integrate('my-charm:db', 'postgresql:database')" in src, src


def test_codegen_renders_secrets_libjuju_session(tmp_path: Path) -> None:
    """Secrets.* bucket-1 ops produce valid, idiomatic jubilant calls.

    Records CreateSecrets + GrantSecret + UpdateSecrets + RemoveSecrets +
    ListSecrets through RecordingLibjuju, hands the log to codegen.generate,
    and checks:

    * The emitted Python parses cleanly.
    * Each op renders the correct jubilant method with redacted content.
    * No plaintext secret value appears in the output.
    * Secrets.RevokeSecret renders as ``juju.cli("revoke-secret", ...)`` —
      bucket-1 since 2026-08-18 via the escape hatch, jubilant still having
      no ``revoke_secret()`` method of its own.
    """
    FakeConnection.rpc = _make_stub(
        [
            # CreateSecrets
            {"request-id": 1, "response": {}},
            # GrantSecret
            {"request-id": 2, "response": {}},
            # UpdateSecrets
            {"request-id": 3, "response": {}},
            # RemoveSecrets
            {"request-id": 4, "response": {}},
            # ListSecrets
            {"request-id": 5, "response": {}},
            # RevokeSecret (bucket-1 via juju.cli)
            {"request-id": 6, "response": {}},
        ]
    )

    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="secrets-model",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "Secrets",
                "request": "CreateSecrets",
                "version": 2,
                "params": {
                    "secrets": [
                        {
                            "label": "my-secret",
                            "content": {"data": {"password": "hunter2"}},
                            "description": "app password",
                        }
                    ]
                },
            }
        )
        _run_rpc(
            {
                "type": "Secrets",
                "request": "GrantSecret",
                "version": 2,
                "params": {
                    "uri": "secret:abc123",
                    "scope-tag": "model-m",
                    "applications": ["consumer"],
                },
            }
        )
        _run_rpc(
            {
                "type": "Secrets",
                "request": "UpdateSecrets",
                "version": 2,
                "params": {
                    "secrets": [
                        {
                            "existing-id": "secret:abc123",
                            "content": {"data": {"password": "n3w-pass"}},
                        }
                    ]
                },
            }
        )
        _run_rpc(
            {
                "type": "Secrets",
                "request": "RemoveSecrets",
                "version": 2,
                "params": {"secrets": [{"uri": "secret:abc123", "revisions": []}]},
            }
        )
        _run_rpc(
            {
                "type": "Secrets",
                "request": "ListSecrets",
                "version": 2,
                "params": {"show-secrets": False, "filter": {}},
            }
        )
        _run_rpc(
            {
                "type": "Secrets",
                "request": "RevokeSecret",
                "version": 2,
                "params": {
                    "uri": "secret:abc123",
                    "scope-tag": "model-m",
                    "applications": ["consumer"],
                },
            }
        )

    import json as _json

    log = _json.loads(log_path.read_text(encoding="utf-8"))
    ops = [e["op"] for e in log["events"]]
    assert ops == [
        "secret_add",
        "secret_grant",
        "secret_update",
        "secret_remove",
        "secret_list",
        "secret_revoke",
    ], ops

    src = generate(log)

    # Must be syntactically valid Python.
    ast.parse(src)

    # Each bucket-1 Secrets op renders the correct jubilant call.
    assert "juju.add_secret('my-secret'" in src, src
    assert "juju.grant_secret('secret:abc123', 'consumer')" in src, src
    assert "juju.update_secret('secret:abc123'" in src, src
    assert "juju.remove_secret('secret:abc123')" in src, src
    assert "juju.secrets()" in src, src
    assert "juju.cli(\"revoke-secret\", 'secret:abc123'" in src, src

    # Redacted content is present; actual secret values are absent.
    assert "<REDACTED>" in src, src
    assert "hunter2" not in src, src
    assert "n3w-pass" not in src, src

    # The TODO comment appears above each content call.
    assert "# TODO: replace with real secret content" in src, src

    # Nothing in this session is bucket-2 any more, so no fallback TODO is
    # expected — RevokeSecret was the last bucket-2 member and was promoted
    # 2026-08-18. (The "replace with real secret content" TODO above is the
    # redaction placeholder, a different thing entirely.)
    assert "# TODO: manual step" not in src, src


def test_codegen_renders_secret_remove_with_revision(tmp_path: Path) -> None:
    """RemoveSecrets with a specific revision renders revision= kwarg."""
    FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="m",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "Secrets",
                "request": "RemoveSecrets",
                "version": 2,
                "params": {"secrets": [{"uri": "secret:xyz", "revisions": [5]}]},
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    src = generate(log)
    ast.parse(src)
    assert "juju.remove_secret('secret:xyz', revision=5)" in src, src


def test_codegen_renders_list_secrets_with_owner(tmp_path: Path) -> None:
    """ListSecrets with an owner filter renders owner= kwarg."""
    FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="m",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "Secrets",
                "request": "ListSecrets",
                "version": 2,
                "params": {
                    "show-secrets": False,
                    "filter": {"owner-tag": "application-myapp"},
                },
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    src = generate(log)
    ast.parse(src)
    assert "juju.secrets(owner='myapp')" in src, src


def test_codegen_renders_find_application_offers(tmp_path: Path) -> None:
    """``ApplicationOffers.FindApplicationOffers`` is bucket-1 (no
    ``Model``/``Controller`` client method calls it, but ``juju.cli(...)``
    covers the gap) — it must render as a real ``find-offers`` CLI call,
    not a TODO stub."""

    FakeConnection.rpc = _make_stub([{"request-id": 1, "response": {}}])
    log_path = tmp_path / "session.json"
    with RecordingLibjuju.start(
        log_path=log_path,
        model="m",
        tap=LibjujuTap(_connection_class=FakeConnection),
    ):
        _run_rpc(
            {
                "type": "ApplicationOffers",
                "request": "FindApplicationOffers",
                "version": 5,
                "params": {"filters": [{"application-name": "postgresql"}]},
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert [e["op"] for e in log["events"]] == ["find_offers"]

    src = generate(log)
    ast.parse(src)
    # The recorded ``application-name`` filter is deliberately NOT forwarded:
    # ``juju find-offers``' flags do not correspond to the ``OfferFilter``
    # fields the correlator captures, same as ``list_offers``.
    assert 'juju.cli("find-offers", "--format=json")' in src or (
        "juju.cli('find-offers', '--format=json')" in src
    ), src
    assert "postgresql" not in src, src


def test_codegen_renders_create_offer_and_consume(tmp_path: Path) -> None:
    """``ApplicationOffers.Offer`` and ``Application.Consume`` are bucket-1
    (classified in jubilant-recorder@16fbcf1) and now
    have working codegen emitters — full tap → correlate → codegen
    round-trip must produce real ``juju.offer(...)``/``juju.consume(...)``
    calls, not TODO stubs."""

    FakeConnection.rpc = _make_stub(
        [
            # ApplicationOffers.Offer
            {"request-id": 1, "response": {"results": [{}]}},
            # Application.Consume
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
                "type": "ApplicationOffers",
                "request": "Offer",
                "version": 5,
                "params": {
                    "Offers": [
                        {
                            "application-name": "postgresql",
                            "endpoints": {"db": "db"},
                            "offer-name": "postgresql",
                            "model-tag": "model-deadbeef",
                        }
                    ]
                },
            }
        )
        _run_rpc(
            {
                "type": "Application",
                "request": "Consume",
                "version": 20,
                "params": {
                    "args": [
                        {
                            "offer-url": "admin/othermodel.postgresql",
                            "application-alias": None,
                        }
                    ]
                },
            }
        )

    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert [e["op"] for e in log["events"]] == ["create_offer", "consume"]

    src = generate(log)
    ast.parse(src)
    assert "juju.offer('postgresql', endpoint='db')" in src, src
    assert "juju.consume('admin/othermodel.postgresql')" in src, src
    assert "# TODO: manual step" not in src, src


def test_the_committed_example_matches_what_codegen_emits() -> None:
    """`examples/libjuju/generated_test.py` is a checked-in codegen output.

    It went stale twice before anything noticed — once carrying `# TODO:
    manual step` blocks for a `config_get` that codegen had learned to
    render, and once with assertions codegen had stopped emitting. The same
    treatment as `tests/fixtures/golden/`: run the pipeline, diff the file.

    Regenerate with the command in `examples/libjuju/README.md`.
    """
    from pathlib import Path as _Path

    from jubilant_recorder import quiet_window, tagger

    root = _Path(__file__).resolve().parents[2] / "examples" / "libjuju"
    log = json.loads((root / "session.json").read_text())
    source = generate(tagger.tag(quiet_window.synthesize(log)), test_name="test_ubuntu_deploy")
    assert source == (root / "generated_test.py").read_text(), (
        "examples/libjuju/generated_test.py no longer matches codegen. "
        "Regenerate it (see examples/libjuju/README.md) and review the diff."
    )
