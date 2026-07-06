from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen.operations import (
    config,
    config_get,
    deploy,
    integrate,
    run_action,
    scale,
    wait_for_idle,
)


def test_deploy_minimal(deploy_event: dict[str, Any]) -> None:
    line = deploy.emit(deploy_event, indent=8)
    assert line == "        juju.deploy('my-charm', channel='edge')"


def test_deploy_with_base() -> None:
    """The carry from step 3: the `base=` kwarg must survive a round-trip
    through the codegen, in the position before `channel=` (matches the
    jubilant signature ordering)."""
    event = {
        "args": {
            "charm": "ubuntu",
            "app": "ubuntu",
            "base": "ubuntu@24.04",
            "channel": None,
        }
    }
    line = deploy.emit(event, indent=8)
    assert line == "        juju.deploy('ubuntu', app='ubuntu', base='ubuntu@24.04')"


def test_deploy_with_trust_and_revision() -> None:
    event = {
        "args": {
            "charm": "my-charm",
            "trust": True,
            "revision": 42,
        }
    }
    line = deploy.emit(event, indent=4)
    assert line == "    juju.deploy('my-charm', revision=42, trust=True)"


def test_deploy_drops_defaults() -> None:
    """``trust=False`` and ``force=False`` (the jubilant defaults) must not
    leak into the emitted call — kept tight."""
    event = {
        "args": {
            "charm": "my-charm",
            "trust": False,
            "force": False,
            "base": None,
            "revision": None,
            "num_units": 1,
        }
    }
    line = deploy.emit(event, indent=0)
    assert line == "juju.deploy('my-charm')"


def test_deploy_with_app_and_config() -> None:
    event = {
        "args": {
            "charm": "my-charm",
            "app": "myapp",
            "channel": "edge",
            "num_units": 3,
            "config": {"log-level": "debug"},
            "resources": {"image": "img:latest"},
        }
    }
    line = deploy.emit(event, indent=4)
    assert line == (
        "    juju.deploy('my-charm', app='myapp', channel='edge', "
        "num_units=3, config={'log-level': 'debug'}, "
        "resources={'image': 'img:latest'})"
    )


def test_integrate(integrate_event: dict[str, Any]) -> None:
    line = integrate.emit(integrate_event, indent=8)
    assert line == "        juju.integrate('my-charm:db', 'postgresql:database')"


def test_config_set(config_event: dict[str, Any]) -> None:
    line = config.emit(config_event, indent=8)
    assert line == "        juju.config('my-charm', values={'log-level': 'info'})"


def test_config_get_full(config_get_event: dict[str, Any]) -> None:
    line = config_get.emit(config_get_event, indent=8, var_name="config_10")
    assert line == "        config_10 = juju.config('my-charm')"


def test_config_get_specific_keys(config_get_specific_keys_event: dict[str, Any]) -> None:
    line = config_get.emit(config_get_specific_keys_event, indent=8, var_name="config_11")
    assert line == (
        "        config_11 = juju.config('my-charm')"
        "  # requested keys: ['log-level', 'debug']"
        " — juju.config() always returns the full dict"
    )


def test_config_get_without_var() -> None:
    event = {"args": {"app": "my-charm", "keys": None}}
    line = config_get.emit(event, indent=8)
    assert line == "        juju.config('my-charm')"


def test_scale(scale_event: dict[str, Any]) -> None:
    line = scale.emit(scale_event, indent=8)
    assert line == "        juju.scale('my-charm', units=3)"


def test_run_action_with_var(run_event: dict[str, Any]) -> None:
    line = run_action.emit(run_event, indent=8, var_name="result_5")
    assert line == ("        result_5 = juju.run('my-charm/0', 'do-thing', params={'key': 'val'})")


def test_run_action_without_var(run_event: dict[str, Any]) -> None:
    line = run_action.emit(run_event, indent=8)
    assert line == ("        juju.run('my-charm/0', 'do-thing', params={'key': 'val'})")


def test_run_action_no_params() -> None:
    event = {"args": {"unit": "my-charm/0", "action": "noop", "params": {}}}
    line = run_action.emit(event, indent=8)
    assert line == "        juju.run('my-charm/0', 'noop')"


def test_wait_for_idle_with_args(wait_for_idle_event: dict[str, Any]) -> None:
    line = wait_for_idle.emit(wait_for_idle_event, indent=8)
    assert (
        line == "        juju.wait(lambda s: jubilant.all_active(s, *['my-charm']), timeout=300)"
    )


def test_wait_for_idle_bare() -> None:
    event = {"args": {"apps": None, "timeout": None}}
    line = wait_for_idle.emit(event, indent=8)
    assert line == "        juju.wait(jubilant.all_active)"
