"""What a person writes to record a session.

Ordinary jubilant, with four extra calls: RecordingJuju.start, and the
three gestures that say what the generated test should assert.
"""

from jubilant_recorder import RecordingJuju, assert_status, checkpoint

with RecordingJuju.start("session.json", model="jtr-demo") as juju:
    juju.deploy("ubuntu", channel="stable")
    juju.wait(lambda s: s.apps["ubuntu"].is_active, timeout=900)
    assert_status("ubuntu", "active")
    checkpoint("deployed")

    juju.config("ubuntu", {"hostname": "demo-host"})
    juju.wait(lambda s: s.apps["ubuntu"].is_active, timeout=300)
    assert_status("ubuntu", "active")
    checkpoint("reconfigured")
