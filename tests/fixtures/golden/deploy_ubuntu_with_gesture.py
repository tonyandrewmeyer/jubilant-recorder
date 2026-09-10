import jubilant


def test_deploy_ubuntu_with_gesture():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu', app='ubuntu')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active, timeout=900)
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, 'ubuntu'))
        assert juju.status().apps['ubuntu'].units['ubuntu/0'].workload_status.current == 'active'
