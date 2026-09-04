"""Per-operation code emitters."""

from __future__ import annotations

from jubilant_recorder.codegen.operations import (
    config,
    config_get,
    config_unset,
    consume,
    create_offer,
    deploy,
    expose,
    find_offers,
    get_consume_details,
    integrate,
    list_offers,
    merge_bindings,
    remove_application,
    remove_integration,
    remove_offer,
    remove_saas,
    run_action,
    scale,
    secret_add,
    secret_grant,
    secret_list,
    secret_remove,
    secret_revoke,
    secret_update,
    set_charm,
    set_constraints,
    set_relations_suspended,
    unexpose,
    update_application_base,
    wait_for_idle,
)

EMITTERS = {
    "deploy": deploy.emit,
    "remove_application": remove_application.emit,
    "integrate": integrate.emit,
    "remove_integration": remove_integration.emit,
    "config": config.emit,
    "config_get": config_get.emit,
    "scale": scale.emit,
    "run": run_action.emit,
    "wait_for_idle": wait_for_idle.emit,
    "secret_add": secret_add.emit,
    "secret_update": secret_update.emit,
    "secret_remove": secret_remove.emit,
    "secret_grant": secret_grant.emit,
    "secret_list": secret_list.emit,
    # "secret_revoke" and "find_offers" (below) were the last two members of
    # the correlator's bucket-2 set, promoted 2026-08-18 for the same reason
    # as the CMR and `Application.*` groups: bucket 2 there only ever meant
    # "jubilant has no client method", which `juju.cli()` answers. That set is
    # now empty by design — see `_BUCKET2_FACADES`' comment in
    # extensions/libjuju/correlate.py. `juju revoke-secret` and
    # `juju find-offers` were both verified against juju 3.6.27 rather than
    # assumed, per the `set_charm` lesson (`juju set-charm` is not a real
    # subcommand; the target is `juju refresh --switch`).
    "secret_revoke": secret_revoke.emit,
    "create_offer": create_offer.emit,
    "consume": consume.emit,
    # "list_offers", "remove_offer", "get_consume_details", "remove_saas" are
    # correlator-classified bucket-1, and jubilant 1.10 still has no
    # dedicated client method for any of them — but each is emitted via
    # `juju.cli(...)`, jubilant's public escape hatch (`jubilant/_juju.py:527`;
    # already used by jubilant's own `bootstrap()`). If jubilant later grows
    # typed client methods for these, swap the `cli()` calls for them here.
    "list_offers": list_offers.emit,
    "remove_offer": remove_offer.emit,
    "get_consume_details": get_consume_details.emit,
    "remove_saas": remove_saas.emit,
    # `find_offers` drops the correlator's captured filters, exactly as
    # `list_offers` does — see that emitter's docstring.
    "find_offers": find_offers.emit,
    # "set_charm", "expose", "unexpose", "set_constraints", "merge_bindings",
    # "set_relations_suspended", "config_unset", "update_application_base"
    # are the 8 `Application.*` bucket-2 → bucket-1 promotions — same
    # shape as the CMR ops above (no jubilant client method, but a direct
    # `juju` CLI subcommand), so each is emitted via `juju.cli(...)` too,
    # rather than falling through to the bucket-2 shell/TODO stub.
    "set_charm": set_charm.emit,
    "expose": expose.emit,
    "unexpose": unexpose.emit,
    "set_constraints": set_constraints.emit,
    "merge_bindings": merge_bindings.emit,
    "set_relations_suspended": set_relations_suspended.emit,
    "config_unset": config_unset.emit,
    "update_application_base": update_application_base.emit,
}

__all__ = [
    "EMITTERS",
    "config",
    "config_get",
    "config_unset",
    "consume",
    "create_offer",
    "deploy",
    "expose",
    "find_offers",
    "get_consume_details",
    "integrate",
    "list_offers",
    "merge_bindings",
    "remove_application",
    "remove_integration",
    "remove_offer",
    "remove_saas",
    "run_action",
    "scale",
    "secret_add",
    "secret_grant",
    "secret_list",
    "secret_remove",
    "secret_revoke",
    "secret_update",
    "set_charm",
    "set_constraints",
    "set_relations_suspended",
    "unexpose",
    "update_application_base",
    "wait_for_idle",
]
