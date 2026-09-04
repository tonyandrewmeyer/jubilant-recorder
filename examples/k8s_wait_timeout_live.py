"""Real-world charm-tech scenario for the recorder.

Drives RecordingJuju against the `control` model on hcts-control's
Canonical Kubernetes (juju 3.6.23 controller; jubilant 1.10.0). Adds
a `data-integrator` consumer to the already-running postgresql-k8s
and exercises the get-credentials action — the kind of session a
charm-tech author writes a regression test for after wiring a new
client.

  juju.deploy("data-integrator", channel="latest/edge",
              config={"database-name": "real_world_demo"})
  juju.integrate("postgresql-k8s", "data-integrator")
  juju.wait(all_active, timeout=900)
  juju.run("data-integrator/0", "get-credentials")
  gestures…

Run from the repo root on hcts-control:

    uv run --with jubilant python k8s_wait_timeout_live.py

Captures a log next to this file; the matching fixture lands at
`tests/fixtures/k8s_wait_timeout.jsonl`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jubilant_recorder import gestures
from jubilant_recorder.recording_juju import RecordingJuju

LOG_PATH = Path(__file__).parent / "k8s_wait_timeout.jsonl"
MODEL = "control"
DB_APP = "postgresql-k8s"
CLIENT_APP = "data-integrator"


def main() -> int:
    """Run this example session against a live controller."""
    print(f"… recording to {LOG_PATH}", file=sys.stderr)
    with RecordingJuju.start(LOG_PATH, model=MODEL) as juju:
        juju.deploy(
            CLIENT_APP,
            channel="latest/edge",
            config={"database-name": "real_world_demo"},
            trust=True,
        )
        juju.integrate(DB_APP, CLIENT_APP)
        juju.wait(
            lambda s: all_units_active(s, CLIENT_APP),
            timeout=900,
        )
        print("  data-integrator settled", file=sys.stderr)

        result = juju.run(f"{CLIENT_APP}/0", "get-credentials")
        print(f"  action result: success={result.success}", file=sys.stderr)
        if result.success and "postgresql" in (result.results or {}):
            pg = result.results["postgresql"]
            print(
                f"  endpoints exposed: {list(pg.keys()) if isinstance(pg, dict) else pg}",
                file=sys.stderr,
            )

        gestures.assert_status(app=CLIENT_APP, unit=f"{CLIENT_APP}/0", status="active")
        gestures.assert_action_result("get-credentials", key="ok", value="True")
        print("  gestures injected", file=sys.stderr)

    log = json.loads(LOG_PATH.read_text())
    print(f"\n=== {len(log['events'])} events recorded ===")
    for ev in log["events"]:
        g = (ev.get("gesture") or {}).get("kind")
        print(f"  seq={ev['seq']} op={ev['op']:<15s} gesture={g}")
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
