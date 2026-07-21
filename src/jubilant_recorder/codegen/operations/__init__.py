from __future__ import annotations

from jubilant_recorder.codegen.operations import (
    config,
    config_get,
    consume,
    create_offer,
    deploy,
    get_consume_details,
    integrate,
    list_offers,
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
    secret_update,
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
    "create_offer": create_offer.emit,
    "consume": consume.emit,
    # "list_offers", "remove_offer", "get_consume_details", "remove_saas" are
    # correlator-classified bucket-1 (the CMR facade notes), and jubilant 1.10
    # still has no dedicated client method for any of them — but each is
    # emitted via `juju.cli(...)`, jubilant's public escape hatch
    # (`jubilant/_juju.py:527`; already used by jubilant's own `bootstrap()`).
    # See the corpus audit §5. If jubilant later grows
    # typed client methods for these, swap the `cli()` calls for them here.
    "list_offers": list_offers.emit,
    "remove_offer": remove_offer.emit,
    "get_consume_details": get_consume_details.emit,
    "remove_saas": remove_saas.emit,
}

__all__ = [
    "EMITTERS",
    "config",
    "config_get",
    "consume",
    "create_offer",
    "deploy",
    "get_consume_details",
    "integrate",
    "list_offers",
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
    "secret_update",
    "wait_for_idle",
]
