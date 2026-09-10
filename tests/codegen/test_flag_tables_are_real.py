"""Every flag a classifier claims must exist on the subcommand it claims it for.

`cli_translate`'s module docstring says its flag tables are the real juju
CLI surface. Nothing checked that, and four of them were not: `remove-unit`
and `destroy-model` were given `-y`/`--yes` aliases juju does not define,
`remove-unit` a `-n` short form it does not have, and `destroy-model` was
missing the `-t` that it does.

An invented flag is not catastrophic — juju would have rejected the command
that used it, so it never reaches a recording — but it is a table that says
something false about juju, and the next person to read it for the real
answer gets the wrong one.

The captured surface is `juju_flags.py`; regenerate it against a newer
client with the command in that file's docstring.
"""

from __future__ import annotations

import pytest

from jubilant_recorder.codegen import cli_translate as ct

from .juju_flags import JUJU_FLAGS

# The two commands that do not take juju's framework logging flags. Both are
# minimal: `juju version` prints a string, `juju wait-for <scope>` polls.
# `_parse` tolerates and drops the logging flags everywhere, so on these two
# it accepts a spelling juju would reject — which costs nothing, because such
# a command exits non-zero and codegen comments it out. Enumerated rather
# than assumed so a third one shows up as a failure here.
_MINIMAL_COMMANDS = frozenset({"version", "wait-for"})

# What each classifier accepts, as (valued, boolean, aliases). Written out
# rather than introspected: the point is to state what the code claims, in a
# place a reviewer can compare against `juju help`, so deriving it from the
# code would check the code against itself.
CLAIMED: dict[str, tuple[frozenset[str], frozenset[str], dict[str, str]]] = {
    "add-machine": (ct._ADD_MACHINE_VALUED, frozenset(), {}),
    "add-model": (ct._ADD_MODEL_VALUED, ct._ADD_MODEL_BOOLEAN, {"-c": "--controller"}),
    "add-secret": (ct._ADD_SECRET_VALUED, frozenset(), {}),
    "add-unit": (ct._ADD_UNIT_VALUED, frozenset(), {"-n": "--num-units"}),
    "config": (ct._CONFIG_VALUED, frozenset(), {}),
    "debug-log": (ct._DEBUG_LOG_VALUED, ct._DEBUG_LOG_BOOLEAN, {"-n": "--lines"}),
    "deploy": (ct._DEPLOY_VALUED, ct._DEPLOY_BOOLEAN, ct._DEPLOY_ALIASES),
    "destroy-model": (ct._DESTROY_MODEL_VALUED, ct._DESTROY_MODEL_BOOLEAN, {"-t": "--timeout"}),
    "exec": (
        ct._EXEC_VALUED,
        ct._EXEC_BOOLEAN,
        {"-u": "--unit", "-a": "--application", "--app": "--application"},
    ),
    "refresh": (ct._REFRESH_VALUED, ct._REFRESH_BOOLEAN, {}),
    "remove-application": (frozenset(), ct._REMOVE_APP_BOOLEAN, {}),
    "remove-unit": (ct._REMOVE_UNIT_VALUED, ct._REMOVE_UNIT_BOOLEAN, {}),
    # `wait-for` is a command *group*: its flags live on the subcommands
    # (`juju wait-for application`), which is what a recorded argv carries
    # and what the classifier parses. `juju_flags.py` captures the
    # subcommand's surface under this key for that reason.
    "run": (ct._RUN_VALUED, ct._RUN_BOOLEAN, {}),
    "scp": (ct._SCP_VALUED, ct._SCP_BOOLEAN, {}),
    "secrets": (ct._SECRETS_VALUED, ct._SECRETS_BOOLEAN, ct._SECRETS_ALIASES),
    "show-secret": (ct._SHOW_SECRET_VALUED, ct._SHOW_SECRET_BOOLEAN, {}),
    "ssh": (ct._SSH_VALUED, ct._SSH_BOOLEAN, {}),
    "status": (ct._STATUS_VALUED, ct._STATUS_BOOLEAN, {}),
    "trust": (ct._TRUST_VALUED, ct._TRUST_BOOLEAN, {}),
    "update-secret": (ct._UPDATE_SECRET_VALUED, ct._UPDATE_SECRET_BOOLEAN, {}),
    "wait-for": (ct._WAIT_FOR_VALUED, ct._WAIT_FOR_BOOLEAN, {}),
}


@pytest.mark.parametrize("subcommand", sorted(CLAIMED))
def test_claimed_flags_exist_on_the_subcommand(subcommand: str) -> None:
    real = JUJU_FLAGS[subcommand]
    valued, boolean, aliases = CLAIMED[subcommand]
    claimed = set(valued) | set(boolean) | set(aliases)
    invented = sorted(claimed - real)
    assert not invented, (
        f"`juju {subcommand}` has no {invented} — either the flag table is "
        f"wrong, or juju_flags.py needs regenerating against a newer client"
    )


@pytest.mark.parametrize("subcommand", sorted(CLAIMED))
def test_an_alias_maps_to_a_flag_the_classifier_handles(subcommand: str) -> None:
    """An alias pointing at nothing silently drops the flag's value."""
    valued, boolean, aliases = CLAIMED[subcommand]
    for short, long in aliases.items():
        assert long in set(valued) | set(boolean) | set(ct._GLOBAL_VALUED) | set(
            ct._GLOBAL_BOOLEAN
        ), f"`juju {subcommand} {short}` resolves to {long}, which nothing handles"


# The logging flags `_parse` drops on every subcommand. `--format`/`-o`/
# `--color`/`--utc` are deliberately not here: they only exist on commands
# that render something, and dropping them is about output shape rather than
# about being global.
_LOGGING_FLAGS = frozenset({"--debug", "--quiet", "--verbose", "--show-log", "--logging-config"})


def test_the_logging_flags_are_global_apart_from_two_commands() -> None:
    """`_parse` drops them everywhere, so where they do not exist it is lenient."""
    without = {sub for sub, real in JUJU_FLAGS.items() if _LOGGING_FLAGS - real}
    assert without == _MINIMAL_COMMANDS, (
        f"the set of commands without juju's logging flags changed: {sorted(without)}"
    )
    assert set(ct._GLOBAL_BOOLEAN) | set(ct._GLOBAL_VALUED) >= _LOGGING_FLAGS


def test_every_classified_subcommand_has_captured_flags() -> None:
    """A new classifier needs its subcommand captured before this can check it."""
    missing = sorted(set(ct._SUBCOMMANDS) - set(JUJU_FLAGS))
    assert not missing, f"juju_flags.py is missing: {missing}"
