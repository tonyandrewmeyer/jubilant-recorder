"""The `assert_config` gesture.

`docs/schema.md` has documented this gesture, its tag shape and its codegen
path since the schema was written; the only missing piece was the function
a user calls. These check the whole round trip, because the tag and the
emitter were the parts that already worked.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from jubilant_recorder import RecordingJuju, assert_config, codegen

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def recorded(tmp_path: Path):
    """A session with one `assert_config`, and nothing else."""
    log_path = tmp_path / "session.json"
    with (
        patch.object(RecordingJuju, "_take_snapshot", return_value=None),
        RecordingJuju.start(log_path, model="m"),
    ):
        assert_config("my-charm", key="log-level", value="debug")
    import json

    return json.loads(log_path.read_text())


def test_the_event_carries_a_config_value_gesture(recorded) -> None:
    (event,) = recorded["events"]
    assert event["op"] == "config_get"
    assert event["gesture"]["kind"] == "assert_config"
    assert event["gesture"]["params"] == {"app": "my-charm", "key": "log-level", "value": "debug"}


def test_it_generates_a_read_and_an_assertion(recorded) -> None:
    src = codegen.generate(recorded)
    ast.parse(src)
    assert "config_1 = juju.config('my-charm')" in src
    assert "assert config_1['log-level'] == 'debug'" in src


def test_calling_it_outside_a_session_raises() -> None:
    with pytest.raises(RuntimeError):
        assert_config("my-charm", key="log-level", value="debug")
