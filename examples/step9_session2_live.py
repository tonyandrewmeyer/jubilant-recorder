"""the plan step 9 — session 2: deploy + integrate.

Two-charm session for the recorder. Drives RecordingJuju against the
same LXD model as step 3, but with a *related* second app (the `nrpe`
subordinate, which attaches to `ubuntu:juju-info`).

  juju.deploy("ubuntu", app="ubuntu", base="ubuntu@24.04")
  juju.deploy("nrpe",   app="nrpe")
  juju.integrate("ubuntu:juju-info", "nrpe:general-info")
  juju.wait(all_active, timeout=600)
  recorder.assert_status("ubuntu", "active", unit="ubuntu/0")
  recorder.assert_status("nrpe",   "active")  # all units; nrpe is subordinate

Run from the repo root:

    uv run --with jubilant python step9_session2_live.py

Captures a log next to this file; STEP9.md or a future step-9 writeup
will commit it as a fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jubilant_recorder import gestures
from jubilant_recorder.recording_juju import RecordingJuju

LOG_PATH = Path(__file__).parent / "step9_session2.jsonl"
MODEL = "jtr-step3"
DB_APP = "postgresql"
CLIENT_APP = "data-integrator"


def main() -> int:
    print(f"… recording to {LOG_PATH}", file=sys.stderr)
    with RecordingJuju.start(LOG_PATH, model=MODEL) as juju:
        juju.deploy(DB_APP, channel="14/stable")
        juju.deploy(
            CLIENT_APP,
            channel="latest/stable",
            config={"database-name": "step9_session2_db"},
        )
        juju.integrate(DB_APP, CLIENT_APP)
        juju.wait(
            lambda s: all_units_active(s, DB_APP) and all_units_active(s, CLIENT_APP),
            timeout=900,
        )
        gestures.assert_status(app=DB_APP, unit=f"{DB_APP}/0", status="active")
        gestures.assert_status(app=CLIENT_APP, unit=f"{CLIENT_APP}/0", status="active")
        print("  both apps active, gestures injected", file=sys.stderr)

    log = json.loads(LOG_PATH.read_text())
    print(f"\n=== {len(log['events'])} events recorded ===")
    for ev in log["events"]:
        print(f"  seq={ev['seq']} op={ev['op']} gesture={(ev.get('gesture') or {}).get('kind')}")
    return 0


def all_units_active(status, app: str) -> bool:
    a = status.apps.get(app)
    if not a:
        return False
    if a.app_status.current != "active":
        return False
    units = a.units or {}
    if not units:
        # Subordinates attach to principals — wait for at least one to exist.
        return False
    return all(u.workload_status.current == "active" for u in units.values())


if __name__ == "__main__":
    sys.exit(main())
