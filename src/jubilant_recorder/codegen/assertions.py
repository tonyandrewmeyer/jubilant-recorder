"""Turn assertion tags into jubilant assertion source lines."""

from __future__ import annotations

from typing import Any


def emit(tag: dict[str, Any], indent: int, *, run_var: str | None = None) -> str:
    """Emit the source line for one assertion tag."""
    kind = tag.get("kind", "")
    pad = " " * indent
    if kind == "unit_status":
        return _emit_unit_status(tag, pad)
    if kind == "unit_count":
        return _emit_unit_count(tag, pad)
    if kind == "action_result":
        return _emit_action_result(tag, pad, run_var=run_var)
    if kind == "config_value":
        return _emit_config_value(tag, pad)
    if kind == "relation_exists":
        return _emit_relation(tag, pad, negated=False)
    if kind == "relation_absent":
        return _emit_relation(tag, pad, negated=True)
    if kind == "user_checkpoint":
        return f"{pad}# checkpoint: {tag.get('label', '')}"
    return ""


def _emit_unit_status(tag: dict[str, Any], pad: str) -> str:
    """Emit a unit-status assertion.

    jubilant exposes ``UnitStatus.workload_status`` as a ``StatusInfo``
    dataclass — compare against ``.current`` (the string name) rather than
    the StatusInfo object itself.
    """
    app = tag["app"]
    unit = tag.get("unit")
    expected = tag["expected"]
    if unit is None:
        if tag.get("scope") == "any":
            # Only some units reached the status; asserting it of all of them
            # would be a stronger claim than the recording supports.
            return (
                f"{pad}assert any(\n"
                f"{pad}    _u.workload_status.current == {expected!r}\n"
                f"{pad}    for _u in juju.status().apps[{app!r}].units.values()\n"
                f"{pad})"
            )
        loop_body = (
            f"{pad}for _u in juju.status().apps[{app!r}].units.values():\n"
            f"{pad}    assert _u.workload_status.current == {expected!r}"
        )
        return loop_body
    return (
        f"{pad}assert juju.status().apps[{app!r}]"
        f".units[{unit!r}].workload_status.current == {expected!r}"
    )


def _emit_unit_count(tag: dict[str, Any], pad: str) -> str:
    app = tag["app"]
    expected = tag["expected"]
    return f"{pad}assert len(juju.status().apps[{app!r}].units) == {expected}"


def _emit_action_result(tag: dict[str, Any], pad: str, *, run_var: str | None) -> str:
    var = run_var or "result"
    lines: list[str] = []
    expected_success = tag.get("expected_success", True)
    if expected_success:
        lines.append(f"{pad}assert {var}.success")
    else:
        lines.append(f"{pad}assert not {var}.success")
    for key, value in tag.get("expected_results", {}).items():
        lines.append(f"{pad}assert {var}.results[{key!r}] == {value!r}")
    return "\n".join(lines)


def _emit_config_value(tag: dict[str, Any], pad: str) -> str:
    app = tag["app"]
    key = tag["key"]
    expected = tag["expected"]
    return f"{pad}assert juju.config({app!r}, keys=[{key!r}])[{key!r}] == {expected!r}"


def _emit_relation(tag: dict[str, Any], pad: str, *, negated: bool) -> str:
    """Emit a relation-present assertion.

    jubilant 1.10 nests relations under each `AppStatus`:
    ``status.apps[<app>].relations`` is ``dict[str, list[AppStatusRelation]]``
    keyed by local endpoint. ``AppStatusRelation`` exposes ``related_app``,
    ``interface`` and ``scope`` — there is **no** ``related_endpoint`` field,
    so we match on the remote app alone, scoped to the local endpoint when
    we know it (when the endpoint tag includes one).

    Each endpoint tag has the form ``"<app>:<endpoint>"`` (the endpoint
    portion is optional and may be missing for unqualified integrations).
    """
    a = tag["endpoint_a"]
    b = tag["endpoint_b"]
    a_app, _, a_ep = a.partition(":")
    b_app, _, _ = b.partition(":")
    prefix = "not " if negated else ""
    if a_ep:
        return (
            f"{pad}assert {prefix}any(r.related_app == {b_app!r}\n"
            f"{pad}    for r in juju.status().apps[{a_app!r}].relations.get({a_ep!r}, []))"
        )
    return (
        f"{pad}assert {prefix}any(\n"
        f"{pad}    r.related_app == {b_app!r}\n"
        f"{pad}    for ep_rels in juju.status().apps[{a_app!r}].relations.values()\n"
        f"{pad}    for r in ep_rels)"
    )
