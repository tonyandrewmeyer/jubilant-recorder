"""Regressions from the first live `pytest --jtr-out` run against a charm.

Three things the fixture corpus never produced, because a hand-built
`FakeConnection` sends what the correlator expects rather than what libjuju
actually sends.
"""

from __future__ import annotations

from jubilant_recorder.extensions.libjuju.correlate import _classify, _extract_args, correlate

_BASE = "2026-09-10T00:00:"


def _ts(second: float) -> str:
    s = int(second)
    ms = round((second - s) * 1000)
    return f"{_BASE}{s:02d}.{ms:03d}Z"


def _rpc(facade: str, method: str, params: dict, *, start: float = 0.0, end: float = 0.1) -> dict:
    return {
        "request_id": 1,
        "ts_start_iso": _ts(start),
        "ts_end_iso": _ts(end),
        "facade": facade,
        "version": 20,
        "method": method,
        "params": params,
    }


def _unit_delta(name: str, app: str, status: str, *, ts: float) -> dict:
    return {
        "ts_iso": _ts(ts),
        "entity_kind": "unit",
        "change_kind": "change",
        "payload": {
            "name": name,
            "application": app,
            "workload-status": {"current": status, "message": "", "since": ""},
            "agent-status": {"current": "idle", "message": "", "since": ""},
        },
    }


# --- DestroyApplication's real wire shape ---


def test_destroy_application_accepts_bare_application_names() -> None:
    """What libjuju 3.6 sends for `Model.remove_application()`.

    The correlator assumed a list of `{application-tag: …}` entities and
    raised `AttributeError` on a list of plain strings — which, before the
    plugin isolated recorder failures, failed the test being recorded.
    """
    assert _extract_args(
        "Application", "DestroyApplication", {"applications": ["ubuntu-peer"]}
    ) == {"app": "ubuntu-peer"}


def test_destroy_application_still_accepts_the_entity_shape() -> None:
    args = _extract_args(
        "Application",
        "DestroyApplication",
        {"applications": [{"application-tag": "application-ubuntu"}]},
    )
    assert args == {"app": "ubuntu"}


def test_destroy_application_with_no_applications_does_not_raise() -> None:
    assert _extract_args("Application", "DestroyApplication", {}) == {"app": ""}


# --- DestroyUnit ---


def test_destroy_unit_is_bucket_one() -> None:
    """`Application.DestroyUnit` was bucket 3, though jubilant has remove_unit()."""
    bucket, op = _classify("Application", "DestroyUnit")
    assert (bucket, op) == ("1", "remove_unit")


def test_destroy_unit_args() -> None:
    args = _extract_args(
        "Application",
        "DestroyUnit",
        {
            "units": [
                {"unit-tag": "unit-ubuntu-1", "destroy-storage": False, "force": False},
                {"unit-tag": "unit-ubuntu-2", "destroy-storage": True, "force": True},
            ]
        },
    )
    assert args == {
        "app_or_unit": ["ubuntu/1", "ubuntu/2"],
        "force": True,
        "destroy_storage": True,
    }


# --- the trailing wait ---


def test_a_session_ending_on_a_wait_gets_a_wait_for_idle() -> None:
    """Nearly every pytest-operator test ends on `wait_for_idle`.

    Synthesis only looked at gaps *between* RPCs, so the last wait was lost,
    its deltas became orphans, and the final snapshot never advanced past
    "waiting" — leaving the generated test with no assertion on the thing
    the test existed to check.
    """
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [
        _unit_delta("ubuntu/0", "ubuntu", "waiting", ts=0.2),
        _unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0),
    ]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    ops = [e["op"] for e in events]
    assert ops == ["deploy", "wait_for_idle"]

    wait = events[-1]
    before = wait["model_snapshot_before"]["apps"]["ubuntu"]["units"]["ubuntu/0"]
    after = wait["model_snapshot_after"]["apps"]["ubuntu"]["units"]["ubuntu/0"]
    assert before["workload_status"] == "waiting"
    assert after["workload_status"] == "active"


def test_the_trailing_deltas_are_no_longer_orphans() -> None:
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [_unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0)]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    assert "_libjuju_orphan_deltas" not in [e["op"] for e in events]


def test_a_short_trailing_gap_is_not_a_wait() -> None:
    """Deltas landing right after the call are the call's own, not a wait."""
    rpcs = [
        _rpc(
            "Application",
            "Deploy",
            {"applications": [{"charm-url": "ch:ubuntu", "application-name": "ubuntu"}]},
        )
    ]
    deltas = [_unit_delta("ubuntu/0", "ubuntu", "waiting", ts=3.0)]
    events = correlate(rpcs, deltas, idle_threshold_seconds=5.0)
    assert "wait_for_idle" not in [e["op"] for e in events]


def test_no_rpcs_at_all_synthesises_nothing() -> None:
    events = correlate([], [_unit_delta("ubuntu/0", "ubuntu", "active", ts=30.0)])
    assert [e["op"] for e in events] == ["_libjuju_orphan_deltas"]


# --- typed objects in params ---


class _LibjujuTypeWithToJson:
    """The shape libjuju's generated `Type` classes have.

    `to_json()` returns a JSON *string*, which `_normalise` used to hand
    straight through as a scalar: structure intact but opaque, and the
    correlator then read a whole entity as if it were a name.
    """

    def to_json(self) -> str:
        return '{"tag": "application-ubuntu-peer", "force": false}'


def test_normalise_parses_a_to_json_string_back_into_structure() -> None:
    from jubilant_recorder.extensions.libjuju.tap import _normalise

    assert _normalise(_LibjujuTypeWithToJson()) == {
        "tag": "application-ubuntu-peer",
        "force": False,
    }


def test_destroy_application_accepts_the_tag_spelling() -> None:
    """`DestroyApplicationParams` says `tag`, `Entities` says `application-tag`."""
    args = _extract_args(
        "Application", "DestroyApplication", {"applications": [{"tag": "application-ubuntu-peer"}]}
    )
    assert args == {"app": "ubuntu-peer"}


# --- state carried between per-test sessions ---


def test_deltas_are_read_against_the_state_the_session_started_from() -> None:
    """A tap that attaches part-way through a model's life misses the past.

    That is every test after the first, when a suite shares one model and
    each test is recorded separately. Without this, `test_scale_up` looked
    like it took a model from no units to one unit, and the generated test
    asserted a count short by everything the earlier tests deployed.
    """
    initial = {
        "schema_version": 1,
        "captured_at": _ts(0),
        "apps": {
            "ubuntu": {
                "units": {
                    "ubuntu/0": {
                        "workload_status": "active",
                        "workload_message": "",
                        "agent_status": "idle",
                    }
                }
            }
        },
        "relations": [],
    }
    rpcs = [
        _rpc(
            "Application",
            "AddUnits",
            {"application": "ubuntu", "num-units": 1},
        )
    ]
    deltas = [_unit_delta("ubuntu/1", "ubuntu", "active", ts=0.2)]

    events = correlate(rpcs, deltas, initial_snapshot=initial)
    after = events[0]["model_snapshot_after"]["apps"]["ubuntu"]["units"]
    assert sorted(after) == ["ubuntu/0", "ubuntu/1"]


def test_without_the_initial_snapshot_only_the_new_unit_is_seen() -> None:
    """The behaviour the parameter exists to correct, pinned so it stays visible."""
    rpcs = [_rpc("Application", "AddUnits", {"application": "ubuntu", "num-units": 1})]
    deltas = [_unit_delta("ubuntu/1", "ubuntu", "active", ts=0.2)]
    events = correlate(rpcs, deltas)
    assert list(events[0]["model_snapshot_after"]["apps"]["ubuntu"]["units"]) == ["ubuntu/1"]


# --- multi-application secret grants ---


def test_grant_secret_keeps_every_application() -> None:
    """`applications[0]` silently discarded the rest of a multi-app grant.

    Both targets can express the whole list — `Juju.grant_secret()` takes
    `str | Iterable[str]`, and `juju revoke-secret` takes a comma-joined
    list — so the narrowing lost information neither of them needed to.
    """
    args = _extract_args(
        "Secrets", "GrantSecret", {"uri": "secret:abc", "applications": ["a", "b"]}
    )
    assert args == {"identifier": "secret:abc", "app": ["a", "b"]}


def test_grant_secret_to_one_application_stays_a_string() -> None:
    args = _extract_args("Secrets", "GrantSecret", {"uri": "secret:abc", "applications": ["a"]})
    assert args == {"identifier": "secret:abc", "app": "a"}


def test_revoke_secret_renders_the_comma_joined_list_the_cli_takes() -> None:
    from jubilant_recorder.codegen.operations import secret_revoke

    line = secret_revoke.emit({"args": {"identifier": "secret:abc", "app": ["a", "b"]}}, 8)
    assert line.strip() == "juju.cli(\"revoke-secret\", 'secret:abc', 'a,b')"


# --- the connection handshake ---


def test_admin_login_is_internal() -> None:
    """`Model.connect()` sends one per connection, and it is not a step.

    A cross-model session makes several, and each rendered as a `# TODO:
    manual step` block in the generated test — carrying, in its raw
    parameters, the controller password.
    """
    from jubilant_recorder.extensions.libjuju.correlate import _is_internal

    assert _is_internal("Admin", "Login")
    assert _is_internal("Admin", "RedirectInfo")


def test_an_unmapped_rpc_has_its_parameters_scrubbed() -> None:
    """Bucket 3 records parameters verbatim, and facades take credentials."""
    from jubilant_recorder.extensions.libjuju.correlate import _redacted_params

    scrubbed = _redacted_params(
        {
            "auth-tag": "user-admin",
            "client-version": "3.6.1.3",
            "credentials": "9fd8bc6a4af0297a4bb452ce0cf1b64e",
        }
    )
    assert scrubbed["credentials"] == "<redacted:credential>"
    assert scrubbed["auth-tag"] == "user-admin"


def test_an_unmapped_rpc_that_cannot_be_scrubbed_is_dropped() -> None:
    """A payload we cannot walk is one we cannot vouch for.

    The tap normalises everything to plain dicts before this, so it should
    never happen — which is exactly why the failure mode has to be "emit
    nothing" rather than "emit the payload".
    """
    from jubilant_recorder.extensions.libjuju.correlate import _redacted_params

    class NotAMapping:
        def keys(self):
            raise RuntimeError("no")

    assert "_redacted" in _redacted_params(NotAMapping())  # type: ignore[arg-type]


def test_a_bucket_three_event_carries_the_scrubbed_parameters() -> None:
    """End to end through `correlate`, not just the helper."""
    rpcs = [
        _rpc("Weird", "Method", {"password": "hunter2", "harmless": "yes"}),
    ]
    events = correlate(rpcs, [])
    (event,) = [e for e in events if e["op"] == "_todo"]
    assert event["args"]["_raw_params"]["password"] == "<redacted:password>"
    assert event["args"]["_raw_params"]["harmless"] == "yes"
