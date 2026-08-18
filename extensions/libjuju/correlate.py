"""RPC → delta-burst association and SCHEMA.md event emission.

``correlate()`` takes the two streams captured by ``LibjujuTap`` — a list of
RPC records and a list of AllWatcher delta records — and produces a list of
``EventEnvelope``-shaped dicts in the jubilant-recorder SCHEMA.md format.

Correlation strategy
--------------------
AllWatcher delta bursts are pushed by the controller in response to state
changes.  Each AllWatcher.Next response carries a batch of deltas but carries
no reference to the request-id of the RPC that triggered the change.

The tap records the *end timestamp* of each user-facing RPC (when the
controller replied "ok") and the *arrival timestamp* of each delta burst (when
the AllWatcher.Next response was received by the client).  Deltas that arrive
within ``window_seconds`` *after* an RPC's end timestamp are attributed to that
RPC.

If a delta arrives before the RPC ends (controller pushed it proactively, or
clock skew), the delta is attributed to the chronologically closest RPC within
the window.  If no RPC is within range, the delta is recorded as an orphan on
the synthetic ``_libjuju_orphan`` event at the end.

Facade → op taxonomy (SCHEMA.md §"Op taxonomy")
------------------------------------------------
Three buckets:

Bucket 1 — clean mapping (records a fully-typed SCHEMA event):
    Application.Deploy        → deploy
    Application.AddRelation   → integrate
    Application.DestroyRelation → remove_integration
    Application.SetConfigs    → config
    Application.Get           → config_get
    Application.GetConfig     → config_get
    Application.AddUnits      → scale
    Application.ScaleApplications → scale
    Application.DestroyApplication → remove_application
    Action.Enqueue            → run
    Action.EnqueueOperation   → run
    Client.Status             → status
    Secrets.CreateSecrets     → secret_add     (content redacted)
    Secrets.UpdateSecrets     → secret_update  (content redacted)
    Secrets.RemoveSecrets     → secret_remove
    Secrets.GrantSecret       → secret_grant
    Secrets.RevokeSecret      → secret_revoke
    Secrets.ListSecrets       → secret_list
    ApplicationOffers.Offer               → create_offer
    ApplicationOffers.ListApplicationOffers → list_offers
    ApplicationOffers.FindApplicationOffers → find_offers
    ApplicationOffers.DestroyOffers       → remove_offer
    ApplicationOffers.GetConsumeDetails   → get_consume_details
    Application.Consume                   → consume
    Application.DestroyConsumedApplications → remove_saas

    Cross-model (CMR) note (see the CMR facade notes): the corpus term
    ``consume_offer`` is a misnomer — there is no ``Model.consume_offer``.
    The real client call is ``Model.consume()``, which drives
    ``Application.Consume`` (an ``Application`` facade RPC, not an
    ``ApplicationOffers.*`` one). Do not add a ``consume_offer`` entry here.

    ``Application.*`` bucket-2 → bucket-1 promotion (see
    the corpus audit §5 "Natural extension"): jubilant
    1.10 has no client method for any of these, but each has a direct
    ``juju`` CLI subcommand, so each is rendered via ``juju.cli(...)``
    rather than left as an opaque shell stub.
    Application.SetCharm              → set_charm
    Application.Expose                → expose
    Application.Unexpose              → unexpose
    Application.SetConstraints        → set_constraints
    Application.MergeBindings         → merge_bindings
    Application.SetRelationsSuspended → set_relations_suspended
    Application.UnsetApplicationsConfig → config_unset
    Application.UpdateApplicationBase → update_application_base

Bucket 2 — lossy / decomposable (records event with ``note`` field):
    Currently empty, deliberately — see ``_BUCKET2_FACADES``' comment for why
    that is the correct end state for this surface rather than a sign the
    classification stopped discriminating. The branch stays live: any facade
    added here still records a ``note``-carrying event.

Bucket 3 — no mapping (records a ``# TODO: manual step`` shape):
    Everything else (raw facade calls with no CLI equivalent).

Internal RPCs (skipped, never emit events):
    AllWatcher.Next, AllWatcher.Stop, Client.WatchAll, Pinger.Ping,
    and any facade whose name starts with "AllWatcher".

Secret content redaction
------------------------
``Secrets.CreateSecrets`` and ``Secrets.UpdateSecrets`` carry actual secret
values in their ``content.data`` dict.  ``_extract_args`` always redacts these
values, replacing each with the sentinel ``"<REDACTED>"``, while preserving the
key names so codegen can hint to the user what keys the secret has.  The
resulting args dict is safe to write to disk (no plaintext secrets).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Facade → op mapping tables
# ---------------------------------------------------------------------------

_INTERNAL_FACADE_METHODS: frozenset[tuple[str, str]] = frozenset(
    {
        ("AllWatcher", "Next"),
        ("AllWatcher", "Stop"),
        ("Client", "WatchAll"),
        # ``Client.FullStatus`` is the backend for both ``model.get_status()``
        # and ``model.wait_for_idle()`` polling. In a real run wait_for_idle
        # calls it hundreds of times; without this exclusion the correlator
        # emits one ``status`` event per poll and drowns every other user
        # intent. Treat as internal; explicit assertions on model state flow
        # through ``model_snapshot_after`` instead.
        ("Client", "FullStatus"),
        # Modern libjuju queries the controller's model config on connect.
        ("ModelConfig", "ModelGet"),
        ("ModelConfig", "GetModelConstraints"),
        # Deploy paths query ResolveCharms / AddCharm before the actual deploy
        # RPC. These are plumbing — the user asked for ``deploy``, not for
        # each resolve step.
        ("Charms", "ResolveCharms"),
        ("Charms", "AddCharm"),
        ("Pinger", "Ping"),
        ("Controller", "WatchAllModels"),
        ("ModelManager", "WatchModelSummaries"),
    }
)

_BUCKET1_MAP: dict[tuple[str, str], str] = {
    ("Application", "Deploy"): "deploy",
    # ``Application.DeployFromRepository`` is the modern deploy facade libjuju
    # 3.6.1+ uses when talking to juju 3.6+ controllers. Params are packed as
    # ``{"Args": ["<json-string>"]}`` — see ``_extract_args``.
    ("Application", "DeployFromRepository"): "deploy",
    ("Application", "AddRelation"): "integrate",
    ("Application", "DestroyRelation"): "remove_integration",
    ("Application", "SetConfigs"): "config",
    ("Application", "Get"): "config_get",
    ("Application", "GetConfig"): "config_get",
    ("Application", "AddUnits"): "scale",
    ("Application", "ScaleApplications"): "scale",
    ("Application", "DestroyApplication"): "remove_application",
    ("Action", "Enqueue"): "run",
    ("Action", "EnqueueOperation"): "run",
    ("Client", "Status"): "status",
    # Secrets facade — bucket-1 promotions (carry c)
    ("Secrets", "CreateSecrets"): "secret_add",
    ("Secrets", "UpdateSecrets"): "secret_update",
    ("Secrets", "RemoveSecrets"): "secret_remove",
    ("Secrets", "GrantSecret"): "secret_grant",
    ("Secrets", "RevokeSecret"): "secret_revoke",
    ("Secrets", "ListSecrets"): "secret_list",
    # Cross-model (CMR) facades — bucket-1 promotions, see the CMR facade notes §1.
    # Facade name here is the wire ``type``, which is ``ApplicationOffers``
    # (v5) for the offer-side calls, not the python-libjuju class name
    # ``ApplicationOffersFacade``. ``Consume``/``DestroyConsumedApplications``
    # are ``Application`` facade RPCs (v20), reusing the same wire type as
    # ``Deploy``/``AddRelation``/etc. above.
    ("ApplicationOffers", "Offer"): "create_offer",
    ("ApplicationOffers", "ListApplicationOffers"): "list_offers",
    ("ApplicationOffers", "FindApplicationOffers"): "find_offers",
    ("ApplicationOffers", "DestroyOffers"): "remove_offer",
    ("ApplicationOffers", "GetConsumeDetails"): "get_consume_details",
    # NOT "consume_offer" — see the CMR facade notes §2.2: the real client
    # call is ``Model.consume()``, there is no ``Model.consume_offer``.
    ("Application", "Consume"): "consume",
    ("Application", "DestroyConsumedApplications"): "remove_saas",
    # ``Application.*`` bucket-2 → bucket-1 promotions, see
    # the corpus audit §5 "Natural extension". None of
    # these have a jubilant client method, but each has a direct `juju`
    # CLI subcommand — rendered via `juju.cli(...)`, same escape hatch as
    # the CMR ops above.
    ("Application", "SetCharm"): "set_charm",
    ("Application", "Expose"): "expose",
    ("Application", "Unexpose"): "unexpose",
    ("Application", "SetConstraints"): "set_constraints",
    ("Application", "MergeBindings"): "merge_bindings",
    ("Application", "SetRelationsSuspended"): "set_relations_suspended",
    ("Application", "UnsetApplicationsConfig"): "config_unset",
    ("Application", "UpdateApplicationBase"): "update_application_base",
}

# Deliberately empty. Every RPC that has ever sat here was here for one
# reason — jubilant has no client method for it — and ``Juju.cli()`` is the
# public escape hatch that answers exactly that (``jubilant/_juju.py:527``,
# already used by jubilant's own ``bootstrap()``). The last two members,
# ``Secrets.RevokeSecret`` and ``ApplicationOffers.FindApplicationOffers``,
# were promoted 2026-08-18 for the same reason the 4 CMR ops and the 8
# ``Application.*`` ops were before them.
#
# An empty bucket 2 on *this* surface is the honest end state, not a
# collapsed taxonomy: a typed RPC with named parameters is always
# re-expressible once an escape hatch exists, because the recorder captured
# the parameter values. The lossy cases all live on the argv surface, where
# bucket 2 is defined as information loss rather than API coverage and is
# classified per-invocation (see the CLI corpus notes §1) — so that bucket can
# never empty and the three-way split stays meaningful. Full reasoning:
# the staging repo internal/jubilant-test-recorder/the bucket-2 design notes.
#
# The rule for future additions, so the escape hatch does not get
# over-applied: a ``juju.cli(...)`` emitter is the right answer when
# jubilant lacks a client method for an op whose arguments were *fully
# captured*. It is not the right answer when the arguments themselves are
# incomplete, unredacted, or unreconstructable — those belong here.
_BUCKET2_FACADES: frozenset[tuple[str, str]] = frozenset()


def _is_internal(facade: str, method: str) -> bool:
    if (facade, method) in _INTERNAL_FACADE_METHODS:
        return True
    return facade == "AllWatcher"


def _classify(facade: str, method: str) -> tuple[str, str | None]:
    """Return ``(bucket, op)`` where bucket is "1", "2", or "3"."""
    key = (facade, method)
    if key in _BUCKET1_MAP:
        return "1", _BUCKET1_MAP[key]
    if key in _BUCKET2_FACADES:
        return "2", None
    return "3", None


# ---------------------------------------------------------------------------
# Model state derived from AllWatcher deltas
# ---------------------------------------------------------------------------


class _ModelState:
    """Lightweight model state built incrementally from AllWatcher deltas."""

    def __init__(self) -> None:
        # unit_name → {workload_status, workload_message, agent_status, app}
        self._units: dict[str, dict[str, str]] = {}
        # set of frozenset({endpoint_a, endpoint_b})
        self._relations: list[frozenset[str]] = []

    def apply_delta(self, delta: dict[str, Any]) -> None:
        entity_kind = delta.get("entity_kind", "")
        change_kind = delta.get("change_kind", "")
        payload = delta.get("payload") or {}

        if entity_kind == "unit":
            unit_name: str = payload.get("name", "")
            if not unit_name:
                return
            if change_kind == "remove":
                self._units.pop(unit_name, None)
            else:
                ws = payload.get("workload-status") or {}
                as_ = payload.get("agent-status") or {}
                app = payload.get("application", unit_name.split("/")[0])
                self._units[unit_name] = {
                    "workload_status": ws.get("current", "unknown"),
                    "workload_message": ws.get("message", ""),
                    "agent_status": as_.get("current", "unknown"),
                    "app": app,
                }

        elif entity_kind == "relation":
            endpoints_data = payload.get("endpoints") or []
            ep_strs: list[str] = []
            for ep in endpoints_data:
                app_name = ep.get("application-name", "")
                ep_name = ep.get("name", "")
                if app_name and ep_name:
                    ep_strs.append(f"{app_name}:{ep_name}")
            if len(ep_strs) >= 2:
                pair = frozenset(ep_strs[:2])
                if change_kind == "remove":
                    self._relations = [r for r in self._relations if r != pair]
                elif pair not in self._relations:
                    self._relations.append(pair)

    def snapshot(self, captured_at: str) -> dict[str, Any]:
        """Build a SCHEMA.md-shaped model snapshot from current state."""
        apps: dict[str, Any] = {}
        for unit_name, info in self._units.items():
            app = info["app"]
            apps.setdefault(app, {"units": {}})
            apps[app]["units"][unit_name] = {
                "workload_status": info["workload_status"],
                "workload_message": info["workload_message"],
                "agent_status": info["agent_status"],
            }

        relations: list[dict[str, Any]] = []
        for pair in self._relations:
            endpoints = sorted(pair)
            relations.append({"endpoints": endpoints})

        return {
            "schema_version": 1,
            "captured_at": captured_at,
            "apps": apps,
            "relations": relations,
        }


# ---------------------------------------------------------------------------
# Args extraction helpers
# ---------------------------------------------------------------------------


def _strip_charm_url_revision(charm_url: str) -> str:
    """Strip a trailing ``-<digits>`` revision suffix from the last path segment.

    ``DeployFromRepository`` reports a resolved charm URL like
    ``ch:amd64/noble/ubuntu-26``; jubilant's CLI rejects revision-in-name and
    wants ``--revision`` separately. Return the URL with the trailing ``-N``
    removed from its final segment: ``ch:amd64/noble/ubuntu``. Non-URL inputs
    and inputs without a numeric suffix pass through unchanged.
    """
    if not charm_url:
        return charm_url
    head, sep, tail = charm_url.rpartition("/")
    seg = tail if sep else charm_url
    app, dash, maybe_rev = seg.rpartition("-")
    if dash and maybe_rev.isdigit() and app:
        seg = app
    return f"{head}/{seg}" if sep else seg


def _unit_tag_to_name(receiver: str) -> str:
    """Convert a Juju unit tag (``unit-my-charm-0``) back to ``my-charm/0``.

    The Juju tag convention is ``unit-<unit name with "/" → "-">``, so the
    unit number is always the trailing ``-N`` segment. Splitting on the
    LAST hyphen is the correct inverse, not the first — applications often
    contain hyphens themselves (``my-charm``, ``postgresql-k8s``).
    """
    if not receiver:
        return ""
    bare = receiver.removeprefix("unit-")
    app, _, num = bare.rpartition("-")
    if not app:
        return bare
    return f"{app}/{num}"


def _storage_tag_to_id(tag: str) -> str:
    """Convert a Juju storage tag (``storage-foo-0``) back to ``foo/0``.

    Same encoding as unit tags (see ``_unit_tag_to_name``): ``names.NewStorageTag``
    (github.com/juju/names) replaces only the LAST ``/`` with ``-`` when building the
    tag, so splitting on the last hyphen is the correct inverse — storage names, like
    application names, may contain hyphens themselves.
    """
    if not tag:
        return ""
    bare = tag.removeprefix("storage-")
    name, _, num = bare.rpartition("-")
    if not name:
        return bare
    return f"{name}/{num}"


def _placement_to_cli_str(placement: dict[str, Any]) -> str:
    """Convert one wire ``instance.Placement`` dict back to a ``--to`` token.

    Inverse of Juju's ``ParsePlacement`` (core/instance/placement.go): machine-scope
    (``scope: "#"``) directives are bare machine ids (``"0"``, not ``"#:0"``); a scope
    with no directive is a bare container-type shorthand for "new container of this
    type" (``"lxd"``); anything else is ``scope:directive`` (e.g. ``"lxd:0"``).
    """
    scope = placement.get("scope", "")
    directive = placement.get("directive", "")
    if scope == "#":
        return directive
    if not directive:
        return scope
    return f"{scope}:{directive}"


def _extract_args(facade: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Map libjuju RPC params to the SCHEMA.md args dict for a bucket-1 op."""
    key = (facade, method)

    if key == ("Application", "Deploy"):
        app_params = (params.get("applications") or [{}])[0]
        return {
            "charm": app_params.get("charm-url", ""),
            "app": app_params.get("application-name") or None,
            "channel": app_params.get("charm-origin", {}).get("track") or None,
            "num_units": app_params.get("num-units", 1),
            "config": app_params.get("config") or {},
            "resources": app_params.get("resource-file-params") or {},
        }

    if key == ("Application", "DeployFromRepository"):
        # libjuju packs the deploy request as ``{"Args": ["<json-string>"]}``
        # where the JSON string decodes to a single ``DeployFromRepositoryArg``
        # dict. Fall back to an empty dict if either layer is malformed.
        raw_args = params.get("Args") or []
        inner: dict[str, Any] = {}
        if raw_args:
            raw = raw_args[0]
            if isinstance(raw, dict):
                inner = raw
            elif isinstance(raw, str):
                import json as _json

                try:
                    inner = _json.loads(raw)
                except (ValueError, TypeError):
                    inner = {}
        # ``CharmName`` is the RESOLVED charm URL (``ch:amd64/noble/ubuntu-26``);
        # jubilant's CLI rejects a trailing ``-<revision>`` in the charm name and
        # wants ``--revision`` separately. Strip the ``-<digits>`` suffix from
        # the last path segment so codegen emits a name the CLI accepts.
        raw_charm = inner.get("CharmName", "")
        charm = _strip_charm_url_revision(raw_charm)
        # Do NOT fall back to ``base.channel`` here: the base's channel
        # (e.g. ``24.04/stable``) is the *Ubuntu release channel*, not the
        # *charm's tracking channel* that jubilant's ``--channel`` selects.
        # If the user did not pin a charm channel, emit no channel and let
        # the CLI default to ``latest/stable``.
        return {
            "charm": charm,
            "app": inner.get("ApplicationName") or None,
            "channel": inner.get("channel") or None,
            "num_units": inner.get("num-units", 1),
            "config": {},
            "resources": inner.get("resources") or {},
        }

    if key == ("Application", "AddRelation"):
        endpoints = params.get("endpoints") or []
        ep1 = endpoints[0] if len(endpoints) > 0 else ""
        ep2 = endpoints[1] if len(endpoints) > 1 else ""
        return {"app1_endpoint": ep1, "app2_endpoint": ep2}

    if key == ("Application", "DestroyRelation"):
        endpoints = params.get("endpoints") or []
        ep1 = endpoints[0] if len(endpoints) > 0 else ""
        ep2 = endpoints[1] if len(endpoints) > 1 else ""
        return {"app1_endpoint": ep1, "app2_endpoint": ep2}

    if key == ("Application", "SetConfigs"):
        app_configs = params.get("application-configs") or [{}]
        ac = app_configs[0] if app_configs else {}
        return {"app": ac.get("application", ""), "values": ac.get("config") or {}}

    if key in (("Application", "Get"), ("Application", "GetConfig")):
        app = params.get(
            "application",
            params.get("entities", [{}])[0].get("tag", "").replace("application-", ""),
        )
        return {"app": app, "keys": None}

    if key == ("Application", "AddUnits"):
        # Relative: "add this many units". Maps to `Juju.add_unit()` — see
        # scale.py / the CLI corpus notes F1-F2.
        #
        # `placement` ([]instance.Placement, wire: {"scope", "directive"} dicts) and
        # `attach-storage` ([]string of "storage-<id>" tags) are confirmed against
        # juju's apiserver AddApplicationUnits params struct and addunit.go's client
        # command (not inferred from the CLI's own `--to`/`--attach-storage` spelling —
        # see the design notes). Rebuilt here into the same
        # comma-joined-string shape `cli_translate._classify_add_unit` already produces
        # from CLI argv, so `scale.py`'s emitter renders identical output regardless of
        # which source observed the operation.
        args: dict[str, Any] = {
            "app": params.get("application", ""),
            "units": params.get("num-units", 1),
            "mode": "relative",
        }
        placements = params.get("placement") or []
        to = ",".join(_placement_to_cli_str(p) for p in placements if p)
        if to:
            args["to"] = to
        storage_tags = params.get("attach-storage") or []
        attach_storage = ",".join(_storage_tag_to_id(tag) for tag in storage_tags if tag)
        if attach_storage:
            args["attach_storage"] = attach_storage
        return args

    if key == ("Application", "ScaleApplications"):
        # Absolute: "set K8s scale to N". No jubilant client method exists
        # for this — falls to `juju.cli("scale-application", ...)`.
        scale_params = (params.get("applications") or [{}])[0]
        return {
            "app": scale_params.get("application-tag", "").replace("application-", ""),
            "units": scale_params.get("scale", 1),
            "mode": "absolute",
        }

    if key == ("Application", "DestroyApplication"):
        entities = params.get("applications") or [{}]
        app_tag = entities[0].get("application-tag", "").replace("application-", "")
        return {"app": app_tag}

    if key in (("Action", "Enqueue"), ("Action", "EnqueueOperation")):
        actions = params.get("actions") or [{}]
        a = actions[0] if actions else {}
        return {
            "unit": _unit_tag_to_name(a.get("receiver", "")),
            "action": a.get("name", ""),
            "params": a.get("parameters") or {},
        }

    if key == ("Client", "Status"):
        return {}

    if key == ("Secrets", "CreateSecrets"):
        secrets = params.get("secrets") or [{}]
        s = secrets[0] if secrets else {}
        data = (s.get("content") or {}).get("data") or {}
        # Always redact secret values; preserve key names as a structure hint.
        redacted_content: dict[str, str] = {k: "<REDACTED>" for k in data}
        return {
            "name": s.get("label") or "",
            "content": redacted_content,
            "info": s.get("description") or None,
        }

    if key == ("Secrets", "UpdateSecrets"):
        secrets = params.get("secrets") or [{}]
        s = secrets[0] if secrets else {}
        data = (s.get("content") or {}).get("data") or {}
        redacted_content = {k: "<REDACTED>" for k in data}
        auto_prune = bool(s.get("auto-prune"))
        return {
            "identifier": s.get("existing-id") or "",
            "content": redacted_content,
            "info": s.get("description") or None,
            "name": s.get("label") or None,
            "auto_prune": auto_prune,
        }

    if key == ("Secrets", "RemoveSecrets"):
        secrets = params.get("secrets") or [{}]
        s = secrets[0] if secrets else {}
        revisions = s.get("revisions") or []
        return {
            "identifier": s.get("uri") or "",
            "revision": revisions[0] if revisions else None,
        }

    if key == ("Secrets", "GrantSecret"):
        apps = params.get("applications") or []
        return {
            "identifier": params.get("uri") or "",
            "app": apps[0] if apps else "",
        }

    if key == ("Secrets", "RevokeSecret"):
        # ``GrantRevokeSecretArg`` — same wire shape as ``GrantSecret``
        # (SECRETS-GAPS.md step 2).
        apps = params.get("applications") or []
        return {
            "identifier": params.get("uri") or "",
            "app": apps[0] if apps else "",
        }

    if key == ("Secrets", "ListSecrets"):
        filter_data = params.get("filter") or {}
        owner_tag = filter_data.get("owner-tag") or None
        # Strip the "application-" prefix from the owner tag if present.
        if owner_tag and owner_tag.startswith("application-"):
            owner: str | None = owner_tag.removeprefix("application-")
        else:
            owner = owner_tag
        return {"owner": owner}

    if key == ("ApplicationOffers", "Offer"):
        # Wire shape per the CMR facade notes §2.1: {"Offers": [AddApplicationOffer, ...]}.
        offers = params.get("Offers") or params.get("offers") or [{}]
        o = offers[0] if offers else {}
        return {
            "app": o.get("application-name", ""),
            "endpoints": o.get("endpoints") or {},
            "offer_name": o.get("offer-name") or None,
            "model_tag": o.get("model-tag") or None,
        }

    if key == ("ApplicationOffers", "ListApplicationOffers"):
        # No literal wire fixture in the recon (the CMR facade notes §2.3) —
        # shape inferred from the ``OfferFilter`` definition fields.
        filters = params.get("filters") or params.get("Filters") or [{}]
        f = filters[0] if filters else {}
        return {
            "model_name": f.get("model-name") or None,
            "application_name": f.get("application-name") or None,
            "offer_name": f.get("offer-name") or None,
        }

    if key == ("ApplicationOffers", "FindApplicationOffers"):
        # Same ``OfferFilter`` shape as ``ListApplicationOffers`` above
        # (the CMR facade notes §2.3); the two differ in what the server does
        # with the filter, not in how libjuju packs it.
        filters = params.get("filters") or params.get("Filters") or [{}]
        f = filters[0] if filters else {}
        return {
            "model_name": f.get("model-name") or None,
            "application_name": f.get("application-name") or None,
            "offer_name": f.get("offer-name") or None,
        }

    if key == ("ApplicationOffers", "DestroyOffers"):
        offer_urls = params.get("offer-urls") or params.get("OfferURLs") or []
        return {
            "force": bool(params.get("force")),
            "offer_urls": offer_urls,
        }

    if key == ("ApplicationOffers", "GetConsumeDetails"):
        # No literal wire fixture in the recon (the CMR facade notes §2.2) —
        # ``offer_urls`` is an ``OfferURLs`` wrapper around a list of strings.
        raw_urls = params.get("offer-urls") or params.get("OfferURLs") or []
        if isinstance(raw_urls, dict):
            raw_urls = raw_urls.get("offer-urls") or []
        return {
            "offer_urls": raw_urls,
            "user_tag": params.get("user-tag") or None,
        }

    if key == ("Application", "Consume"):
        args_list = params.get("args") or params.get("Args") or [{}]
        a = args_list[0] if args_list else {}
        return {
            "offer_url": a.get("offer-url", ""),
            "application_alias": a.get("application-alias") or None,
        }

    if key == ("Application", "DestroyConsumedApplications"):
        # No literal wire fixture in the recon (mentioned only by source
        # location, the CMR facade notes §5) — shape inferred from the
        # sibling ``DestroyApplication`` RPC's ``application-tag`` convention.
        apps = params.get("applications") or [{}]
        app_tag = apps[0].get("application-tag", "") if apps else ""
        return {"app": app_tag.replace("application-", "")}

    # -----------------------------------------------------------------
    # ``Application.*`` bucket-2 → bucket-1 promotions (see
    # the corpus audit §5 "Natural extension"). No live
    # wire fixture was captured for any of these eight — shapes below are
    # inferred from the apiserver's ``params.Application*`` request structs
    # (mirroring the field-naming conventions already seen above: kebab-case,
    # ``application``/``application-tag`` for the target app).
    # -----------------------------------------------------------------

    if key == ("Application", "SetCharm"):
        return {
            "app": params.get("application", ""),
            "charm_url": params.get("charm-url") or None,
            "channel": params.get("channel") or None,
            "force": bool(params.get("force")),
            "config_settings": params.get("config-settings") or {},
            "storage_constraints": params.get("storage-constraints") or {},
            "resource_ids": params.get("resource-ids") or {},
        }

    if key == ("Application", "Expose"):
        return {
            "app": params.get("application", ""),
            "exposed_endpoints": params.get("exposed-endpoints") or {},
        }

    if key == ("Application", "Unexpose"):
        return {
            "app": params.get("application", ""),
            "exposed_endpoints": params.get("exposed-endpoints") or [],
        }

    if key == ("Application", "SetConstraints"):
        return {
            "app": params.get("application", ""),
            "constraints": params.get("constraints") or {},
        }

    if key == ("Application", "MergeBindings"):
        # ``MergeBindings`` batches multiple applications per call
        # (``ApplicationMergeBindingsArgs{Args: []ApplicationMergeBindings}``);
        # the codegen surface only ever recorded one app per user gesture in
        # the sampled corpus, so only the first entry is used.
        args_list = params.get("args") or [{}]
        a = args_list[0] if args_list else {}
        app_tag = a.get("application-tag", "")
        return {
            "app": app_tag.replace("application-", ""),
            "bindings": a.get("bindings") or {},
            "force": bool(a.get("force")),
        }

    if key == ("Application", "SetRelationsSuspended"):
        # ``RelationSuspendedArgs{Args: []RelationSuspendedArg}`` — one
        # relation id per arg entry; a single user gesture (suspend/resume)
        # can name several relations at once, all sharing one suspended/
        # message value, so the batch is collapsed to a single event.
        args_list = params.get("args") or [{}]
        relation_ids = [
            a.get("relation-id") for a in args_list if a.get("relation-id") is not None
        ]
        first = args_list[0] if args_list else {}
        return {
            "relation_ids": relation_ids,
            "suspended": bool(first.get("suspended")),
            "message": first.get("message") or None,
        }

    if key == ("Application", "UnsetApplicationsConfig"):
        # ``ApplicationUnset{ApplicationName string, Options []string}``,
        # batched the same way ``SetConfigs`` is on the sibling RPC.
        args_list = params.get("args") or [{}]
        a = args_list[0] if args_list else {}
        return {
            "app": a.get("application", ""),
            "options": a.get("options") or [],
        }

    if key == ("Application", "UpdateApplicationBase"):
        args_list = params.get("args") or [{}]
        a = args_list[0] if args_list else {}
        app_tag = a.get("application-tag", "")
        base = a.get("base") or {}
        return {
            "app": app_tag.replace("application-", ""),
            "base_name": base.get("name") or None,
            "base_channel": base.get("channel") or None,
            "force": bool(a.get("force")),
        }

    return {}


def _format_ts(dt: datetime) -> str:
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def _parse_iso(ts: str) -> float:
    """Parse ISO-8601 UTC timestamp to a Unix timestamp float."""
    # e.g. "2026-06-22T01:02:03.456Z"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return 0.0


def _find_last_delta_ts(
    deltas: list[dict[str, Any]],
    window_start: float,
    window_end: float,
) -> float | None:
    """Return the latest delta timestamp in (window_start, window_end], or None."""
    latest: float | None = None
    for d in deltas:
        ts = _parse_iso(d.get("ts_iso", ""))
        if window_start < ts <= window_end and (latest is None or ts > latest):
            latest = ts
    return latest


# ---------------------------------------------------------------------------
# Main correlator
# ---------------------------------------------------------------------------


def correlate(
    rpcs: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    *,
    window_seconds: float = 2.0,
    idle_threshold_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Pair RPCs with their delta bursts; emit SCHEMA.md-shaped events.

    Parameters
    ----------
    rpcs:
        List of RPC records from ``LibjujuTap.rpcs``.
    deltas:
        List of delta records from ``LibjujuTap.deltas``.
    window_seconds:
        Deltas arriving within this many seconds after an RPC's end timestamp
        are attributed to that RPC.  Default 2 s.
    idle_threshold_seconds:
        Minimum quiet-window duration (seconds) between two consecutive
        user-facing RPCs that triggers synthesis of a ``wait_for_idle`` event.
        A "quiet window" is the period from the last AllWatcher delta arrival
        in the inter-RPC gap to the start of the next user RPC.  If ``None``
        (the default), the value is read from the ``LIBJUJU_IDLE_THRESHOLD_S``
        environment variable, falling back to 5.0 s.

    Returns
    -------
    list of event dicts in SCHEMA.md EventEnvelope shape, with ``seq``
    starting at 1.
    """
    if idle_threshold_seconds is None:
        try:
            idle_threshold_seconds = float(os.environ.get("LIBJUJU_IDLE_THRESHOLD_S", "5.0"))
        except ValueError:
            idle_threshold_seconds = 5.0
    # Filter to user-facing RPCs only
    user_rpcs = [r for r in rpcs if not _is_internal(r.get("facade", ""), r.get("method", ""))]

    # Attach deltas to their nearest preceding RPC within window_seconds.
    rpc_deltas: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(user_rpcs))}
    orphan_deltas: list[dict[str, Any]] = []

    for delta in deltas:
        delta_ts = _parse_iso(delta.get("ts_iso", ""))
        best_idx: int | None = None
        best_dist = float("inf")

        for i, rpc in enumerate(user_rpcs):
            rpc_end_ts = _parse_iso(rpc.get("ts_end_iso", ""))
            dist = delta_ts - rpc_end_ts  # positive = delta after RPC
            # Accept if delta arrives within window_seconds after (or just slightly before) RPC
            # end.
            if -0.5 <= dist <= window_seconds and dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx is not None:
            rpc_deltas[best_idx].append(delta)
        else:
            orphan_deltas.append(delta)

    # Build events by replaying model state and emitting one event per RPC.
    state = _ModelState()
    events: list[dict[str, Any]] = []
    seq = 0

    # Pre-apply all deltas that arrive before the first user RPC (initial sync burst).
    first_rpc_ts = _parse_iso(user_rpcs[0]["ts_end_iso"]) if user_rpcs else float("inf")
    pre_deltas = [
        d for d in deltas if _parse_iso(d.get("ts_iso", "")) < first_rpc_ts - window_seconds
    ]
    for d in pre_deltas:
        state.apply_delta(d)

    for i, rpc in enumerate(user_rpcs):
        facade = rpc.get("facade", "")
        method = rpc.get("method", "")
        params = rpc.get("params") or {}
        ts = rpc.get("ts_start_iso", rpc.get("ts_end_iso", ""))

        bucket, op = _classify(facade, method)

        rpc_start_ts_float = _parse_iso(rpc.get("ts_start_iso", ts))
        rpc_end_ts_float = _parse_iso(rpc.get("ts_end_iso", ts))
        duration_ms = max(0.0, (rpc_end_ts_float - rpc_start_ts_float) * 1000)

        snap_before = state.snapshot(rpc.get("ts_start_iso", ts))

        # Apply the deltas attributed to this RPC.
        attributed = rpc_deltas.get(i, [])
        for d in attributed:
            state.apply_delta(d)

        snap_after = state.snapshot(rpc.get("ts_end_iso", ts))

        seq += 1
        rpc_label = f"libjuju {facade}.{method}"

        if bucket == "1" and op is not None:
            args = _extract_args(facade, method, params)
            result: dict[str, Any] = {}
            if op == "deploy":
                result = {"app_name": args.get("app") or args.get("charm", "").split("/")[-1]}
            elif op == "config_get":
                result = {"values": {}}
            elif op == "run":
                result = {"success": True, "results": {}, "message": None}
            elif op == "secret_add":
                # URI is assigned by the controller; the tap does not capture
                # the response body, so we record an empty placeholder here.
                result = {"uri": ""}

            event: dict[str, Any] = {
                "seq": seq,
                "op": op,
                "ts": ts,
                "args": args,
                "result": result,
                "model_snapshot_before": snap_before,
                "model_snapshot_after": snap_after,
                "assertions": [],
                "gesture": None,
                "duration_ms": duration_ms,
                "_libjuju_source": rpc_label,
            }

        elif bucket == "2":
            event = {
                "seq": seq,
                "op": "shell",
                "ts": ts,
                "args": {"command": [f"# libjuju {facade}.{method}"], "cwd": None},
                "result": {"captured": False, "returncode": None, "stdout": None, "stderr": None},
                "model_snapshot_before": snap_before,
                "model_snapshot_after": snap_after,
                "assertions": [],
                "gesture": None,
                "duration_ms": duration_ms,
                "note": rpc_label,
                "_libjuju_source": rpc_label,
            }

        else:  # bucket 3
            event = {
                "seq": seq,
                "op": "_todo",
                "ts": ts,
                "args": {"_raw_facade": facade, "_raw_method": method, "_raw_params": params},
                "result": {},
                "model_snapshot_before": snap_before,
                "model_snapshot_after": snap_after,
                "assertions": [],
                "gesture": None,
                "duration_ms": duration_ms,
                "note": f"# TODO: manual step — {rpc_label}",
                "_libjuju_source": rpc_label,
            }

        events.append(event)

        # Synthesise a wait_for_idle event when the inter-RPC quiet window exceeds the threshold.
        # A "quiet window" starts at the last delta arrival in the gap and ends when the next RPC
        # starts.
        if i + 1 < len(user_rpcs):
            next_rpc = user_rpcs[i + 1]
            next_rpc_start_ts = _parse_iso(
                next_rpc.get("ts_start_iso", next_rpc.get("ts_end_iso", ""))
            )
            last_delta_ts = _find_last_delta_ts(deltas, rpc_end_ts_float, next_rpc_start_ts)
            window_start = last_delta_ts if last_delta_ts is not None else rpc_end_ts_float
            quiet_duration = next_rpc_start_ts - window_start
            if quiet_duration >= idle_threshold_seconds:
                quiet_start_iso = _format_ts(datetime.fromtimestamp(window_start, tz=UTC))
                settled_at_iso = _format_ts(datetime.fromtimestamp(next_rpc_start_ts, tz=UTC))
                idle_snap = state.snapshot(quiet_start_iso)
                seq += 1
                events.append(
                    {
                        "seq": seq,
                        "op": "wait_for_idle",
                        "ts": quiet_start_iso,
                        "args": {"apps": None, "timeout": None},
                        "result": {"settled_at": settled_at_iso},
                        "model_snapshot_before": idle_snap,
                        "model_snapshot_after": idle_snap,
                        "assertions": [],
                        "gesture": None,
                        "duration_ms": quiet_duration * 1000,
                        "_libjuju_source": "synthesised from AllWatcher cadence",
                    }
                )

    # Emit orphan event if there were unattributed deltas.
    if orphan_deltas:
        for d in orphan_deltas:
            state.apply_delta(d)
        seq += 1
        now_iso = _format_ts(datetime.now(UTC))
        events.append(
            {
                "seq": seq,
                "op": "_libjuju_orphan_deltas",
                "ts": now_iso,
                "args": {},
                "result": {"orphan_delta_count": len(orphan_deltas)},
                "model_snapshot_before": None,
                "model_snapshot_after": state.snapshot(now_iso),
                "assertions": [],
                "gesture": None,
                "duration_ms": 0.0,
                "note": f"# {len(orphan_deltas)} delta(s) not attributable to any RPC",
            }
        )

    return events
