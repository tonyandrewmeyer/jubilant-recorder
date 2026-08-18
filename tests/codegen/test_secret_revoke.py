"""``secret_revoke`` emitter — the last Secrets bucket-2 → bucket-1 promotion.

jubilant has no ``revoke_secret()`` client method (checked at 1.12.0, not
just the 1.10 ``SECRETS-GAPS.md`` was written against), so this emits via
``juju.cli()`` rather than a typed call — unlike its sibling
``secret_grant``, which gets ``juju.grant_secret()`` only because that
method happens to exist.
"""

from __future__ import annotations

from typing import Any

from jubilant_recorder.codegen import generate
from jubilant_recorder.codegen.operations import secret_revoke


def test_secret_revoke_basic(secret_revoke_event: dict[str, Any]) -> None:
    line = secret_revoke.emit(secret_revoke_event, indent=8)
    assert line == "        juju.cli(\"revoke-secret\", 'secret:abc123', 'consumer')"


def test_secret_revoke_indent_respected(secret_revoke_event: dict[str, Any]) -> None:
    assert secret_revoke.emit(secret_revoke_event, indent=0).startswith("juju.cli(")


def test_secret_revoke_uses_the_real_subcommand(
    secret_revoke_event: dict[str, Any],
) -> None:
    """``juju revoke-secret`` is a real subcommand (verified against 3.6.27).

    Guards the ``set_charm`` lesson: its naive mapping ``juju set-charm``
    does not exist in modern Juju, so a plausible-looking subcommand name is
    not evidence of a working call.
    """
    line = secret_revoke.emit(secret_revoke_event, indent=0)
    assert '"revoke-secret"' in line
    assert "revoke_secret" not in line, "jubilant has no such method"


def test_secret_revoke_missing_args_degrade_to_empty_strings() -> None:
    line = secret_revoke.emit({"args": {}}, indent=0)
    assert line == "juju.cli(\"revoke-secret\", '', '')"


def test_secret_revoke_renders_without_fallback(
    secret_revoke_event: dict[str, Any],
) -> None:
    """Registered in ``EMITTERS`` — must not reach the ``# TODO`` fallback."""
    src = generate({"events": [secret_revoke_event]})
    assert '"revoke-secret"' in src
    assert "# TODO: manual step" not in src
