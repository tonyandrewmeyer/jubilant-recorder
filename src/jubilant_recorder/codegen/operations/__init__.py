from __future__ import annotations

from jubilant_recorder.codegen.operations import (
    config,
    deploy,
    integrate,
    run_action,
    scale,
    wait_for_idle,
)

EMITTERS = {
    "deploy": deploy.emit,
    "integrate": integrate.emit,
    "config": config.emit,
    "scale": scale.emit,
    "run": run_action.emit,
    "wait_for_idle": wait_for_idle.emit,
}

__all__ = [
    "EMITTERS",
    "config",
    "deploy",
    "integrate",
    "run_action",
    "scale",
    "wait_for_idle",
]
