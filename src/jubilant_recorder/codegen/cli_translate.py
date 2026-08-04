"""Bucket-1 argv -> jubilant translation for PATH-shim ``juju <subcommand>`` calls.

Implements the classification built in the CLI corpus notes: a recorded shim event
(``op: "shell"``, ``args.source == "shim"``, ``args.argv`` the raw ``juju``
argv minus the ``juju`` binary itself) is translated into one of the 28
existing ``EMITTERS`` ops when its argv shape is a lossless match. Anything
else (an unhandled subcommand, or a handled subcommand used with a flag
outside the mapped subset) returns ``None`` so the caller falls through to
the existing ``# shell: ...`` comment rendering — bucket 2/3 needs no new
code, that fallback already exists.

Only the 20 subcommands the CLI corpus notes §4 classifies bucket 1 are handled
here (plus ``add-unit``/``scale-application``, promoted from bucket 2 to
bucket 1 by the F1/F2 fix in ``operations/scale.py`` — see the docstring
there and the dated correction in the CLI corpus notes). Every other subcommand —
including ``add-secret``/``update-secret`` (F5: shim has no redaction),
``remove-unit`` (F3: no op targets it), and the 130 bucket-3 subcommands —
is deliberately absent from ``_SUBCOMMANDS`` and falls through untouched.

Design rule used throughout: each classifier only recognizes the flags it
has deliberate handling for (mapped to a kwarg, or a documented "harmless
to drop" output-shape flag per the CLI corpus notes). Any other ``-``-prefixed
token — including one this module has simply never heard of — aborts
classification immediately and returns ``None``. This means a flag that
would otherwise be silently misparsed as a positional (corrupting the
translation) can never reach that code path: we bail at the flag, before
ever touching the tokens after it. This is the "bias to bucket 2 wherever
the mapping is not exact" rule from the plan, applied structurally rather
than case-by-case.

Version pin (the CLI corpus notes §8's open question, task note 4): all flag
tables below are the Juju **4.0** CLI surface, matching the CLI corpus notes's own
primary pin. A session recorded against a different client version may
misclassify (a flag that exists on 4.0 but not on the recording's actual
client, or vice versa) — accepted, not handled, per §8's "pin one version"
alternative. The one documented 3.6 divergence (``set-application-base``,
F4) has no the CLI corpus notes bucket-1 row at all and is correspondingly absent
from ``_SUBCOMMANDS`` here.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# See module docstring "Version pin" above.
JUJU_CLIENT_VERSION = "4.0"

_ALIASES = {
    "relate": "integrate",
    "list-secrets": "secrets",
    "list-offers": "offers",
}

_UNIT_RE = re.compile(r"^[\w][\w-]*/(?:leader|\d+)$")
_UINT_RE = re.compile(r"^\d+$")


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
) -> _Parsed | None:
    """Tokenize a subcommand's argv into positionals + recognized flags.

    Returns ``None`` (caller should fall back to bucket 2/3) the moment it
    sees a ``-``-prefixed token that isn't (after alias resolution) in
    ``valued``/``boolean`` — see module docstring. Also returns ``None`` if a
    valued flag is the last token with no value following, or a boolean flag
    is given a ``--flag=value`` form.
    """
    aliases = aliases or {}
    positionals: list[str] = []
    flags: dict[str, list[str | None]] = {}
    i = 0
    n = len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            positionals.extend(rest[i + 1 :])
            break
        if tok.startswith("-") and tok != "-":
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
    argv — the CLI corpus notes §5.5) aborts the whole fold, not just that entry.
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
    """YAML-type a `run` param value the way juju itself does (§5.3).

    Uses PyYAML's ``safe_load`` as the "YAML-typed" implementation. One
    known divergence from real juju CLI behaviour, found while implementing
    this rather than assumed: juju's own YAML-1.1-ish parser treats bare
    ``y``/``n`` as booleans, but PyYAML's default (non-1.1) resolver does
    not — only the full words (``yes``/``no``/``true``/``false``/``on``/
    ``off``) coerce. A recorded ``key=y`` stays the string ``"y"`` here
    rather than becoming ``True``. Not fixed: hand-rolling a YAML-1.1
    resolver to match one juju quirk is out of proportion to the risk (bare
    ``y``/``n`` action params are rare in practice), but this is a real,
    sourced gap between the CLI corpus notes §5.3's example and what this module
    does — flagged rather than silently shipped.
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
# §4.1 deploy
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
            return None  # file-content shape — §5.5
        if config_values:
            args["config"] = config_values

    return "deploy", args


# ---------------------------------------------------------------------------
# §4.2 config / config_get / config_unset
# ---------------------------------------------------------------------------

_CONFIG_ALIASES = {"-m": "--model"}
_CONFIG_VALUED = frozenset({"--file", "--reset", "--model"})
_CONFIG_EXCEPTED = frozenset({"--file", "--model"})


def _classify_config(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, aliases=_CONFIG_ALIASES, valued=_CONFIG_VALUED)
    if parsed is None or not parsed.positionals:
        return None
    if _CONFIG_EXCEPTED & parsed.flags.keys():
        return None  # --file / --model — §5.5 file content, or cross-model

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
                return None  # key=@path file directive — §5.5
            values[key] = val
        if not values:
            return None
        return "config", {"app": app, "values": values}

    if len(rest_pos) > 1:
        return None
    return "config_get", {"app": app, "keys": rest_pos or None}


# ---------------------------------------------------------------------------
# §4.3 refresh -> set_charm
# ---------------------------------------------------------------------------

_REFRESH_VALUED = frozenset({"--switch", "--channel", "--storage", "--resource"})
_REFRESH_BOOLEAN = frozenset({"--force"})


def _classify_refresh(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, valued=_REFRESH_VALUED, boolean=_REFRESH_BOOLEAN)
    if parsed is None or len(parsed.positionals) != 1:
        return None
    app = parsed.positionals[0]

    args: dict[str, Any] = {"app": app}
    switch = _last(parsed.flags.get("--switch"))
    if switch:
        args["charm_url"] = switch
    channel = _last(parsed.flags.get("--channel"))
    if channel:
        args["channel"] = channel
    if parsed.flags.get("--force"):
        args["force"] = True
    # --storage/--resource have no clean kwarg either (set_charm.py's
    # config_settings/storage_constraints/resource_ids are TODO'd, not
    # dropped) — forwarding a truthy value keeps that existing TODO-comment
    # behaviour rather than silently losing the flag or forcing bucket 2.
    storage = parsed.flags.get("--storage")
    if storage:
        args["storage_constraints"] = list(storage)
    resource = parsed.flags.get("--resource")
    if resource:
        args["resource_ids"] = list(resource)
    return "set_charm", args


# ---------------------------------------------------------------------------
# §4.4 remove-application
# ---------------------------------------------------------------------------


def _classify_remove_application(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or not parsed.positionals:
        return None
    apps = parsed.positionals
    return "remove_application", {"app": apps[0] if len(apps) == 1 else apps}


# ---------------------------------------------------------------------------
# §4.5 integrate/relate, remove-relation
# ---------------------------------------------------------------------------


def _classify_integrate(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    a, b = parsed.positionals
    if "." in a.split(":", 1)[0] or "." in b.split(":", 1)[0]:
        return None  # dotted model-qualified — cross-model, §4.5
    return "integrate", {"app1_endpoint": a, "app2_endpoint": b}


def _classify_remove_relation(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    a, b = parsed.positionals
    return "remove_integration", {"app1_endpoint": a, "app2_endpoint": b}


# ---------------------------------------------------------------------------
# §4.6 run
# ---------------------------------------------------------------------------


def _classify_run(rest: list[str]) -> tuple[str, dict[str, Any]] | None:
    parsed = _parse(rest, boolean=frozenset({"--string-args"}))
    if parsed is None:
        return None
    positionals = parsed.positionals

    units: list[str] = []
    i = 0
    while i < len(positionals) and _UNIT_RE.match(positionals[i]):
        units.append(positionals[i])
        i += 1
    if len(units) != 1:
        return None  # zero units, or multi-unit — bucket 2, §4.6
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
# §4.7 secrets
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
    parsed = _parse(rest)
    if parsed is None or len(parsed.positionals) != 2:
        return None
    identifier, app = parsed.positionals
    return "secret_grant", {"identifier": identifier, "app": app}


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
# §4.8 cross-model (CMR)
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
        return None  # dotted model-qualified app — §4.8
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
        return None  # multi-name not representable by remove_saas.py — §4.8
    return "remove_saas", {"app": parsed.positionals[0]}


# ---------------------------------------------------------------------------
# §4.9 expose / unexpose
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
# §4.10 set-constraints
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
# §4.11 bind -> merge_bindings
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
# §4.12 suspend-relation / resume-relation -> set_relations_suspended
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


def classify_argv(argv: list[str]) -> tuple[str, dict[str, Any]] | None:
    """Classify a raw ``juju`` argv (subcommand + flags, no ``juju`` itself).

    Returns ``(op, args)`` for a bucket-1 match, or ``None`` for anything
    that should fall back to the existing bucket-2/3 ``# shell: ...``
    rendering. Never raises — an unexpected argv shape inside a recognized
    subcommand's classifier degrades to ``None``, same as an unrecognized
    subcommand.
    """
    if not argv:
        return None
    subcommand = _ALIASES.get(argv[0], argv[0])
    handler = _SUBCOMMANDS.get(subcommand)
    if handler is None:
        return None
    try:
        return handler(list(argv[1:]))
    except Exception:
        return None


def classify(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Classify a shim-sourced ``op: "shell"`` event's ``args.argv``."""
    args = event.get("args") or {}
    return classify_argv(list(args.get("argv") or []))
