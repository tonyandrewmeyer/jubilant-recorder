"""Translations only a Kubernetes model can produce.

Juju's CLI forks on the cloud type in ways the recorder has to follow, and a
machine-cloud run exercises none of them: `scale-application` does not exist
on a machine model, `remove-unit --num-units` is the Kubernetes spelling,
`--container` selects a workload container, and `trust --scope cluster` is
required on Kubernetes and rejected elsewhere.

Every argv here was typed against a real microk8s model on juju 3.6.28 and
recorded by the shim, so these are the shapes that actually reach codegen —
not shapes invented from the help text.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import cli_translate
from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap

CHARM = "snappass-test"
CONTAINER = "snappass"


def _c(*argv: str) -> tuple[str, dict[str, Any]]:
    result = cli_translate.classify_argv(list(argv))
    assert result is not None, f"argv did not classify: {argv}"
    return result


def _src(*argv: str) -> str:
    event = {
        "seq": 1,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": list(argv), "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }
    return generate(_wrap([event]))


def test_scale_application_is_the_k8s_scale() -> None:
    """`juju add-unit` also works on k8s, but `scale-application` is the k8s one.

    jubilant has no absolute-scale method, so this is `juju.cli()` — the
    documented escape hatch, not a gap.
    """
    assert _c("scale-application", CHARM, "3") == (
        "scale",
        {"app": CHARM, "units": 3, "mode": "absolute"},
    )
    assert f"juju.cli(\"scale-application\", '{CHARM}', '3')" in _src(
        "scale-application", CHARM, "3"
    )


def test_remove_unit_by_count_is_the_k8s_spelling() -> None:
    """Kubernetes units are not individually named, so removal is by count."""
    assert f"juju.remove_unit('{CHARM}', num_units=1)" in _src(
        "remove-unit", CHARM, "--num-units", "1"
    )


def test_trust_scope_cluster() -> None:
    """Required on Kubernetes; `Juju.trust()` accepts no other scope."""
    assert f"juju.trust('{CHARM}', scope='cluster')" in _src("trust", CHARM, "--scope", "cluster")


def test_ssh_into_a_workload_container() -> None:
    assert f"juju.ssh('{CHARM}/0', 'hostname', container='{CONTAINER}')" in _src(
        "ssh", "--container", CONTAINER, f"{CHARM}/0", "hostname"
    )


def test_scp_into_a_workload_container() -> None:
    assert f"juju.scp('./f', '{CHARM}/0:/f', container='{CONTAINER}')" in _src(
        "scp", "--container", CONTAINER, "./f", f"{CHARM}/0:/f"
    )


def test_exec_on_a_k8s_unit() -> None:
    assert f"juju.exec('hostname', unit='{CHARM}/0')" in _src(
        "exec", "--unit", f"{CHARM}/0", "hostname"
    )


def test_add_machine_is_still_translated_on_a_k8s_argv() -> None:
    """It is meaningless on Kubernetes, and juju rejects it there.

    The classifier does not need to know that: a rejected command exits
    non-zero, and codegen comments it out. Translating it unconditionally
    keeps the argv surface one table rather than two.
    """
    assert _c("add-machine")[0] == "add_machine"
