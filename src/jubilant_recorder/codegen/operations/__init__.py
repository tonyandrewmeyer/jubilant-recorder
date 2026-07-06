from __future__ import annotations

from jubilant_recorder.codegen.operations import (
    config,
    deploy,
    integrate,
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
    "integrate": integrate.emit,
    "config": config.emit,
    "scale": scale.emit,
    "run": run_action.emit,
    "wait_for_idle": wait_for_idle.emit,
    "secret_add": secret_add.emit,
    "secret_update": secret_update.emit,
    "secret_remove": secret_remove.emit,
    "secret_grant": secret_grant.emit,
    "secret_list": secret_list.emit,
}

__all__ = [
    "EMITTERS",
    "config",
    "deploy",
    "integrate",
    "run_action",
    "scale",
    "secret_add",
    "secret_grant",
    "secret_list",
    "secret_remove",
    "secret_update",
    "wait_for_idle",
]
