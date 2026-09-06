"""The ``jtr`` command-line interface."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from jubilant_recorder import codegen
from jubilant_recorder.shim import juju_shim

_SHELL_INIT_BEGIN_MARKER = "# BEGIN jtr shell-init"
_SHELL_INIT_END_MARKER = "# END jtr shell-init"


def _now_ts() -> str:
    dt = datetime.now(UTC)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jtr"


def _state_file(session_id: str) -> Path:
    return _cache_dir() / f"{session_id}.json"


def _append_jsonl_event(path: Path | str, event_data: dict) -> None:
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            count = sum(1 for line in content.splitlines() if line.strip())
            event_data["seq"] = count + 1
            f.seek(0, 2)
            f.write(json.dumps(event_data) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


_BASENAME_DENYLIST = frozenset(
    {
        "juju",
        "ls",
        "cd",
        "pwd",
        "cat",
        "less",
        "more",
        "bat",
        "vim",
        "nvim",
        "nano",
        "emacs",
        "code",
        "clear",
        "reset",
        "history",
        "jtr",
        "sudo",
        "pass",
        "vault",
        "gpg",
        "ssh-keygen",
    }
)
_ARGV_DENYPATS = [
    re.compile(r"^kubectl\s+(create|get|describe)\s+secret\b"),
    re.compile(r"^juju\s+(add|update|remove|show|grant|revoke)-secret\b"),
    re.compile(r"^openssl\s+(genrsa|passwd|pkcs8)\b"),
    re.compile(r"^gh\s+auth\b"),
]
_CONTEXT_ALLOWLIST = frozenset(
    {
        "kubectl",
        "k8s",
        "microk8s",
        "lxc",
        "lxd",
        "charmcraft",
        "rockcraft",
        "snapcraft",
        "curl",
        "http",
        "wget",
        "jq",
        "yq",
        "helm",
        "terraform",
    }
)


def _render_shell_init(shell: str, no_path_shim: bool) -> str:
    header = (
        "# jtr shell-init output\n# bash-preexec must be sourced BEFORE this block"
        if shell == "bash"
        else "# jtr shell-init output"
    )
    core = """preexec() {
    [[ -z "${JTR_SESSION:-}" ]] && return
    [[ "${JTR_PAUSED:-}" == "1" ]] && return
    _JTR_PREEXEC_CMD="$1"
    _JTR_PREEXEC_TS="$(date -u +%s%3N)"
}

precmd() {
    local _exit=$?
    [[ -z "${JTR_SESSION:-}" ]] && return
    [[ -z "${_JTR_PREEXEC_CMD:-}" ]] && return
    command jtr _hook_event \\
        --session "$JTR_SESSION" \\
        --cmd "$_JTR_PREEXEC_CMD" \\
        --exit "$_exit" \\
        --start-ms "$_JTR_PREEXEC_TS" \\
        --log "$JTR_LOG"
    _JTR_PREEXEC_CMD=""
    _JTR_PREEXEC_TS=""
}

# shell function to eval env-var changes
jtr() {
    case "$1" in
        start|stop|pause|resume|attach)
            eval "$(command jtr "$@")" ;;
        *)
            command jtr "$@" ;;
    esac
}"""
    # bash-preexec iterates preexec_functions / precmd_functions arrays and
    # ignores bare functions named preexec/precmd (unlike zsh). Without this
    # registration, sourcing the snippet in bash records zero shell events.
    bash_footer = "\npreexec_functions+=(preexec)\nprecmd_functions+=(precmd)"
    snippet = f"{header}\n{core}"
    if shell == "bash":
        snippet += bash_footer
    if not no_path_shim:
        snippet += '\n\n# Add jtr shim directory to PATH\nexport PATH="$HOME/.local/share/jtr/shims:$PATH"'
    return snippet


def _resolve_shell(shell: str | None) -> str:
    if not shell:
        shell_env = os.environ.get("SHELL", "")
        shell = os.path.basename(shell_env) if shell_env else ""
    return shell


def cmd_shell_init(args: argparse.Namespace) -> int:
    """Print the shell snippet that wires up jtr."""
    shell = _resolve_shell(getattr(args, "shell", None))
    if shell == "fish":
        print("jtr: fish not yet supported", file=sys.stderr)
        return 1
    if not shell or shell not in ("bash", "zsh"):
        print(f"jtr: cannot detect shell or unsupported shell: {shell!r}", file=sys.stderr)
        return 1
    no_path_shim = getattr(args, "no_path_shim", False)
    print(_render_shell_init(shell, no_path_shim))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Start a recording session."""
    if os.environ.get("JTR_SESSION"):
        print("jtr: session already active.", file=sys.stderr)
        return 1
    session_id = str(uuid.uuid4())
    name = getattr(args, "name", None)
    if not name:
        name = f"jtr-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
    output = getattr(args, "output", None)
    if output:
        log_path = Path(output)
    else:
        log_path = _cache_dir() / "sessions" / f"{name}-{session_id[:8]}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()
    shared = getattr(args, "shared", False)
    state = {
        "session_id": session_id,
        "session_name": name,
        "log_path": str(log_path),
        "started_at": _now_ts(),
        "shared": shared,
        "overrides": {"include": [], "exclude": [], "redact": []},
    }
    state_file = _state_file(session_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))
    if shared:
        (_cache_dir() / "current").write_text(session_id)
    print(f"export JTR_SESSION={session_id}\nexport JTR_LOG={log_path}\nexport JTR_PAUSED=")
    print(f"jtr: session '{name}' started. Log: {log_path}", file=sys.stderr)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop the active session."""
    session_id = os.environ.get("JTR_SESSION")
    if not session_id:
        print("jtr: no active session.", file=sys.stderr)
        print("", end="")  # no stdout output
        return 0
    state: dict | None = None
    state_file = _state_file(session_id)
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except Exception:
            state = None
    if state:
        log_path = state.get("log_path")
        if log_path:
            try:
                event = {
                    "seq": None,
                    "op": "session_end",
                    "ts": _now_ts(),
                    "args": {},
                    "result": {},
                    "model_snapshot_before": None,
                    "model_snapshot_after": None,
                    "assertions": [],
                    "gesture": None,
                }
                _append_jsonl_event(log_path, event)
            except Exception:
                pass
        with contextlib.suppress(Exception):
            state_file.unlink()
        if state.get("shared"):
            with contextlib.suppress(Exception):
                (_cache_dir() / "current").unlink(missing_ok=True)
    print("unset JTR_SESSION\nunset JTR_LOG\nunset JTR_PAUSED")
    auto = getattr(args, "auto", False)
    if not auto and state:
        name = state.get("session_name", session_id)
        print(f"jtr: session '{name}' stopped.", file=sys.stderr)
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    """Pause recording without ending the session."""
    if not os.environ.get("JTR_SESSION"):
        return 0
    print("export JTR_PAUSED=1")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a paused session."""
    if not os.environ.get("JTR_SESSION"):
        return 0
    print("export JTR_PAUSED=")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print the current session's status."""
    as_json = getattr(args, "json", False)
    session_id = os.environ.get("JTR_SESSION")
    log_path = os.environ.get("JTR_LOG")
    paused = os.environ.get("JTR_PAUSED") == "1"
    if not session_id:
        if as_json:
            print(json.dumps({"active": False}))
        else:
            print("jtr: no active session.")
        return 0
    state: dict | None = None
    state_file = _state_file(session_id)
    if state_file.exists():
        with contextlib.suppress(Exception):
            state = json.loads(state_file.read_text())
    event_count = 0
    if log_path and Path(log_path).exists():
        try:
            lines = Path(log_path).read_text().splitlines()
            event_count = sum(1 for line in lines if line.strip())
        except Exception:
            pass
    name = (state or {}).get("session_name", session_id)
    if as_json:
        print(
            json.dumps(
                {
                    "active": True,
                    "session_id": session_id,
                    "session_name": name,
                    "log_path": log_path,
                    "paused": paused,
                    "event_count": event_count,
                }
            )
        )
    else:
        print(f"jtr: session '{name}' active. Log: {log_path}. Events: {event_count}.")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    """Follow the active session's events."""
    session_id = os.environ.get("JTR_SESSION")
    log_path = os.environ.get("JTR_LOG")
    if not session_id or not log_path:
        print("jtr: no active session.")
        return 1
    as_json = getattr(args, "json", False)
    seen = 0
    try:
        while True:
            try:
                lines = Path(log_path).read_text().splitlines()
            except Exception:
                time.sleep(0.1)
                continue
            non_empty = [line for line in lines if line.strip()]
            for line in non_empty[seen:]:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if as_json:
                    print(json.dumps(event))
                else:
                    op = event.get("op", "?")
                    seq = event.get("seq", "?")
                    args_str = str(event.get("args", {}))[:60]
                    print(f"[{seq}] {op}: {args_str}")
                if event.get("op") == "session_end":
                    return 0
            seen = len(non_empty)
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 0


def cmd_note(args: argparse.Namespace) -> int:
    """Attach a free-text note to the session."""
    session_id = os.environ.get("JTR_SESSION")
    log_path = os.environ.get("JTR_LOG")
    if not session_id or not log_path:
        print("jtr: no active session.", file=sys.stderr)
        return 1
    text = args.text
    if len(text) > 500:
        text = text[:499] + "…"
    event = {
        "seq": None,
        "op": "note",
        "ts": _now_ts(),
        "args": {"text": text},
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }
    _append_jsonl_event(log_path, event)
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    """Attach an assertion tag to the last event."""
    session_id = os.environ.get("JTR_SESSION")
    log_path = os.environ.get("JTR_LOG")
    if not session_id or not log_path:
        print("jtr: no active session.", file=sys.stderr)
        return 1
    label = args.label
    if not re.match(r"^[a-zA-Z0-9 ]+$", label) or not (1 <= len(label) <= 80):
        print(f"jtr: invalid tag label: {label!r}", file=sys.stderr)
        return 1
    event = {
        "seq": None,
        "op": "tag",
        "ts": _now_ts(),
        "args": {"label": label},
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }
    _append_jsonl_event(log_path, event)
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    """Attach a file to the session."""
    session_id = getattr(args, "session_id", None)
    if not session_id:
        current_file = _cache_dir() / "current"
        if not current_file.exists():
            print("jtr: no shared session found.", file=sys.stderr)
            return 1
        session_id = current_file.read_text().strip()
    state_file = _state_file(session_id)
    if not state_file.exists():
        print(f"jtr: no state file for session {session_id}", file=sys.stderr)
        return 1
    state = json.loads(state_file.read_text())
    log_path = state.get("log_path", "")
    print(f"export JTR_SESSION={session_id}\nexport JTR_LOG={log_path}")
    return 0


def cmd_include(args: argparse.Namespace) -> int:
    """Include matching events in generation."""
    return _cmd_override(args, "include")


def cmd_exclude(args: argparse.Namespace) -> int:
    """Exclude matching events from generation."""
    return _cmd_override(args, "exclude")


def cmd_redact(args: argparse.Namespace) -> int:
    """Redact matching values from the log."""
    return _cmd_override(args, "redact")


def _cmd_override(args: argparse.Namespace, kind: str) -> int:
    session_id = os.environ.get("JTR_SESSION")
    log_path = os.environ.get("JTR_LOG")
    if not session_id:
        print("jtr: no active session.", file=sys.stderr)
        return 1
    pattern = args.pattern
    state_file = _state_file(session_id)
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            state.setdefault("overrides", {"include": [], "exclude": [], "redact": []})
            state["overrides"].setdefault(kind, [])
            state["overrides"][kind].append(pattern)
            state_file.write_text(json.dumps(state))
        except Exception:
            pass
    if log_path:
        event = {
            "seq": None,
            "op": "config_override",
            "ts": _now_ts(),
            "args": {"kind": kind, "pattern": pattern},
            "result": {},
            "model_snapshot_before": None,
            "model_snapshot_after": None,
            "assertions": [],
            "gesture": None,
        }
        _append_jsonl_event(log_path, event)
    return 0


def _hook_event_impl(
    session_id: str,
    cmd: str,
    exit_code: int,
    start_ms: int,
    log_path: str,
) -> None:
    """Core logic for _hook_event; always exits 0, never raises."""
    try:
        if os.environ.get("JTR_PAUSED") == "1":
            return

        # Extract basename from cmd
        # Split on shell operators to get first command
        first_token = re.split(r"\s*(?:\|{1,2}|&&)\s*", cmd)[0].strip()
        try:
            argv0 = shlex.split(first_token)[0] if first_token else cmd
        except ValueError:
            argv0 = first_token.split()[0] if first_token else cmd
        basename = os.path.basename(argv0)

        # Apply denylist
        if basename in _BASENAME_DENYLIST:
            return
        for pat in _ARGV_DENYPATS:
            if pat.search(cmd):
                return

        # Read per-session overrides
        include_list: list[str] = []
        exclude_list: list[str] = []
        redact_list: list[str] = []
        state_file = _state_file(session_id)
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                overrides = state.get("overrides") or {}
                include_list = overrides.get("include") or []
                exclude_list = overrides.get("exclude") or []
                redact_list = overrides.get("redact") or []
            except Exception:
                pass

        # Apply include/exclude overrides
        if basename in include_list:
            pass  # explicitly allowed
        elif basename in exclude_list or basename not in _CONTEXT_ALLOWLIST:
            return

        # Apply redaction
        redacted_cmd = cmd
        for pat_str in redact_list:
            with contextlib.suppress(Exception):
                redacted_cmd = re.sub(pat_str, "<redacted>", redacted_cmd)

        if not Path(log_path).exists():
            return

        # Check cap
        try:
            line_count = sum(1 for line in Path(log_path).read_text().splitlines() if line.strip())
            if line_count > 1000:
                cap_event = {
                    "seq": None,
                    "op": "cap_reached",
                    "ts": _now_ts(),
                    "args": {},
                    "result": {},
                    "model_snapshot_before": None,
                    "model_snapshot_after": None,
                    "assertions": [],
                    "gesture": None,
                }
                _append_jsonl_event(log_path, cap_event)
                return
        except Exception:
            pass

        event = {
            "seq": None,
            "op": "shell_context",
            "ts": _now_ts(),
            "args": {
                "argv": [redacted_cmd],
                "basename": basename,
                "source": "hook",
                "session_id": session_id,
            },
            "result": {
                "exit_code": exit_code,
                "stdout": None,
                "stderr": None,
                "stdout_truncated": False,
            },
            "model_snapshot_before": None,
            "model_snapshot_after": None,
            "assertions": [],
            "gesture": None,
        }
        _append_jsonl_event(log_path, event)
    except Exception:
        pass


def cmd_hook_event(args: argparse.Namespace) -> int:
    """Record a shell-hook event, swallowing any error.

    Always exits 0 so a recording failure never breaks the user's shell.
    """
    with contextlib.suppress(Exception):
        _hook_event_impl(
            session_id=args.session,
            cmd=args.cmd,
            exit_code=int(args.exit),
            start_ms=int(args.start_ms),
            log_path=args.log,
        )
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate a jubilant test from the session."""
    session_log = getattr(args, "session_log", None) or os.environ.get("JTR_LOG")
    if not session_log:
        print("jtr generate: no --session-log given and $JTR_LOG is not set.", file=sys.stderr)
        return 1
    log_path = Path(session_log)
    if not log_path.exists():
        print(f"jtr generate: session log not found: {log_path}", file=sys.stderr)
        return 1
    try:
        events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        print(f"jtr generate: could not parse session log {log_path}: {exc}", file=sys.stderr)
        return 1
    if not events:
        print(f"jtr generate: session log {log_path} has no events.", file=sys.stderr)
        return 1
    session_id = (events[0].get("args") or {}).get("session_id") or "unknown"
    wrapped = {"schema_version": "1.0", "session_id": session_id, "events": events}
    test_name = getattr(args, "name", None) or "test_recorded_session"
    source = codegen.generate(wrapped, test_name=test_name)
    out = getattr(args, "out", None)
    if out:
        Path(out).write_text(source)
    else:
        sys.stdout.write(source)
    return 0


def cmd_shim_install(args: argparse.Namespace) -> int:
    """Install the recording ``juju`` shim."""
    target = getattr(args, "target", None)
    if target:
        target_dir = Path(target)
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
        target_dir = base / "jtr" / "shims"

    real_juju = getattr(args, "real_juju", None) or shutil.which("juju")
    if not real_juju:
        print(
            "jtr shim install: --real-juju not given and no `juju` found on PATH.",
            file=sys.stderr,
        )
        return 1

    shim_source = Path(juju_shim.__file__).read_text()
    shim_source = shim_source.replace("__REAL_JUJU__", str(real_juju))

    # The shim is installed as an executable named `juju` and found via PATH,
    # so it needs an interpreter line: without one the kernel hands it to sh,
    # every line is a shell syntax error, and `juju` stops working entirely
    # for the duration of the session. `sys.executable` rather than
    # `/usr/bin/env python3` because that is the interpreter the shim was
    # installed with, and it is the one known to exist here. The shim itself
    # imports only stdlib, so it does not need jtr's own environment.
    if not shim_source.startswith("#!"):
        shim_source = f"#!{sys.executable}\n" + shim_source

    target_dir.mkdir(parents=True, exist_ok=True)
    shim_path = target_dir / "juju"
    shim_path.write_text(shim_source)
    shim_path.chmod(0o755)
    print(f"installed at {shim_path}")
    return 0


def cmd_shim(args: argparse.Namespace) -> int:
    """Run the recording ``juju`` shim."""
    if getattr(args, "shim_command", None) == "install":
        return cmd_shim_install(args)
    print("jtr shim: missing subcommand (expected: install)", file=sys.stderr)
    return 1


def cmd_shell_install(args: argparse.Namespace) -> int:
    """Install the jtr shell integration into the user's shell rc file."""
    shell = _resolve_shell(getattr(args, "shell", None))
    if not shell or shell not in ("bash", "zsh"):
        print(
            f"jtr shell install: cannot detect shell or unsupported shell: {shell!r}",
            file=sys.stderr,
        )
        return 1

    rcfile = getattr(args, "rcfile", None)
    if rcfile:
        rc_path = Path(rcfile)
    else:
        rc_path = Path.home() / (".bashrc" if shell == "bash" else ".zshrc")

    no_path_shim = getattr(args, "no_path_shim", False)
    snippet = _render_shell_init(shell, no_path_shim)
    block = f"{_SHELL_INIT_BEGIN_MARKER}\n{snippet}\n{_SHELL_INIT_END_MARKER}"

    existing = rc_path.read_text() if rc_path.exists() else ""
    marker_pattern = re.compile(
        re.escape(_SHELL_INIT_BEGIN_MARKER) + r".*?" + re.escape(_SHELL_INIT_END_MARKER),
        re.DOTALL,
    )
    if marker_pattern.search(existing):
        updated = marker_pattern.sub(lambda _match: block, existing, count=1)
    else:
        sep = "" if not existing or existing.endswith("\n") else "\n"
        updated = f"{existing}{sep}{block}\n"

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(updated)
    print(f"updated {rc_path}")
    print("re-source your rc file to activate", file=sys.stderr)
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    """Start a shell with recording enabled."""
    if getattr(args, "shell_command", None) == "install":
        return cmd_shell_install(args)
    print("jtr shell: missing subcommand (expected: install)", file=sys.stderr)
    return 1


def main() -> None:
    """Run the ``jtr`` command-line interface."""
    parser = argparse.ArgumentParser(prog="jtr")
    sub = parser.add_subparsers(dest="command")

    # shell-init
    p_shell_init = sub.add_parser("shell-init", help="Print the shell-hook init snippet.")
    p_shell_init.add_argument("--shell", choices=["bash", "zsh", "fish"])
    p_shell_init.add_argument("--no-path-shim", action="store_true", dest="no_path_shim")

    # generate
    p_generate = sub.add_parser(
        "generate", help="Generate a pytest test from a shell-hook JSONL session log."
    )
    p_generate.add_argument(
        "--session-log",
        dest="session_log",
        help="Path to the JSONL session log (defaults to $JTR_LOG).",
    )
    p_generate.add_argument(
        "--out", help="Write the generated test to this path instead of stdout."
    )
    p_generate.add_argument("--name", help="Test function name (default: test_recorded_session).")

    # shim / shim install
    p_shim = sub.add_parser("shim", help="Manage the jtr juju PATH shim.")
    shim_sub = p_shim.add_subparsers(dest="shim_command")
    p_shim_install = shim_sub.add_parser("install", help="Materialise the juju shim on disk.")
    p_shim_install.add_argument(
        "--target", help="Directory to install the shim into (default: $XDG_DATA_HOME/jtr/shims)."
    )
    p_shim_install.add_argument(
        "--real-juju",
        dest="real_juju",
        help="Path to the real juju binary (default: `which juju`).",
    )

    # shell / shell install
    p_shell = sub.add_parser("shell", help="Manage the jtr shell-init rc file wiring.")
    shell_sub = p_shell.add_subparsers(dest="shell_command")
    p_shell_install = shell_sub.add_parser(
        "install", help="Append/update the shell-init snippet in your rc file."
    )
    p_shell_install.add_argument("--shell", choices=["bash", "zsh"])
    p_shell_install.add_argument(
        "--rcfile", help="rc file to edit (default: ~/.bashrc or ~/.zshrc)."
    )
    p_shell_install.add_argument("--no-path-shim", action="store_true", dest="no_path_shim")

    # start
    p_start = sub.add_parser("start")
    p_start.add_argument("name", nargs="?")
    p_start.add_argument("--output")
    p_start.add_argument("--shared", action="store_true")

    # stop
    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--auto", action="store_true")

    # pause
    sub.add_parser("pause")

    # resume
    sub.add_parser("resume")

    # status
    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true")

    # tail
    p_tail = sub.add_parser("tail")
    p_tail.add_argument("--json", action="store_true")
    p_tail.add_argument("--jubilant-only", action="store_true")
    p_tail.add_argument("--context-only", action="store_true")

    # note
    p_note = sub.add_parser("note")
    p_note.add_argument("text")

    # tag
    p_tag = sub.add_parser("tag")
    p_tag.add_argument("label")

    # attach
    p_attach = sub.add_parser("attach")
    p_attach.add_argument("session_id", nargs="?")

    # include / exclude / redact
    p_include = sub.add_parser("include")
    p_include.add_argument("pattern")
    p_exclude = sub.add_parser("exclude")
    p_exclude.add_argument("pattern")
    p_redact = sub.add_parser("redact")
    p_redact.add_argument("pattern")

    # _hook_event (internal)
    p_hook = sub.add_parser("_hook_event")
    p_hook.add_argument("--session", required=True)
    p_hook.add_argument("--cmd", required=True)
    p_hook.add_argument("--exit", required=True, dest="exit")
    p_hook.add_argument("--start-ms", required=True, dest="start_ms")
    p_hook.add_argument("--log", required=True)

    args = parser.parse_args()

    handlers = {
        "shell-init": cmd_shell_init,
        "generate": cmd_generate,
        "shim": cmd_shim,
        "shell": cmd_shell,
        "start": cmd_start,
        "stop": cmd_stop,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "status": cmd_status,
        "tail": cmd_tail,
        "note": cmd_note,
        "tag": cmd_tag,
        "attach": cmd_attach,
        "include": cmd_include,
        "exclude": cmd_exclude,
        "redact": cmd_redact,
        "_hook_event": cmd_hook_event,
    }

    if args.command not in handlers:
        parser.print_help()
        sys.exit(1)

    sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
