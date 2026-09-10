import jubilant


def test_ubuntu_deploy():
    with jubilant.temp_model() as juju:
        juju.deploy('ch:amd64/noble/ubuntu', app='ubuntu')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active)
        juju.config('ubuntu')
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        assert len(juju.status().apps['ubuntu'].units) == 1
