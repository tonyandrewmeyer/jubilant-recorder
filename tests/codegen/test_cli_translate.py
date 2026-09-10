"""``juju`` argv -> jubilant translation.

Every mapping here is a pure function of (subcommand, argv) -> args dict, so
these are fixture tests with no live juju needed.

Two outcomes are possible for a non-empty argv, and both are asserted:
a *typed* op, when the shape maps onto a `jubilant.Juju` method, and
``cli_passthrough`` — rendered as ``juju.cli(...)`` — for everything else.
There is no third "unrepresentable" outcome: `classify_argv` returns None
only for an empty argv.
"""

from __future__ import annotations

from jubilant_recorder.codegen import cli_translate


def _c(*argv: str) -> tuple[str, dict] | None:
    return cli_translate.classify_argv(list(argv))


def _ok(*argv: str) -> tuple[str, dict]:
    """``_c``, for argv that must classify.

    Unpacking ``_c(...)`` directly hides the failure: an unrecognised argv
    returns None and surfaces as a TypeError about iteration rather than
    naming the argv that was not understood.
    """
    result = _c(*argv)
    assert result is not None, f"argv did not classify: {argv}"
    return result


def _cli(*argv: str) -> dict:
    """``_c``, for argv that no typed classifier claims.

    Asserts the argv reaches the ``juju.cli(...)`` passthrough with its
    tokens intact, and returns the args dict so a caller can go on to check
    ``include_model``/``add_no_prompt``.
    """
    op, args = _ok(*argv)
    assert op == "cli_passthrough", f"expected passthrough, got {op}: {argv}"
    assert args["argv"] == list(argv)
    return args


# --- deploy ---


def test_deploy_minimal() -> None:
    assert _c("deploy", "my-charm") == ("deploy", {"charm": "my-charm"})


def test_deploy_full() -> None:
    op, args = _ok(
        "deploy",
        "my-charm",
        "myapp",
        "--base",
        "ubuntu@24.04",
        "--channel",
        "edge",
        "--revision",
        "12",
        "-n",
        "3",
        "--to",
        "0,1",
        "--force",
        "--trust",
        "--constraints",
        "cores=2",
        "--constraints",
        "mem=4G",
        "--resource",
        "img=my-image",
        "--config",
        "log-level=debug",
    )
    assert op == "deploy"
    assert args == {
        "charm": "my-charm",
        "app": "myapp",
        "base": "ubuntu@24.04",
        "channel": "edge",
        "revision": 12,
        "num_units": 3,
        "to": "0,1",
        "force": True,
        "trust": True,
        "constraints": {"cores": "2", "mem": "4G"},
        "resources": {"img": "my-image"},
        "config": {"log-level": "debug"},
    }


def test_deploy_config_last_wins() -> None:
    _, args = _ok("deploy", "c", "--config", "a=1", "--config", "a=2")
    assert args["config"] == {"a": "2"}


def test_deploy_config_bare_path_falls_through_to_cli() -> None:
    _cli("deploy", "c", "--config", "bundle.yaml")


def test_deploy_config_at_directive_falls_through_to_cli() -> None:
    _cli("deploy", "c", "--config", "key=@path")


def test_deploy_attach_storage_falls_through_to_cli() -> None:
    _cli("deploy", "c", "--attach-storage", "foo/0")


def test_deploy_dry_run_falls_through_to_cli() -> None:
    _cli("deploy", "c", "--dry-run")


def test_deploy_no_charm_falls_through_to_cli() -> None:
    _cli("deploy")


# --- config / config_get / config_unset ---


def test_config_set() -> None:
    op, args = _ok("config", "my-charm", "log-level=debug", "debug=true")
    assert op == "config"
    assert args == {"app": "my-charm", "values": {"log-level": "debug", "debug": "true"}}


def test_config_get_no_keys() -> None:
    assert _c("config", "my-charm") == ("config_get", {"app": "my-charm", "keys": None})


def test_config_get_one_key() -> None:
    assert _c("config", "my-charm", "log-level") == (
        "config_get",
        {"app": "my-charm", "keys": ["log-level"]},
    )


def test_config_unset() -> None:
    op, args = _ok("config", "my-charm", "--reset", "log-level,debug")
    assert op == "config_unset"
    assert args == {"app": "my-charm", "options": ["log-level", "debug"]}


def test_config_file_flag_falls_through_to_cli() -> None:
    _cli("config", "my-charm", "--file", "cfg.yaml")


def test_config_at_directive_falls_through_to_cli() -> None:
    _cli("config", "my-charm", "log-level=@path")


def test_config_model_flag_with_an_equals_is_also_stripped() -> None:
    """juju's flag parser takes `-m=x` and `--model=x` as well as `-m x`."""
    for flag in ("-m=othermodel", "--model=othermodel"):
        assert _c("config", flag, "my-charm", "log-level=debug") == (
            "config",
            {
                "app": "my-charm",
                "values": {"log-level": "debug"},
                "recorded_model": "othermodel",
            },
        )


def test_config_model_flag_is_stripped_and_recorded() -> None:
    """A `-m` scope is dropped, not passed through.

    The generated test runs in the model `jubilant.temp_model()` made for
    it, so the recording's model name would name a model that does not
    exist at test time. `recorded_model` keeps what was dropped.
    """
    assert _c("config", "-m", "othermodel", "my-charm", "log-level=debug") == (
        "config",
        {
            "app": "my-charm",
            "values": {"log-level": "debug"},
            "recorded_model": "othermodel",
        },
    )


# --- refresh ---


def test_refresh_switch_falls_through_to_cli() -> None:
    """`--switch` has no `Juju.refresh()` keyword, so it keeps the raw call."""
    _cli("refresh", "my-charm", "--switch", "ch:my-charm", "--channel", "edge")


def test_refresh_bare() -> None:
    assert _c("refresh", "my-charm") == ("refresh", {"app": "my-charm"})


def test_refresh_channel_force() -> None:
    assert _c("refresh", "my-charm", "--channel", "edge", "--force") == (
        "refresh",
        {"app": "my-charm", "channel": "edge", "force": True},
    )


def test_refresh_config() -> None:
    assert _c("refresh", "my-charm", "--config", "k=v") == (
        "refresh",
        {"app": "my-charm", "config": {"k": "v"}},
    )


def test_refresh_revision() -> None:
    assert _c("refresh", "my-charm", "--revision", "3") == (
        "refresh",
        {"app": "my-charm", "revision": 3},
    )


def test_refresh_storage() -> None:
    assert _c("refresh", "my-charm", "--storage", "pgdata=1GB") == (
        "refresh",
        {"app": "my-charm", "storage": {"pgdata": "1GB"}},
    )


# --- remove-application ---


def test_remove_application_single() -> None:
    assert _c("remove-application", "my-charm") == ("remove_application", {"app": "my-charm"})


def test_remove_application_multi() -> None:
    assert _c("remove-application", "a", "b") == ("remove_application", {"app": ["a", "b"]})


def test_remove_application_force_and_storage() -> None:
    assert _c("remove-application", "my-charm", "--force", "--destroy-storage") == (
        "remove_application",
        {"app": "my-charm", "destroy_storage": True, "force": True},
    )


def test_remove_application_no_prompt_is_not_carried() -> None:
    """`remove_application()` always passes `--no-prompt` itself."""
    assert _c("remove-application", "my-charm", "--no-prompt") == (
        "remove_application",
        {"app": "my-charm"},
    )


def test_remove_application_dry_run_falls_through_to_cli() -> None:
    """A dry run changed nothing, so replaying it as a real removal is wrong."""
    args = _cli("remove-application", "my-charm", "--dry-run")
    # It still needs `--no-prompt`: an unattended test cannot answer a prompt.
    assert args["add_no_prompt"] is True


# --- integrate/relate, remove-relation ---


def test_integrate() -> None:
    assert _c("integrate", "my-charm:db", "postgresql:database") == (
        "integrate",
        {"app1_endpoint": "my-charm:db", "app2_endpoint": "postgresql:database"},
    )


def test_relate_alias() -> None:
    assert _c("relate", "a:db", "b:database") == (
        "integrate",
        {"app1_endpoint": "a:db", "app2_endpoint": "b:database"},
    )


def test_integrate_cross_model_dotted_falls_through_to_cli() -> None:
    _cli("integrate", "my-charm:db", "othermodel.postgresql:database")


def test_integrate_via_falls_through_to_cli() -> None:
    _cli("integrate", "a:db", "b:database", "--via", "10.0.0.0/8")


def test_remove_relation() -> None:
    assert _c("remove-relation", "a:db", "b:database") == (
        "remove_integration",
        {"app1_endpoint": "a:db", "app2_endpoint": "b:database"},
    )


# --- run ---


def test_run_single_unit_no_params() -> None:
    assert _c("run", "my-charm/0", "do-thing") == (
        "run",
        {"unit": "my-charm/0", "action": "do-thing"},
    )


def test_run_leader() -> None:
    assert _c("run", "my-charm/leader", "backup") == (
        "run",
        {"unit": "my-charm/leader", "action": "backup"},
    )


def test_run_typed_params() -> None:
    op, args = _ok("run", "my-charm/0", "backup", "time=1000", "verbose=true", "label=foo")
    assert op == "run"
    assert args["params"] == {"time": 1000, "verbose": True, "label": "foo"}


def test_run_string_args_keeps_raw_strings() -> None:
    _op, args = _ok("run", "my-charm/0", "backup", "--string-args", "time=1000")
    assert args["params"] == {"time": "1000"}


def test_run_dotted_params() -> None:
    _op, args = _ok("run", "my-charm/0", "backup", "opts.retries=3")
    assert args["params"] == {"opts": {"retries": 3}}


def test_run_multi_unit_falls_through_to_cli() -> None:
    _cli("run", "my-charm/0", "my-charm/1", "backup")


def test_run_zero_units_falls_through_to_cli() -> None:
    _cli("run", "backup")


def test_run_params_file_falls_through_to_cli() -> None:
    _cli("run", "my-charm/0", "backup", "--params", "p.yaml")


def test_run_params_file_mixed_with_inline_override_is_bucket2() -> None:
    """File + inline-override mix can't resolve without file content.

    ``--params`` is simply absent from ``_classify_run``'s recognized flag set, so any
    invocation carrying it — whether the file is the only params source or inline
    ``key=value`` args are meant to override it — aborts classification and falls to
    bucket 2, regardless of where the flag sits relative to the inline args.
    """
    _cli("run", "my-charm/0", "backup", "--params", "p.yaml", "time=1000")
    _cli("run", "my-charm/0", "backup", "time=1000", "--params", "p.yaml")


# --- add-unit / scale-application -> scale (F1/F2 promotion) ---


def test_add_unit_default() -> None:
    assert _c("add-unit", "my-charm") == (
        "scale",
        {"app": "my-charm", "units": 1, "mode": "relative"},
    )


def test_add_unit_num_units() -> None:
    assert _c("add-unit", "my-charm", "-n", "3") == (
        "scale",
        {"app": "my-charm", "units": 3, "mode": "relative"},
    )


def test_add_unit_to() -> None:
    """Follow-on to F1/F2: scale.py's emitter now forwards `to=` — see its docstring."""
    assert _c("add-unit", "my-charm", "--to", "0,1") == (
        "scale",
        {"app": "my-charm", "units": 1, "mode": "relative", "to": "0,1"},
    )


def test_add_unit_attach_storage() -> None:
    assert _c("add-unit", "my-charm", "--attach-storage", "foo/0") == (
        "scale",
        {"app": "my-charm", "units": 1, "mode": "relative", "attach_storage": "foo/0"},
    )


def test_add_unit_attach_storage_repeated_flag_accumulates() -> None:
    """`--attach-storage` is a `flag.Var`-backed accumulator upstream (unlike `--to`'s
    plain `StringVar`), so repeated occurrences must all be kept, not last-wins —
    see `cmd/juju/application/flags.go`'s `attachStorageFlag.Set()`."""
    assert _c(
        "add-unit", "my-charm", "--attach-storage", "foo/0", "--attach-storage", "bar/1"
    ) == (
        "scale",
        {
            "app": "my-charm",
            "units": 1,
            "mode": "relative",
            "attach_storage": "foo/0,bar/1",
        },
    )


def test_add_unit_to_and_attach_storage_and_num_units() -> None:
    assert _c(
        "add-unit",
        "my-charm",
        "-n",
        "3",
        "--to",
        "lxd:7,lxd:7",
        "--attach-storage",
        "foo/0",
    ) == (
        "scale",
        {
            "app": "my-charm",
            "units": 3,
            "mode": "relative",
            "to": "lxd:7,lxd:7",
            "attach_storage": "foo/0",
        },
    )


def test_scale_application() -> None:
    assert _c("scale-application", "my-charm", "5") == (
        "scale",
        {"app": "my-charm", "units": 5, "mode": "absolute"},
    )


def test_scale_application_force_falls_through_to_cli() -> None:
    _cli("scale-application", "my-charm", "5", "--force")


# --- secrets ---


def test_remove_secret() -> None:
    assert _c("remove-secret", "my-secret") == ("secret_remove", {"identifier": "my-secret"})


def test_remove_secret_with_revision() -> None:
    assert _c("remove-secret", "my-secret", "--revision", "2") == (
        "secret_remove",
        {"identifier": "my-secret", "revision": 2},
    )


def test_grant_secret() -> None:
    assert _c("grant-secret", "my-secret", "my-app") == (
        "secret_grant",
        {"identifier": "my-secret", "app": "my-app"},
    )


def test_secrets_bare() -> None:
    assert _c("secrets") == ("secret_list", {})


def test_secrets_list_alias() -> None:
    assert _c("list-secrets") == ("secret_list", {})


def test_secrets_owner() -> None:
    assert _c("secrets", "--owner", "my-app") == ("secret_list", {"owner": "my-app"})


def test_secrets_format_harmless_drop() -> None:
    assert _c("secrets", "--format", "json") == ("secret_list", {})


def test_add_secret() -> None:
    """Inline `key=value` content translates; the shim redacts it on the way in.

    `jubilant_recorder.redaction` runs over the shim's argv before it
    reaches the log, so a real secret arrives here already replaced by its
    `<redacted:…>` marker and renders as a visible placeholder rather than
    a working credential. See `tests/test_shim.py`.
    """
    assert _c("add-secret", "my-secret", "token=hunter2") == (
        "secret_add_cli",
        {"name": "my-secret", "content": {"token": "hunter2"}},
    )


def test_add_secret_file_falls_through_to_cli() -> None:
    """`--file` content never reaches argv, so there is nothing to translate."""
    _cli("add-secret", "my-secret", "--file", "content.yaml")


def test_update_secret() -> None:
    assert _c("update-secret", "my-secret", "token=hunter2") == (
        "secret_update_cli",
        {"identifier": "my-secret", "content": {"token": "hunter2"}},
    )


# --- CMR ---


def test_offer() -> None:
    assert _c("offer", "my-charm:db") == (
        "create_offer",
        {"app": "my-charm", "endpoints": ["db"]},
    )


def test_offer_multi_endpoint_and_name() -> None:
    assert _c("offer", "my-charm:db,admin", "my-offer") == (
        "create_offer",
        {"app": "my-charm", "endpoints": ["db", "admin"], "offer_name": "my-offer"},
    )


def test_offer_dotted_model_falls_through_to_cli() -> None:
    args = _cli("offer", "othermodel.my-charm:db")
    assert args["include_model"] is False  # `juju offer` rejects --model


def test_offer_controller_flag_falls_through_to_cli() -> None:
    _cli("offer", "my-charm:db", "-c", "mycontroller")


def test_consume() -> None:
    assert _c("consume", "admin/default.my-offer") == (
        "consume",
        {"offer_url": "admin/default.my-offer"},
    )


def test_consume_with_alias() -> None:
    assert _c("consume", "admin/default.my-offer", "local-name") == (
        "consume",
        {"offer_url": "admin/default.my-offer", "application_alias": "local-name"},
    )


def test_offers_bare() -> None:
    assert _c("offers") == ("list_offers", {})


def test_offers_list_alias_with_dropped_filters() -> None:
    assert _c("list-offers", "--interface", "db", "--active-only") == ("list_offers", {})


def test_remove_offer_single() -> None:
    assert _c("remove-offer", "admin/default.my-offer") == (
        "remove_offer",
        {"offer_urls": ["admin/default.my-offer"]},
    )


def test_remove_offer_multi_and_force() -> None:
    op, args = _ok("remove-offer", "--force", "offer1", "offer2")
    assert op == "remove_offer"
    assert args == {"offer_urls": ["offer1", "offer2"], "force": True}


def test_show_offer() -> None:
    assert _c("show-offer", "admin/default.my-offer") == (
        "get_consume_details",
        {"offer_urls": ["admin/default.my-offer"]},
    )


def test_remove_saas_single() -> None:
    assert _c("remove-saas", "my-saas") == ("remove_saas", {"app": "my-saas"})


def test_remove_saas_multi_falls_through_to_cli() -> None:
    _cli("remove-saas", "a", "b")


# --- expose / unexpose ---


def test_expose_bare() -> None:
    assert _c("expose", "my-charm") == ("expose", {"app": "my-charm"})


def test_expose_to_cidrs_falls_through_to_cli() -> None:
    _cli("expose", "my-charm", "--to-cidrs", "10.0.0.0/8")


def test_unexpose_bare() -> None:
    assert _c("unexpose", "my-charm") == ("unexpose", {"app": "my-charm"})


def test_unexpose_endpoints() -> None:
    assert _c("unexpose", "my-charm", "--endpoints", "db,admin") == (
        "unexpose",
        {"app": "my-charm", "exposed_endpoints": ["db", "admin"]},
    )


# --- set-constraints ---


def test_set_constraints() -> None:
    assert _c("set-constraints", "my-charm", "cores=2", "mem=4G") == (
        "set_constraints",
        {"app": "my-charm", "constraints": {"cores": "2", "mem": "4G"}},
    )


# --- bind -> merge_bindings ---


def test_bind_endpoints_only() -> None:
    assert _c("bind", "my-charm", "db=space1") == (
        "merge_bindings",
        {"app": "my-charm", "bindings": {"db": "space1"}},
    )


def test_bind_default_space_and_endpoint() -> None:
    op, args = _ok("bind", "my-charm", "default-space", "db=space1")
    assert op == "merge_bindings"
    assert args == {"app": "my-charm", "bindings": {"": "default-space", "db": "space1"}}


def test_bind_force_todo_still_bucket1() -> None:
    op, args = _ok("bind", "my-charm", "db=space1", "--force")
    assert op == "merge_bindings"
    assert args["force"] is True


# --- suspend-relation / resume-relation ---


def test_suspend_relation() -> None:
    assert _c("suspend-relation", "123", "456") == (
        "set_relations_suspended",
        {"relation_ids": ["123", "456"], "suspended": True},
    )


def test_suspend_relation_message() -> None:
    _op, args = _ok("suspend-relation", "123", "--message", "maintenance")
    assert args == {"relation_ids": ["123"], "suspended": True, "message": "maintenance"}


def test_resume_relation() -> None:
    assert _c("resume-relation", "123") == (
        "set_relations_suspended",
        {"relation_ids": ["123"], "suspended": False},
    )


def test_resume_relation_message_falls_through_to_cli() -> None:
    """`--message` isn't a real `resume-relation` flag — unrecognized, so bucket 2."""
    _cli("resume-relation", "123", "--message", "x")


# --- dispatch edge cases ---


def test_empty_argv() -> None:
    assert _c() is None


def test_unknown_subcommand_falls_through_to_cli() -> None:
    _cli("no-such-subcommand", "arg")
    args = _cli("list-machines")
    assert "include_model" not in args  # `juju list-machines` takes --model


def test_classify_never_raises_on_malformed_event() -> None:
    assert cli_translate.classify({"args": {"argv": ["deploy"], "source": "shim"}}) == (
        "cli_passthrough",
        {"argv": ["deploy"]},
    )
    assert cli_translate.classify({"args": {}}) is None
    assert cli_translate.classify({}) is None
