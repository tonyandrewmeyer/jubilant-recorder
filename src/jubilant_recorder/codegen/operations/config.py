from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    args = event["args"]
    app = args["app"]
    values = args["values"]
    return " " * indent + f"juju.config({app!r}, values={values!r})"
