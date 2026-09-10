"""Assertions the tagger derived from a diagnostic-only event.

`_libjuju*` events are dropped by codegen — they describe the recording,
not a step the user performed. But the tagger reads snapshots, and an
orphan-delta trailer carries the last model state the recording saw, so it
is often exactly where "everything reached active" lands. Dropping the
event took the assertion with it.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap


def _orphan_event(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "seq": 4,
        "op": "_libjuju_orphan_deltas",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {},
        "result": {"orphan_delta_count": 25},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": assertions,
        "gesture": None,
    }


def test_the_event_is_dropped_but_its_assertions_are_not() -> None:
    src = generate(
        _wrap(
            [
                _orphan_event(
                    [
                        {
                            "kind": "unit_status",
                            "app": "ubuntu",
                            "unit": None,
                            "expected": "active",
                            "scope": "all",
                            "strict": False,
                            "source": "delta",
                        }
                    ]
                )
            ]
        )
    )
    assert "_libjuju_orphan_deltas" not in src
    assert "TODO" not in src
    assert "assert _u.workload_status.current == 'active'" in src


def test_a_diagnostic_event_with_no_assertions_leaves_nothing_behind() -> None:
    src = generate(_wrap([_orphan_event([])]))
    assert "_libjuju" not in src
    assert "pass" in src  # nothing else to put in the body
