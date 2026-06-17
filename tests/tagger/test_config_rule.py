from __future__ import annotations

from jubilant_recorder.tagger import tag


def test_config_value_tag_fires_when_get_confirms_set(config_session):
    result = tag(config_session)
    config_get_event = result["events"][1]
    tags = sorted(
        (a for a in config_get_event["assertions"] if a["kind"] == "config_value"),
        key=lambda a: a["key"],
    )
    assert tags == [
        {
            "kind": "config_value",
            "app": "my-charm",
            "key": "debug",
            "expected": True,
            "strict": False,
            "source": "delta",
        },
        {
            "kind": "config_value",
            "app": "my-charm",
            "key": "log-level",
            "expected": "info",
            "strict": False,
            "source": "delta",
        },
    ]


def test_config_value_tag_does_not_fire_without_verify(config_no_verify_session):
    result = tag(config_no_verify_session)
    [event] = result["events"]
    assert not any(a["kind"] == "config_value" for a in event["assertions"])


def test_config_value_tag_does_not_fire_when_get_value_differs():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log(
        [
            make_event(
                1,
                "config",
                args={"app": "my-charm", "values": {"log-level": "info"}},
                before=snap,
                after=snap,
            ),
            make_event(
                2,
                "config_get",
                args={"app": "my-charm", "keys": None},
                result={"values": {"log-level": "debug"}},
                before=snap,
                after=snap,
            ),
        ]
    )
    result = tag(log)
    config_get_event = result["events"][1]
    assert not any(a["kind"] == "config_value" for a in config_get_event["assertions"])


def test_config_value_tag_does_not_fire_when_state_change_in_between():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    snap = make_snapshot(apps={"my-charm": {"units": {"my-charm/0": make_unit()}}})
    log = make_log(
        [
            make_event(
                1,
                "config",
                args={"app": "my-charm", "values": {"log-level": "info"}},
                before=snap,
                after=snap,
            ),
            make_event(2, "scale", args={"app": "my-charm", "units": 2}, before=snap, after=snap),
            make_event(
                3,
                "config_get",
                args={"app": "my-charm", "keys": None},
                result={"values": {"log-level": "info"}},
                before=snap,
                after=snap,
            ),
        ]
    )
    result = tag(log)
    config_get_event = result["events"][2]
    assert not any(a["kind"] == "config_value" for a in config_get_event["assertions"])
