from __future__ import annotations

from jubilant_recorder.tagger import tag


def test_relation_exists_tag_fires_on_integrate_with_delta(relation_session):
    result = tag(relation_session)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "relation_exists"]
    assert tags == [
        {
            "kind": "relation_exists",
            "endpoint_a": "my-charm:db",
            "endpoint_b": "postgresql:database",
            "strict": False,
            "source": "delta",
        }
    ]


def test_relation_absent_tag_fires_on_remove_integration(relation_remove_session):
    result = tag(relation_remove_session)
    [event] = result["events"]
    tags = [a for a in event["assertions"] if a["kind"] == "relation_absent"]
    assert tags == [
        {
            "kind": "relation_absent",
            "endpoint_a": "my-charm:db",
            "endpoint_b": "postgresql:database",
            "strict": False,
            "source": "delta",
        }
    ]


def test_relation_tag_does_not_fire_when_no_delta():
    from .conftest import make_event, make_log, make_snapshot, make_unit

    snap = make_snapshot(
        apps={
            "my-charm": {"units": {"my-charm/0": make_unit()}},
            "postgresql": {"units": {"postgresql/0": make_unit()}},
        },
        relations=[{"endpoints": ["my-charm:db", "postgresql:database"]}],
    )
    log = make_log(
        [
            make_event(
                1,
                "integrate",
                args={"app1_endpoint": "my-charm:db", "app2_endpoint": "postgresql:database"},
                before=snap,
                after=snap,
            ),
        ]
    )
    result = tag(log)
    [event] = result["events"]
    assert not any(a["kind"].startswith("relation_") for a in event["assertions"])


def test_relation_tag_does_not_fire_on_non_relation_ops(status_session):
    result = tag(status_session)
    [event] = result["events"]
    assert not any(a["kind"].startswith("relation_") for a in event["assertions"])
