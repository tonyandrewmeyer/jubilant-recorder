"""Record Juju sessions and generate jubilant integration tests."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from jubilant_recorder.gestures import assert_action_result, assert_status, checkpoint
from jubilant_recorder.recording_juju import RecordingJuju
from jubilant_recorder.session_log import SessionLog

try:
    __version__ = version("jubilant-recorder")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0.0.0+unknown"

__all__ = [
    "RecordingJuju",
    "SessionLog",
    "__version__",
    "assert_action_result",
    "assert_status",
    "checkpoint",
]
