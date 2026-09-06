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


def _coverage(tag_dict: dict[str, Any]) -> tuple[Any, ...] | None:
    """Return a coarser key for what a tag *claims*, ignoring how it is scoped.

    Only ``unit_status`` needs this. The delta rule is app-scoped, because a
    recorded unit name does not survive into a fresh model; a gesture may name
    a unit, because the author chose to. Those two make the same claim about
    the same app and status, so identity alone would let both through and the
    generated test would assert it twice.
    """
    if tag_dict.get("kind") != "unit_status":
        return None
    return ("unit_status", tag_dict.get("app"), tag_dict.get("expected"))


def tag(log: SessionLog, *, proposer: AssertionProposer | None = None) -> SessionLog:
    """Return the session log with assertion tags added."""
    out = copy.deepcopy(log)
    events: list[dict[str, Any]] = out.get("events", [])
    for index in range(len(events)):
        event = events[index]
        if "assertions" not in event or event["assertions"] is None:
            event["assertions"] = []
        existing = {_identity(a) for a in event["assertions"] if isinstance(a, dict)}
        covered = {
            key
            for a in event["assertions"]
            if isinstance(a, dict) and (key := _coverage(a)) is not None
        }
        for rule in _RULES:
            for produced in rule.evaluate(events, index):
                if not isinstance(produced, AssertionTag):
                    continue
                tag_dict = produced.to_dict()
                ident = _identity(tag_dict)
                if ident in existing:
                    continue
                claim = _coverage(tag_dict)
                if claim is not None and claim in covered:
                    continue
                event["assertions"].append(tag_dict)
                existing.add(ident)
                if claim is not None:
                    covered.add(claim)

    if proposer is not None:
        from jubilant_recorder.tagger.llm import llm_augment

        out = llm_augment(out, proposer)

    return out
