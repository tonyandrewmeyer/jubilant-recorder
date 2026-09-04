"""Bucket-1 argv translation.

Every mapping here is a pure function of (subcommand, argv) -> args dict, so
these are fixture tests with no live juju needed.
"""

from __future__ import annotations

from jubilant_recorder.codegen import cli_translate


def _c(*argv: str) -> tuple[str, dict] | None:
    return cli_translate.classify_argv(list(argv))


# --- deploy ---


def test_deploy_minimal() -> None:
    assert _c("deploy", "my-charm") == ("deploy", {"charm": "my-charm"})


def test_deploy_full() -> None:
    op, args = _c(
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
    _, args = _c("deploy", "c", "--config", "a=1", "--config", "a=2")
    assert args["config"] == {"a": "2"}


def test_deploy_config_bare_path_is_bucket2() -> None:
    assert _c("deploy", "c", "--config", "bundle.yaml") is None


def test_deploy_config_at_directive_is_bucket2() -> None:
    assert _c("deploy", "c", "--config", "key=@path") is None


def test_deploy_attach_storage_is_bucket2() -> None:
    assert _c("deploy", "c", "--attach-storage", "foo/0") is None


def test_deploy_dry_run_is_bucket2() -> None:
    assert _c("deploy", "c", "--dry-run") is None


def test_deploy_no_charm_is_bucket2() -> None:
    assert _c("deploy") is None


# --- config / config_get / config_unset ---


def test_config_set() -> None:
    op, args = _c("config", "my-charm", "log-level=debug", "debug=true")
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
    op, args = _c("config", "my-charm", "--reset", "log-level,debug")
    assert op == "config_unset"
    assert args == {"app": "my-charm", "options": ["log-level", "debug"]}


def test_config_file_flag_is_bucket2() -> None:
    assert _c("config", "my-charm", "--file", "cfg.yaml") is None


def test_config_at_directive_is_bucket2() -> None:
    assert _c("config", "my-charm", "log-level=@path") is None


def test_config_model_flag_is_bucket2() -> None:
    assert _c("config", "-m", "othermodel", "my-charm", "log-level=debug") is None


# --- refresh -> set_charm ---


def test_refresh_switch_channel_force() -> None:
    op, args = _c("refresh", "my-charm", "--switch", "ch:my-charm", "--channel", "edge", "--force")
    assert op == "set_charm"
    assert args == {
        "app": "my-charm",
        "charm_url": "ch:my-charm",
        "channel": "edge",
        "force": True,
    }


def test_refresh_bare() -> None:
    assert _c("refresh", "my-charm") == ("set_charm", {"app": "my-charm"})


def test_refresh_config_is_bucket2() -> None:
    assert _c("refresh", "my-charm", "--config", "k=v") is None


def test_refresh_revision_is_bucket2() -> None:
    assert _c("refresh", "my-charm", "--revision", "3") is None


def test_refresh_storage_todo_still_bucket1() -> None:
    op, args = _c("refresh", "my-charm", "--storage", "pgdata=1GB")
    assert op == "set_charm"
    assert args["storage_constraints"] == ["pgdata=1GB"]


# --- remove-application ---


def test_remove_application_single() -> None:
    assert _c("remove-application", "my-charm") == ("remove_application", {"app": "my-charm"})


def test_remove_application_multi() -> None:
    assert _c("remove-application", "a", "b") == ("remove_application", {"app": ["a", "b"]})


def test_remove_application_force_is_bucket2() -> None:
    assert _c("remove-application", "my-charm", "--force") is None


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


def test_integrate_cross_model_dotted_is_bucket2() -> None:
    assert _c("integrate", "my-charm:db", "othermodel.postgresql:database") is None


def test_integrate_via_is_bucket2() -> None:
    assert _c("integrate", "a:db", "b:database", "--via", "10.0.0.0/8") is None


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
    op, args = _c("run", "my-charm/0", "backup", "time=1000", "verbose=true", "label=foo")
    assert op == "run"
    assert args["params"] == {"time": 1000, "verbose": True, "label": "foo"}


def test_run_string_args_keeps_raw_strings() -> None:
    _op, args = _c("run", "my-charm/0", "backup", "--string-args", "time=1000")
    assert args["params"] == {"time": "1000"}


def test_run_dotted_params() -> None:
    _op, args = _c("run", "my-charm/0", "backup", "opts.retries=3")
    assert args["params"] == {"opts": {"retries": 3}}


def test_run_multi_unit_is_bucket2() -> None:
    assert _c("run", "my-charm/0", "my-charm/1", "backup") is None


def test_run_zero_units_is_bucket2() -> None:
    assert _c("run", "backup") is None


def test_run_params_file_is_bucket2() -> None:
    assert _c("run", "my-charm/0", "backup", "--params", "p.yaml") is None


def test_run_params_file_mixed_with_inline_override_is_bucket2() -> None:
    """File + inline-override mix can't resolve without file content.

    ``--params`` is simply absent from ``_classify_run``'s recognized flag set, so any
    invocation carrying it — whether the file is the only params source or inline
    ``key=value`` args are meant to override it — aborts classification and falls to
    bucket 2, regardless of where the flag sits relative to the inline args.
    """
    assert _c("run", "my-charm/0", "backup", "--params", "p.yaml", "time=1000") is None
    assert _c("run", "my-charm/0", "backup", "time=1000", "--params", "p.yaml") is None


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


def test_scale_application_force_is_bucket2() -> None:
    assert _c("scale-application", "my-charm", "5", "--force") is None


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


def test_add_secret_not_translated() -> None:
    """F5: no shim redaction yet — add-secret/update-secret stay bucket 2 always."""
    assert _c("add-secret", "my-secret", "token=hunter2") is None


def test_update_secret_not_translated() -> None:
    assert _c("update-secret", "my-secret", "token=hunter2") is None


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


def test_offer_dotted_model_is_bucket2() -> None:
    assert _c("offer", "othermodel.my-charm:db") is None


def test_offer_controller_flag_is_bucket2() -> None:
    assert _c("offer", "my-charm:db", "-c", "mycontroller") is None


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
    op, args = _c("remove-offer", "--force", "offer1", "offer2")
    assert op == "remove_offer"
    assert args == {"offer_urls": ["offer1", "offer2"], "force": True}


def test_show_offer() -> None:
    assert _c("show-offer", "admin/default.my-offer") == (
        "get_consume_details",
        {"offer_urls": ["admin/default.my-offer"]},
    )


def test_remove_saas_single() -> None:
    assert _c("remove-saas", "my-saas") == ("remove_saas", {"app": "my-saas"})


def test_remove_saas_multi_is_bucket2() -> None:
    assert _c("remove-saas", "a", "b") is None


# --- expose / unexpose ---


def test_expose_bare() -> None:
    assert _c("expose", "my-charm") == ("expose", {"app": "my-charm"})


def test_expose_to_cidrs_is_bucket2() -> None:
    assert _c("expose", "my-charm", "--to-cidrs", "10.0.0.0/8") is None


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
    op, args = _c("bind", "my-charm", "default-space", "db=space1")
    assert op == "merge_bindings"
    assert args == {"app": "my-charm", "bindings": {"": "default-space", "db": "space1"}}


def test_bind_force_todo_still_bucket1() -> None:
    op, args = _c("bind", "my-charm", "db=space1", "--force")
    assert op == "merge_bindings"
    assert args["force"] is True


# --- suspend-relation / resume-relation ---


def test_suspend_relation() -> None:
    assert _c("suspend-relation", "123", "456") == (
        "set_relations_suspended",
        {"relation_ids": ["123", "456"], "suspended": True},
    )


def test_suspend_relation_message() -> None:
    _op, args = _c("suspend-relation", "123", "--message", "maintenance")
    assert args == {"relation_ids": ["123"], "suspended": True, "message": "maintenance"}


def test_resume_relation() -> None:
    assert _c("resume-relation", "123") == (
        "set_relations_suspended",
        {"relation_ids": ["123"], "suspended": False},
    )


def test_resume_relation_message_is_bucket2() -> None:
    """`--message` isn't a real `resume-relation` flag — unrecognized, so bucket 2."""
    assert _c("resume-relation", "123", "--message", "x") is None


# --- dispatch edge cases ---


def test_empty_argv() -> None:
    assert _c() is None


def test_unknown_subcommand() -> None:
    assert _c("status") is None
    assert _c("ssh", "my-charm/0", "ls") is None


def test_classify_never_raises_on_malformed_event() -> None:
    assert cli_translate.classify({"args": {"argv": ["deploy"], "source": "shim"}}) is None
    assert cli_translate.classify({"args": {}}) is None
    assert cli_translate.classify({}) is None
