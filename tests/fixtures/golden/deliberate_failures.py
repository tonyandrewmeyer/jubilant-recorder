import jubilant
import pytest


def test_deliberate_failures():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu', app='ubuntu', base='ubuntu@24.04')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active, timeout=300)
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, *['ubuntu']))
        assert juju.status().apps['ubuntu'].units['ubuntu/0'].workload_status.current == 'active'
        # TODO: manual step — codegen can't represent failed deploy: Command '['juju', 'deploy', '--model', 'jtr-demo', 'totally-nonexistent-charm-zzz', '--channel', 'latest/edge']' returned non-zero exit status 1.
        # attempted: deploy(app=None, attach_storage=None, base=None, bind=None, channel='latest/edge', charm='totally-nonexistent-charm-zzz', config={}, constraints=None, force=False, num_units=1, overlays=[], resources={}, revision=None, storage=None, to=None, trust=False)
        pytest.skip(reason='recorded session: deploy failed — review and replace this step')
        # TODO: manual step — codegen can't represent failed integrate: Command '['juju', 'integrate', '--model', 'jtr-demo', 'ubuntu', 'ubuntu']' returned non-zero exit status 1.
        # attempted: integrate(app1_endpoint='ubuntu', app2_endpoint='ubuntu')
        # (unreachable — an earlier step already skipped this test)
