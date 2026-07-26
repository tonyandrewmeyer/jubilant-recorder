"""Types shared by the assertion tagger."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclasses.dataclass(frozen=True)
class AssertionTag:
    """One proposed assertion about a recorded event."""

    kind: str
    strict: bool
    source: str
    payload: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "strict": self.strict,
            **dict(self.payload),
        }
