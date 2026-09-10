"""Every `juju.<method>(...)` codegen emits must bind to jubilant's signature.

Parsing is not enough. `juju.config(app, keys=[...])` parsed perfectly and
raised `TypeError` the moment anyone ran the test, because `Juju.config()`
has no `keys` parameter — and nothing caught it until a generated test was
executed against a real controller.

This walks the source codegen produces for a representative invocation of
every subcommand it types, finds each `juju.<method>` call, and binds its
arguments against `inspect.signature(jubilant.Juju.<method>)`. A misnamed
keyword, a positional too many, a method that does not exist at all: all
of them fail here, offline, in milliseconds.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any

import jubilant
import pytest

from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap

# One invocation per typed translation, chosen to exercise the kwargs each
# emitter can produce rather than only its bare form.
INVOCATIONS: tuple[tuple[str, ...], ...] = (
    ("status",),
    ("deploy", "ubuntu", "myapp", "--channel", "edge", "--base", "ubuntu@24.04", "-n", "2"),
    ("deploy", "ubuntu", "--force", "--trust", "--constraints", "mem=4G", "--config", "a=b"),
    ("config", "ubuntu"),
    ("config", "ubuntu", "log-level=debug"),
    ("config", "ubuntu", "--reset", "log-level,other"),
    ("refresh", "ubuntu", "--channel", "edge", "--revision", "7", "--force", "--trust"),
    ("refresh", "ubuntu", "--config", "a=b", "--resource", "r=1", "--storage", "s=1G"),
    ("remove-application", "ubuntu", "--force", "--destroy-storage"),
    ("integrate", "a:db", "b:database"),
    ("remove-relation", "a:db", "b:database"),
    ("run", "ubuntu/0", "do-thing", "key=value", "--wait", "30s"),
    ("add-unit", "ubuntu", "-n", "2", "--to", "0"),
    ("remove-unit", "ubuntu/1", "ubuntu/2", "--force", "--destroy-storage"),
    ("remove-unit", "ubuntu", "--num-units", "2"),
    ("add-machine", "lxd:0", "--base", "ubuntu@24.04", "-n", "3", "--constraints", "mem=4G"),
    ("ssh", "ubuntu/0", "ls", "-la"),
    ("ssh", "--container", "web", "root@ubuntu/0", "ls"),
    ("ssh", "--no-host-key-checks", "ubuntu/0", "ls"),
    ("exec", "--unit", "ubuntu/0", "--wait", "30s", "hostname"),
    ("exec", "--machine", "0", "hostname"),
    ("scp", "ubuntu/0:/tmp/a", "./a"),
    ("scp", "--container", "web", "--no-host-key-checks", "ubuntu/0:/tmp/a", "./a"),
    ("debug-log", "--no-tail", "--limit", "50"),
    ("show-model",),
    ("show-model", "other"),
    ("model-config",),
    ("model-config", "a=b"),
    ("model-config", "--reset", "a,b"),
    ("model-constraints",),
    ("set-model-constraints", "mem=4G", "cores=2"),
    ("trust", "ubuntu", "--scope", "cluster"),
    ("trust", "ubuntu", "--remove"),
    ("add-ssh-key", "ssh-rsa AAA me@host"),
    ("remove-ssh-key", "me@host"),
    ("version",),
    # A model-lifecycle command only becomes a call when it names a model
    # other than the session's own; `PRELUDE` supplies a session model so
    # these two do. See `operations/model_lifecycle.py`.
    ("add-model", "other"),
    ("destroy-model", "other", "--force", "--no-wait", "--destroy-storage", "-t", "5m"),
    ("add-secret", "mine", "k=v", "--info", "a secret"),
    ("update-secret", "mine", "k=v", "--info", "x", "--name", "y", "--auto-prune"),
    ("show-secret", "mine", "--reveal", "--revision", "2"),
    ("grant-secret", "mine", "a,b"),
    ("secrets", "--owner", "me"),
    ("offer", "ubuntu:db", "myoffer"),
    ("consume", "other.myoffer", "alias"),
    ("wait-for", "application", "ubuntu", "--timeout", "10m"),
    ("wait-for", "model", "demo"),
)

# Names bound to something that is not a literal in the generated source.
_NON_LITERAL = object()


# Every generated source in this module is produced from this event
# followed by the one under test, so that `cli_translate.session_model()`
# has an answer and the model-lifecycle entries above render as calls.
PRELUDE: tuple[str, ...] = ("add-model", "the-session-model")


def _event(argv: tuple[str, ...], seq: int = 2) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": list(argv), "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _juju_calls(source: str) -> list[ast.Call]:
    """Every `juju.<method>(...)` call in `source`, statements only.

    Assertion bodies are skipped: those read `juju.status()` and index into
    the result, which is a different (and already exercised) surface.
    """
    calls: list[ast.Call] = []
    for node in ast.parse(source).body:
        for statement in ast.walk(node):
            if isinstance(statement, ast.Assert):
                continue
            # A bare call (`juju.deploy(...)`) or a bound one
            # (`result_1 = juju.run(...)`) — both are steps.
            if isinstance(statement, ast.Expr | ast.Assign) and isinstance(
                statement.value, ast.Call
            ):
                call = statement.value
            else:
                continue
            func = call.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "juju"
            ):
                calls.append(call)
    return calls


def _value(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return _NON_LITERAL


@pytest.mark.parametrize("argv", INVOCATIONS, ids=lambda a: " ".join(a))
def test_emitted_calls_bind_to_jubilant(argv: tuple[str, ...]) -> None:
    source = generate(_wrap([_event(PRELUDE, seq=1), _event(argv)]))
    calls = _juju_calls(source)
    assert calls, f"{argv} emitted no juju call:\n{source}"

    for call in calls:
        assert isinstance(call.func, ast.Attribute)
        method_name = call.func.attr
        method = getattr(jubilant.Juju, method_name, None)
        assert method is not None, f"jubilant.Juju has no {method_name}() ({argv})"

        positional = [_value(a) for a in call.args]
        keywords = {kw.arg: _value(kw.value) for kw in call.keywords if kw.arg}
        try:
            # `None` for self: binding checks names and arity, not types.
            inspect.signature(method).bind(None, *positional, **keywords)
        except TypeError as exc:
            pytest.fail(
                f"{argv} emitted a call jubilant will reject: "
                f"juju.{method_name}(...) — {exc}\n{source}"
            )


def test_the_table_reaches_every_typed_op() -> None:
    """A translation with no invocation here is not being signature-checked."""
    from jubilant_recorder.codegen import cli_translate

    reached = set()
    for argv in INVOCATIONS:
        result = cli_translate.classify_argv(list(argv))
        assert result is not None
        reached.add(result[0])

    # Every op a `juju` argv can reach that renders as a *call*.
    # `cli_passthrough` is the untyped floor and `switch_model` renders as a
    # comment, so neither belongs in a table about call signatures.
    expected = {
        "add_machine",
        "add_model",
        "add_ssh_key",
        "config",
        "config_get",
        "config_unset",
        "consume",
        "create_offer",
        "debug_log",
        "deploy",
        "destroy_model",
        "exec",
        "integrate",
        "model_config",
        "model_constraints",
        "refresh",
        "remove_application",
        "remove_integration",
        "remove_ssh_key",
        "remove_unit",
        "run",
        "scale",
        "scp",
        "secret_add_cli",
        "secret_grant",
        "secret_list",
        "secret_update_cli",
        "show_model",
        "show_secret",
        "ssh",
        "status_call",
        "trust",
        "version",
        "wait_for",
    }
    assert expected <= reached, f"table no longer reaches: {sorted(expected - reached)}"
    assert "cli_passthrough" not in reached, (
        "an invocation in the table fell through to juju.cli() — either it is "
        "malformed, or a classifier stopped claiming it"
    )
