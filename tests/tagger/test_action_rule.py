from __future__ import annotations

from jubilant_recorder.tagger import tag


def test_action_result_tag_fires_on_successful_run(action_session):
    result = tag(action_session)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "action_result"]
    assert tags == [
        {
            "kind": "action_result",
            "unit": "my-charm/0",
            "action": "do-thing",
            "expected_success": True,
            "expected_results": {"output": "done"},
            "strict": False,
            "source": "delta",
        }
    ]


def test_action_result_tag_fires_on_failed_run(action_failed_session):
    result = tag(action_failed_session)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "action_result"]
    assert tags == [
        {
            "kind": "action_result",
            "unit": "my-charm/0",
            "action": "do-thing",
            "expected_success": False,
            "expected_results": {},
            "strict": False,
            "source": "delta",
        }
    ]


def test_action_result_tag_does_not_fire_for_non_run_events(status_session):
    result = tag(status_session)
    [event] = result["events"]
    assert not any(a["kind"] == "action_result" for a in event["assertions"])


def test_action_result_tag_filters_unstable_result_values():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log(
        [
            make_event(
                1,
                "run",
                args={"unit": "my-charm/0", "action": "do-thing", "params": {}},
                result={
                    "success": True,
                    "results": {
                        "output": "done",
                        "timestamp": "2026-05-30T09:01:53.100Z",
                        "ip": "10.5.46.1",
                        "count": 7,
                    },
                    "message": None,
                },
                before=snap,
                after=snap,
            ),
        ]
    )
    result = tag(log)
    [event] = result["events"]
    [assertion] = [a for a in event["assertions"] if a["kind"] == "action_result"]
    assert assertion["expected_results"] == {"output": "done", "count": 7}
