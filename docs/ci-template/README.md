# CI workflow template

These files are intended to live at `.github/workflows/` in the standalone
`jubilant-recorder` repo after the lift. They are kept under `docs/ci-template/`
in the staging tree because the staging repo
(`the staging repo`) forbids real workflows under `.github/`.

When lifting the project to its own repo, move these into `.github/workflows/`
verbatim.

| File | Purpose |
|---|---|
| `quality-checks.yaml` | ruff + pyright + pytest on every PR. |
| `build-and-publish.yaml` | Build sdist/wheel on push, publish on tag. |
