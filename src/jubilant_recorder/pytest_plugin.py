"""Record an existing pytest-operator suite as it runs.

The point of the libjuju front-end is migration: you have an integration
suite written against python-libjuju, you want the same coverage in
jubilant, and translating it by hand is a day's careful work. This plugin
is how that suite gets recorded without editing it — run it as you always
do, with one extra flag::

    pytest tests/integration --jtr-record=session --jtr-out=test_migrated.py

Every RPC libjuju sends is captured (`extensions/libjuju/tap.py`),
correlated back into operations (`extensions/libjuju/correlate.py`), and
emitted as a jubilant test.

Per test, not per run
---------------------
Each test function is recorded as its own session and becomes its own
generated test, in the order pytest ran them. That is the shape a
pytest-operator suite already has: its `ops_test` fixture is module-scoped,
so the tests run in order against one shared model, each building on what
the last left behind. `codegen.generate_module` renders that as a
module-scoped `juju` fixture and a series of tests taking it, which is
jubilant's idiom for the same thing.

What the output is for
----------------------
A starting point, not a finished suite. The recorder can see what the tests
*did* to the model; it cannot see what they meant, and a test's real
assertions live in Python the tap never observes. Read the generated file,
and expect to add back the assertions that made each test worth writing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

_RECORDER_KEY = "_jtr_recorder"
_SNAPSHOT_KEY = "_jtr_snapshot"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the recording options."""
    group = parser.getgroup("jubilant-recorder")
    group.addoption(
        "--jtr-record",
        action="store",
        default=None,
        metavar="DIR",
        help=(
            "Record this run's libjuju traffic as jubilant-recorder session logs, "
            "one per test, written under DIR."
        ),
    )
    group.addoption(
        "--jtr-out",
        action="store",
        default=None,
        metavar="PATH",
        help="Also write a generated jubilant test module to PATH (implies --jtr-record).",
    )
    group.addoption(
        "--jtr-ai",
        action="store_true",
        default=False,
        help="Run the LLM assertion and polish passes over the result (needs OPENROUTER_API_KEY).",
    )


def _recorded(config: pytest.Config) -> list[tuple[str, Path]]:
    """Return the (test name, session log) pairs recorded so far in this run.

    Kept on the config object rather than a module global so that a nested
    pytest run (pytester, or a suite that shells out to pytest) does not
    append into its parent's list.
    """
    existing = getattr(config, _RECORDER_KEY, None)
    if existing is None:
        existing = []
        setattr(config, _RECORDER_KEY, existing)
    return existing


def _record_dir(config: pytest.Config) -> Path | None:
    """Return where session logs go, or None if recording was not asked for."""
    explicit = config.getoption("--jtr-record")
    if explicit:
        return Path(explicit)
    out = config.getoption("--jtr-out")
    if out:
        # `--jtr-out` alone is the common case: the user wants the test, not
        # the intermediate logs. Put them next to it rather than making them
        # pass a second path they do not care about.
        return Path(out).parent / f"{Path(out).stem}-sessions"
    return None


def pytest_configure(config: pytest.Config) -> None:
    """Fail early if recording was asked for but libjuju is not installed."""
    if _record_dir(config) is None:
        return
    try:
        import juju  # noqa: F401
    except ImportError:
        raise pytest.UsageError(
            "--jtr-record needs python-libjuju, which is not installed. "
            "Install jubilant-recorder with its 'libjuju' extra."
        ) from None


def _safe_test_name(item: pytest.Item) -> str:
    """Build a python identifier naming this test, unique within the run.

    Parametrised tests arrive as ``test_deploy[postgresql-16]``; the
    brackets and dashes are not identifier characters, so they become
    underscores. The name is what the reader sees in the generated file, so
    it keeps the parameter rather than dropping it for a counter.
    """
    raw = item.name
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in raw).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"test_{cleaned}"
    if not cleaned.startswith("test"):
        cleaned = f"test_{cleaned}"
    return cleaned


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, None, None]:
    """Wrap each test's call phase in a recording session.

    The call phase only — setup and teardown are where pytest-operator
    builds and destroys the model, and that is the harness's business, not
    the test's. Recording it would put a model creation at the top of every
    generated test, which is exactly what the module-scoped `juju` fixture
    is there to do once.
    """
    directory = _record_dir(item.config)
    if directory is None:
        yield
        return

    from jubilant_recorder.extensions.libjuju.recording import RecordingLibjuju

    directory.mkdir(parents=True, exist_ok=True)
    name = _safe_test_name(item)
    log_path = directory / f"{name}.json"
    recorded = _recorded(item.config)
    # Carry the model state forward. The AllWatcher stream is a stream of
    # *changes*, and each test gets its own recording session against a model
    # they all share — so from the second test onwards the tap sees only what
    # changed, and a session that starts from "no units" produces assertions
    # that are short by whatever the earlier tests left behind.
    recorder = RecordingLibjuju(
        output_log_path=log_path,
        model="",
        initial_snapshot=getattr(item.config, _SNAPSHOT_KEY, None),
    )
    try:
        recorder.__enter__()
    except Exception as exc:  # pragma: no cover - defensive
        _warn(item, f"could not start recording: {exc!r}")
        yield
        return
    try:
        yield
    finally:
        # A bug in the recorder must not fail the test it is recording.
        # This is not hypothetical: a wire shape the correlator had not seen
        # (`Application.DestroyApplication` sending bare application names)
        # turned a passing test red, which is the worst thing a migration
        # tool can do to the suite it is migrating. Report and carry on; the
        # session log for that one test is lost, the run is not.
        try:
            recorder.__exit__(None, None, None)
        except Exception as exc:
            _warn(item, f"recording failed and was discarded: {exc!r}")
        else:
            recorded.append((name, log_path))
            setattr(item.config, _SNAPSHOT_KEY, recorder.final_snapshot)


def _warn(item: pytest.Item, message: str) -> None:
    """Surface a recording problem without failing the test."""
    item.warn(pytest.PytestWarning(f"jubilant-recorder: {message}"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Generate the jubilant test module from everything that was recorded."""
    del exitstatus
    config = session.config
    out = config.getoption("--jtr-out")
    if not out:
        return
    recorded = _recorded(config)
    if not recorded:
        return

    from jubilant_recorder import codegen, shim_snapshots, tagger

    use_ai = config.getoption("--jtr-ai")
    proposer = polisher = None
    if use_ai:
        from jubilant_recorder.cli import _make_ai_components

        proposer, polisher = _make_ai_components(True)

    sessions: list[tuple[str, dict[str, Any]]] = []
    for name, log_path in recorded:
        try:
            log = json.loads(log_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        log = shim_snapshots.attach_status_snapshots(log)
        sessions.append((name, tagger.tag(log, proposer=proposer)))

    source = codegen.generate_module(sessions)
    if use_ai:
        merged = {"events": [e for _, log in sessions for e in log.get("events") or []]}
        source = codegen.ai_polish.polish(source, merged, polisher=polisher)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(source)
    print(f"\njubilant-recorder: wrote {out_path}")
