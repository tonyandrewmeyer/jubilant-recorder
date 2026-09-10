import jubilant
import pytest


def test_k8s_wait_timeout():
    with jubilant.temp_model() as juju:
        # NOTE: this session was recorded against a model that already had
        # applications deployed (postgresql-k8s (1 unit), scheduler-admin-k8s (1 unit), scheduler-k8s (1 unit), web-frontend (1 unit)), which jubilant.temp_model() above does not
        # recreate — it gives this test a fresh, empty model. Set that state
        # up by hand if the recorded operations below assumed it was there.
        juju.deploy('data-integrator', channel='latest/edge', config={'database-name': 'real_world_demo'}, trust=True)
        assert len(juju.status().apps['data-integrator'].units) == 1
        juju.integrate('postgresql-k8s', 'data-integrator')
        assert any(r.related_app == 'postgresql-k8s'
            for r in juju.status().apps['data-integrator'].relations.get('postgresql', []))
        # TODO: manual step — codegen can't represent failed wait_for_idle: wait timed out after 900s
        # attempted: wait_for_idle(apps=None, timeout=900)
        pytest.skip(reason='recorded session: wait_for_idle failed — review and replace this step')
        # TODO: manual step — codegen can't represent failed session.error: wait timed out after 900s
        # attempted: session.error()
        # (unreachable — an earlier step already skipped this test)
