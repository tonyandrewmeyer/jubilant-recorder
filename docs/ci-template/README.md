# CI workflow template

These files are templates for `.github/workflows/` that have not been
activated yet — only `lint.yaml` currently runs there. Promote them by
moving them into `.github/workflows/` verbatim when ready.

| File | Purpose |
|---|---|
| `quality-checks.yaml` | ruff + pyright + pytest on every PR. |
| `build-and-publish.yaml` | Build sdist/wheel on push, publish on tag. |
