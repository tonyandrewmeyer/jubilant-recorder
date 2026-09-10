"""Module-level imports and the `jubilant.temp_model()` wrapper.

WHY `jubilant.temp_model()` (over hand-rolled add_model / destroy_model in
fixtures): the generated test should follow the jubilant
idiom, and the documented idiom is the `temp_model` context manager —
model creation, teardown, and exception safety in a single block.

WHY the non-empty-model comment: `temp_model()`
always gives the test a fresh, empty model. If the recording that produced
this test actually started from a model that already had applications
deployed, the generated test silently inherits an assumption — "this state
already exists" — that `temp_model()` does not honour, and the test will
fail for a reason the file itself never explains. Detecting this only takes
the first recorded event's `model_snapshot_before` (docs/schema.md is the source
of truth for its shape), so codegen surfaces it as a comment rather than
leaving it as a silent trap. When the first snapshot is empty — the common
case, and what every existing fixture records — nothing is emitted and
output stays byte-identical to before this existed.
"""

from __future__ import annotations

import dataclasses
from typing import Any

BODY_INDENT = 8
# A test that takes the module-scoped `juju` fixture has one less level of
# nesting than one that opens `temp_model()` itself.
FIXTURE_BODY_INDENT = 4


def pre_existing_apps(snapshot: dict[str, Any] | None) -> tuple[str, ...]:
    """Describe the apps present in a `model_snapshot_before`, sorted by name.

    Each entry reads ``"<app> (<n> units)"``. Returns an empty tuple for a
    missing/null snapshot or one with no apps at all — the fresh-model case.
    """
    if not snapshot:
        return ()
    apps = snapshot.get("apps") or {}
    described = []
    for name in sorted(apps):
        units = (apps[name] or {}).get("units") or {}
        count = len(units)
        noun = "unit" if count == 1 else "units"
        described.append(f"{name} ({count} {noun})")
    return tuple(described)


@dataclasses.dataclass(frozen=True)
class Preamble:
    """The imports and fixtures emitted above a generated test body."""

    test_name: str
    needs_pytest: bool = False
    pre_existing_apps: tuple[str, ...] = ()
    cross_model_models: tuple[str, ...] = ()

    def lines(self) -> list[str]:
        # `import pytest` is emitted only when the body needs it (a
        # `pytest.skip(...)` for an unrepresentable op — see
        # codegen.unrepresentable). Logs containing only representable ops
        # leave `needs_pytest` False, so their preamble — and therefore the
        # whole generated file — stays byte-identical to prior snapshots.
        imports = ["import jubilant"]
        if self.needs_pytest:
            imports.append("import pytest")
        lines = [
            *imports,
            "",
            "",
            f"def {self.test_name}():",
            "    with jubilant.temp_model() as juju:",
        ]
        if self.pre_existing_apps:
            lines.extend(self._non_empty_model_comment())
        if self.cross_model_models:
            lines.extend(cross_model_lines(self.cross_model_models, BODY_INDENT))
        return lines

    def _non_empty_model_comment(self) -> list[str]:
        return _non_empty_model_lines(
            self.pre_existing_apps, BODY_INDENT, "jubilant.temp_model() above"
        )


def cross_model_lines(models: tuple[str, ...], indent: int) -> list[str]:
    """Warn that the offers this test consumes live in a model it does not make.

    A cross-model relation needs two models. A generated test opens one —
    `jubilant.temp_model()` — so the offer URLs below name a model that is
    the *recording's*, not the test's. The calls themselves are right, and
    they work while that model exists and still publishes the offer; they
    fail with "offer not found" otherwise. Emitted once, listing the models,
    rather than beside each call: a CMR session touches the same model four
    or five times and the repetition would bury the steps.
    """
    pad = " " * indent
    named = ", ".join(models)
    plural = "models" if len(models) > 1 else "model"
    return [
        f"{pad}# NOTE: the cross-model steps below reference offers in {plural} {named},",
        f"{pad}# which this test does not create — jubilant.temp_model() gives it one",
        f"{pad}# model of its own. They work while that {plural.rstrip('s')} exists and still",
        f'{pad}# publishes the offer, and fail with "offer not found" otherwise.',
    ]


def empty_body_filler(indent: int = BODY_INDENT) -> str:
    """Return the body used when a session recorded no operations."""
    return " " * indent + "pass"


def module_header(*, needs_pytest: bool = True) -> list[str]:
    """Build the imports and module-scoped `juju` fixture for a multi-test module.

    A pytest-operator suite shares one model across every test in a module:
    its `ops_test` fixture is module-scoped, so `test_deploy` sets up what
    `test_scale` then acts on. Generating each recorded test as its own
    `jubilant.temp_model()` block would give each one an empty model and
    every test after the first would fail on state it never created.

    The jubilant idiom for the same thing is a module-scoped fixture, so
    that is what a multi-test module gets. `needs_pytest` is always true in
    practice — the fixture decorator needs it — and is a parameter only so
    the single-test `Preamble` and this share one convention.
    """
    imports = ["import jubilant"]
    if needs_pytest:
        imports.append("import pytest")
    return [
        *imports,
        "",
        "",
        '@pytest.fixture(scope="module")',
        "def juju():",
        "    with jubilant.temp_model() as juju:",
        "        yield juju",
    ]


def test_header(
    test_name: str,
    pre_existing_apps: tuple[str, ...] = (),
    cross_model_models: tuple[str, ...] = (),
) -> list[str]:
    """Build the `def <name>(juju):` line for one test in a multi-test module.

    ``pre_existing_apps`` is only ever passed for the *first* test in the
    module. For every test after it, a non-empty starting model is not a
    trap — it is what the tests before it deployed, which is the whole
    point of the shared fixture. Warning about it on each one buried the
    real steps under a five-line note that was also wrong.
    """
    # Two blank lines before a top-level def, as PEP 8 and every formatter
    # the reader runs over this file will expect.
    lines = ["", "", f"def {test_name}(juju: jubilant.Juju):"]
    if pre_existing_apps:
        lines.extend(
            _non_empty_model_lines(pre_existing_apps, FIXTURE_BODY_INDENT, "the `juju` fixture")
        )
    if cross_model_models:
        lines.extend(cross_model_lines(cross_model_models, FIXTURE_BODY_INDENT))
    return lines


def _non_empty_model_lines(
    pre_existing_apps: tuple[str, ...], indent: int, source: str
) -> list[str]:
    pad = " " * indent
    present = ", ".join(pre_existing_apps)
    return [
        f"{pad}# NOTE: this session was recorded against a model that already had",
        f"{pad}# applications deployed ({present}), which {source} does not",
        f"{pad}# recreate — it gives this test a fresh, empty model. Set that state",
        f"{pad}# up by hand if the recorded operations below assumed it was there.",
    ]
