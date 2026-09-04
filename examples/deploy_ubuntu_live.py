"""Live-run script driving `RecordingJuju` against a real LXD juju model.

  * `juju add-model jtr-examples` is assumed to exist already.
  * the test deploys `charm-ubuntu`, waits for active, then reads status.
  * the session log lands at `deploy_ubuntu.jsonl` next to this script.

Run from the repo root:

    uv run --extra dev python deploy_ubuntu_live.py

The script's output is the path of the captured log plus a brief summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jubilant_recorder import gestures
from jubilant_recorder.recording_juju import RecordingJuju

LOG_PATH = Path(__file__).parent / "deploy_ubuntu.jsonl"
MODEL = "jtr-examples"
APP = "ubuntu"


def main() -> int:
    """Run this example session against a live controller."""
    print(f"… recording to {LOG_PATH}", file=sys.stderr)
    with RecordingJuju.start(LOG_PATH, model=MODEL) as juju:
        juju.deploy("ubuntu", app=APP, base="ubuntu@24.04")
        juju.wait(lambda status: jubilant_active(status, APP), timeout=900)
        # Inject an explicit gesture so codegen emits a real assertion
        # instead of the `# TODO: manual step` fallback.
        gestures.assert_status(app=APP, unit=f"{APP}/0", status="active")
        print("  ubuntu deployed + asserted active via gesture", file=sys.stderr)

    # Quick summary so the script doubles as a smoke test.
    # The on-disk format is a single pretty-printed JSON object, not JSONL —
    # see SCHEMA.md's "stable key ordering" note. Don't be fooled by the
    # `.jsonl` filename extension.
    log = json.loads(LOG_PATH.read_text())
    events = log["events"]
    print(f"\n=== recorded {len(events)} events ===")
    for ev in events:
        print(f"  seq={ev['seq']} op={ev['op']} gesture={ev.get('gesture')}")
    return 0


def jubilant_active(status, app: str) -> bool:
    """Return True when every unit of the application is active."""
    a = status.apps.get(app)
    if not a:
        return False
    if a.app_status.current != "active":
        return False
    return all(u.workload_status.current == "active" for u in a.units.values())


if __name__ == "__main__":
    sys.exit(main())
