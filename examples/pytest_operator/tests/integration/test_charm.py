#!/usr/bin/env python3
"""A small pytest-operator suite, in the shape real charm suites use.

Deploys published charms rather than building any, so it runs anywhere a
controller does — the point here is the *recording*, not the charm.

Modelled on the integration suites in canonical/data-integrator and
friends: a module-scoped `ops_test`, tests that run in order and build on
each other, `asyncio.gather` over deploys, `wait_for_idle`, `get_config`,
`add_units`, `destroy_units`, and a teardown.
"""

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

APP = "ubuntu"
PEER = "ubuntu-peer"


@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest):
    """Deploy the applications under test."""
    await asyncio.gather(
        ops_test.model.deploy(APP, application_name=APP, num_units=1, base="ubuntu@24.04"),
        ops_test.model.deploy(APP, application_name=PEER, num_units=1, base="ubuntu@24.04"),
    )
    await ops_test.model.wait_for_idle(apps=[APP, PEER], status="active", timeout=900)
    assert ops_test.model.applications[APP].status == "active"


async def test_read_config(ops_test: OpsTest):
    """Read an application's configuration."""
    config = await ops_test.model.applications[APP].get_config()
    logger.info("%s config keys: %s", APP, sorted(config))
    assert isinstance(config, dict)


async def test_scale_up(ops_test: OpsTest):
    """Add a unit and wait for it to settle."""
    await ops_test.model.applications[APP].add_units(count=1)
    await ops_test.model.wait_for_idle(apps=[APP], status="active", timeout=900)
    assert len(ops_test.model.applications[APP].units) == 2


async def test_scale_down(ops_test: OpsTest):
    """Remove the unit again."""
    unit = ops_test.model.applications[APP].units[-1]
    await ops_test.model.applications[APP].destroy_units(unit.name)
    await ops_test.model.wait_for_idle(apps=[APP], status="active", timeout=900)
    assert len(ops_test.model.applications[APP].units) == 1


async def test_remove_peer(ops_test: OpsTest):
    """Tear one application down."""
    await ops_test.model.remove_application(PEER, block_until_done=True)
    assert PEER not in ops_test.model.applications
