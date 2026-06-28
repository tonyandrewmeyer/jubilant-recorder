from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import UTC, datetime

REAL_JUJU = "__REAL_JUJU__"


def _now_ts() -> str:
    dt = datetime.now(UTC)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def main() -> None:
    try:
        real_juju = os.environ.get("_JTR_REAL_JUJU", REAL_JUJU)

        session_id = os.environ.get("JTR_SESSION")
        if not session_id:
            os.execv(real_juju, [real_juju] + sys.argv[1:])
            return

        if os.environ.get("JTR_PAUSED") == "1":
            os.execv(real_juju, [real_juju] + sys.argv[1:])
            return

        if os.environ.get("JTR_PYTHON_ACTIVE"):
            op = "shell_context"
        else:
            op = "shell"

        ts = _now_ts()
        argv = sys.argv[1:]
        basename = os.path.basename(sys.argv[0])

        if op == "shell":
            event = {
                "seq": None,  # filled in below
                "op": "shell",
                "ts": ts,
                "args": {
                    "argv": argv,
                    "basename": basename,
                    "source": "shim",
                    "session_id": session_id,
                },
                "result": {"captured": False, "exit_code": None},
                "model_snapshot_before": None,
                "model_snapshot_after": None,
                "assertions": [],
                "gesture": None,
            }
        else:
            event = {
                "seq": None,  # filled in below
                "op": "shell_context",
                "ts": ts,
                "args": {
                    "argv": argv,
                    "basename": basename,
                    "source": "shim",
                    "session_id": session_id,
                },
                "result": {
                    "exit_code": None,
                    "stdout": None,
                    "stderr": None,
                    "stdout_truncated": False,
                },
                "model_snapshot_before": None,
                "model_snapshot_after": None,
                "assertions": [],
                "gesture": None,
            }

        log_path = os.environ.get("JTR_LOG")
        if log_path:
            try:
                with open(log_path, "a+") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    try:
                        f.seek(0)
                        content = f.read()
                        count = sum(1 for line in content.splitlines() if line.strip())
                        seq = count + 1
                        event["seq"] = seq
                        f.seek(0, 2)  # seek to end
                        f.write(json.dumps(event) + "\n")
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass

    except Exception:
        pass

    real_juju = os.environ.get("_JTR_REAL_JUJU", REAL_JUJU)
    os.execv(real_juju, [real_juju] + sys.argv[1:])


if __name__ == "__main__":
    main()
