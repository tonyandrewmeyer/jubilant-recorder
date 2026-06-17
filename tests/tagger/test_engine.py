from __future__ import annotations

import copy
import dataclasses

import pytest

from jubilant_recorder.tagger import AssertionTag, tag


def test_tag_does_not_mutate_input(happy_path_session):
    snapshot = copy.deepcopy(happy_path_session)
    tag(happy_path_session)
    assert happy_path_session == snapshot


def test_tag_preserves_event_order_and_count(happy_path_session):
    result = tag(happy_path_session)
    assert len(result["events"]) == len(happy_path_session["events"])
    assert [e["seq"] for e in result["events"]] == [1, 2, 3]
    assert [e["op"] for e in result["events"]] == ["deploy", "wait_for_idle", "run"]


def test_happy_path_emits_expected_tags(happy_path_session):
    result = tag(happy_path_session)
    deploy_event, wait_event, run_event = result["events"]

    deploy_kinds = {a["kind"] for a in deploy_event["assertions"]}
    assert "unit_count" in deploy_kinds

    wait_kinds = {a["kind"] for a in wait_event["assertions"]}
    assert "unit_status" in wait_kinds

    run_kinds = {a["kind"] for a in run_event["assertions"]}
    assert "action_result" in run_kinds


def test_negative_path_emits_no_tags(negative_path_session):
    result = tag(negative_path_session)
    for event in result["events"]:
        assert event["assertions"] == []


def test_existing_tag_is_not_overridden(gesture_already_tagged_session):
    result = tag(gesture_already_tagged_session)
    [event] = result["events"]
    unit_status_tags = [a for a in event["assertions"] if a["kind"] == "unit_status"]
    assert len(unit_status_tags) == 1
    assert unit_status_tags[0]["source"] == "gesture"
    assert unit_status_tags[0]["strict"] is True


def test_assertion_tag_dataclass_is_frozen():
    instance = AssertionTag(
        kind="unit_status",
        strict=False,
        source="delta",
        payload={"app": "x", "unit": "x/0", "expected": "active"},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.kind = "other"  # type: ignore[misc]


def test_assertion_tag_to_dict_shape_matches_schema():
    instance = AssertionTag(
        kind="unit_status",
        strict=False,
        source="delta",
        payload={"app": "my-charm", "unit": "my-charm/0", "expected": "active"},
    )
    assert instance.to_dict() == {
        "kind": "unit_status",
        "source": "delta",
        "strict": False,
        "app": "my-charm",
        "unit": "my-charm/0",
        "expected": "active",
    }
