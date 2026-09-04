"""Delta-based assertion tagger.

Conservative bias is the rule here: an
over-permissive tagger (one that emits assertions when the user wasn't
really checking) is more expensive than an under-permissive one, because
a missing assertion is obvious to the test author whereas a wrong
assertion bakes a falsehood into the generated test. Each rule module
prefers to stay silent rather than guess.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, TypeAlias

from jubilant_recorder.tagger.rules import action, config, relation, scale, status
from jubilant_recorder.tagger.types import AssertionTag

if TYPE_CHECKING:
    from jubilant_recorder.tagger.llm import AssertionProposer

SessionLog: TypeAlias = dict[str, Any]

_RULES = (status, action, scale, config, relation)

_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "unit_status": ("app", "unit"),
    "unit_count": ("app",),
    "action_result": ("unit", "action"),
    "config_value": ("app", "key"),
    "relation_exists": ("endpoint_a", "endpoint_b"),
    "relation_absent": ("endpoint_a", "endpoint_b"),
    "user_checkpoint": ("label",),
}


def _identity(tag_dict: dict[str, Any]) -> tuple[Any, ...]:
    kind = tag_dict.get("kind", "")
    fields = _IDENTITY_FIELDS.get(kind, ())
    return (kind, *(tag_dict.get(f) for f in fields))


def tag(log: SessionLog, *, proposer: AssertionProposer | None = None) -> SessionLog:
    """Return the session log with assertion tags added."""
    out = copy.deepcopy(log)
    events: list[dict[str, Any]] = out.get("events", [])
    for index in range(len(events)):
        event = events[index]
        if "assertions" not in event or event["assertions"] is None:
            event["assertions"] = []
        existing = {_identity(a) for a in event["assertions"] if isinstance(a, dict)}
        for rule in _RULES:
            for produced in rule.evaluate(events, index):
                if not isinstance(produced, AssertionTag):
                    continue
                tag_dict = produced.to_dict()
                ident = _identity(tag_dict)
                if ident in existing:
                    continue
                event["assertions"].append(tag_dict)
                existing.add(ident)

    if proposer is not None:
        from jubilant_recorder.tagger.llm import llm_augment

        out = llm_augment(out, proposer)

    return out
