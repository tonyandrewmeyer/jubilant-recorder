from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="run the end-to-end tests, which need a real Juju controller",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect e2e tests unless they are asked for.

    The rest of the suite is fixture-driven and offline. These are neither, so
    a plain `pytest` in a checkout that happens to have a controller configured
    should not start deploying charms.
    """
    if config.getoption("--e2e") or os.environ.get("JTR_E2E"):
        return
    skip = pytest.mark.skip(reason="needs a real Juju controller; run with --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
