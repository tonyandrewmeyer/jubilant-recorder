"""Example test generated from a recorded libjuju session."""

import jubilant


def test_ubuntu_deploy():
    """Deploy ubuntu and wait for it to become active."""
    with jubilant.temp_model() as juju:
        juju.deploy("ch:amd64/noble/ubuntu", app="ubuntu")
        assert len(juju.status().apps["ubuntu"].units) == 1
        juju.wait(jubilant.all_active)
        # TODO: manual step — config_get
        # {
        #   "args": {
        #     "app": "ubuntu",
        #     "keys": null
        #   },
        #   "op": "config_get",
        #   "result": {
        #     "values": {}
        #   }
        # }
        # TODO: manual step — _libjuju_orphan_deltas
        # {
        #   "args": {},
        #   "op": "_libjuju_orphan_deltas",
        #   "result": {
        #     "orphan_delta_count": 25
        #   }
        # }
        assert juju.status().apps["ubuntu"].units["ubuntu/0"].workload_status.current == "active"
        assert len(juju.status().apps["ubuntu"].units) == 1
