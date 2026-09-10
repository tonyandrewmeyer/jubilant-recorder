"""Emit ``juju.cli(...)`` for a recorded ``juju`` invocation with no typed match.

This is the floor of the shell-capture translation ladder. Every ``juju``
command the classifiers in ``codegen/cli_translate.py`` decline to type
arrives here and becomes a real, runnable ``juju.cli(...)`` call rather
than a ``# shell: juju …`` comment the reader has to retype by hand.
``juju.cli()`` is jubilant's documented escape hatch (it is what jubilant's
own ``bootstrap()`` uses) and returns the command's standard output, so a
passthrough step loses nothing but its typing.

Two rewrites happen on the way through, both of which the generated test
needs in order to run at all:

* ``include_model=False`` for the subcommands that reject ``--model``.
  ``juju.cli()`` inserts ``--model <model>`` after the first argument by
  default; doing that to ``juju whoami`` makes the step fail on a flag
  parse error instead of running.
* ``--no-prompt`` for the subcommands that otherwise wait on stdin for a
  confirmation nobody is there to give.
* an explicit ``--model`` for the command groups whose *subcommands* take
  one even though the group does not (``juju wait-for application``), since
  ``juju.cli()`` can only insert it in the one position that does not work
  there.
"""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("<subcommand>", ...)`` call."""
    args = event["args"]
    argv = [str(a) for a in (args.get("argv") or [])]
    if not argv:
        raise ValueError("cli_passthrough event missing argv")

    if args.get("add_no_prompt"):
        argv = [argv[0], "--no-prompt", *argv[1:]]

    parts = [repr(a) for a in argv]
    if args.get("model_after_subcommand"):
        # Read the model off the instance at test time — `temp_model()` names
        # it, and codegen cannot.
        parts.extend([repr("--model"), "juju.model"])
    if args.get("include_model") is False:
        parts.append("include_model=False")
    return " " * indent + f"juju.cli({', '.join(parts)})"
