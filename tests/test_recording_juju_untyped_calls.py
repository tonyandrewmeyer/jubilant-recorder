"""Jubilant methods `RecordingJuju` has no typed override for.

`jubilant.Juju` has some thirty public methods; this class overrides nine.
Every other one went through `_cli()`, had its argv captured, and was then
dropped — so a scripted session that used `ssh`, `exec`, `refresh`, `trust`
or any of the rest produced a test with those steps simply missing.

They are recorded as raw argv now, in the same shape the PATH shim writes,
and go through the same argv translation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import jubilant
import pytest

from jubilant_recorder import RecordingJuju, codegen

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fake_juju(tmp_path: Path) -> str:
    """A stand-in juju binary that prints its argv and succeeds."""
    path = tmp_path / "fake-juju"
    path.write_text('#!/bin/sh\necho "ran: $*"\n')
    path.chmod(0o755)
    return str(path)


def _record(tmp_path: Path, fake_juju: str, body) -> dict:
    log_path = tmp_path / "session.json"
    with RecordingJuju.start(log_path, model="m", cli_binary=fake_juju) as juju:
        body(juju)
    return json.loads(log_path.read_text())


def test_an_untyped_method_is_recorded(tmp_path: Path, fake_juju: str) -> None:
    log = _record(tmp_path, fake_juju, lambda juju: juju.ssh("ubuntu/0", "uptime"))
    (event,) = log["events"]
    assert event["op"] == "shell"
    assert event["args"]["source"] == "jubilant"
    # No `--model`: jubilant injects it inside its own `_cli()`, after the
    # argv this override sees. Nothing to strip, and nothing recorded that
    # would point the generated test at a model it did not create.
    assert event["args"]["argv"] == ["ssh", "ubuntu/0", "uptime"]


def test_it_generates_the_typed_jubilant_call(tmp_path: Path, fake_juju: str) -> None:
    """Through the same argv translation the shim's events use."""
    log = _record(tmp_path, fake_juju, lambda juju: juju.ssh("ubuntu/0", "uptime"))
    src = codegen.generate(log)
    assert "juju.ssh('ubuntu/0', 'uptime')" in src


def test_the_recording_model_never_reaches_the_generated_test(
    tmp_path: Path, fake_juju: str
) -> None:
    log = _record(tmp_path, fake_juju, lambda juju: juju.ssh("ubuntu/0", "uptime"))
    assert "'m'" not in codegen.generate(log)


def test_several_untyped_calls_keep_their_order(tmp_path: Path, fake_juju: str) -> None:
    def body(juju: jubilant.Juju) -> None:
        juju.trust("ubuntu")
        juju.ssh("ubuntu/0", "uptime")
        juju.add_ssh_key("ssh-rsa AAA me@host")

    log = _record(tmp_path, fake_juju, body)
    assert [e["args"]["argv"][0] for e in log["events"]] == ["trust", "ssh", "add-ssh-key"]


def test_a_typed_method_is_not_recorded_twice(tmp_path: Path, fake_juju: str) -> None:
    """The typed emitter claims the argv `_cli()` captured for it."""
    log = _record(tmp_path, fake_juju, lambda juju: juju.remove_application("ubuntu"))
    assert [e["op"] for e in log["events"]] == ["remove_application"]


def test_a_mix_of_typed_and_untyped_calls(tmp_path: Path, fake_juju: str) -> None:
    def body(juju: jubilant.Juju) -> None:
        juju.trust("ubuntu")
        juju.remove_application("ubuntu")
        juju.ssh("ubuntu/0", "uptime")

    log = _record(tmp_path, fake_juju, body)
    assert [e["op"] for e in log["events"]] == ["shell", "remove_application", "shell"]
    src = codegen.generate(log)
    assert (
        src.index("juju.trust(") < src.index("juju.remove_application(") < src.index("juju.ssh(")
    )


def test_a_failing_untyped_call_records_its_exit_code(tmp_path: Path) -> None:
    failing = tmp_path / "failing-juju"
    failing.write_text("#!/bin/sh\nexit 4\n")
    failing.chmod(0o755)

    log_path = tmp_path / "session.json"
    with (
        pytest.raises(jubilant.CLIError),
        RecordingJuju.start(log_path, model="m", cli_binary=str(failing)) as juju,
    ):
        juju.ssh("ubuntu/0", "uptime")

    events = json.loads(log_path.read_text())["events"]
    shell = [e for e in events if e["op"] == "shell"]
    assert shell and shell[0]["result"]["exit_code"] == 4


def test_a_secret_in_an_untyped_call_is_redacted(tmp_path: Path, fake_juju: str) -> None:
    log = _record(
        tmp_path,
        fake_juju,
        lambda juju: juju.ssh("ubuntu/0", "curl", "https://u:pw@example.com/"),
    )
    assert "u:pw@example.com" not in json.dumps(log)


def test_an_untyped_call_before_a_wait_is_not_swallowed(tmp_path: Path) -> None:
    """`wait()` runs its own `_cli()` under suppression.

    So the argv it clears when it emits its typed event is not its own — it
    would be the previous untyped call's, dropped on the floor. Each capture
    is flushed at the start of the next operation instead.
    """
    status_json = json.dumps(
        {
            "model": {
                "name": "m",
                "type": "iaas",
                "controller": "c",
                "cloud": "localhost",
                "version": "3.6.28",
            },
            "machines": {},
            "applications": {},
            "storage": {},
            "controller": {"timestamp": "10:00:00"},
        }
    )
    fake = tmp_path / "fake-juju"
    fake.write_text(f"#!/bin/sh\ncat <<'EOF'\n{status_json}\nEOF\n")
    fake.chmod(0o755)

    log_path = tmp_path / "session.json"
    with RecordingJuju.start(log_path, model="m", cli_binary=str(fake)) as juju:
        juju.trust("ubuntu")
        juju.wait(lambda _s: True, successes=1)

    events = json.loads(log_path.read_text())["events"]
    assert [e["op"] for e in events] == ["shell", "wait_for_idle"]
    assert events[0]["args"]["argv"][0] == "trust"


def test_an_untyped_call_before_a_gesture_is_not_swallowed(tmp_path: Path, fake_juju: str) -> None:
    from jubilant_recorder import checkpoint

    log_path = tmp_path / "session.json"
    with RecordingJuju.start(log_path, model="m", cli_binary=fake_juju) as juju:
        juju.trust("ubuntu")
        checkpoint("trusted")

    events = json.loads(log_path.read_text())["events"]
    assert [e["op"] for e in events] == ["shell", "checkpoint"]
