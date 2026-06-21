"""CLI entry point for the jubilant test recorder.

Wires the existing recorder library (RecordingJuju + tagger + codegen) into
four subcommands: start, stop, run, generate. The CLI is glue — all logic
lives in the underlying modules.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jubilant_recorder import codegen, tagger
from jubilant_recorder.codegen.ai_polish import AnthropicPolisher, Polisher, StubPolisher
from jubilant_recorder.session_log import SessionLog
from jubilant_recorder.tagger.llm import AnthropicProposer, AssertionProposer, StubProposer


def _state_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "jubilant-recorder"
    return Path.home() / ".cache" / "jubilant-recorder"


def _state_file() -> Path:
    return _state_dir() / "active.json"


def _write_state(state: dict[str, Any]) -> None:
    sd = _state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps(state, indent=2, sort_keys=True))


def _read_state() -> dict[str, Any] | None:
    sf = _state_file()
    if not sf.exists():
        return None
    return json.loads(sf.read_text())


def _delete_state() -> None:
    sf = _state_file()
    if sf.exists():
        sf.unlink()


def _default_session_log() -> Path:
    return Path.cwd() / "session.json"


def _make_ai_components(use_ai: bool) -> tuple[AssertionProposer, Polisher]:
    """Return (proposer, polisher) for the current run.

    When --ai is not set, both are stubs (no LLM calls, deterministic output).
    When --ai is set, tries to build a shared anthropic.Anthropic() client from
    ANTHROPIC_API_KEY; falls back to stubs with a warning if the key is absent.
    """
    if not use_ai:
        return StubProposer(), StubPolisher()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        warnings.warn(
            "ANTHROPIC_API_KEY is not set — --ai flag has no effect; "
            "using offline stubs. Set ANTHROPIC_API_KEY to enable LLM features.",
            stacklevel=3,
        )
        return StubProposer(), StubPolisher()

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    return AnthropicProposer(client), AnthropicPolisher(client)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_start(args: argparse.Namespace) -> int:
    session_log = Path(args.session_log).absolute() if args.session_log else _default_session_log()
    model = args.model or ""
    state = {
        "model": model,
        "pid": os.getpid(),
        "session_log_path": str(session_log),
        "started_at": _now_iso(),
    }
    _write_state(state)
    if not session_log.exists():
        log = SessionLog(session_log, model=model)
        log.close()
    print(str(session_log))
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    state = _read_state()
    if state is None:
        print("error: no active recording session", file=sys.stderr)
        return 1
    session_log_path = Path(state["session_log_path"])
    if not session_log_path.exists():
        log = SessionLog(session_log_path, model=state.get("model", ""))
        log.close()
    else:
        try:
            doc = json.loads(session_log_path.read_text())
        except (OSError, json.JSONDecodeError):
            doc = None
        if not isinstance(doc, dict) or "schema_version" not in doc:
            log = SessionLog(session_log_path, model=state.get("model", ""))
            log.close()
    _delete_state()
    print(f"stopped: {session_log_path}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    use_ai = getattr(args, "ai", False)
    proposer, polisher = _make_ai_components(use_ai)
    session_log_path = Path(args.session_log)
    log = json.loads(session_log_path.read_text())
    annotated = tagger.tag(log, proposer=proposer if use_ai else None)
    test_name = args.name or "test_recorded_session"
    source = codegen.generate(annotated, test_name=test_name)
    if use_ai:
        source = codegen.ai_polish.polish(source, annotated, polisher=polisher)
    if args.out:
        Path(args.out).write_text(source)
        print(str(Path(args.out).absolute()))
    else:
        sys.stdout.write(source)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    use_ai = getattr(args, "ai", False)
    proposer, polisher = _make_ai_components(use_ai)
    session_log = Path(args.session_log).absolute() if args.session_log else _default_session_log()
    log = SessionLog(session_log)
    log.close()
    state = {
        "model": "",
        "pid": os.getpid(),
        "session_log_path": str(session_log),
        "started_at": _now_iso(),
    }
    _write_state(state)
    cmd = args.cmd or [os.environ.get("SHELL", "/bin/sh")]
    rc = 0
    try:
        env = dict(os.environ, JUBILANT_RECORDER_SESSION_LOG=str(session_log))
        result = subprocess.run(cmd, env=env, check=False)
        rc = result.returncode
    finally:
        _delete_state()
    out_path = Path(args.out).absolute() if args.out else session_log.with_suffix(".py")
    log_doc = json.loads(session_log.read_text())
    annotated = tagger.tag(log_doc, proposer=proposer if use_ai else None)
    source = codegen.generate(annotated, test_name=args.name or "test_recorded_session")
    if use_ai:
        source = codegen.ai_polish.polish(source, annotated, polisher=polisher)
    out_path.write_text(source)
    print(str(out_path))
    return rc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recorder",
        description="Record a jubilant session and generate a pytest integration test.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_start = sub.add_parser("start", help="Begin a recording session.")
    p_start.add_argument("--session-log", default=None)
    p_start.add_argument("--model", default=None)
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Finalise the active recording session.")
    p_stop.set_defaults(func=cmd_stop)

    p_run = sub.add_parser(
        "run",
        help="Start a session, run CMD under the recorder, stop, and generate a test.",
    )
    p_run.add_argument("--session-log", default=None)
    p_run.add_argument("--out", default=None)
    p_run.add_argument("--name", default=None)
    p_run.add_argument(
        "--ai",
        action="store_true",
        help="Run the optional LLM polish pass over the generated test "
        "(experimental — review the output before committing).",
    )
    p_run.add_argument("cmd", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_run)

    p_gen = sub.add_parser("generate", help="Generate a pytest test file from a session log.")
    p_gen.add_argument("session_log")
    p_gen.add_argument("--out", default=None)
    p_gen.add_argument("--name", default=None)
    p_gen.add_argument(
        "--ai",
        action="store_true",
        help="Run the optional LLM polish pass over the generated test "
        "(experimental — review the output before committing).",
    )
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "cmd"):
        cmd_args = list(args.cmd or [])
        if cmd_args and cmd_args[0] == "--":
            cmd_args = cmd_args[1:]
        args.cmd = cmd_args
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
