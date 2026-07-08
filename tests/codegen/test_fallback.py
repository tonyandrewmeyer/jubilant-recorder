from __future__ import annotations

import ast
from typing import Any

from jubilant_recorder.codegen import fallback, generate


def test_fallback_emits_todo_comment() -> None:
    event = {
        "op": "totally_unrecognized_op",
        "args": {"app": "my-charm"},
        "result": {},
    }
    out = fallback.emit(event, indent=8)
    lines = out.splitlines()
    assert lines[0] == "        # TODO: manual step — totally_unrecognized_op"
    for rest in lines[1:]:
        assert rest.startswith("        # ")


def test_fallback_payload_is_valid_json_after_strip() -> None:
    import json

    event = {
        "op": "fancy_op",
        "args": {"foo": "bar"},
        "result": {"ok": True},
    }
    out = fallback.emit(event, indent=4)
    json_lines = [line[len("    # ") :] for line in out.splitlines()[1:]]
    payload = json.loads("\n".join(json_lines))
    assert payload == {
        "op": "fancy_op",
        "args": {"foo": "bar"},
        "result": {"ok": True},
    }


def test_unknown_op_in_full_log_routes_to_fallback(
    unknown_op_log: dict[str, Any],
) -> None:
    src = generate(unknown_op_log)
    ast.parse(src)
    assert "# TODO: manual step — totally_unrecognized_op" in src
    assert "juju.totally_unrecognized_op(" not in src
