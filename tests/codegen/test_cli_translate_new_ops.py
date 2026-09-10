"""Translation of the `juju` subcommands that map onto jubilant methods.

These are the subcommands that used to render as `# shell:` comments
because `cli_translate` had no classifier for them. Each assertion here
pins both halves of the mapping: the argv shape that is claimed, and the
argv shape that is deliberately *not* (falling through to `juju.cli`
rather than being translated approximately).
"""

from __future__ import annotations

import pytest

from jubilant_recorder.codegen import cli_translate
from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap


def _c(*argv: str) -> tuple[str, dict]:
    """``classify_argv``, narrowed: every argv here is non-empty, so it classifies."""
    result = cli_translate.classify_argv(list(argv))
    assert result is not None, f"argv did not classify: {argv}"
    return result


def _src(*argv: str, exit_code: int = 0) -> str:
    event = {
        "seq": 1,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": list(argv), "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": exit_code},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }
    return generate(_wrap([event]))


# --- status ---


def test_status_translates() -> None:
    assert _c("status") == ("status_call", {})
    assert "juju.status()" in _src("status")


def test_status_output_flags_are_dropped() -> None:
    """`juju.status()` picks its own format and returns a typed Status."""
    assert _c("status", "--format", "json", "--relations") == ("status_call", {})


def test_status_filter_falls_through_to_cli() -> None:
    """jubilant's `status()` has no filter argument, so the filter must survive."""
    assert _c("status", "ubuntu")[0] == "cli_passthrough"


def test_status_watch_falls_through_to_cli() -> None:
    assert _c("status", "--watch", "5s")[0] == "cli_passthrough"


# --- model lifecycle ---


def test_a_second_add_model_is_a_real_call() -> None:
    """Only the session's *own* model is the one temp_model() stands in for."""
    src = generate(_wrap([_shim(1, ["add-model", "demo"]), _shim(2, ["add-model", "other"])]))
    assert "juju.add_model('other')" in src


def test_add_model_of_the_session_model_is_a_note() -> None:
    """temp_model() already made the model; add_model() would redirect away from it."""
    src = generate(
        _wrap(
            [
                _shim(1, ["add-model", "demo"]),
                _shim(2, ["deploy", "ubuntu"]),
            ]
        )
    )
    assert "juju.add_model(" not in src
    assert "jubilant.temp_model() above creates the" in src
    assert "juju.deploy('ubuntu')" in src


def test_destroy_model_of_the_session_model_is_a_note() -> None:
    src = generate(
        _wrap(
            [_shim(1, ["add-model", "demo"]), _shim(2, ["destroy-model", "demo", "--no-prompt"])]
        )
    )
    assert "juju.destroy_model(" not in src
    assert "tears the" in src


def test_destroy_model_of_another_model_is_a_real_call() -> None:
    src = generate(
        _wrap(
            [
                _shim(1, ["add-model", "demo"]),
                _shim(2, ["destroy-model", "leftovers", "--no-prompt"]),
            ]
        )
    )
    assert "juju.destroy_model('leftovers')" in src


def test_destroy_model_flags() -> None:
    assert _c("destroy-model", "m", "--no-prompt", "--force", "--timeout", "5m") == (
        "destroy_model",
        {"model": "m", "force": True, "timeout": 300.0},
    )


def test_switch_to_the_session_model_is_a_note() -> None:
    src = _src("switch", "demo")
    assert "juju.cli('switch'" not in src
    assert "this test's model is the one temp_model() made" in src


def test_switch_to_another_model_points_at_a_second_juju() -> None:
    src = generate(_wrap([_shim(1, ["add-model", "demo"]), _shim(2, ["switch", "other"])]))
    assert "juju.cli('switch'" not in src
    assert "jubilant.Juju(model='other')" in src


def test_session_model_inference_prefers_add_model() -> None:
    events = [_shim(1, ["switch", "old"]), _shim(2, ["add-model", "new"])]
    assert cli_translate.session_model(events) == "new"


def test_session_model_falls_back_to_the_model_flag() -> None:
    events = [_shim(1, ["status", "-m", "prod"]), _shim(2, ["deploy", "u", "-m", "prod"])]
    assert cli_translate.session_model(events) == "prod"


def test_session_model_is_none_when_never_named() -> None:
    assert cli_translate.session_model([_shim(1, ["status"])]) is None


# --- units and machines ---


def test_remove_unit_machine_model_shape() -> None:
    assert _c("remove-unit", "ubuntu/1", "ubuntu/2") == (
        "remove_unit",
        {"app_or_unit": ["ubuntu/1", "ubuntu/2"]},
    )
    assert "juju.remove_unit('ubuntu/1', 'ubuntu/2')" in _src(
        "remove-unit", "ubuntu/1", "ubuntu/2"
    )


def test_remove_unit_k8s_shape() -> None:
    """`--num-units` only; `juju remove-unit -n` is rejected outright."""
    assert _c("remove-unit", "ubuntu", "--num-units", "2") == (
        "remove_unit",
        {"app_or_unit": ["ubuntu"], "num_units": 2},
    )


def test_remove_unit_num_units_with_several_targets_falls_through() -> None:
    """jubilant raises TypeError for that combination rather than accepting it."""
    assert _c("remove-unit", "a", "b", "--num-units", "2")[0] == "cli_passthrough"


def test_add_machine() -> None:
    assert _c("add-machine", "lxd:0", "--base", "ubuntu@24.04", "-n", "3") == (
        "add_machine",
        {"target": "lxd:0", "base": "ubuntu@24.04", "num_machines": 3},
    )
    assert "juju.add_machine()" in _src("add-machine")


# --- ssh / exec / scp ---


def test_ssh_command_and_args() -> None:
    assert "juju.ssh('ubuntu/0', 'ls', '-la')" in _src("ssh", "ubuntu/0", "ls", "-la")


def test_ssh_user_and_container() -> None:
    assert _c("ssh", "--container", "web", "root@ubuntu/0", "ls") == (
        "ssh",
        {"target": "ubuntu/0", "command": "ls", "container": "web", "user": "root"},
    )


def test_ssh_without_a_command_falls_through_to_cli() -> None:
    """`Juju.ssh()` requires a command; an interactive login has no equivalent."""
    assert _c("ssh", "ubuntu/0")[0] == "cli_passthrough"


def test_exec_unit_and_machine() -> None:
    assert "juju.exec('hostname', unit='ubuntu/0')" in _src(
        "exec", "--unit", "ubuntu/0", "hostname"
    )
    assert "juju.exec('hostname', machine='0')" in _src("exec", "--machine", "0", "hostname")


@pytest.mark.parametrize(
    "argv",
    [
        ["exec", "--all", "hostname"],
        ["exec", "--application", "ubuntu", "hostname"],
        ["exec", "--unit", "ubuntu/0,ubuntu/1", "hostname"],
        ["exec", "hostname"],
        ["exec", "--unit", "u/0", "--machine", "0", "hostname"],
    ],
)
def test_exec_multi_target_shapes_fall_through_to_cli(argv: list[str]) -> None:
    """`Juju.exec()` targets exactly one machine or unit."""
    assert _c(*argv)[0] == "cli_passthrough"


def test_scp() -> None:
    assert "juju.scp('ubuntu/0:/tmp/a', './a')" in _src("scp", "ubuntu/0:/tmp/a", "./a")


def test_scp_with_forwarded_options_falls_through_to_cli() -> None:
    assert _c("scp", "-r", "ubuntu/0:/tmp/a", "./a")[0] == "cli_passthrough"


# --- read-only model queries ---


def test_debug_log_needs_no_tail() -> None:
    assert _c("debug-log", "--no-tail") == ("debug_log", {})
    assert _c("debug-log")[0] == "cli_passthrough"


def test_show_model() -> None:
    assert "juju.show_model()" in _src("show-model")
    assert "juju.show_model('other')" in _src("show-model", "other")


def test_model_config_read_set_and_reset() -> None:
    assert _c("model-config") == ("model_config", {})
    assert _c("model-config", "a=b") == ("model_config", {"values": {"a": "b"}})
    assert _c("model-config", "--reset", "a,b") == ("model_config", {"reset": ["a", "b"]})


def test_model_config_single_key_read_falls_through_to_cli() -> None:
    """`model_config()` returns the whole mapping; it cannot read one key."""
    assert _c("model-config", "logging-config")[0] == "cli_passthrough"


def test_model_constraints_read_and_set() -> None:
    assert "juju.model_constraints()" in _src("model-constraints")
    assert "juju.model_constraints({'mem': '2G'})" in _src("set-model-constraints", "mem=2G")


def test_version() -> None:
    assert "juju.version()" in _src("version")
    assert "juju.version()" in _src("--version")


# --- trust, refresh, ssh keys ---


def test_trust() -> None:
    assert "juju.trust('ubuntu')" in _src("trust", "ubuntu")
    assert "juju.trust('ubuntu', remove=True)" in _src("trust", "ubuntu", "--remove")
    assert "juju.trust('ubuntu', scope='cluster')" in _src("trust", "ubuntu", "--scope", "cluster")


def test_trust_unknown_scope_falls_through_to_cli() -> None:
    assert _c("trust", "ubuntu", "--scope", "namespace")[0] == "cli_passthrough"


def test_refresh_emits_typed_call() -> None:
    assert "juju.refresh('ubuntu', channel='edge')" in _src(
        "refresh", "ubuntu", "--channel", "edge"
    )


def test_ssh_keys() -> None:
    assert "juju.add_ssh_key('ssh-rsa AAA me@host')" in _src("add-ssh-key", "ssh-rsa AAA me@host")
    assert "juju.remove_ssh_key('me@host')" in _src("remove-ssh-key", "me@host")


# --- secrets ---


def test_show_secret() -> None:
    assert "juju.show_secret('mine', reveal=True)" in _src("show-secret", "mine", "--reveal")


def test_secret_add_and_update() -> None:
    assert "juju.add_secret('mine', {'k': 'v'})" in _src("add-secret", "mine", "k=v")
    assert "juju.update_secret('mine', {'k': 'v'})" in _src("update-secret", "mine", "k=v")


# --- wait-for ---


def test_wait_for_application() -> None:
    src = _src("wait-for", "application", "ubuntu")
    assert "juju.wait(lambda status: jubilant.all_active(status, 'ubuntu'))" in src


def test_wait_for_unit_waits_on_its_application() -> None:
    """A recorded unit name does not survive into a fresh model."""
    src = _src("wait-for", "unit", "ubuntu/0")
    assert "jubilant.all_active(status, 'ubuntu')" in src


def test_wait_for_model_waits_on_everything() -> None:
    assert "juju.wait(jubilant.all_active)" in _src("wait-for", "model", "demo")


def test_wait_for_timeout_is_carried() -> None:
    assert _c("wait-for", "application", "u", "--timeout", "10m") == (
        "wait_for",
        {"scope": "application", "targets": ["u"], "timeout": 600.0},
    )


def test_wait_for_query_falls_through_to_cli() -> None:
    """The query language has no jubilant equivalent, so it must survive verbatim."""
    args = _c("wait-for", "application", "u", "--query", 'status=="active"')[1]
    assert args["argv"][-1] == 'status=="active"'
    assert args["include_model"] is False


# --- failed commands ---


def test_failed_command_is_commented_out() -> None:
    src = _src("deploy", "nosuchcharm", exit_code=1)
    assert "# juju.deploy('nosuchcharm')" in src
    assert "\n        juju.deploy(" not in src
    assert "exited 1 when recorded" in src


def _shim(seq: int, argv: list[str], exit_code: int = 0) -> dict:
    return {
        "seq": seq,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": argv, "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": exit_code},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def test_wait_for_query_carries_the_model_explicitly() -> None:
    """`juju wait-for` rejects `--model`; `juju wait-for application` needs it.

    `juju.cli()` inserts the flag after the first argument, which lands on
    the group and fails to parse — and leaving it off waits on whatever
    model the CLI happens to point at, which is worse than failing.
    """
    src = _src("wait-for", "application", "ubuntu", "--query", 'status=="active"')
    assert "'--model', juju.model" in src
    assert "include_model=False" in src


def test_wait_for_drops_a_recorded_model_before_adding_its_own() -> None:
    src = _src("wait-for", "unit", "ubuntu/0", "-m", "prod-cluster", "--query", "x")
    assert "prod-cluster" not in src
    assert "'--model', juju.model" in src


def test_grant_secret_to_several_applications() -> None:
    """The CLI joins them with commas; `Juju.grant_secret()` takes an iterable."""
    assert _c("grant-secret", "mine", "a,b") == (
        "secret_grant",
        {"identifier": "mine", "app": ["a", "b"]},
    )
    assert "juju.grant_secret('mine', ['a', 'b'])" in _src("grant-secret", "mine", "a,b")


def test_grant_secret_to_one_application_stays_a_string() -> None:
    assert "juju.grant_secret('mine', 'a')" in _src("grant-secret", "mine", "a")


def test_show_model_naming_the_session_model_drops_the_argument() -> None:
    """That model does not exist in the generated test; the current one does."""
    src = generate(_wrap([_shim(1, ["add-model", "demo"]), _shim(2, ["show-model", "demo"])]))
    assert "juju.show_model()" in src
    assert "juju.show_model('demo')" not in src


def test_show_model_naming_another_model_keeps_it() -> None:
    src = generate(_wrap([_shim(1, ["add-model", "demo"]), _shim(2, ["show-model", "other"])]))
    assert "juju.show_model('other')" in src
