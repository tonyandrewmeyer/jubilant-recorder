"""The pytest plugin that records an existing suite as it runs.

Driven through pytest's own `pytester` fixture: the plugin's contract is
about what happens to a *pytest run*, so testing it any other way would
test the parts and not the thing.

libjuju itself is not involved — `RecordingLibjuju` is exercised properly
in `tests/libjuju/`, and what matters here is that the plugin records one
session per test, in order, and renders them as one module.
"""

from __future__ import annotations

import json

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture
def suite(pytester: pytest.Pytester) -> pytest.Pytester:
    """A two-test suite that writes a session log entry when it runs."""
    pytester.makepyfile(
        test_charm="""
        def test_deploy():
            assert True

        def test_scale():
            assert True
        """
    )
    return pytester


def test_no_flag_records_nothing(suite: pytest.Pytester) -> None:
    """The plugin autoloads for everyone, so it must be inert by default."""
    result = suite.runpytest()
    result.assert_outcomes(passed=2)
    assert not list(suite.path.glob("**/*.json"))


def test_one_session_log_per_test(suite: pytest.Pytester) -> None:
    result = suite.runpytest(f"--jtr-record={suite.path / 'sessions'}")
    result.assert_outcomes(passed=2)
    written = sorted(p.name for p in (suite.path / "sessions").glob("*.json"))
    assert written == ["test_deploy.json", "test_scale.json"]


def test_generated_module_has_a_test_per_recorded_test(suite: pytest.Pytester) -> None:
    out = suite.path / "test_migrated.py"
    result = suite.runpytest(f"--jtr-out={out}")
    result.assert_outcomes(passed=2)
    source = out.read_text()
    assert "def test_deploy(juju: jubilant.Juju):" in source
    assert "def test_scale(juju: jubilant.Juju):" in source
    # One shared model, because pytest-operator's own fixture is module-scoped.
    assert source.count("temp_model") == 1
    assert source.index("def test_deploy") < source.index("def test_scale")


def test_jtr_out_alone_still_keeps_the_session_logs(suite: pytest.Pytester) -> None:
    """The logs are the evidence; losing them would make the output unauditable."""
    out = suite.path / "test_migrated.py"
    suite.runpytest(f"--jtr-out={out}")
    logs = sorted(p.name for p in (suite.path / "test_migrated-sessions").glob("*.json"))
    assert logs == ["test_deploy.json", "test_scale.json"]


def test_parametrised_test_names_survive_as_identifiers(pytester: pytest.Pytester) -> None:
    """`test_deploy[pg-16]` has to become something Python will accept."""
    pytester.makepyfile(
        test_charm="""
        import pytest

        @pytest.mark.parametrize("channel", ["14/stable", "16/edge"])
        def test_deploy(channel):
            assert channel
        """
    )
    out = pytester.path / "test_migrated.py"
    pytester.runpytest(f"--jtr-out={out}")
    source = out.read_text()
    assert "def test_deploy_14_stable(juju: jubilant.Juju):" in source
    assert "def test_deploy_16_edge(juju: jubilant.Juju):" in source
    compile(source, "test_migrated.py", "exec")


def test_a_failing_test_is_still_recorded(pytester: pytest.Pytester) -> None:
    """What the test did to the model before it failed is still worth having."""
    pytester.makepyfile(
        test_charm="""
        def test_deploy():
            raise AssertionError("boom")
        """
    )
    sessions = pytester.path / "sessions"
    result = pytester.runpytest(f"--jtr-record={sessions}")
    result.assert_outcomes(failed=1)
    log = json.loads((sessions / "test_deploy.json").read_text())
    assert log["events"] or log.get("schema_version")
