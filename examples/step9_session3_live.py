"""Live session (session 3): deploy + integrate + action + config.

The fullest live session in this set. Drives RecordingJuju against an
LXD model and covers every op the assertion tagger + codegen pipeline
knows about:

    deploy(postgresql)
    deploy(data-integrator, config={database-name=...})
    integrate(postgresql, data-integrator)
    wait(all_active)
    config(data-integrator, extra-user-roles=...)   # config change
    wait(all_active)                                  # settle
    run(data-integrator/0, get-credentials)           # action
    gestures.assert_*                                 # explicit checkpoints

Run from the repo root:

    uv run --with jubilant python step9_session3_live.py

Captures a log next to this file; the matching fixture commits as
`tests/fixtures/step9_session3_postgres_data_integrator_full.jsonl`.

Cold-start budget for postgresql + data-integrator is ~17 minutes from
fresh LXD containers; bumped wait timeout to 1800 s accordingly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jubilant_recorder import gestures
from jubilant_recorder.recording_juju import RecordingJuju

LOG_PATH = Path(__file__).parent / "step9_session3.jsonl"
MODEL = "jtr-step3"
DB_APP = "postgresql"
CLIENT_APP = "data-integrator"


def main() -> int:
    """Run this example session against a live controller."""
    print(f"… recording to {LOG_PATH}", file=sys.stderr)
    with RecordingJuju.start(LOG_PATH, model=MODEL) as juju:
        juju.deploy(DB_APP, channel="14/stable")
        juju.deploy(
            CLIENT_APP,
            channel="latest/stable",
            config={"database-name": "step9_session3_db"},
        )
        juju.integrate(DB_APP, CLIENT_APP)
        juju.wait(
            lambda s: all_units_active(s, DB_APP) and all_units_active(s, CLIENT_APP),
            timeout=1800,
        )
        print("  initial deploys + integrate settled", file=sys.stderr)

        juju.config(CLIENT_APP, {"extra-user-roles": "SELECT"})
        juju.wait(
            lambda s: all_units_active(s, DB_APP) and all_units_active(s, CLIENT_APP),
            timeout=600,
        )
        print("  config change settled", file=sys.stderr)

        result = juju.run(f"{CLIENT_APP}/0", "get-credentials")
        print(f"  action result: success={result.success}", file=sys.stderr)

        gestures.assert_status(app=DB_APP, unit=f"{DB_APP}/0", status="active")
        gestures.assert_status(app=CLIENT_APP, unit=f"{CLIENT_APP}/0", status="active")
        # Gesture API: action_id is a label, key/value are the expected
        # result-field assertion. The gesture finds the most-recent run
        # event and attaches the assertion to it.
        gestures.assert_action_result("get-credentials", key="ok", value="True")
        print("  gestures injected", file=sys.stderr)

    log = json.loads(LOG_PATH.read_text())
    print(f"\n=== {len(log['events'])} events recorded ===")
    for ev in log["events"]:
        gesture_kind = (ev.get("gesture") or {}).get("kind")
        print(f"  seq={ev['seq']} op={ev['op']:<15s} gesture={gesture_kind}")
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
