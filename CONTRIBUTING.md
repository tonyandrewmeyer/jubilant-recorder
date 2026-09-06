# Contributing

Thanks for taking a look. This is an alpha personal project, so the process
is light.

## Setup

```bash
uv sync --extra dev --extra libjuju
pre-commit install
```

The `libjuju` extra is needed for `pyright` to check the libjuju extension;
without it that code is skipped as an unresolved import.

## Before you push

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Pre-commit runs the first three. CI runs all four, on Python 3.11 through
3.13, and checks that the built wheel imports.

## Tests

The unit suite is entirely fixture-driven — no Juju controller, about twelve
seconds. Add tests next to the behaviour they cover, named `test_<thing>.py`.

The end-to-end tests in `tests/e2e/` do need a real controller and are
deselected by default:

```bash
uv run pytest tests/e2e --e2e
```

`tests/fixtures/golden/` holds the generated output for each recorded
session. If a change alters codegen, regenerate them and **read the diff**:

```bash
JTR_UPDATE_GOLDEN=1 uv run pytest tests/codegen/test_recorded_sessions_golden.py
```

An unexplained change there means codegen moved under you.

## Conventions

- Python 3.11+. Type-annotate public APIs; `pyright` runs in `standard` mode.
- Ruff handles formatting and lint. Line length 99. Don't disable rules ad
  hoc — adjust `pyproject.toml`, with a comment saying why.
- [Conventional Commits](https://www.conventionalcommits.org/) for commit
  messages.

## Things to be careful about

- **The session-log schema** ([docs/schema.md](docs/schema.md)) is a public
  contract. Changing an event shape needs a schema version bump and a
  codegen update in lock-step.
- **The gesture API** (`assert_status`, `assert_action_result`,
  `checkpoint`) is user-facing; signature changes ripple into the example
  scripts and every generated test.
- **Redaction** applies to both arguments and results. If you add a code
  path that writes to a session log, make sure it goes through
  `redact_payload`; `tests/test_fixtures_are_redacted.py` is the backstop,
  not the design.
- **LLM augmentation** is gated behind `--ai` and must not run by default.
  The deterministic codegen path is the source of truth.

## Reporting bugs

Open an issue. For anything security-related, see [SECURITY.md](SECURITY.md)
instead.
