"""Module-level imports and the `jubilant.temp_model()` wrapper.

WHY `jubilant.temp_model()` (over hand-rolled add_model / destroy_model in
fixtures): the plan §(C) requires the generated test to follow the jubilant
idiom, and the documented idiom is the `temp_model` context manager —
model creation, teardown, and exception safety in a single block.

WHY the non-empty-model comment (the plan open question 3): `temp_model()`
always gives the test a fresh, empty model. If the recording that produced
this test actually started from a model that already had applications
deployed, the generated test silently inherits an assumption — "this state
already exists" — that `temp_model()` does not honour, and the test will
fail for a reason the file itself never explains. Detecting this only takes
the first recorded event's `model_snapshot_before` (SCHEMA.md is the source
of truth for its shape), so codegen surfaces it as a comment rather than
leaving it as a silent trap. When the first snapshot is empty — the common
case, and what every existing fixture records — nothing is emitted and
output stays byte-identical to before this existed.
"""

from __future__ import annotations

import dataclasses
from typing import Any

BODY_INDENT = 8


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
        return lines

    def _non_empty_model_comment(self) -> list[str]:
        pad = " " * BODY_INDENT
        present = ", ".join(self.pre_existing_apps)
        return [
            f"{pad}# NOTE: this session was recorded against a model that already had",
            f"{pad}# applications deployed ({present}). jubilant.temp_model() above gives",
            f"{pad}# this test a fresh, empty model instead, so that pre-existing state is",
            f"{pad}# NOT recreated here — set it up by hand if the recorded operations",
            f"{pad}# below assumed it was already present.",
        ]


def empty_body_filler() -> str:
    """Return the body used when a session recorded no operations."""
    return " " * BODY_INDENT + "pass"
