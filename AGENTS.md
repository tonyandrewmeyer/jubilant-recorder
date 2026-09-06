# Agent instructions

Python tool that wraps `jubilant.Juju`, records every CLI call plus
before/after model snapshots, and generates a pytest integration test from
the resulting session log.

## Layout

- `src/jubilant_recorder/` — package source (recorder, codegen, CLI).
- `tests/` — pytest suite. No real Juju required; tests use fixtures.
- `examples/` — sample recording scripts.
- `docs/`, `SCHEMA.md` — design and session-log schema reference.

Entry point: `jubilant-recorder` (defined in `pyproject.toml`).

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

- The session log schema (`SCHEMA.md`) is a public contract — changes to event
  shapes need a schema version bump and codegen update in lock-step.
- The gesture API (`assert_status`, `assert_action_result`, `checkpoint`) is
  user-facing; signature changes ripple into example scripts and the generated
  test surface.
- LLM augmentation is gated behind `--ai` and must not run by default; the
  deterministic codegen path is the source of truth.
