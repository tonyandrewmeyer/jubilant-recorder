import jubilant
import pytest


def test_postgresql_config_action():
    with jubilant.temp_model() as juju:
        juju.deploy('postgresql', channel='14/stable')
        assert len(juju.status().apps['postgresql'].units) == 1
        juju.deploy('data-integrator', channel='latest/stable', config={'database-name': 'demo_db'})
        assert len(juju.status().apps['data-integrator'].units) == 1
        juju.integrate('postgresql', 'data-integrator')
        assert any(r.related_app == 'postgresql'
            for r in juju.status().apps['data-integrator'].relations.get('postgresql', []))
        juju.wait(jubilant.all_active, timeout=1800)
        for _u in juju.status().apps['data-integrator'].units.values():
            assert _u.workload_status.current == 'active'
        for _u in juju.status().apps['postgresql'].units.values():
            assert _u.workload_status.current == 'active'
        juju.config('data-integrator', values={'extra-user-roles': 'SELECT'})
        juju.wait(jubilant.all_active, timeout=600)
        result_7 = juju.run('data-integrator/0', 'get-credentials')
        assert result_7.success
        assert result_7.results['ok'] == 'True'
        juju.wait(lambda s: jubilant.all_active(s, *['postgresql']))
        assert juju.status().apps['postgresql'].units['postgresql/0'].workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, *['data-integrator']))
        assert juju.status().apps['data-integrator'].units['data-integrator/0'].workload_status.current == 'active'
        # TODO: manual step — codegen can't represent failed session.error: assert_action_result() got an unexpected keyword argument 'unit'
        # attempted: session.error()
        pytest.skip(reason='recorded session: session.error failed — review and replace this step')
