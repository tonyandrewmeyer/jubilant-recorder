"""Emit jubilant code for the remaining model-scoped ``juju`` subcommands.

One module per one-or-two-line emitter would be more modules than
information; these are grouped because each is the same shape — take the
classifier's kwargs, drop the ones at their jubilant default, render the
call. Every method named here exists on ``jubilant.Juju`` as of 1.10; where
jubilant has no method, ``cli_passthrough`` handles it instead.
"""

from __future__ import annotations

from typing import Any


def _render(indent: int, call: str, var_name: str | None = None) -> str:
    if var_name:
        return " " * indent + f"{var_name} = {call}"
    return " " * indent + call


def _kwarg(parts: list[str], args: dict[str, Any], name: str, *, default: Any = None) -> None:
    value = args.get(name)
    if value is None or value == default:
        return
    parts.append(f"{name}={value!r}")


def emit_remove_unit(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.remove_unit(...)``."""
    args = event["args"]
    parts = [repr(u) for u in args["app_or_unit"]]
    _kwarg(parts, args, "destroy_storage", default=False)
    _kwarg(parts, args, "force", default=False)
    _kwarg(parts, args, "num_units", default=0)
    return _render(indent, f"juju.remove_unit({', '.join(parts)})")


def emit_add_machine(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.add_machine(...)``."""
    args = event["args"]
    parts: list[str] = []
    target = args.get("target")
    if target:
        parts.append(repr(target))
    for name in ("base", "constraints", "disks", "private_key", "public_key"):
        _kwarg(parts, args, name)
    _kwarg(parts, args, "num_machines", default=1)
    return _render(indent, f"juju.add_machine({', '.join(parts)})")


def emit_ssh(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.ssh(...)``."""
    args = event["args"]
    parts = [repr(args["target"]), repr(args["command"])]
    parts.extend(repr(a) for a in args.get("command_args") or [])
    _kwarg(parts, args, "container")
    _kwarg(parts, args, "host_key_checks", default=True)
    _kwarg(parts, args, "user")
    return _render(indent, f"juju.ssh({', '.join(parts)})", var_name)


def emit_exec(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.exec(...)``."""
    args = event["args"]
    parts = [repr(args["command"])]
    parts.extend(repr(a) for a in args.get("command_args") or [])
    target = args["target"]
    if args["target_kind"] == "machine":
        parts.append(f"machine={target!r}")
    else:
        parts.append(f"unit={target!r}")
    _kwarg(parts, args, "wait")
    return _render(indent, f"juju.exec({', '.join(parts)})", var_name)


def emit_scp(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.scp(...)``."""
    args = event["args"]
    parts = [repr(args["source"]), repr(args["destination"])]
    _kwarg(parts, args, "container")
    _kwarg(parts, args, "host_key_checks", default=True)
    return _render(indent, f"juju.scp({', '.join(parts)})")


def emit_debug_log(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.debug_log(...)``."""
    args = event["args"]
    parts: list[str] = []
    _kwarg(parts, args, "limit", default=0)
    return _render(indent, f"juju.debug_log({', '.join(parts)})", var_name)


def emit_show_model(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.show_model(...)``."""
    args = event["args"]
    parts: list[str] = []
    model = args.get("model")
    if model:
        parts.append(repr(model))
    return _render(indent, f"juju.show_model({', '.join(parts)})", var_name)


def emit_model_config(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.model_config(...)`` — a read, a set, or a reset."""
    args = event["args"]
    parts: list[str] = []
    values = args.get("values")
    if values:
        parts.append(repr(values))
    reset = args.get("reset")
    if reset:
        parts.append(f"reset={reset[0]!r}" if len(reset) == 1 else f"reset={reset!r}")
    call = f"juju.model_config({', '.join(parts)})"
    # Only the no-argument form returns anything; a set/reset returns None,
    # so binding it to a variable would be misleading.
    return _render(indent, call, var_name if not parts else None)


def emit_model_constraints(
    event: dict[str, Any], indent: int, *, var_name: str | None = None
) -> str:
    """Emit ``juju.model_constraints(...)`` — a read or a set."""
    constraints = event["args"].get("constraints")
    if constraints:
        return _render(indent, f"juju.model_constraints({constraints!r})")
    return _render(indent, "juju.model_constraints()", var_name)


def emit_trust(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.trust(...)``."""
    args = event["args"]
    parts = [repr(args["app"])]
    _kwarg(parts, args, "remove", default=False)
    _kwarg(parts, args, "scope")
    return _render(indent, f"juju.trust({', '.join(parts)})")


def emit_refresh(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.refresh(...)``."""
    args = event["args"]
    parts = [repr(args["app"])]
    for name in ("base", "channel", "config", "path", "resources", "revision", "storage"):
        _kwarg(parts, args, name)
    _kwarg(parts, args, "force", default=False)
    _kwarg(parts, args, "trust", default=False)
    return _render(indent, f"juju.refresh({', '.join(parts)})")


def emit_add_ssh_key(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.add_ssh_key(...)``."""
    keys = event["args"]["keys"]
    return _render(indent, f"juju.add_ssh_key({', '.join(repr(k) for k in keys)})")


def emit_remove_ssh_key(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.remove_ssh_key(...)``."""
    ids = event["args"]["ids"]
    return _render(indent, f"juju.remove_ssh_key({', '.join(repr(i) for i in ids)})")


def emit_version(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.version()``."""
    del event
    return _render(indent, "juju.version()", var_name)


def emit_show_secret(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.show_secret(...)``."""
    args = event["args"]
    parts = [repr(args["identifier"])]
    _kwarg(parts, args, "reveal", default=False)
    _kwarg(parts, args, "revision")
    _kwarg(parts, args, "revisions", default=False)
    return _render(indent, f"juju.show_secret({', '.join(parts)})", var_name)


def emit_secret_add_cli(event: dict[str, Any], indent: int, *, var_name: str | None = None) -> str:
    """Emit ``juju.add_secret(...)`` from a recorded ``juju add-secret``.

    Distinct from ``secret_add``, which renders the libjuju
    ``Secrets.CreateSecrets`` shape: that path redacts content at record
    time and so can only emit placeholder keys, whereas a CLI ``key=value``
    carries whatever survived `jubilant_recorder.redaction`.
    """
    args = event["args"]
    parts = [repr(args["name"]), repr(args["content"])]
    _kwarg(parts, args, "info")
    return _render(indent, f"juju.add_secret({', '.join(parts)})", var_name)


def emit_secret_update_cli(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.update_secret(...)`` from a recorded ``juju update-secret``."""
    args = event["args"]
    parts = [repr(args["identifier"]), repr(args["content"])]
    _kwarg(parts, args, "info")
    _kwarg(parts, args, "name")
    _kwarg(parts, args, "auto_prune", default=False)
    return _render(indent, f"juju.update_secret({', '.join(parts)})")


_WAIT_READY = {
    "application": "jubilant.all_active",
    "unit": "jubilant.all_active",
    "machine": "jubilant.all_active",
    "model": "jubilant.all_active",
}


def emit_wait_for(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.wait(...)`` for a default-query ``juju wait-for``.

    ``juju wait-for`` without ``--query`` waits for everything in scope to
    reach active/idle, which is what ``jubilant.all_active`` tests. A
    ``--query`` expression is a different language with no mapping, so
    ``cli_translate`` keeps those on ``juju.cli`` rather than guessing here.

    The scope's targets are rendered as ``apps=[…]`` where jubilant's
    ``all_active`` accepts them, so a wait recorded against one application
    does not become a wait on the whole model.
    """
    args = event["args"]
    scope = args["scope"]
    targets = args.get("targets") or []
    pad = " " * indent
    ready = _WAIT_READY[scope]
    if scope in ("application", "unit") and targets:
        apps = sorted({t.split("/")[0] for t in targets}) if scope == "unit" else sorted(targets)
        rendered = ", ".join(repr(a) for a in apps)
        ready = f"lambda status: {ready}(status, {rendered})"
    parts = [ready]
    timeout = args.get("timeout")
    if timeout:
        parts.append(f"timeout={timeout!r}")
    line = f"{pad}juju.wait({', '.join(parts)})"
    if scope == "machine":
        return (
            f"{pad}# `juju wait-for machine {' '.join(targets)}` — jubilant has no\n"
            f"{pad}# machine-scoped predicate; this waits for the workloads instead.\n" + line
        )
    return line
