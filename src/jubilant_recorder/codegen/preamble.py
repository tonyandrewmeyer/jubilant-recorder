"""Module-level imports and the `jubilant.temp_model()` wrapper.

WHY `jubilant.temp_model()` (over hand-rolled add_model / destroy_model in
fixtures): the plan §(C) requires the generated test to follow the jubilant
idiom, and the documented idiom is the `temp_model` context manager —
model creation, teardown, and exception safety in a single block.
"""

from __future__ import annotations

import dataclasses

BODY_INDENT = 8


@dataclasses.dataclass(frozen=True)
class Preamble:
    """The imports and fixtures emitted above a generated test body."""

    test_name: str
    needs_pytest: bool = False

    def lines(self) -> list[str]:
        # `import pytest` is emitted only when the body needs it (a
        # `pytest.skip(...)` for an unrepresentable op — see
        # codegen.unrepresentable). Logs containing only representable ops
        # leave `needs_pytest` False, so their preamble — and therefore the
        # whole generated file — stays byte-identical to prior snapshots.
        imports = ["import jubilant"]
        if self.needs_pytest:
            imports.append("import pytest")
        return [
            *imports,
            "",
            "",
            f"def {self.test_name}():",
            "    with jubilant.temp_model() as juju:",
        ]


def empty_body_filler() -> str:
    """Return the body used when a session recorded no operations."""
    return " " * BODY_INDENT + "pass"
