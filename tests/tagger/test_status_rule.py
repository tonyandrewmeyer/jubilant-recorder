from __future__ import annotations

from jubilant_recorder.tagger import tag


def test_unit_status_tag_fires_when_workload_settles_to_active(status_session):
    result = tag(status_session)
    [event] = result["events"]
    [assertion] = event["assertions"]
    assert assertion == {
        "kind": "unit_status",
        "app": "my-charm",
        "unit": "my-charm/0",
        "expected": "active",
        "strict": False,
        "source": "delta",
    }


def test_unit_status_tag_does_not_fire_when_no_status_delta(status_no_delta_session):
    result = tag(status_no_delta_session)
    [event] = result["events"]
    assert event["assertions"] == []


def test_unit_status_tag_does_not_fire_when_after_status_is_transient():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    before = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit(workload_status="unknown")}}},
    )
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {"my-charm/0": make_unit(workload_status="maintenance")},
            },
        },
    )
    log = make_log([make_event(1, "deploy", before=before, after=after)])
    result = tag(log)
    [event] = result["events"]
    assert not any(a["kind"] == "unit_status" for a in event["assertions"])


def test_unit_status_tag_fires_on_blocked_status():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    before = make_snapshot(
        apps={"my-charm": {"units": {"my-charm/0": make_unit(workload_status="waiting")}}},
    )
    after = make_snapshot(
        apps={
            "my-charm": {
                "units": {
                    "my-charm/0": make_unit(
                        workload_status="blocked", workload_message="bad config"
                    ),
                },
            },
        },
    )
    log = make_log([make_event(1, "wait_for_idle", before=before, after=after)])
    result = tag(log)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "unit_status"]
    assert tags == [
        {
            "kind": "unit_status",
            "app": "my-charm",
            "unit": "my-charm/0",
            "expected": "blocked",
            "strict": False,
            "source": "delta",
        }
    ]
