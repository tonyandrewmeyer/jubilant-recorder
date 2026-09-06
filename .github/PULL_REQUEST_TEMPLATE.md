<!-- What does this change, and why? Link an issue if there is one. -->

## Checks

- [ ] `uv run pytest` passes
- [ ] `uv run ruff check` and `uv run ruff format --check .` pass
- [ ] `uv run pyright` passes
- [ ] If codegen output changed, `tests/fixtures/golden/` is regenerated and the diff reviewed
- [ ] If the session-log schema changed, `schema_version` is bumped and `docs/schema.md` updated
