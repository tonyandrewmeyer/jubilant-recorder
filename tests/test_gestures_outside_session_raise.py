"""Calling any gesture without an active RecordingJuju session raises."""

from __future__ import annotations

import pytest

from jubilant_recorder import assert_action_result, assert_status, checkpoint


def test_checkpoint_outside_session_raises() -> None:
    with pytest.raises(RuntimeError, match="no active recording session"):
        checkpoint("phase")


def test_assert_status_outside_session_raises() -> None:
    with pytest.raises(RuntimeError, match="no active recording session"):
        assert_status("my-charm", "active")


def test_assert_status_no_args_outside_session_raises() -> None:
    with pytest.raises(RuntimeError, match="no active recording session"):
        assert_status()


def test_assert_action_result_outside_session_raises() -> None:
    with pytest.raises(RuntimeError, match="no active recording session"):
        assert_action_result("latest", key="output", value="done")
