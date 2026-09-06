"""Behavioural equality: a recorded `add-unit --to/--attach-storage` operation must
emit the identical jubilant call whether it was observed by the CLI/shim tap or the
RPC tap.

Before this, only the CLI/shim path populated `to`/`attach_storage` in the `scale`
op's args, so the same underlying `juju add-unit ... --to ... --attach-storage ...`
invocation produced different generated code depending on which tap recorded it. A
placement-sensitive test recorded via the RPC tap alone would silently lose its unit
placement and replay onto an arbitrary machine.

This asserts on the emitted *line*, not on the intermediate args dict having some
key — a dict-shape assertion would pass even if the two sources disagreed on
formatting (e.g. one producing a list, the other a string) in a way that still
renders through `repr()` to different, non-equivalent jubilant calls.
"""

from __future__ import annotations

from jubilant_recorder.codegen import cli_translate
from jubilant_recorder.codegen.operations import scale
from jubilant_recorder.extensions.libjuju.correlate import _extract_args


def test_single_placement_and_attach_storage_emit_identically():
    cli_result = cli_translate.classify_argv(
        ["add-unit", "my-charm", "--to", "0", "--attach-storage", "foo/0"]
    )
    assert cli_result is not None
    cli_op, cli_args = cli_result
    rpc_args = _extract_args(
        "Application",
        "AddUnits",
        {
            "application": "my-charm",
            "num-units": 1,
            "placement": [{"scope": "#", "directive": "0"}],
            "attach-storage": ["storage-foo-0"],
        },
    )

    assert cli_op == "scale"
    cli_line = scale.emit({"args": cli_args}, indent=0)
    rpc_line = scale.emit({"args": rpc_args}, indent=0)

    assert cli_line == rpc_line
    assert cli_line == "juju.add_unit('my-charm', num_units=1, to='0', attach_storage='foo/0')"


def test_multiple_placements_emit_identically():
    cli_result = cli_translate.classify_argv(
        ["add-unit", "my-charm", "-n", "2", "--to", "0,lxd:1"]
    )
    assert cli_result is not None
    cli_op, cli_args = cli_result
    rpc_args = _extract_args(
        "Application",
        "AddUnits",
        {
            "application": "my-charm",
            "num-units": 2,
            "placement": [
                {"scope": "#", "directive": "0"},
                {"scope": "lxd", "directive": "1"},
            ],
        },
    )

    assert cli_op == "scale"
    cli_line = scale.emit({"args": cli_args}, indent=0)
    rpc_line = scale.emit({"args": rpc_args}, indent=0)

    assert cli_line == rpc_line
    assert cli_line == "juju.add_unit('my-charm', num_units=2, to='0,lxd:1')"


def test_no_placement_or_storage_emit_identically():
    cli_result = cli_translate.classify_argv(["add-unit", "my-charm"])
    assert cli_result is not None
    cli_op, cli_args = cli_result
    rpc_args = _extract_args(
        "Application", "AddUnits", {"application": "my-charm", "num-units": 1}
    )

    assert cli_op == "scale"
    cli_line = scale.emit({"args": cli_args}, indent=0)
    rpc_line = scale.emit({"args": rpc_args}, indent=0)

    assert cli_line == rpc_line
    assert cli_line == "juju.add_unit('my-charm', num_units=1)"
