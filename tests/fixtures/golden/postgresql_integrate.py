import jubilant


def test_postgresql_integrate():
    with jubilant.temp_model() as juju:
        juju.deploy('postgresql', channel='14/stable')
        assert len(juju.status().apps['postgresql'].units) == 1
        juju.deploy('data-integrator', channel='latest/stable', config={'database-name': 'demo_db'})
        assert len(juju.status().apps['data-integrator'].units) == 1
        juju.integrate('postgresql', 'data-integrator')
        assert any(r.related_app == 'postgresql'
            for r in juju.status().apps['data-integrator'].relations.get('postgresql', []))
        juju.wait(jubilant.all_active, timeout=900)
        for _u in juju.status().apps['data-integrator'].units.values():
            assert _u.workload_status.current == 'active'
        for _u in juju.status().apps['postgresql'].units.values():
            assert _u.workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, *['postgresql']))
        assert juju.status().apps['postgresql'].units['postgresql/0'].workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, *['data-integrator']))
        assert juju.status().apps['data-integrator'].units['data-integrator/0'].workload_status.current == 'active'
