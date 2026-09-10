# Recording a pytest-operator suite

A small `pytest-operator` integration suite, used to exercise the migration
path end to end: run it under the recorder and read the jubilant test that
comes out.

It deploys published charms rather than building any, so it runs anywhere a
controller does. The point is the recording, not the charm.

## Running it under the recorder

```bash
cd examples/pytest_operator
uv run --with pytest-operator --with pytest-asyncio \
    --with 'jubilant-recorder[libjuju] @ ../..' \
    pytest tests/integration --jtr-out=test_migrated.py
```

Nothing about the suite changes — no conftest edit, no import. The plugin
ships with `jubilant-recorder` and hooks nothing unless one of its options
is passed. See [docs/libjuju.md](../../docs/libjuju.md#migrating-a-charms-integration-suite).

## What comes out

One test per recorded test, in the order they ran, sharing a module-scoped
`juju` fixture — the same shape `ops_test` already gives them:

```python
import jubilant
import pytest


@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju: jubilant.Juju):
    juju.deploy("ch:amd64/noble/ubuntu", app="ubuntu")
    assert len(juju.status().apps["ubuntu"].units) == 1
    juju.deploy("ch:amd64/noble/ubuntu", app="ubuntu-peer")
    juju.wait(jubilant.all_active)
    for _u in juju.status().apps["ubuntu"].units.values():
        assert _u.workload_status.current == "active"
```

A starting point, not a finished suite: the recorder sees what each test
*did* to the model, and a test's own assertions live in Python that never
reaches the wire. Read the file and expect to add those back.

## Automated coverage

`tests/e2e/test_pytest_plugin_mode.py` runs this shape against a real
controller and then runs the module it generates, so both halves of the
claim are checked rather than described.
