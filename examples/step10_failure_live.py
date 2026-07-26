"""the plan step 10 — deliberate-failure live session.

The real-world k8s session (`step9_real_world_k8s.jsonl`) accidentally
exercised step-10's `wait_for_idle` failure path because containerd
was corrupt. This script exercises step-10's other failure paths
deliberately and against a fresh model:

  * juju.deploy with a charm name that does not exist on Charmhub
    (jubilant raises CLIError — the recorder captures result.error
    + snap_after=None and re-raises).
  * juju.integrate two apps that share no compatible interface
    (same CLIError shape).
  * One assert_status gesture after the surviving deploy so codegen
    has at least one explicit assertion in the mix.

The codegen output should produce `pytest.skip(...)` blocks for the
two failure events with TODO comments for the human to repair. The
surviving deploy + assertion should remain as real test steps.

Run from the repo root:

    uv run --with jubilant python step10_failure_live.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jubilant

from jubilant_recorder import gestures
from jubilant_recorder.recording_juju import RecordingJuju

LOG_PATH = Path(__file__).parent / "step10_failure.jsonl"
MODEL = "jtr-step3"


def main() -> int:
    """Run this example session against a live controller."""
    print(f"… recording to {LOG_PATH}", file=sys.stderr)
    with RecordingJuju.start(LOG_PATH, model=MODEL) as juju:
        # Successful deploy first so we have a working baseline.
        juju.deploy("ubuntu", app="ubuntu", base="ubuntu@24.04")
        juju.wait(
            lambda s: all_units_active(s, "ubuntu"),
            timeout=300,
        )
        gestures.assert_status(app="ubuntu", unit="ubuntu/0", status="active")
        print("  ubuntu active + gesture injected", file=sys.stderr)

        # Failure 1: deploy a charm that does not exist on Charmhub.
        try:
            juju.deploy("totally-nonexistent-charm-zzz", channel="latest/edge")
        except jubilant.CLIError as exc:
            print(f"  expected failure 1 (nonexistent charm): {str(exc)[:80]}", file=sys.stderr)

        # Failure 2: integrate two apps with no compatible interface.
        # `ubuntu` has no required interfaces; integrating with itself fails.
        try:
            juju.integrate("ubuntu", "ubuntu")
        except jubilant.CLIError as exc:
            print(f"  expected failure 2 (no compatible iface): {str(exc)[:80]}", file=sys.stderr)

    log = json.loads(LOG_PATH.read_text())
    print(f"\n=== {len(log['events'])} events recorded ===")
    for ev in log["events"]:
        has_error = bool((ev.get("result") or {}).get("error"))
        g = (ev.get("gesture") or {}).get("kind")
        marker = "ERR" if has_error else ""
        print(f"  seq={ev['seq']} op={ev['op']:<15s} gesture={g} {marker}")
    return 0


def all_units_active(status, app: str) -> bool:
    """Return True when every unit of the application is active."""
    a = status.apps.get(app)
    if not a:
        return False
    if a.app_status.current != "active":
        return False
    units = a.units or {}
    if not units:
        return False
    return all(u.workload_status.current == "active" for u in units.values())


if __name__ == "__main__":
    sys.exit(main())
