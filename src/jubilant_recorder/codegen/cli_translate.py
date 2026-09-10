"""``juju`` argv -> jubilant translation for PATH-shim shell-capture events.

Classifies each recorded shim event (``op: "shell"``, ``args.source ==
"shim"``, ``args.argv`` the raw ``juju`` argv minus the ``juju`` binary
itself) and turns it into a jubilant call.

The classification is **total**: every non-empty argv produces an op.
Where the argv shape maps cleanly onto a ``jubilant.Juju`` method it
produces that method's typed op; where it does not — an unhandled
subcommand, or a handled one used with a flag outside the mapped
subset — it produces ``cli_passthrough``, which renders as
``juju.cli(...)``. Only an empty argv (a bare ``juju``, which prints help
and does nothing) returns ``None``, and only that still renders as a
``# shell:`` comment.

That is the whole design: the reader of a generated test should never have
to retype a command the recording already captured. ``juju.cli()`` is
jubilant's documented escape hatch and returns the command's standard
output, so the passthrough loses the *typing* of an operation, never the
operation.

Design rule used throughout: each classifier only recognizes the flags it
has deliberate handling for (mapped to a kwarg, or a documented "harmless
to drop" output-shape flag; the juju-wide logging and output flags in
``_GLOBAL_BOOLEAN``/``_GLOBAL_VALUED`` are always droppable). Any other
``-``-prefixed token — including one this module has simply never heard
of — aborts classification immediately, and the whole command goes to
``juju.cli`` verbatim. This means a flag that would otherwise be silently
misparsed as a positional (corrupting the translation) can never reach
that code path: we bail at the flag, before ever touching the tokens after
it. The bias is "an untyped call that is right beats a typed call that is
a guess", applied structurally rather than case-by-case.

Version pin: the flag tables below are the Juju CLI surface, cross-checked
against ``juju help <subcommand>`` on 3.6.28. A session recorded against a
different client may misclassify (a flag that exists on one and not the
other) — that costs the command its typed translation and sends it to
``juju.cli``, which is a degradation rather than a failure.
``NO_MODEL_SUBCOMMANDS`` carries the command to regenerate it.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# See module docstring "Version pin" above.
JUJU_CLIENT_VERSION = "3.6.28"

_ALIASES = {
    "relate": "integrate",
    "add-relation": "integrate",
    "destroy-relation": "remove-relation",
    "destroy-model": "destroy-model",
    "list-secrets": "secrets",
    "list-offers": "offers",
    "list-offer": "offers",
}

_UNIT_RE = re.compile(r"^[\w][\w-]*/(?:leader|\d+)$")
_UINT_RE = re.compile(r"^\d+$")

# Flags juju accepts on (almost) every subcommand, which change only how the
# client logs or renders — never what the operation does. `_parse` tolerates
# and discards them by default, so that a `juju deploy ubuntu --debug` still
# reaches `_classify_deploy` instead of being pushed onto `juju.cli` by a
# token that has no bearing on the translation. jubilant's typed methods all
# choose their own output format, so `--format`/`-o` are droppable for the
# same reason.
#
# Taken from the `Options` block that `juju help <subcommand>` prints on
# 3.6.28; the four `--…-log`/logging spellings and `-B` are the ones the
# command framework injects rather than any individual command.
_GLOBAL_BOOLEAN = frozenset(
    {
        "--debug",
        "--quiet",
        "--verbose",
        "--show-log",
        "--no-browser-login",
        "--color",
        "--no-color",
        "--utc",
    }
)
_GLOBAL_VALUED = frozenset({"--logging-config", "--format", "--output"})
_GLOBAL_ALIASES = {"-B": "--no-browser-login", "-o": "--output"}


@dataclasses.dataclass
class _Parsed:
    positionals: list[str]
    flags: dict[str, list[str | None]]


def _parse(
    rest: list[str],
    *,
    aliases: dict[str, str] | None = None,
    valued: frozenset[str] = frozenset(),
    boolean: frozenset[str] = frozenset(),
    globals_ok: bool = True,
    stop_at_positional: bool = False,
) -> _Parsed | None:
    """Tokenize a subcommand's argv into positionals + recognized flags.

    Returns ``None`` (caller should fall back to `juju.cli`) the moment it
    sees a ``-``-prefixed token that isn't (after alias resolution) in
    ``valued``/``boolean`` — see module docstring. Also returns ``None`` if a
    valued flag is the last token with no value following, or a boolean flag
    is given a ``--flag=value`` form.

    ``globals_ok`` (the default) additionally accepts the juju-wide logging
    and output flags in `_GLOBAL_BOOLEAN`/`_GLOBAL_VALUED`; a caller that
    defines its own meaning for one of those spellings passes its own entry,
    which wins.

    ``stop_at_positional`` ends flag parsing at the first non-flag token, so
    everything from there on is a positional even if it starts with ``-``.
    `juju ssh`/`exec`/`scp` need this: the tokens after the target are a
    *remote* command whose own flags (``ls -la``) must not be parsed, or
    silently swallowed, as juju's.
    """
    aliases = {**_GLOBAL_ALIASES, **(aliases or {})} if globals_ok else (aliases or {})
    if globals_ok:
        boolean = (boolean | _GLOBAL_BOOLEAN) - valued
        valued = valued | (_GLOBAL_VALUED - boolean)
    positionals: list[str] = []
    flags: dict[str, list[str | None]] = {}
    i = 0
    n = len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            positionals.extend(rest[i + 1 :])
            break
        if tok.startswith("-") and tok != "-" and not (stop_at_positional and positionals):
            if tok.startswith("--") and "=" in tok:
                name, _, value = tok.partition("=")
            else:
                name, value = tok, None
            canonical = aliases.get(name, name)
            if canonical in boolean:
                if value is not None:
                    return None
                flags.setdefault(canonical, []).append(None)
                i += 1
                continue
            if canonical in valued:
                if value is None:
                    i += 1
                    if i >= n:
                        return None
                    value = rest[i]
                flags.setdefault(canonical, []).append(value)
                i += 1
                continue
            return None
        positionals.append(tok)
        i += 1
    return _Parsed(positionals=positionals, flags=flags)


def _last(values: list[str | None] | None) -> str | None:
    if not values:
        return None
    return values[-1]


def _strs(values: list[str | None] | None) -> list[str]:
    """Filter a flag's collected values down to `str`.

    Only boolean flags ever store `None` entries; a `valued`-flag's values
    are always strings, but `_Parsed.flags`'s shared type can't express that
    per-key distinction — this narrows it back for `_fold_kv`/`_fold_config`.
    """
    return [v for v in (values or []) if v is not None]


def _fold_kv(values: list[str]) -> dict[str, str] | None:
    """Fold repeated ``key=value`` flag occurrences into a dict, last wins."""
    result: dict[str, str] = {}
    for v in values:
        if "=" not in v:
            return None
        key, _, val = v.partition("=")
        result[key] = val
    return result


def _fold_config(values: list[str]) -> dict[str, str] | None:
    """Fold repeated ``--config`` flags into a dict, last wins.

    Unlike ``_fold_kv``, a bare path or ``key=@path`` (file content not in
    argv) aborts the whole fold, not just that entry.
    """
    result: dict[str, str] = {}
    for v in values:
        if "=" not in v:
            return None
        key, _, val = v.partition("=")
        if val.startswith("@"):
            return None
        result[key] = val
    return result


def _yaml_scalar(raw: str) -> Any:
    """YAML-type a `run` param value the way juju itself does.

    Uses PyYAML's ``safe_load`` as the "YAML-typed" implementation. One
    known divergence from real juju CLI behaviour, found while implementing
    this rather than assumed: juju's own YAML-1.1-ish parser treats bare
    ``y``/``n`` as booleans, but PyYAML's default (non-1.1) resolver does
    not — only the full words (``yes``/``no``/``true``/``false``/``on``/
    ``off``) coerce. A recorded ``key=y`` stays the string ``"y"`` here
    rather than becoming ``True``. Not fixed: hand-rolling a YAML-1.1
    resolver to match one juju quirk is out of proportion to the risk (bare
    ``y``/``n`` action params are rare in practice), but this is a real gap
    between juju's actual CLI behaviour and what this module does —
    flagged rather than silently shipped.
    """
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _set_dotted(d: dict[str, Any], keys: list[str], value: Any) -> None:
    node = d
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------

_DEPLOY_ALIASES = {"-n": "--num-units"}
_DEPLOY_VALUED = frozenset(
    {
        "--base",
        "--channel",
        "--revision",
        "--num-units",
        "--to",
        "--constraints",
        "--resource",
        "--config",
    }
)
_DEPLOY_BOOLEAN = frozenset({"--force", "--trust"})


def _classify_deploy(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases=_DEPLOY_ALIASES, valued=_DEPLOY_VALUED, boolean=_DEPLOY_BOOLEAN)
    if parsed is None or not parsed.positionals:
        return None
    charm = parsed.positionals[0]
    app = parsed.positionals[1] if len(parsed.positionals) > 1 else None
    if len(parsed.positionals) > 2:
        return None

    args: dict[str, Any] = {"charm": charm}
    if app:
        args["app"] = app
    base = _last(parsed.flags.get("--base"))
    if base:
        args["base"] = base
    channel = _last(parsed.flags.get("--channel"))
    if channel:
        args["channel"] = channel
    revision = _last(parsed.flags.get("--revision"))
    if revision is not None:
        if not re.match(r"^-?\d+$", revision):
            return None
        args["revision"] = int(revision)
    num_units = _last(parsed.flags.get("--num-units"))
    if num_units is not None:
        if not _UINT_RE.match(num_units):
            return None
        args["num_units"] = int(num_units)
    to = _last(parsed.flags.get("--to"))
    if to:
        args["to"] = to
    if parsed.flags.get("--force"):
        args["force"] = True
    if parsed.flags.get("--trust"):
        args["trust"] = True

    constraints = _fold_kv(_strs(parsed.flags.get("--constraints")))
    if constraints is None and parsed.flags.get("--constraints"):
        return None
    if constraints:
        args["constraints"] = constraints

    resources = _fold_kv(_strs(parsed.flags.get("--resource")))
    if resources is None and parsed.flags.get("--resource"):
        return None
    if resources:
        args["resources"] = resources

    config_flag = parsed.flags.get("--config")
    if config_flag:
        config_values = _fold_config(_strs(config_flag))
        if config_values is None:
            return None  # file-content shape
        if config_values:
            args["config"] = config_values

    return "deploy", args


# ---------------------------------------------------------------------------
# config / config_get / config_unset
# ---------------------------------------------------------------------------

_CONFIG_ALIASES = {"-m": "--model"}
_CONFIG_VALUED = frozenset({"--file", "--reset", "--model"})
_CONFIG_EXCEPTED = frozenset({"--file", "--model"})


def _classify_config(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases=_CONFIG_ALIASES, valued=_CONFIG_VALUED)
    if parsed is None or not parsed.positionals:
        return None
    if _CONFIG_EXCEPTED & parsed.flags.keys():
        return None  # --file / --model — file content, or cross-model

    app = parsed.positionals[0]
    rest_pos = parsed.positionals[1:]

    reset_value = _last(parsed.flags.get("--reset"))
    if reset_value is not None:
        if rest_pos:
            return None
        options = [k for k in reset_value.split(",") if k]
        if not options:
            return None
        return "config_unset", {"app": app, "options": options}

    kv_positionals = [p for p in rest_pos if "=" in p]
    if kv_positionals:
        if len(kv_positionals) != len(rest_pos):
            return None  # mixed key=value and bare tokens — unexpected shape
        values: dict[str, Any] = {}
        for p in rest_pos:
            key, _, val = p.partition("=")
            if val.startswith("@"):
                return None  # key=@path file directive
            values[key] = val
        if not values:
            return None
        return "config", {"app": app, "values": values}

    if len(rest_pos) > 1:
        return None
    return "config_get", {"app": app, "keys": rest_pos or None}


# ---------------------------------------------------------------------------
# refresh -> set_charm
# ---------------------------------------------------------------------------

_REFRESH_VALUED = frozenset(
    {"--base", "--channel", "--config", "--path", "--resource", "--revision", "--storage"}
)
_REFRESH_BOOLEAN = frozenset({"--force", "--force-base", "--force-units", "--trust"})


def _classify_refresh(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju refresh APP`` -> ``juju.refresh(...)``.

    ``--switch`` has no ``Juju.refresh()`` keyword (jubilant refreshes an
    application in place, it does not swap the charm), so that shape falls
    through to ``juju.cli("refresh", …)`` where the switch target survives.
    The ``set_charm`` op is *not* reused here: it is the libjuju
    ``Application.SetCharm`` shape, which carries a resolved charm URL and
    is emitted as ``juju.cli`` for exactly that reason.
    """
    parsed = _parse(rest, valued=_REFRESH_VALUED, boolean=_REFRESH_BOOLEAN)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"app": parsed.positionals[0]}
    base = _last(parsed.flags.get("--base"))
    if base:
        args["base"] = base
    channel = _last(parsed.flags.get("--channel"))
    if channel:
        args["channel"] = channel
    path = _last(parsed.flags.get("--path"))
    if path:
        args["path"] = path
    revision = _last(parsed.flags.get("--revision"))
    if revision is not None:
        if not _UINT_RE.match(revision):
            return None
        args["revision"] = int(revision)
    config = _fold_config(_strs(parsed.flags.get("--config")))
    if config is None and parsed.flags.get("--config"):
        return None
    if config:
        args["config"] = config
    resources = _fold_kv(_strs(parsed.flags.get("--resource")))
    if resources is None and parsed.flags.get("--resource"):
        return None
    if resources:
        args["resources"] = resources
    storage = _fold_kv(_strs(parsed.flags.get("--storage")))
    if storage is None and parsed.flags.get("--storage"):
        return None
    if storage:
        args["storage"] = storage
    if (
        parsed.flags.get("--force")
        or parsed.flags.get("--force-base")
        or parsed.flags.get("--force-units")
    ):
        args["force"] = True
    if parsed.flags.get("--trust"):
        args["trust"] = True
    return "refresh", args


# ---------------------------------------------------------------------------
# remove-application
# ---------------------------------------------------------------------------


_REMOVE_APP_BOOLEAN = frozenset(
    {"--no-prompt", "-y", "--yes", "--destroy-storage", "--force", "--no-wait", "--dry-run"}
)


def _classify_remove_application(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-y": "--no-prompt", "--yes": "--no-prompt"},
        boolean=_REMOVE_APP_BOOLEAN,
    )
    if parsed is None or not parsed.positionals:
        return None
    if parsed.flags.get("--dry-run"):
        return None  # a dry run changed nothing; it is not a step to replay
    apps = parsed.positionals
    args: dict[str, Any] = {"app": apps[0] if len(apps) == 1 else apps}
    if parsed.flags.get("--destroy-storage"):
        args["destroy_storage"] = True
    if parsed.flags.get("--force"):
        args["force"] = True
    # `--no-prompt` is not carried: jubilant's `remove_application()` always
    # passes it, since a library call has no terminal to prompt at.
    return "remove_application", args


# ---------------------------------------------------------------------------
# integrate/relate, remove-relation
# ---------------------------------------------------------------------------


def _classify_integrate(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    a, b = parsed.positionals
    if "." in a.split(":", 1)[0] or "." in b.split(":", 1)[0]:
        return None  # dotted model-qualified — cross-model
    return "integrate", {"app1_endpoint": a, "app2_endpoint": b}


def _classify_remove_relation(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    a, b = parsed.positionals
    return "remove_integration", {"app1_endpoint": a, "app2_endpoint": b}


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


_RUN_VALUED = frozenset({"--wait", "--format"})
_RUN_BOOLEAN = frozenset({"--string-args", "--background", "--utc"})


def _classify_run(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-o": "--format"}, valued=_RUN_VALUED, boolean=_RUN_BOOLEAN)
    if parsed is None or parsed.flags.get("--background"):
        return None
    positionals = parsed.positionals

    units: list[str] = []
    i = 0
    while i < len(positionals) and _UNIT_RE.match(positionals[i]):
        units.append(positionals[i])
        i += 1
    if len(units) != 1:
        return None  # zero units, or multi-unit — `Juju.run()` takes exactly one
    if i >= len(positionals):
        return None  # no action name captured
    action = positionals[i]
    i += 1

    string_args = bool(parsed.flags.get("--string-args"))
    params: dict[str, Any] = {}
    for tok in positionals[i:]:
        if "=" not in tok:
            return None
        key_path, _, raw_value = tok.partition("=")
        if not key_path:
            return None
        value = raw_value if string_args else _yaml_scalar(raw_value)
        _set_dotted(params, key_path.split("."), value)

    args: dict[str, Any] = {"unit": units[0], "action": action}
    if params:
        args["params"] = params
    wait = _last(parsed.flags.get("--wait"))
    if wait is not None:
        seconds = _duration_seconds(wait)
        if seconds is None:
            return None
        args["wait"] = seconds
    return "run", args


# ---------------------------------------------------------------------------
# add-unit / scale-application -> scale (F1/F2 promotion — see scale.py)
# ---------------------------------------------------------------------------


_ADD_UNIT_VALUED = frozenset({"--num-units", "--to", "--attach-storage"})


def _classify_add_unit(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-n": "--num-units"}, valued=_ADD_UNIT_VALUED)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    app = parsed.positionals[0]
    units_str = _last(parsed.flags.get("--num-units"))
    units = 1
    if units_str is not None:
        if not _UINT_RE.match(units_str):
            return None
        units = int(units_str)
    args: dict[str, Any] = {"app": app, "units": units, "mode": "relative"}
    # `--to` is a single StringVar upstream (cmd/juju/application/addunit.go) — a
    # repeated occurrence just overwrites, so `_last()` matches real CLI semantics.
    to = _last(parsed.flags.get("--to"))
    if to:
        args["to"] = to
    # `--attach-storage` is NOT single-valued upstream: it's a `flag.Var` over a
    # custom `attachStorageFlag` (cmd/juju/application/flags.go) whose `Set()`
    # comma-splits *and* appends across repeated occurrences, so
    # `--attach-storage a --attach-storage b` accumulates both. `_last()` would
    # silently drop everything but the final occurrence — comma-join every
    # occurrence's values instead so nothing is lost.
    attach_storage_values = _strs(parsed.flags.get("--attach-storage"))
    if attach_storage_values:
        args["attach_storage"] = ",".join(attach_storage_values)
    return "scale", args


def _classify_scale_application(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    app, scale_str = parsed.positionals
    if not _UINT_RE.match(scale_str):
        return None
    return "scale", {"app": app, "units": int(scale_str), "mode": "absolute"}


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------


def _classify_remove_secret(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=frozenset({"--revision"}))
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"identifier": parsed.positionals[0]}
    revision = _last(parsed.flags.get("--revision"))
    if revision is not None:
        if not _UINT_RE.match(revision):
            return None
        args["revision"] = int(revision)
    return "secret_remove", args


def _classify_grant_secret(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju grant-secret ID app[,app...]`` -> ``juju.grant_secret(...)``.

    The CLI takes its applications comma-joined in one argument;
    ``Juju.grant_secret()`` takes ``str | Iterable[str]``. Split so a grant
    to several applications reads as the list it is.
    """
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    identifier, app_arg = parsed.positionals
    apps = [a for a in app_arg.split(",") if a]
    if not apps:
        return None
    return "secret_grant", {"identifier": identifier, "app": apps[0] if len(apps) == 1 else apps}


_SECRETS_ALIASES = {"-o": "--format"}
_SECRETS_VALUED = frozenset({"--owner", "--format"})
_SECRETS_BOOLEAN = frozenset({"--revisions"})


def _classify_secrets(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest, aliases=_SECRETS_ALIASES, valued=_SECRETS_VALUED, boolean=_SECRETS_BOOLEAN
    )
    if parsed is None or parsed.positionals:
        return None
    args: dict[str, Any] = {}
    owner = _last(parsed.flags.get("--owner"))
    if owner is not None:
        args["owner"] = owner
    return "secret_list", args


# ---------------------------------------------------------------------------
# cross-model (CMR)
# ---------------------------------------------------------------------------


def _classify_offer(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals or len(parsed.positionals) > 2:
        return None
    spec = parsed.positionals[0]
    offer_name = parsed.positionals[1] if len(parsed.positionals) == 2 else None
    if ":" not in spec:
        return None
    app_part, _, endpoints_part = spec.partition(":")
    if not app_part or "." in app_part:
        return None  # dotted model-qualified app
    endpoints = [e for e in endpoints_part.split(",") if e]
    if not endpoints:
        return None
    args: dict[str, Any] = {"app": app_part, "endpoints": endpoints}
    if offer_name:
        args["offer_name"] = offer_name
    return "create_offer", args


def _classify_consume(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals or len(parsed.positionals) > 2:
        return None
    args: dict[str, Any] = {"offer_url": parsed.positionals[0]}
    if len(parsed.positionals) == 2:
        args["application_alias"] = parsed.positionals[1]
    return "consume", args


_OFFERS_VALUED = frozenset(
    {"--interface", "--application", "--connected-user", "--allowed-consumer"}
)
_OFFERS_BOOLEAN = frozenset({"--active-only"})


def _classify_offers(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=_OFFERS_VALUED, boolean=_OFFERS_BOOLEAN)
    if parsed is None or len(parsed.positionals) > 1:
        return None
    return "list_offers", {}


def _classify_remove_offer(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, boolean=frozenset({"--force"}))
    if parsed is None or not parsed.positionals:
        return None
    args: dict[str, Any] = {"offer_urls": list(parsed.positionals)}
    if parsed.flags.get("--force"):
        args["force"] = True
    return "remove_offer", args


def _classify_show_offer(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    return "get_consume_details", {"offer_urls": list(parsed.positionals)}


def _classify_remove_saas(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 1:
        return None  # multi-name not representable by remove_saas.py
    return "remove_saas", {"app": parsed.positionals[0]}


# ---------------------------------------------------------------------------
# expose / unexpose
# ---------------------------------------------------------------------------


def _classify_expose(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    return "expose", {"app": parsed.positionals[0]}


def _classify_unexpose(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=frozenset({"--endpoints"}))
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"app": parsed.positionals[0]}
    endpoints_val = _last(parsed.flags.get("--endpoints"))
    if endpoints_val is not None:
        endpoints = [e for e in endpoints_val.split(",") if e]
        if endpoints:
            args["exposed_endpoints"] = endpoints
    return "unexpose", args


# ---------------------------------------------------------------------------
# set-constraints
# ---------------------------------------------------------------------------


def _classify_set_constraints(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) < 2:
        return None
    app = parsed.positionals[0]
    constraints: dict[str, str] = {}
    for tok in parsed.positionals[1:]:
        if "=" not in tok:
            return None
        key, _, val = tok.partition("=")
        constraints[key] = val
    if not constraints:
        return None
    return "set_constraints", {"app": app, "constraints": constraints}


# ---------------------------------------------------------------------------
# bind -> merge_bindings
# ---------------------------------------------------------------------------


def _classify_bind(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, boolean=frozenset({"--force"}))
    if parsed is None or not parsed.positionals:
        return None
    app = parsed.positionals[0]
    remaining = parsed.positionals[1:]
    bindings: dict[str, str] = {}
    if remaining and "=" not in remaining[0]:
        bindings[""] = remaining[0]
        remaining = remaining[1:]
    for tok in remaining:
        if "=" not in tok:
            return None
        key, _, val = tok.partition("=")
        bindings[key] = val
    args: dict[str, Any] = {"app": app}
    if bindings:
        args["bindings"] = bindings
    if parsed.flags.get("--force"):
        args["force"] = True
    return "merge_bindings", args


# ---------------------------------------------------------------------------
# suspend-relation / resume-relation -> set_relations_suspended
# ---------------------------------------------------------------------------


def _classify_suspend_relation(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=frozenset({"--message"}))
    if parsed is None or not parsed.positionals:
        return None
    args: dict[str, Any] = {"relation_ids": list(parsed.positionals), "suspended": True}
    message = _last(parsed.flags.get("--message"))
    if message is not None:
        args["message"] = message
    return "set_relations_suspended", args


def _classify_resume_relation(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    return "set_relations_suspended", {
        "relation_ids": list(parsed.positionals),
        "suspended": False,
    }


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

_STATUS_VALUED = frozenset({"--watch", "--retry-count", "--retry-delay"})
_STATUS_BOOLEAN = frozenset({"--relations", "--integrations", "--storage"})


def _classify_status(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju status`` -> ``juju.status()``.

    Output-shape flags (``--format``, ``--relations``, colour) are dropped:
    ``juju.status()`` always fetches ``--format json`` and returns a typed
    :class:`jubilant.Status`, so the recorded rendering choice has no
    bearing on the generated test. A positional filter (``juju status
    ubuntu``) is *not* dropped — jubilant has no filter argument, so that
    shape falls through to ``juju.cli`` where the filter survives.
    """
    parsed = _parse(rest, valued=_STATUS_VALUED, boolean=_STATUS_BOOLEAN)
    if parsed is None or parsed.positionals:
        return None
    if parsed.flags.get("--watch"):
        return None  # a blocking watch is not a single status call
    return "status_call", {}


# ---------------------------------------------------------------------------
# model lifecycle: add-model / destroy-model / switch
# ---------------------------------------------------------------------------

_ADD_MODEL_VALUED = frozenset({"--config", "--credential", "--controller", "-c"})
_ADD_MODEL_BOOLEAN = frozenset({"--no-switch"})


def _classify_add_model(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-c": "--controller"},
        valued=_ADD_MODEL_VALUED,
        boolean=_ADD_MODEL_BOOLEAN,
    )
    if parsed is None or not parsed.positionals or len(parsed.positionals) > 2:
        return None
    args: dict[str, Any] = {"model": parsed.positionals[0]}
    if len(parsed.positionals) == 2:
        args["cloud"] = parsed.positionals[1]
    controller = _last(parsed.flags.get("--controller"))
    if controller:
        args["controller"] = controller
    credential = _last(parsed.flags.get("--credential"))
    if credential:
        args["credential"] = credential
    config = _fold_config(_strs(parsed.flags.get("--config")))
    if config is None and parsed.flags.get("--config"):
        return None
    if config:
        args["config"] = config
    return "add_model", args


_DESTROY_MODEL_VALUED = frozenset({"--timeout"})
_DESTROY_MODEL_BOOLEAN = frozenset(
    {
        "--no-prompt",
        "-y",
        "--yes",
        "--destroy-storage",
        "--release-storage",
        "--force",
        "--no-wait",
    }
)


def _classify_destroy_model(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-y": "--no-prompt", "--yes": "--no-prompt"},
        valued=_DESTROY_MODEL_VALUED,
        boolean=_DESTROY_MODEL_BOOLEAN,
    )
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"model": parsed.positionals[0]}
    if parsed.flags.get("--destroy-storage"):
        args["destroy_storage"] = True
    if parsed.flags.get("--release-storage"):
        args["release_storage"] = True
    if parsed.flags.get("--force"):
        args["force"] = True
    if parsed.flags.get("--no-wait"):
        args["no_wait"] = True
    timeout = _last(parsed.flags.get("--timeout"))
    if timeout is not None:
        seconds = _duration_seconds(timeout)
        if seconds is None:
            return None
        args["timeout"] = seconds
    return "destroy_model", args


def _classify_switch(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    return "switch_model", {"model": parsed.positionals[0]}


def _duration_seconds(raw: str) -> float | None:
    """Parse a Go-style duration (``30s``, ``5m``, ``1h``) or bare seconds."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", raw)
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2) or "s"
    return value * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]


# ---------------------------------------------------------------------------
# remove-unit
# ---------------------------------------------------------------------------

_REMOVE_UNIT_VALUED = frozenset({"--num-units"})
_REMOVE_UNIT_BOOLEAN = frozenset({"--no-prompt", "-y", "--yes", "--destroy-storage", "--force"})


def _classify_remove_unit(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-y": "--no-prompt", "--yes": "--no-prompt", "-n": "--num-units"},
        valued=_REMOVE_UNIT_VALUED,
        boolean=_REMOVE_UNIT_BOOLEAN,
    )
    if parsed is None or not parsed.positionals:
        return None
    args: dict[str, Any] = {"app_or_unit": list(parsed.positionals)}
    num_units = _last(parsed.flags.get("--num-units"))
    if num_units is not None:
        if not _UINT_RE.match(num_units) or len(parsed.positionals) > 1:
            return None
        args["num_units"] = int(num_units)
    if parsed.flags.get("--destroy-storage"):
        args["destroy_storage"] = True
    if parsed.flags.get("--force"):
        args["force"] = True
    return "remove_unit", args


# ---------------------------------------------------------------------------
# add-machine
# ---------------------------------------------------------------------------

_ADD_MACHINE_VALUED = frozenset(
    {"--base", "--constraints", "--disks", "--num-machines", "--private-key", "--public-key"}
)


def _classify_add_machine(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-n": "--num-machines"}, valued=_ADD_MACHINE_VALUED)
    if parsed is None or len(parsed.positionals) > 1:
        return None
    args: dict[str, Any] = {}
    if parsed.positionals:
        args["target"] = parsed.positionals[0]
    base = _last(parsed.flags.get("--base"))
    if base:
        args["base"] = base
    constraints = _fold_kv(_strs(parsed.flags.get("--constraints")))
    if constraints is None and parsed.flags.get("--constraints"):
        return None
    if constraints:
        args["constraints"] = constraints
    disks = _last(parsed.flags.get("--disks"))
    if disks:
        args["disks"] = disks
    num_machines = _last(parsed.flags.get("--num-machines"))
    if num_machines is not None:
        if not _UINT_RE.match(num_machines):
            return None
        args["num_machines"] = int(num_machines)
    private_key = _last(parsed.flags.get("--private-key"))
    if private_key:
        args["private_key"] = private_key
    public_key = _last(parsed.flags.get("--public-key"))
    if public_key:
        args["public_key"] = public_key
    return "add_machine", args


# ---------------------------------------------------------------------------
# ssh / exec / scp
# ---------------------------------------------------------------------------

_SSH_VALUED = frozenset({"--container", "--pty"})
_SSH_BOOLEAN = frozenset({"--no-host-key-checks", "--proxy", "--remote"})


def _classify_ssh(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju ssh <target> <command...>`` -> ``juju.ssh(target, command, ...)``.

    A bare ``juju ssh <target>`` (an interactive login, no command) has no
    jubilant equivalent — ``ssh()`` requires a command — so it falls through
    to ``juju.cli``, where it stays as recorded.
    """
    parsed = _parse(rest, valued=_SSH_VALUED, boolean=_SSH_BOOLEAN, stop_at_positional=True)
    if parsed is None or len(parsed.positionals) < 2:
        return None
    target, *command = parsed.positionals
    user = None
    if "@" in target:
        user, _, target = target.partition("@")
        if not user or not target:
            return None
    args: dict[str, Any] = {"target": target, "command": command[0]}
    if len(command) > 1:
        args["command_args"] = command[1:]
    container = _last(parsed.flags.get("--container"))
    if container:
        args["container"] = container
    if parsed.flags.get("--no-host-key-checks"):
        args["host_key_checks"] = False
    if user:
        args["user"] = user
    return "ssh", args


_EXEC_VALUED = frozenset({"--machine", "--unit", "--application", "--wait", "--execution-group"})
_EXEC_BOOLEAN = frozenset({"--all", "--background", "--operator", "--parallel"})


def _classify_exec(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju exec --unit u -- cmd`` -> ``juju.exec('cmd', unit='u')``.

    jubilant's ``exec()`` targets exactly one machine or unit, so the
    multi-target shapes (``--all``, ``--application``, a comma-separated
    ``--unit``) fall through to ``juju.cli``.
    """
    parsed = _parse(
        rest,
        aliases={"-u": "--unit", "-a": "--application", "--app": "--application"},
        valued=_EXEC_VALUED,
        boolean=_EXEC_BOOLEAN,
        stop_at_positional=True,
    )
    if parsed is None or not parsed.positionals:
        return None
    if parsed.flags.get("--all") or parsed.flags.get("--application"):
        return None
    machine = _last(parsed.flags.get("--machine"))
    unit = _last(parsed.flags.get("--unit"))
    if (machine is None) == (unit is None):
        return None  # neither, or both
    target = machine if machine is not None else unit
    if target is None:  # unreachable: the xor check above guarantees one
        return None
    if "," in target:
        return None  # multi-target
    args: dict[str, Any] = {
        "command": parsed.positionals[0],
        "target_kind": "machine" if machine is not None else "unit",
        "target": target,
    }
    if len(parsed.positionals) > 1:
        args["command_args"] = parsed.positionals[1:]
    wait = _last(parsed.flags.get("--wait"))
    if wait is not None:
        seconds = _duration_seconds(wait)
        if seconds is None:
            return None
        if seconds:
            args["wait"] = seconds
    return "exec", args


_SCP_VALUED = frozenset({"--container"})
_SCP_BOOLEAN = frozenset({"--no-host-key-checks", "--proxy", "--remote"})


def _classify_scp(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju scp SOURCE DEST`` -> ``juju.scp(...)``.

    Anything between the flags and the two paths — the ``-r``/``-C``-style
    options `juju scp` forwards to the real ``scp`` — makes this more than
    two positionals, so those invocations stay on ``juju.cli``. jubilant's
    ``scp_options`` could carry them, but only if we could tell an option
    apart from a path, which after a bare ``--`` separator we cannot.
    """
    parsed = _parse(rest, valued=_SCP_VALUED, boolean=_SCP_BOOLEAN)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    source, destination = parsed.positionals
    args: dict[str, Any] = {"source": source, "destination": destination}
    container = _last(parsed.flags.get("--container"))
    if container:
        args["container"] = container
    if parsed.flags.get("--no-host-key-checks"):
        args["host_key_checks"] = False
    return "scp", args


# ---------------------------------------------------------------------------
# debug-log
# ---------------------------------------------------------------------------

_DEBUG_LOG_VALUED = frozenset({"--limit", "--lines"})
_DEBUG_LOG_BOOLEAN = frozenset({"--no-tail", "--tail", "--replay", "--date", "--ms", "--location"})


def _classify_debug_log(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju debug-log --no-tail`` -> ``juju.debug_log()``.

    Without ``--no-tail`` the real command follows the log forever, which is
    not a step a generated test can contain — that shape stays on
    ``juju.cli`` so the reader sees exactly what was typed and can decide.
    """
    parsed = _parse(
        rest, aliases={"-n": "--lines"}, valued=_DEBUG_LOG_VALUED, boolean=_DEBUG_LOG_BOOLEAN
    )
    if parsed is None or parsed.positionals:
        return None
    if not parsed.flags.get("--no-tail") or parsed.flags.get("--tail"):
        return None
    args: dict[str, Any] = {}
    limit = _last(parsed.flags.get("--limit")) or _last(parsed.flags.get("--lines"))
    if limit is not None:
        if not _UINT_RE.match(limit):
            return None
        args["limit"] = int(limit)
    return "debug_log", args


# ---------------------------------------------------------------------------
# show-model
# ---------------------------------------------------------------------------


def _classify_show_model(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-o": "--format"}, valued=frozenset({"--format"}))
    if parsed is None or len(parsed.positionals) > 1:
        return None
    args: dict[str, Any] = {}
    if parsed.positionals:
        args["model"] = parsed.positionals[0]
    return "show_model", args


# ---------------------------------------------------------------------------
# secrets: add / update / show
# ---------------------------------------------------------------------------

_ADD_SECRET_VALUED = frozenset({"--info", "--file"})


def _classify_add_secret(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju add-secret NAME key=value`` -> ``juju.add_secret(...)``.

    ``key=value`` content is carried through; the redaction pass
    (``jubilant_recorder.redaction``) is what keeps real values out of the
    session log, and a value it replaced arrives here as its
    ``<redacted:…>`` marker, which renders as a visible placeholder in the
    generated test rather than a working secret. ``--file`` content never
    reaches argv at all, so that shape falls through to ``juju.cli``.
    """
    parsed = _parse(rest, valued=_ADD_SECRET_VALUED)
    if parsed is None or not parsed.positionals:
        return None
    if parsed.flags.get("--file"):
        return None
    name = parsed.positionals[0]
    content = _fold_config([p for p in parsed.positionals[1:]])
    if content is None or not content:
        return None
    args: dict[str, Any] = {"name": name, "content": content}
    info = _last(parsed.flags.get("--info"))
    if info:
        args["info"] = info
    return "secret_add_cli", args


_UPDATE_SECRET_VALUED = frozenset({"--info", "--file", "--name"})
_UPDATE_SECRET_BOOLEAN = frozenset({"--auto-prune"})


def _classify_update_secret(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=_UPDATE_SECRET_VALUED, boolean=_UPDATE_SECRET_BOOLEAN)
    if parsed is None or not parsed.positionals:
        return None
    if parsed.flags.get("--file"):
        return None
    identifier = parsed.positionals[0]
    content = _fold_config([p for p in parsed.positionals[1:]])
    if content is None or not content:
        return None
    args: dict[str, Any] = {"identifier": identifier, "content": content}
    info = _last(parsed.flags.get("--info"))
    if info:
        args["info"] = info
    new_name = _last(parsed.flags.get("--name"))
    if new_name:
        args["name"] = new_name
    if parsed.flags.get("--auto-prune"):
        args["auto_prune"] = True
    return "secret_update_cli", args


_SHOW_SECRET_VALUED = frozenset({"--revision", "--format"})
_SHOW_SECRET_BOOLEAN = frozenset({"--reveal", "--revisions"})


def _classify_show_secret(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-o": "--format"},
        valued=_SHOW_SECRET_VALUED,
        boolean=_SHOW_SECRET_BOOLEAN,
    )
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"identifier": parsed.positionals[0]}
    if parsed.flags.get("--reveal"):
        args["reveal"] = True
    if parsed.flags.get("--revisions"):
        args["revisions"] = True
    revision = _last(parsed.flags.get("--revision"))
    if revision is not None:
        if not _UINT_RE.match(revision):
            return None
        args["revision"] = int(revision)
    return "show_secret", args


# ---------------------------------------------------------------------------
# model-config / model-constraints
# ---------------------------------------------------------------------------

_MODEL_CONFIG_VALUED = frozenset({"--reset", "--file", "--format"})


def _classify_model_config(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-o": "--format"}, valued=_MODEL_CONFIG_VALUED)
    if parsed is None or parsed.flags.get("--file"):
        return None
    args: dict[str, Any] = {}
    reset = _last(parsed.flags.get("--reset"))
    if reset is not None:
        keys = [k for k in reset.split(",") if k]
        if not keys:
            return None
        args["reset"] = keys
    if parsed.positionals:
        values = _fold_config(list(parsed.positionals))
        if values is None or not values:
            return None  # a bare key is a *read* of one key, which
            # `model_config()` cannot express — it returns the whole mapping.
        args["values"] = values
    return "model_config", args


def _classify_model_constraints(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases={"-o": "--format"}, valued=frozenset({"--format"}))
    if parsed is None or parsed.positionals:
        return None
    return "model_constraints", {}


def _classify_set_model_constraints(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    constraints = _fold_kv(list(parsed.positionals))
    if constraints is None or not constraints:
        return None
    return "model_constraints", {"constraints": constraints}


# ---------------------------------------------------------------------------
# trust
# ---------------------------------------------------------------------------

_TRUST_VALUED = frozenset({"--scope"})
_TRUST_BOOLEAN = frozenset({"--remove"})


def _classify_trust(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=_TRUST_VALUED, boolean=_TRUST_BOOLEAN)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    args: dict[str, Any] = {"app": parsed.positionals[0]}
    if parsed.flags.get("--remove"):
        args["remove"] = True
    scope = _last(parsed.flags.get("--scope"))
    if scope is not None:
        if scope != "cluster":
            return None  # jubilant's only accepted scope
        args["scope"] = scope
    return "trust", args


# ---------------------------------------------------------------------------
# ssh keys
# ---------------------------------------------------------------------------


def _classify_add_ssh_key(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    return "add_ssh_key", {"keys": list(parsed.positionals)}


def _classify_remove_ssh_key(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    return "remove_ssh_key", {"ids": list(parsed.positionals)}


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def _classify_version(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(
        rest,
        aliases={"-o": "--format"},
        valued=frozenset({"--format"}),
        boolean=frozenset({"--all"}),
    )
    if parsed is None or parsed.positionals:
        return None
    return "version", {}


# ---------------------------------------------------------------------------
# wait-for
# ---------------------------------------------------------------------------

_WAIT_FOR_VALUED = frozenset({"--query", "--timeout", "--format"})


def _classify_wait_for(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    """``juju wait-for application X`` -> ``juju.wait(jubilant.all_active)``.

    ``juju wait-for`` takes a scope (``application``/``unit``/``machine``/
    ``model``) and an optional ``--query`` expression. jubilant's ``wait()``
    takes a ready-callable instead, and the two query languages do not map
    onto one another, so only the *default* query — which is "everything in
    scope is active/idle" — is translated. Any explicit ``--query`` falls
    through to ``juju.cli``, where the expression survives verbatim for the
    reader to translate by hand.
    """
    parsed = _parse(rest, valued=_WAIT_FOR_VALUED)
    if parsed is None or not parsed.positionals:
        return None
    if parsed.flags.get("--query"):
        return None
    scope = parsed.positionals[0]
    if scope not in {"application", "unit", "model", "machine"}:
        return None
    targets = parsed.positionals[1:]
    if scope == "model":
        if len(targets) != 1:
            return None
        targets = []
    elif len(targets) != 1:
        return None
    args: dict[str, Any] = {"scope": scope, "targets": targets}
    timeout = _last(parsed.flags.get("--timeout"))
    if timeout is not None:
        seconds = _duration_seconds(timeout)
        if seconds is None:
            return None
        args["timeout"] = seconds
    return "wait_for", args


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_SUBCOMMANDS: dict[str, Callable[[list[str]], tuple[str, dict[str, Any]] | None]] = {
    "deploy": _classify_deploy,
    "config": _classify_config,
    "refresh": _classify_refresh,
    "remove-application": _classify_remove_application,
    "integrate": _classify_integrate,
    "remove-relation": _classify_remove_relation,
    "run": _classify_run,
    "add-unit": _classify_add_unit,
    "scale-application": _classify_scale_application,
    "remove-unit": _classify_remove_unit,
    "add-machine": _classify_add_machine,
    "status": _classify_status,
    "add-model": _classify_add_model,
    "destroy-model": _classify_destroy_model,
    "switch": _classify_switch,
    "show-model": _classify_show_model,
    "model-config": _classify_model_config,
    "model-constraints": _classify_model_constraints,
    "set-model-constraints": _classify_set_model_constraints,
    "ssh": _classify_ssh,
    "exec": _classify_exec,
    "scp": _classify_scp,
    "debug-log": _classify_debug_log,
    "trust": _classify_trust,
    "add-ssh-key": _classify_add_ssh_key,
    "remove-ssh-key": _classify_remove_ssh_key,
    "version": _classify_version,
    "wait-for": _classify_wait_for,
    "add-secret": _classify_add_secret,
    "update-secret": _classify_update_secret,
    "show-secret": _classify_show_secret,
    "remove-secret": _classify_remove_secret,
    "grant-secret": _classify_grant_secret,
    "secrets": _classify_secrets,
    "offer": _classify_offer,
    "consume": _classify_consume,
    "offers": _classify_offers,
    "remove-offer": _classify_remove_offer,
    "show-offer": _classify_show_offer,
    "remove-saas": _classify_remove_saas,
    "expose": _classify_expose,
    "unexpose": _classify_unexpose,
    "set-constraints": _classify_set_constraints,
    "bind": _classify_bind,
    "suspend-relation": _classify_suspend_relation,
    "resume-relation": _classify_resume_relation,
}

# Subcommands that operate on a controller, a cloud, or the local client
# rather than on a model, and therefore reject ``--model``. The passthrough
# emitter turns this into ``include_model=False``, because ``juju.cli()``
# inserts ``--model <model>`` after the first argument by default and doing
# that to any of these makes the generated test fail with a flag-parse error
# rather than run.
#
# Generated, not hand-written: this is every subcommand in ``juju help
# commands`` on juju 3.6.28 whose ``juju help <subcommand>`` output has no
# ``-m, --model`` entry. Regenerate it against a newer client with::
#
#     for c in $(juju help commands | awk '{print $1}'); do
#         juju help "$c" | grep -q -- '-m, --model' || echo "$c"
#     done
NO_MODEL_SUBCOMMANDS = frozenset(
    {
        "add-cloud",
        "add-credential",
        "add-k8s",
        "add-model",
        "add-secret-backend",
        "add-user",
        "agree",
        "agreements",
        "autoload-credentials",
        "bootstrap",
        "change-user-password",
        "clouds",
        "controller-config",
        "controllers",
        "credentials",
        "default-credential",
        "default-region",
        "destroy-controller",
        "destroy-model",
        "disable-user",
        "documentation",
        "download",
        "enable-destroy-controller",
        "enable-ha",
        "enable-user",
        "find",
        "grant",
        "grant-cloud",
        "help",
        "help-action-commands",
        "help-hook-commands",
        "info",
        "kill-controller",
        "list-agreements",
        "list-clouds",
        "list-controllers",
        "list-credentials",
        "list-models",
        "list-regions",
        "list-secret-backends",
        "list-users",
        "login",
        "logout",
        "migrate",
        "model-default",
        "model-defaults",
        "models",
        "offer",
        "regions",
        "register",
        "remove-cloud",
        "remove-credential",
        "remove-k8s",
        "remove-offer",
        "remove-secret-backend",
        "remove-user",
        "revoke",
        "revoke-cloud",
        "secret-backends",
        "set-default-credentials",
        "set-default-region",
        "show-cloud",
        "show-controller",
        "show-credential",
        "show-credentials",
        "show-model",
        "show-secret-backend",
        "show-user",
        "switch",
        "unregister",
        "update-cloud",
        "update-credential",
        "update-credentials",
        "update-k8s",
        "update-public-clouds",
        "update-secret-backend",
        "upgrade-controller",
        "users",
        "version",
        "wait-for",
        "whoami",
    }
)

# Subcommands that ask for interactive confirmation unless told not to.
# A generated test runs unattended, so the passthrough adds ``--no-prompt``
# when the recorded argv did not already carry it (or its ``-y``/``--yes``
# spelling) — without it the test hangs on stdin rather than failing.
_PROMPTING_SUBCOMMANDS = frozenset(
    {
        "destroy-controller",
        "destroy-model",
        "kill-controller",
        "remove-application",
        "remove-cloud",
        "remove-credential",
        "remove-machine",
        "remove-offer",
        "remove-saas",
        "remove-unit",
        "remove-user",
        "unregister",
    }
)
_NO_PROMPT_SPELLINGS = frozenset({"--no-prompt", "-y", "--yes"})

# Command groups whose *subcommands* take `--model` even though the group
# itself rejects it: `juju wait-for` has no model flag, but `juju wait-for
# application` does. `juju.cli()` inserts `--model` after the first argument,
# which lands on the group and fails to parse — and `include_model=False`
# would silently wait on whatever model the operator's CLI happens to be
# pointing at, which is worse. So the passthrough appends the model itself,
# after the subcommand, reading it off the `Juju` instance at test time.
MODEL_AFTER_SUBCOMMAND = frozenset({"wait-for"})

# ``juju`` invoked with a global flag and no subcommand at all.
_GLOBAL_FLAG_ONLY = {
    "--version": ("version", {}),
    "--help": None,
    "-h": None,
}


def _strip_model_flag(argv: list[str]) -> tuple[list[str], str | None]:
    """Remove a ``-m``/``--model`` flag from a model-scoped argv.

    A generated test runs inside the model `jubilant.temp_model()` created
    for it, and jubilant threads that model through every call itself. The
    model the session was recorded against does not exist when the test
    runs, so carrying its name into the generated call would point the step
    at a model the test never created — a guaranteed failure. Dropping the
    flag is therefore a required rewrite, not a lossy one, and it is the
    same rewrite the `RecordingJuju` and libjuju front-ends perform
    implicitly by never recording a model in the first place.

    Returns the argv without the flag, plus the model name that was
    dropped (``None`` if there was none), so a caller can surface it.
    Subcommands in `NO_MODEL_SUBCOMMANDS` are left alone: for those, a
    bare positional model name is the operand, not a redundant scope.
    """
    if not argv or (argv[0] in NO_MODEL_SUBCOMMANDS and argv[0] not in MODEL_AFTER_SUBCOMMAND):
        return argv, None
    stripped: list[str] = []
    dropped: str | None = None
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-m", "--model") and i + 1 < len(argv):
            dropped = argv[i + 1]
            i += 2
            continue
        if tok.startswith("--model="):
            dropped = tok.partition("=")[2]
            i += 1
            continue
        if tok == "--":
            stripped.extend(argv[i:])
            break
        stripped.append(tok)
        i += 1
    return stripped, dropped


def _passthrough(argv: list[str]) -> tuple[str, dict[str, Any]]:
    """Wrap an untranslated ``juju`` argv as a ``cli_passthrough`` event.

    This is the floor of the translation ladder, and it is deliberately
    total: every ``juju`` invocation the classifiers above decline becomes a
    real ``juju.cli(...)`` call in the generated test rather than a
    ``# shell:`` comment the reader has to retype. ``juju.cli()`` is
    jubilant's documented escape hatch and returns the command's stdout, so
    nothing about the recorded step is lost — only its typing.
    """
    subcommand = argv[0] if argv else ""
    args: dict[str, Any] = {"argv": list(argv)}
    if subcommand in MODEL_AFTER_SUBCOMMAND:
        args["include_model"] = False
        args["model_after_subcommand"] = True
    elif subcommand in NO_MODEL_SUBCOMMANDS or subcommand.startswith("-"):
        args["include_model"] = False
    if subcommand in _PROMPTING_SUBCOMMANDS and not (_NO_PROMPT_SPELLINGS & set(argv)):
        args["add_no_prompt"] = True
    return "cli_passthrough", args


def classify_argv(argv: list[str]) -> tuple[str, dict[str, Any]] | None:
    """Classify a raw ``juju`` argv (subcommand + flags, no ``juju`` itself).

    Returns ``(op, args)`` for every non-empty argv: a typed op when the
    shape maps cleanly onto a jubilant method, and ``cli_passthrough``
    (rendered as ``juju.cli(...)``) otherwise. Only an *empty* argv — a bare
    ``juju`` with no arguments, which does nothing but print help — returns
    ``None`` and keeps the ``# shell:`` comment rendering.

    Never raises: an unexpected argv shape inside a recognized subcommand's
    classifier degrades to the passthrough, same as an unrecognized
    subcommand.
    """
    if not argv:
        return None
    argv, dropped_model = _strip_model_flag(argv)
    if not argv:
        return None
    result = _classify_stripped_argv(argv)
    if dropped_model is not None:
        result[1]["recorded_model"] = dropped_model
    return result


def _classify_stripped_argv(argv: list[str]) -> tuple[str, dict[str, Any]]:
    """Dispatch a model-flag-free argv to its classifier, or the passthrough."""
    if argv[0] in _GLOBAL_FLAG_ONLY:
        mapped = _GLOBAL_FLAG_ONLY[argv[0]]
        if mapped is not None and len(argv) == 1:
            return mapped
        return _passthrough(argv)
    subcommand = _ALIASES.get(argv[0], argv[0])
    handler = _SUBCOMMANDS.get(subcommand)
    if handler is None:
        return _passthrough(argv)
    try:
        translated = handler(list(argv[1:]))
    except Exception:
        translated = None
    return _passthrough(argv) if translated is None else translated


def classify(
    event: dict[str, Any], *, session_model: str | None = None
) -> tuple[str, dict[str, Any]] | None:
    """Classify a shim-sourced ``op: "shell"`` event's ``args.argv``.

    ``session_model`` is the model the recording itself worked in (see
    `session_model`); when a model-lifecycle op names it, the result carries
    ``is_session_model: True`` so `operations/model_lifecycle.py` renders a
    note instead of a call that would fight `jubilant.temp_model()`.
    """
    args = event.get("args") or {}
    result = classify_argv(list(args.get("argv") or []))
    if result is None:
        return None
    op, op_args = result
    is_own = session_model is not None and op_args.get("model") == session_model
    if op in _MODEL_LIFECYCLE_OPS and is_own:
        op_args["is_session_model"] = True
    return op, op_args


_MODEL_LIFECYCLE_OPS = frozenset({"add_model", "destroy_model", "switch_model"})


def session_model(events: list[dict[str, Any]]) -> str | None:
    """Infer the model a shell-capture session was recorded against.

    The first ``juju add-model NAME`` in the log wins: that is the model the
    operator made to work in, and the one `jubilant.temp_model()` stands in
    for in the generated test. Failing that, the first ``juju switch NAME``
    (an operator working in a model they made earlier), and failing that the
    model named most often by a ``-m``/``--model`` flag.

    Returns ``None`` for a session that never names a model — which is the
    common case, and leaves every model-lifecycle command translated
    literally, since there is then nothing to say `temp_model()` replaced.
    """
    switched: str | None = None
    counts: dict[str, int] = {}
    for event in events:
        args = event.get("args") or {}
        if event.get("op") != "shell" or args.get("source") not in ("shim", "jubilant"):
            continue
        argv = [str(a) for a in (args.get("argv") or [])]
        if not argv:
            continue
        if argv[0] == "add-model":
            for tok in argv[1:]:
                if not tok.startswith("-"):
                    return tok
        if argv[0] == "switch" and switched is None:
            for tok in argv[1:]:
                if not tok.startswith("-"):
                    switched = tok
                    break
        _, dropped = _strip_model_flag(argv)
        if dropped:
            counts[dropped] = counts.get(dropped, 0) + 1
    if switched is not None:
        return switched
    if counts:
        return max(sorted(counts), key=lambda name: counts[name])
    return None
