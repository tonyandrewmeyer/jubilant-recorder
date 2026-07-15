from __future__ import annotations

from jubilant_recorder.codegen.operations import (
    config,
    config_get,
    consume,
    create_offer,
    deploy,
    integrate,
    remove_application,
    remove_integration,
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
    # correlator-classified bucket-1 (the CMR facade notes) but jubilant 1.10
    # has no client method for any of them (confirmed by grepping
    # jubilant/_juju.py — see the corpus audit §5) — no
    # EMITTERS entry, so they fall through to the fallback `# TODO: manual
    # step` renderer like any other unmapped op.
}

__all__ = [
    "EMITTERS",
    "config",
    "config_get",
    "consume",
    "create_offer",
    "deploy",
    "integrate",
    "remove_application",
    "remove_integration",
    "run_action",
    "scale",
    "secret_add",
    "secret_grant",
    "secret_list",
    "secret_remove",
    "secret_update",
    "wait_for_idle",
]
