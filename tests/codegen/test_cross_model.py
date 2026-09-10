"""Cross-model relations: what translates, and what the reader is warned about.

A CMR session touches two models. A generated test opens one, so the offer
URLs it emits name a model the test does not create — the calls are right,
the environment is not, and saying nothing produced a test that read fine
and could not pass.

Every argv here was typed against two live LXD models on juju 3.6.28 and
recorded by the shim.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import cli_translate
from jubilant_recorder.codegen.emit import generate

from .conftest import _wrap

OFFER_URL = "admin/cmr-offer.pgoffer2"


def _shim(seq: int, argv: list[str]) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": "shell",
        "ts": "2026-09-10T10:00:00.000Z",
        "args": {"argv": argv, "basename": "juju", "source": "shim", "session_id": "s"},
        "result": {"captured": False, "exit_code": 0},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def _src(*argvs: list[str]) -> str:
    return generate(_wrap([_shim(i + 1, a) for i, a in enumerate(argvs)]))


# --- the offer itself ---


def test_a_dotted_offer_is_the_normal_cmr_shape() -> None:
    """`juju offer` has no `--model`, so the model goes in the app name."""
    src = _src(["offer", "cmr-offer.postgresql:database", "pgoffer2"])
    assert "juju.offer('cmr-offer.postgresql', endpoint='database', name='pgoffer2')" in src


def test_an_undotted_offer_still_works() -> None:
    """Offering from the model you are switched to needs no model name."""
    assert "juju.offer('postgresql', endpoint='database')" in _src(
        ["offer", "postgresql:database"]
    )


def test_several_endpoints_in_one_offer() -> None:
    assert "juju.offer('pg', endpoint=['db', 'log'])" in _src(["offer", "pg:db,log"])


def test_a_controller_needs_a_dotted_model() -> None:
    """`Juju.offer()` raises ValueError otherwise, so it is not translated."""
    classified = cli_translate.classify_argv(["offer", "pg:db", "-c", "ctl"])
    assert classified is not None
    assert classified[0] == "cli_passthrough"
    assert "juju.offer('m.pg', endpoint='db', controller='ctl')" in _src(
        ["offer", "m.pg:db", "-c", "ctl"]
    )


# --- consuming, and the rest of the lifecycle ---


def test_consume_with_an_alias() -> None:
    assert f"juju.consume('{OFFER_URL}', 'pg')" in _src(["consume", OFFER_URL, "pg"])


def test_the_saas_alias_integrates_like_any_application() -> None:
    assert "juju.integrate('data-integrator', 'pg')" in _src(
        ["integrate", "data-integrator", "pg"]
    )


def test_the_readers_and_removers_use_the_escape_hatch() -> None:
    """jubilant has no client method for any of these."""
    src = _src(
        ["offers"],
        ["show-offer", OFFER_URL],
        ["remove-saas", "pg"],
        ["remove-offer", OFFER_URL, "--force"],
    )
    assert 'juju.cli("offers"' in src
    assert 'juju.cli("show-offer"' in src
    assert "juju.cli(\"remove-saas\", 'pg')" in src
    assert 'juju.cli("remove-offer"' in src


def test_suspend_and_resume_a_cross_model_relation() -> None:
    src = _src(
        ["suspend-relation", "1", "--message", "planned maintenance"],
        ["resume-relation", "1"],
    )
    assert "juju.cli(\"suspend-relation\", '1', \"--message\", 'planned maintenance')" in src
    assert "juju.cli(\"resume-relation\", '1')" in src


# --- the warning ---


def test_a_cross_model_session_says_the_other_model_is_not_created() -> None:
    src = _src(["offer", "cmr-offer.postgresql:database", "o"], ["consume", OFFER_URL, "pg"])
    assert "# NOTE: the cross-model steps below reference offers in model cmr-offer" in src
    assert "which this test does not create" in src


def test_the_note_is_emitted_once_however_many_steps_touch_the_model() -> None:
    """A CMR session touches the same model four or five times."""
    src = _src(
        ["offer", "cmr-offer.postgresql:database", "o"],
        ["show-offer", OFFER_URL],
        ["consume", OFFER_URL, "pg"],
        ["remove-offer", OFFER_URL],
    )
    assert src.count("# NOTE: the cross-model steps") == 1


def test_several_models_are_all_named() -> None:
    src = _src(["consume", "admin/one.x", "a"], ["consume", "admin/two.y", "b"])
    assert "in models one, two" in src


def test_a_session_with_no_cross_model_steps_says_nothing() -> None:
    assert "# NOTE: the cross-model" not in _src(["deploy", "ubuntu"], ["status"])


def test_the_session_own_model_is_not_treated_as_foreign() -> None:
    """An offer published from the model the session made is not cross-model."""
    events = [
        _shim(1, ["add-model", "mine"]),
        _shim(2, ["offer", "mine.postgresql:database", "o"]),
    ]
    assert cli_translate.cross_model_models(events) == ()


# --- the libjuju front-end reaches these ops without an argv ---


def _typed(seq: int, op: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": seq,
        "op": op,
        "ts": "2026-09-10T10:00:00.000Z",
        "args": args,
        "result": {},
        "model_snapshot_before": None,
        "model_snapshot_after": None,
        "assertions": [],
        "gesture": None,
    }


def test_a_libjuju_recorded_session_is_warned_about_too() -> None:
    """It produces typed ops directly, never an argv to scan."""
    src = generate(
        _wrap(
            [
                _typed(1, "consume", {"offer_url": OFFER_URL, "application_alias": "ljpg"}),
                _typed(
                    2, "integrate", {"app1_endpoint": "data-integrator", "app2_endpoint": "ljpg"}
                ),
                _typed(3, "remove_offer", {"offer_urls": [OFFER_URL], "force": True}),
            ]
        )
    )
    assert "# NOTE: the cross-model steps below reference offers in model cmr-offer" in src
    assert f"juju.consume('{OFFER_URL}', 'ljpg')" in src


def test_an_offer_with_no_model_name_warns_about_nothing() -> None:
    """libjuju's `create_offer` carries a model UUID, which is not a name.

    The correlator drops it rather than fabricating a dotted form, so there
    is no second model to warn about — the offer replays from the test's own.
    """
    src = generate(
        _wrap([_typed(1, "create_offer", {"app": "postgresql", "endpoints": ["database"]})])
    )
    assert "# NOTE: the cross-model" not in src
    assert "juju.offer('postgresql', endpoint='database')" in src
