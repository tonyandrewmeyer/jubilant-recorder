from __future__ import annotations

from jubilant_recorder.tagger import tag


def test_unit_count_tag_fires_when_unit_count_increases(scale_session):
    result = tag(scale_session)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "unit_count"]
    assert tags == [
        {
            "kind": "unit_count",
            "app": "my-charm",
            "expected": 3,
            "strict": False,
            "source": "delta",
        }
    ]


def test_unit_count_tag_does_not_fire_when_no_count_change(action_session):
    result = tag(action_session)
    [event] = result["events"]
    assert not any(a["kind"] == "unit_count" for a in event["assertions"])


def test_unit_count_tag_fires_on_first_deploy():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    before = make_snapshot()
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(
                        workload_status="maintenance", agent_status="executing"
                    ),
                },
            },
        },
    )
    log = make_log([make_event(1, "deploy", before=before, after=after)])
    result = tag(log)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "unit_count"]
    assert tags == [
        {
            "kind": "unit_count",
            "app": "my-charm",
            "expected": 1,
            "strict": False,
            "source": "delta",
        }
    ]
