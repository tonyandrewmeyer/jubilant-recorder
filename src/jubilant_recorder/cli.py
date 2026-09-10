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

from jubilant_recorder import (
    __version__,
    codegen,
    openrouter,
    quiet_window,
    shim_snapshots,
    tagger,
)
from jubilant_recorder.codegen.ai_polish import LLMPolisher, Polisher, StubPolisher
from jubilant_recorder.session_log import SessionLog
from jubilant_recorder.tagger.llm import AssertionProposer, LLMProposer, StubProposer


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


def _make_ai_components(
    use_ai: bool, *, model: str | None = None
) -> tuple[AssertionProposer, Polisher]:
    """Return (proposer, polisher) for the current run.

    When --ai is not set, both are stubs (no LLM calls, deterministic output).
    When --ai is set, tries to build a shared httpx.Client for OpenRouter from
    OPENROUTER_API_KEY; falls back to stubs with a warning if the key is
    absent. `model` overrides OPENROUTER_MODEL and the built-in default.
    """
    if not use_ai:
        return StubProposer(), StubPolisher()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        warnings.warn(
            "OPENROUTER_API_KEY is not set — --ai flag has no effect; "
            "using offline stubs. Set OPENROUTER_API_KEY to enable LLM features.",
            stacklevel=3,
        )
        return StubProposer(), StubPolisher()

    client = openrouter.make_client(api_key)
    resolved_model = openrouter.resolve_model(model)
    return LLMProposer(client, model=resolved_model), LLMPolisher(client, model=resolved_model)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_start(args: argparse.Namespace) -> int:
    """Start recording a session."""
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
    """Stop the active recording."""
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
    """Generate a jubilant test from a recorded session."""
    use_ai = getattr(args, "ai", False)
    proposer, polisher = _make_ai_components(use_ai, model=getattr(args, "ai_model", None))
    session_log_path = Path(args.session_log)
    log = json.loads(session_log_path.read_text())
    log = shim_snapshots.attach_status_snapshots(log)
    log = quiet_window.synthesize(log)
    annotated = tagger.tag(log, proposer=proposer if use_ai else None)

    overlay = None
    test_name = args.name
    source_aware = getattr(args, "source_aware", None)
    if source_aware:
        # Optional, purely decorative — see extensions/libjuju/source_overlay.py.
        # A missing/unparsed source file yields an empty overlay; codegen output
        # is unaffected either way. Parses source with ast, so it needs no
        # libjuju install of its own.
        from jubilant_recorder.extensions.libjuju.source_overlay import (
            align_events,
            extract_call_sites,
        )

        found = extract_call_sites(Path(source_aware))
        overlay = align_events(found.call_sites, annotated.get("events", []) or [])
        if test_name is None:
            test_name = found.test_name
    test_name = test_name or "test_recorded_session"

    source = codegen.generate(annotated, test_name=test_name, overlay=overlay)
    if use_ai:
        source = codegen.ai_polish.polish(source, annotated, polisher=polisher)
    if args.out:
        Path(args.out).write_text(source)
        print(str(Path(args.out).absolute()))
    else:
        sys.stdout.write(source)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Record a session while running the given command."""
    use_ai = getattr(args, "ai", False)
    proposer, polisher = _make_ai_components(use_ai, model=getattr(args, "ai_model", None))
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
    log_doc = shim_snapshots.attach_status_snapshots(log_doc)
    log_doc = quiet_window.synthesize(log_doc)
    annotated = tagger.tag(log_doc, proposer=proposer if use_ai else None)
    source = codegen.generate(annotated, test_name=args.name or "test_recorded_session")
    if use_ai:
        source = codegen.ai_polish.polish(source, annotated, polisher=polisher)
    out_path.write_text(source)
    print(str(out_path))
    return rc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jubilant-recorder",
        description="Record a jubilant session and generate a pytest integration test.",
    )
    parser.add_argument("--version", action="version", version=f"jubilant-recorder {__version__}")
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
    p_run.add_argument(
        "--ai-model",
        default=None,
        metavar="MODEL",
        help="OpenRouter model id for --ai (default: $OPENROUTER_MODEL or "
        f"{openrouter.DEFAULT_MODEL}).",
    )
    p_run.add_argument("cmd", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_run)

    p_gen = sub.add_parser("generate", help="Generate a pytest test file from a session log.")
    p_gen.add_argument("session_log")
    p_gen.add_argument("--out", default=None)
    p_gen.add_argument("--name", default=None)
    p_gen.add_argument(
        "--source-aware",
        default=None,
        metavar="PATH",
        help="Path to the libjuju/jubilant test file that produced this session log. "
        "Decorative only (extensions/libjuju/source_overlay.py): improves generated "
        "variable names and carries source comments through; the recording alone is "
        "always sufficient without it.",
    )
    p_gen.add_argument(
        "--ai",
        action="store_true",
        help="Run the optional LLM polish pass over the generated test "
        "(experimental — review the output before committing).",
    )
    p_gen.add_argument(
        "--ai-model",
        default=None,
        metavar="MODEL",
        help="OpenRouter model id for --ai (default: $OPENROUTER_MODEL or "
        f"{openrouter.DEFAULT_MODEL}).",
    )
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the jubilant-recorder command-line interface."""
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
