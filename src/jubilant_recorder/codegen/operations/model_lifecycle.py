"""Emit jubilant code for recorded model-lifecycle commands.

``juju add-model`` / ``destroy-model`` / ``switch`` are the one group where
translating the recorded command literally produces a *worse* test than not
translating it. A generated test opens with ``jubilant.temp_model()``, which
creates a fresh model, points ``juju`` at it, and tears it down again. The
model the session created by hand is that same model in intent, so:

* ``juju.add_model(...)`` for it would create a *second* model and — because
  ``add_model`` reassigns ``Juju.model`` — silently redirect every later step
  away from the one ``temp_model()`` is going to clean up, leaving the real
  model behind after the test passes.
* ``juju.destroy_model(...)`` for it would destroy the test's own model
  mid-test, and ``temp_model()`` would then fail to tear it down.

So the session's *own* model is rendered as a comment naming what happened
and where it went, while any *other* model named in the session — a second
model created for a cross-model test, say — is translated to the real
``juju.add_model()``/``destroy_model()`` call, because there ``temp_model()``
is not standing in for it.

``codegen.cli_translate.session_model()`` decides which is which.
"""

from __future__ import annotations

from typing import Any


def _kwargs(args: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    parts = []
    for name in names:
        value = args.get(name)
        if value is None or value is False:
            continue
        parts.append(f"{name}={value!r}")
    return parts


def emit_add_model(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.add_model(...)``, or a note if it is the test's own model."""
    args = event["args"]
    model = args["model"]
    pad = " " * indent
    if args.get("is_session_model"):
        return (
            f"{pad}# `juju add-model {model}` — jubilant.temp_model() above creates the\n"
            f"{pad}# model this test runs in, so the recorded add-model is not repeated."
        )
    parts = [repr(model)]
    cloud = args.get("cloud")
    if cloud:
        parts.append(repr(cloud))
    parts.extend(_kwargs(args, ("controller", "config", "credential")))
    return pad + f"juju.add_model({', '.join(parts)})"


def emit_destroy_model(event: dict[str, Any], indent: int) -> str:
    """Emit ``juju.destroy_model(...)``, or a note if it is the test's own model."""
    args = event["args"]
    model = args["model"]
    pad = " " * indent
    if args.get("is_session_model"):
        return (
            f"{pad}# `juju destroy-model {model}` — jubilant.temp_model() above tears the\n"
            f"{pad}# model down on the way out of the `with` block."
        )
    parts = [repr(model)]
    parts.extend(
        _kwargs(args, ("destroy_storage", "force", "no_wait", "release_storage", "timeout"))
    )
    return pad + f"juju.destroy_model({', '.join(parts)})"


def emit_switch_model(event: dict[str, Any], indent: int) -> str:
    """Emit a note for ``juju switch``.

    jubilant has no ``switch`` method by design: a ``Juju`` instance carries
    its model in :attr:`jubilant.Juju.model`, and ``temp_model()`` has
    already set that. Switching the *CLI's* current model from inside a test
    would change which model the operator's own terminal points at, which is
    never what the test wants.
    """
    model = event["args"]["model"]
    pad = " " * indent
    if event["args"].get("is_session_model"):
        return f"{pad}# `juju switch {model}` — this test's model is the one temp_model() made."
    return (
        f"{pad}# `juju switch {model}` — to work against a different model, construct a\n"
        f"{pad}# second `jubilant.Juju(model={model!r})` rather than switching this one."
    )
