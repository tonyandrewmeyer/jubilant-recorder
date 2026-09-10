"""jtr PATH shim for juju.

Intercepts juju invocations when a jtr shell-hook session is active.
When $JTR_SESSION is unset the shim is a zero-overhead pass-through.

REAL_JUJU is hardcoded at shim install time by `jtr shim install`.
For testing, set _JTR_REAL_JUJU env var to override.

What the shim records
---------------------
The argv, the exit code, and — for the read-only subcommands in
`_CAPTURE_STDOUT` — the command's standard output. Everything else is
forwarded untouched: the child inherits this process's stdin, stdout and
stderr, so an interactive `juju ssh` or a progress-printing `juju deploy`
behaves exactly as it does without the shim.

`juju status` gets one extra thing. The operator typing `juju status` is
asking "what does the model look like now?", and that answer is what the
generated test should assert. So after forwarding the command (uncaptured,
so the operator's own terminal keeps its colour and layout), the shim runs
`juju status --format=json` a second time and stores the raw JSON in
`result.status_json`. `jubilant_recorder.shim_snapshots` turns that into
the same `model_snapshot_after` shape `RecordingJuju` records, which is
what lets the tagger derive assertions from a shell session at all. The
cost is one extra status call per recorded `juju status`; set
`JTR_NO_SNAPSHOT=1` to skip it.

Why the exit code matters: codegen turns every recorded `juju` command
into a jubilant call. A command that *failed* during recording must not
become a line that silently claims to have worked, so `jtr generate`
comments those out. That is only possible if the shim waits for the child
and reports its status, which is why this runs a subprocess rather than
`execv`-ing when a session is active. With no session it still `execv`s
and costs nothing.

Redaction
---------
Command lines are recorded verbatim apart from redaction, and `juju
add-secret my-secret token=hunter2` puts a live credential on the command
line. `_redact_argv` applies the same rules as the rest of the recorder,
plus any per-session patterns registered with `jtr redact`. The shared
implementation is imported when it is importable and mirrored inline when
it is not: the shim runs under whatever interpreter installed it and is
deliberately import-light, so it must still redact if `jubilant_recorder`
is not on that interpreter's path.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime

# Replaced with the absolute path to the real juju binary at install time.
# Override with _JTR_REAL_JUJU env var for testing.
REAL_JUJU = "__REAL_JUJU__"

# Read-only subcommands whose stdout is worth keeping: it is what the
# operator was *looking at* when they decided the next step, so it belongs
# in the session log as context. Excluded are anything that streams
# (`debug-log` without `--no-tail`), anything interactive (`ssh`, `scp`,
# `exec`), and anything long-running (`wait-for`) — capturing those would
# hold the output back until the command finished, changing what the
# operator sees at their own terminal.
_CAPTURE_STDOUT = frozenset(
    {
        "config",
        "constraints",
        "machines",
        "model-config",
        "model-constraints",
        "models",
        "offers",
        "secrets",
        "show-application",
        "show-machine",
        "show-model",
        "show-offer",
        "show-secret",
        "show-unit",
        "status",
        "storage",
        "version",
        "whoami",
    }
)
# `status` is captured through `_status_snapshot` instead, so that the
# operator's own view keeps whatever format and colour they asked for.
_CAPTURE_STDOUT = _CAPTURE_STDOUT - {"status"}
_MAX_STDOUT_BYTES = 64 * 1024

# Fallback mirror of `jubilant_recorder.redaction`, used only when that
# module is not importable under the shim's interpreter. Deliberately the
# same shapes, not a superset: a divergence here would mean the redaction a
# user sees depends on how they installed jtr.
_FALLBACK_RULES = [
    (re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE), "bearer"),
    (re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"), "url-credentials"),
    (re.compile(r"(?i)password=[^&\s]+"), "password"),
    (re.compile(r"(?i)token=[^&\s]+"), "token"),
]
_SENSITIVE_KEY = re.compile(r"(?i)(password|token|secret|key|credential|cert)")


def _now_ts() -> str:
    dt = datetime.now(UTC)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def _redact_string(value: str) -> str:
    try:
        from jubilant_recorder.redaction import redact_string

        return redact_string(value)[0]
    except Exception:
        for pattern, label in _FALLBACK_RULES:
            value = pattern.sub(f"<redacted:{label}>", value)
        return value


def _session_redact_patterns(session_id: str) -> list[str]:
    """Read the patterns registered for this session with `jtr redact`."""
    try:
        cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        with open(os.path.join(cache, "jtr", f"{session_id}.json")) as f:
            state = json.load(f)
        return list((state.get("overrides") or {}).get("redact") or [])
    except Exception:
        return []


def _redact_argv(argv: list[str], extra_patterns: list[str]) -> list[str]:
    """Redact credentials from a recorded juju argv.

    Handles the three shapes that put a secret on a juju command line: a
    `key=value` token whose key names a credential (`juju add-secret …
    token=hunter2`), a value the shared rules recognise on its own (a URL
    with embedded credentials), and whatever the user asked for with
    `jtr redact`.
    """
    out: list[str] = []
    for token in argv:
        redacted = token
        key, sep, _ = token.partition("=")
        if sep:
            match = _SENSITIVE_KEY.search(key.lstrip("-"))
            if match:
                redacted = f"{key}=<redacted:{match.group(1).lower()}>"
        if redacted == token:
            redacted = _redact_string(token)
        for pattern in extra_patterns:
            try:
                redacted = re.sub(pattern, "<redacted>", redacted)
            except Exception:
                continue
        out.append(redacted)
    return out


def _append_event(log_path: str, event: dict) -> None:
    with open(log_path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            event["seq"] = sum(1 for line in content.splitlines() if line.strip()) + 1
            f.seek(0, 2)
            f.write(json.dumps(event) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _should_capture_stdout(argv: list[str]) -> bool:
    return bool(argv) and argv[0] in _CAPTURE_STDOUT


def _model_flag(argv: list[str]) -> list[str]:
    """Return the ``-m``/``--model`` pair from *argv*, if it has one."""
    for i, tok in enumerate(argv):
        if tok in ("-m", "--model") and i + 1 < len(argv):
            return ["--model", argv[i + 1]]
        if tok.startswith("--model="):
            return [tok]
    return []


def _status_snapshot(real_juju: str, argv: list[str]) -> str | None:
    """Capture ``juju status --format=json`` alongside a recorded status.

    Returns None — never raises, and never blocks for long — if anything
    goes wrong: a missing snapshot costs the generated test some
    assertions, whereas a shim that fails here would cost the operator
    their `juju status`.
    """
    if not argv or argv[0] != "status" or os.environ.get("JTR_NO_SNAPSHOT") == "1":
        return None
    # `--watch` never returns; there is no single moment to snapshot.
    if any(a.startswith("--watch") for a in argv):
        return None
    try:
        completed = subprocess.run(
            [real_juju, "status", "--format", "json", *_model_flag(argv)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or None


def main() -> None:
    """Forward a shimmed ``juju`` invocation and record it."""
    real_juju = os.environ.get("_JTR_REAL_JUJU", REAL_JUJU)
    argv = sys.argv[1:]

    session_id = os.environ.get("JTR_SESSION")
    if not session_id or os.environ.get("JTR_PAUSED") == "1":
        os.execv(real_juju, [real_juju, *argv])
        return

    ts = _now_ts()
    op = "shell_context" if os.environ.get("JTR_PYTHON_ACTIVE") else "shell"
    capture = _should_capture_stdout(argv)

    stdout_text: str | None = None
    status_json: str | None = None
    truncated = False
    try:
        if capture:
            completed = subprocess.run(
                [real_juju, *argv], capture_output=True, text=True, check=False
            )
            exit_code = completed.returncode
            sys.stdout.write(completed.stdout)
            sys.stdout.flush()
            sys.stderr.write(completed.stderr)
            sys.stderr.flush()
            stdout_text = completed.stdout
            if len(stdout_text) > _MAX_STDOUT_BYTES:
                stdout_text = stdout_text[:_MAX_STDOUT_BYTES]
                truncated = True
        else:
            exit_code = subprocess.run([real_juju, *argv], check=False).returncode
            if exit_code == 0:
                status_json = _status_snapshot(real_juju, argv)
    except KeyboardInterrupt:
        exit_code = 130
    except Exception:
        # The shim must never be the reason a juju command does not run.
        os.execv(real_juju, [real_juju, *argv])
        return

    try:
        log_path = os.environ.get("JTR_LOG")
        if log_path:
            patterns = _session_redact_patterns(session_id)
            event = {
                "seq": None,  # filled in by _append_event under the lock
                "op": op,
                "ts": ts,
                "args": {
                    "argv": _redact_argv(argv, patterns),
                    "basename": "juju",
                    "source": "shim",
                    "session_id": session_id,
                },
                "result": {
                    "captured": capture,
                    "exit_code": exit_code,
                    "stdout": _redact_string(stdout_text) if stdout_text else None,
                    "stderr": None,
                    "stdout_truncated": truncated,
                    "status_json": status_json,
                },
                "model_snapshot_before": None,
                "model_snapshot_after": None,
                "assertions": [],
                "gesture": None,
            }
            _append_event(log_path, event)
    except Exception:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
