"""Every juju subcommand produces runnable Python.

The classifier is total by design: a `juju` command the recorder captured
must become a jubilant call, never a comment and never an exception. That
is a claim about the whole CLI surface, so it is checked against the whole
CLI surface rather than the handful of subcommands the other tests name.

What this does *not* check is that each translation is right — the argvs
here are shapes, not real invocations. It checks the two properties that
must hold for every one of them: the classifier does not raise, and what
codegen emits parses.
"""

from __future__ import annotations

import ast

import pytest

from jubilant_recorder.codegen import cli_translate
from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap
from .juju_subcommands import JUJU_SUBCOMMANDS

# Subcommands that take `-m`/`--model`, per `juju help <subcommand>` on the
# client `NO_MODEL_SUBCOMMANDS` was generated from. Only these can carry a
# model *scope* to strip; on the rest, a `-m` is a flag juju would have
# rejected, so passing it through verbatim is the honest thing to do.
MODEL_SCOPED = tuple(s for s in JUJU_SUBCOMMANDS if s not in cli_translate.NO_MODEL_SUBCOMMANDS)

# Argv tails that between them cover the shapes juju commands take: bare,
# one operand, two operands, a key=value, a flag with a value, a flag
# without one, and a `--` separator.
_TAILS: tuple[tuple[str, ...], ...] = (
    (),
    ("thing",),
    ("thing", "other"),
    ("thing", "key=value"),
    ("thing", "--some-flag", "value"),
    ("thing", "--force"),
    ("--", "thing"),
)


def _event(argv: tuple[str, ...]) -> dict:
    return {
        "seq": 1,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": list(argv), "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


@pytest.mark.parametrize("subcommand", JUJU_SUBCOMMANDS)
def test_every_subcommand_classifies_and_generates(subcommand: str) -> None:
    for tail in _TAILS:
        argv = (subcommand, *tail)
        result = cli_translate.classify_argv(list(argv))
        assert result is not None, f"{argv} did not classify"
        source = generate(_wrap([_event(argv)]))
        try:
            ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - the failure message
            pytest.fail(f"{argv} generated unparseable Python ({exc}):\n{source}")


@pytest.mark.parametrize("subcommand", JUJU_SUBCOMMANDS)
def test_no_subcommand_renders_as_a_shell_comment(subcommand: str) -> None:
    """The whole point: nothing is left for the reader to retype."""
    for tail in _TAILS:
        source = generate(_wrap([_event((subcommand, *tail))]))
        assert "# shell:" not in source, f"{subcommand} {tail} fell back to a comment"


@pytest.mark.parametrize("subcommand", MODEL_SCOPED)
def test_a_model_scoped_flag_never_reaches_the_generated_test(subcommand: str) -> None:
    """A generated test runs in its own model, not the recording's."""
    source = generate(_wrap([_event((subcommand, "thing", "-m", "the-recorded-model"))]))
    assert "the-recorded-model" not in source, source


def test_the_model_scoped_list_is_most_of_the_cli() -> None:
    """Guard against the parametrisation above quietly emptying out."""
    assert len(MODEL_SCOPED) > 100
