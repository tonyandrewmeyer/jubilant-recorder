"""Tests for the LLM-augmented tagger pass.

All tests use stub seams — no real LLM calls are made. The LLMProposer
path is covered via a minimal mock that returns pre-canned JSON, exercising
the full parse-and-validate pipeline without a network round-trip.
"""

from __future__ import annotations

import copy
import json
import warnings
from typing import Any
from unittest.mock import MagicMock

import pytest

from jubilant_recorder.tagger import tag
from jubilant_recorder.tagger.llm import (
    AssertionProposer,
    LLMProposer,
    StubProposer,
    _collect_known_entities,
    _json_payload,
    llm_augment,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def make_snapshot(
    *, apps: dict[str, Any] | None = None, relations: list | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:00:00.000Z",
        "apps": apps or {},
        "relations": relations or [],
    }


def make_unit(status: str = "active") -> dict[str, Any]:
    return {"workload_status": status, "workload_message": "", "agent_status": "idle"}


def make_event(
    seq: int,
    op: str,
    *,
    args: dict | None = None,
    result: dict | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": "2026-05-30T09:00:00Z",
        "args": args or {},
        "result": result or {},
        "model_snapshot_before": before,
        "model_snapshot_after": after,
        "assertions": [],
        "gesture": None,
    }


def make_log(events: list[dict]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "test",
        "recorded_at": "2026-05-30T09:05:00Z",
        "juju_version": "3.6.23",
        "jubilant_version": "1.0.0",
        "model": "test-model",
        "events": events,
    }


# ── StubProposer ─────────────────────────────────────────────────────────────


def test_stub_proposer_returns_empty():
    proposer = StubProposer()
    log = make_log([make_event(1, "deploy", args={"charm": "x", "app": None})])
    assert proposer.propose(log) == []


def test_stub_proposer_satisfies_protocol():
    assert isinstance(StubProposer(), AssertionProposer)


# ── AssertionProposer Protocol ────────────────────────────────────────────────


def test_custom_proposer_satisfies_protocol():
    class MyProposer:
        def propose(self, log):
            return []

    assert isinstance(MyProposer(), AssertionProposer)


# ── _collect_known_entities ───────────────────────────────────────────────────


def test_collect_known_entities():
    snap = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit(), "my-charm/1": make_unit()}}}
    )
    log = make_log([make_event(1, "deploy", before=snap, after=snap)])
    apps, units = _collect_known_entities(log)
    assert "my-charm" in apps
    assert "my-charm/0" in units
    assert "my-charm/1" in units


def test_collect_known_entities_empty_log():
    log = make_log([])
    apps, units = _collect_known_entities(log)
    assert apps == set()
    assert units == set()


# ── llm_augment safety rail ───────────────────────────────────────────────────


def _proposer_from(proposals: list[dict]) -> AssertionProposer:
    class _Fixed:
        def propose(self, log):
            return proposals

    return _Fixed()


def test_llm_augment_unknown_seq_dropped():
    log = make_log([make_event(1, "deploy")])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 99,
                        "kind": "unit_status",
                        "app": "x",
                        "unit": "x/0",
                        "expected": "active",
                    }
                ]
            ),
        )

    assert any("unknown seq" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_unknown_kind_dropped():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "deploy", before=snap, after=snap)])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log, _proposer_from([{"seq": 1, "kind": "hallucinated_kind", "app": "my-charm"}])
        )

    assert any("unknown kind" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_unknown_app_dropped():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "deploy", before=snap, after=snap)])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 1,
                        "kind": "unit_status",
                        "app": "ghost-app",
                        "unit": "my-charm/0",
                        "expected": "active",
                    }
                ]
            ),
        )

    assert any("not in session log" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_unknown_unit_dropped():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "deploy", before=snap, after=snap)])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 1,
                        "kind": "unit_status",
                        "app": "my-charm",
                        "unit": "my-charm/99",
                        "expected": "active",
                    }
                ]
            ),
        )

    assert any("not in session log" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_action_result_wrong_event_dropped():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "deploy", args={"charm": "my-charm"}, before=snap, after=snap)])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 1,
                        "kind": "action_result",
                        "unit": "my-charm/0",
                        "action": "do-thing",
                        "expected_success": True,
                        "expected_results": {},
                    }
                ]
            ),
        )

    assert any("not a 'run' event" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_action_result_unit_mismatch_dropped():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log(
        [
            make_event(
                1,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {}},
                result={"success": True, "results": {}, "message": None},
                before=snap,
                after=snap,
            )
        ]
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 1,
                        "kind": "action_result",
                        "unit": "my-charm/1",
                        "action": "do-thing",
                        "expected_success": True,
                        "expected_results": {},
                    }
                ]
            ),
        )

    assert any("does not match event unit" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_relation_invalid_endpoint_dropped():
    log = make_log(
        [make_event(1, "integrate", args={"app1_endpoint": "a:b", "app2_endpoint": "c:d"})]
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = llm_augment(
            log,
            _proposer_from(
                [
                    {
                        "seq": 1,
                        "kind": "relation_exists",
                        "endpoint_a": "no-colon",
                        "endpoint_b": "c:d",
                    }
                ]
            ),
        )

    assert any("not a valid app:endpoint string" in str(warning.message) for warning in w)
    assert out["events"][0]["assertions"] == []


def test_llm_augment_non_dict_proposal_dropped():
    log = make_log([make_event(1, "deploy")])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        llm_augment(log, _proposer_from(["not a dict"]))

    assert any("not a dict" in str(warning.message) for warning in w)


# ── llm_augment valid proposals ───────────────────────────────────────────────


def test_llm_augment_unit_status_merged():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap, after=snap)])

    out = llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "unit_status",
                    "app": "my-charm",
                    "unit": "my-charm/0",
                    "expected": "active",
                }
            ]
        ),
    )

    assertions = out["events"][0]["assertions"]
    assert len(assertions) == 1
    assert assertions[0]["kind"] == "unit_status"
    assert assertions[0]["source"] == "llm"
    assert assertions[0]["strict"] is False
    assert assertions[0]["app"] == "my-charm"
    assert assertions[0]["unit"] == "my-charm/0"
    assert assertions[0]["expected"] == "active"


def test_llm_augment_unit_count_merged():
    snap = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit(), "my-charm/1": make_unit()}}}
    )
    log = make_log(
        [make_event(1, "scale", args={"app": "my-charm", "units": 2}, before=snap, after=snap)]
    )

    out = llm_augment(
        log, _proposer_from([{"seq": 1, "kind": "unit_count", "app": "my-charm", "expected": 2}])
    )

    assertions = out["events"][0]["assertions"]
    assert len(assertions) == 1
    assert assertions[0]["kind"] == "unit_count"
    assert assertions[0]["source"] == "llm"
    assert assertions[0]["expected"] == 2


def test_llm_augment_action_result_merged():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log(
        [
            make_event(
                1,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {}},
                result={"success": True, "results": {"output": "ok"}, "message": None},
                before=snap,
                after=snap,
            )
        ]
    )

    out = llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "action_result",
                    "unit": "my-charm/0",
                    "action": "do-thing",
                    "expected_success": True,
                    "expected_results": {"output": "ok"},
                }
            ]
        ),
    )

    assertions = out["events"][0]["assertions"]
    assert len(assertions) == 1
    a = assertions[0]
    assert a["kind"] == "action_result"
    assert a["source"] == "llm"
    assert a["expected_success"] is True
    assert a["expected_results"] == {"output": "ok"}


def test_llm_augment_relation_exists_merged_and_sorted():
    log = make_log(
        [make_event(1, "integrate", args={"app1_endpoint": "a:rel", "app2_endpoint": "b:db"})]
    )

    out = llm_augment(
        log,
        _proposer_from(
            [{"seq": 1, "kind": "relation_exists", "endpoint_a": "b:db", "endpoint_b": "a:rel"}]
        ),
    )

    assertions = out["events"][0]["assertions"]
    assert len(assertions) == 1
    a = assertions[0]
    assert a["kind"] == "relation_exists"
    assert a["source"] == "llm"
    # endpoints are sorted
    assert a["endpoint_a"] == "a:rel"
    assert a["endpoint_b"] == "b:db"


def test_llm_augment_deduplicates_against_existing():
    """LLM proposal for an assertion already added by the delta tagger is skipped."""
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    existing_tag = {
        "kind": "unit_status",
        "source": "delta",
        "strict": False,
        "app": "my-charm",
        "unit": "my-charm/0",
        "expected": "active",
    }
    event = make_event(1, "wait_for_idle", before=snap, after=snap)
    event["assertions"] = [existing_tag]
    log = make_log([event])

    out = llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "unit_status",
                    "app": "my-charm",
                    "unit": "my-charm/0",
                    "expected": "active",
                }
            ]
        ),
    )

    # still only one assertion, the original delta one
    assertions = out["events"][0]["assertions"]
    assert len(assertions) == 1
    assert assertions[0]["source"] == "delta"


def test_llm_augment_does_not_mutate_input():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap, after=snap)])
    original = copy.deepcopy(log)

    llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "unit_status",
                    "app": "my-charm",
                    "unit": "my-charm/0",
                    "expected": "active",
                }
            ]
        ),
    )

    assert log == original


def test_llm_augment_returns_same_object_when_no_proposals():
    """When proposer returns [], llm_augment skips the deep-copy for efficiency."""
    log = make_log([make_event(1, "deploy")])
    out = llm_augment(log, StubProposer())
    assert out is log  # identity — no copy when nothing to do


# ── tag() integration with proposer ──────────────────────────────────────────


def test_tag_with_stub_proposer_unchanged():
    """tag(log, proposer=StubProposer()) produces the same result as tag(log)."""
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit("maintenance")}}})
    active = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit("active")}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap, after=active)])

    without = tag(log)
    with_stub = tag(log, proposer=StubProposer())
    assert without == with_stub


def test_tag_with_none_proposer_unchanged():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit("maintenance")}}})
    active = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit("active")}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap, after=active)])

    without = tag(log)
    with_none = tag(log, proposer=None)
    assert without == with_none


def test_tag_merges_llm_and_delta_assertions():
    """LLM and delta assertions coexist on the same event."""
    snap_before = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit("maintenance")}}}
    )
    snap_after = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit("active")}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap_before, after=snap_after)])

    # Delta rule will emit unit_status for my-charm/0.
    # LLM proposer will propose unit_count (different kind → not a duplicate).
    proposer = _proposer_from([{"seq": 1, "kind": "unit_count", "app": "my-charm", "expected": 1}])
    out = tag(log, proposer=proposer)

    event = out["events"][0]
    kinds = {a["kind"] for a in event["assertions"]}
    assert "unit_status" in kinds  # from delta rule
    assert "unit_count" in kinds  # from LLM proposer
    sources = {a["source"] for a in event["assertions"]}
    assert "delta" in sources
    assert "llm" in sources


# ── LLMProposer (mock client) ─────────────────────────────────────────────────


def _make_mock_client(response_text: str) -> Any:
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": response_text}}]}
    client = MagicMock()
    client.post.return_value = response
    return client


def test_llm_proposer_parses_valid_response():
    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log([make_event(1, "wait_for_idle", before=snap, after=snap)])

    payload = '{"proposals": [{"seq": 1, "kind": "unit_status", "app": "my-charm", "unit": "my-charm/0", "expected": "active"}]}'
    proposer = LLMProposer(_make_mock_client(payload), model="test/model")
    proposals = proposer.propose(log)

    assert len(proposals) == 1
    assert proposals[0]["kind"] == "unit_status"


def test_llm_proposer_bad_json_warns_and_returns_empty():
    log = make_log([make_event(1, "deploy")])
    proposer = LLMProposer(_make_mock_client("not json at all"), model="test/model")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        proposals = proposer.propose(log)

    assert proposals == []
    assert any("non-JSON" in str(warning.message) for warning in w)


def test_llm_proposer_missing_proposals_key_warns():
    log = make_log([make_event(1, "deploy")])
    proposer = LLMProposer(_make_mock_client('{"something_else": []}'), model="test/model")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        proposals = proposer.propose(log)

    assert proposals == []
    assert any("proposals" in str(warning.message) for warning in w)


def test_llm_proposer_api_error_warns_and_returns_empty():
    log = make_log([make_event(1, "deploy")])
    client = MagicMock()
    client.post.side_effect = RuntimeError("network down")
    proposer = LLMProposer(client, model="test/model")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        proposals = proposer.propose(log)

    assert proposals == []
    assert any("API call failed" in str(warning.message) for warning in w)


def test_llm_proposer_satisfies_protocol():
    client = MagicMock()
    assert isinstance(LLMProposer(client, model="test/model"), AssertionProposer)


class TestTolerantJSONPayload:
    """A fenced or preambled reply is still a usable set of proposals.

    Seen intermittently from a live model: the prompt asks for bare JSON and
    usually gets it, but not always, and a bare json.loads skipped the whole
    LLM pass with a warning when it did not.
    """

    _OBJ = '{"proposals": [{"seq": 1, "kind": "unit_count", "app": "ubuntu", "expected": 1}]}'

    def test_bare_json_is_unchanged(self):
        assert json.loads(_json_payload(self._OBJ))["proposals"]

    def test_json_fence_is_stripped(self):
        raw = f"```json\n{self._OBJ}\n```"
        assert json.loads(_json_payload(raw))["proposals"]

    def test_bare_fence_is_stripped(self):
        raw = f"```\n{self._OBJ}\n```"
        assert json.loads(_json_payload(raw))["proposals"]

    def test_preamble_before_the_object_is_dropped(self):
        raw = f"Here are the proposals:\n\n{self._OBJ}"
        assert json.loads(_json_payload(raw))["proposals"]

    def test_prose_with_no_object_is_returned_unchanged(self):
        """The caller's JSONDecodeError path has to stay reachable."""
        raw = "I can't help with that."
        assert _json_payload(raw) == raw
        with pytest.raises(json.JSONDecodeError):
            json.loads(_json_payload(raw))


def test_llm_proposal_does_not_restate_a_gesture_assertion():
    """A proposal must not duplicate what a gesture already asserted.

    The proposer does not only add assertions: given a gesture that asserted a
    status app-wide, it proposed the same claim pinned to the recorded unit
    name, and the generated test then carried both -- once portably, once in a
    form that raises KeyError in a fresh model. An explicit assertion being
    restated by a proposal is worse than a proposal being dropped.
    """
    snap_before = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/1": make_unit("waiting")}}},
    )
    snap_after = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/1": make_unit("active")}}},
    )
    event = make_event(1, "wait_for_idle", before=snap_before, after=snap_after)
    event["assertions"] = [
        {
            "kind": "unit_status",
            "app": "my-charm",
            "unit": None,
            "expected": "active",
            "strict": True,
            "source": "gesture",
        }
    ]
    log = make_log([event])

    out = llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "unit_status",
                    "app": "my-charm",
                    "unit": "my-charm/1",
                    "expected": "active",
                }
            ]
        ),
    )

    tags = [a for a in out["events"][0]["assertions"] if a["kind"] == "unit_status"]
    assert len(tags) == 1
    assert tags[0]["source"] == "gesture"
    assert tags[0]["unit"] is None


def test_llm_proposal_for_a_different_status_is_still_added():
    """The coverage check keys on app *and* status, so it must not over-suppress."""
    snap_before = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit("waiting")}}},
    )
    snap_after = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit("active")}}},
    )
    event = make_event(1, "wait_for_idle", before=snap_before, after=snap_after)
    event["assertions"] = [
        {
            "kind": "unit_status",
            "app": "my-charm",
            "unit": None,
            "expected": "active",
            "strict": True,
            "source": "gesture",
        }
    ]
    log = make_log([event])

    out = llm_augment(
        log,
        _proposer_from(
            [
                {
                    "seq": 1,
                    "kind": "unit_status",
                    "app": "my-charm",
                    "unit": "my-charm/0",
                    "expected": "blocked",
                }
            ]
        ),
    )

    tags = [a for a in out["events"][0]["assertions"] if a["kind"] == "unit_status"]
    assert len(tags) == 2
    assert {t["expected"] for t in tags} == {"active", "blocked"}
