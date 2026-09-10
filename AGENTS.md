# Agent instructions

Python tool that wraps `jubilant.Juju`, records every CLI call plus
before/after model snapshots, and generates a pytest integration test from
the resulting session log.

## Layout

- `src/jubilant_recorder/` — package source (recorder, codegen, CLIs).
  - `codegen/cli_translate.py` — every recorded `juju` argv becomes a
    jubilant call: a typed one where a method exists, `juju.cli(...)` where
    it does not. Flag tables are the real juju CLI surface; the regeneration
    command for the `--model` list is in the file.
  - `pytest_plugin.py` — records an unmodified pytest-operator suite
    (`pytest --jtr-out=...`). Registered as a `pytest11` entry point, inert
    unless one of its options is passed.
- `tests/` — pytest suite. No real Juju required; tests use fixtures.
  `tests/e2e/` is the exception: those need a controller and are deselected
  unless you pass `--e2e`. They are what proves a generated test *runs*, and
  they run against both a machine cloud and Kubernetes — juju's CLI forks on
  the cloud type, so one of them alone leaves half the translations
  unexercised. The suite picks its charm from the controller's cloud.
- `examples/` — sample recording scripts, plus a libjuju driver and a
  pytest-operator suite for the two non-scripted modes.
- `docs/` — schema reference, demo, and per-mode guides.

Entry points: `jubilant-recorder` and `jtr` (the shell-capture CLI), both
defined in `pyproject.toml`, plus the `pytest11` plugin entry point.

## Setup

```bash
uv sync --extra dev --extra libjuju
```

## Checks before pushing

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright   # needs the libjuju extra synced
uv run pytest
```

Pre-commit runs format + lint + pyright; CI runs those plus the tests on
every supported Python, and checks the built wheel.

## Conventions

- Python 3.11+. Type-annotate public APIs; `pyright` runs in `standard` mode.
- Ruff handles formatting and lint (see `[tool.ruff]` in `pyproject.toml`).
  Line length 99. Don't disable rules ad hoc — adjust `pyproject.toml`.
- Tests live next to behaviour, named `test_<thing>.py`.
- Conventional Commits for commit messages.

## What to be careful about

- The session log schema (`docs/schema.md`) is a public contract — changes to event
  shapes need a schema version bump and codegen update in lock-step.
- The gesture API (`assert_status`, `assert_action_result`, `assert_config`,
  `checkpoint`) is user-facing; signature changes ripple into example scripts
  and the generated test surface.
- LLM augmentation is gated behind `--ai` and must not run by default; the
  deterministic codegen path is the source of truth.
- The pytest plugin runs inside somebody else's test suite. A bug in the
  recorder must never fail the test it is recording — it warns and discards
  that session log. There is a test for this; keep it passing.
- Generated code has to run, not just parse. Check a new emitter's call
  against the real `jubilant.Juju` signature; a plausible-looking kwarg that
  does not exist (`juju.config(app, keys=[...])` was one) turns every
  generated test using it into a TypeError. The dependency floor
  (`jubilant>=1.10`) is set by what codegen emits, not by what the recorder
  calls — raise it when an emitter starts using a newer method.
- `docs/demo.md` is a showboat document: every block in it was really run.
  Re-record it rather than editing its outputs
  (`uvx showboat verify docs/demo.md --output docs/demo.md`), and read
  `docs/running-the-demo.md` first.
