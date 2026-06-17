from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jubilant_recorder.tagger.types import AssertionTag


def _relation_set(snapshot: dict[str, Any] | None) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
    if not isinstance(snapshot, dict):
        return out
    for rel in snapshot.get("relations") or []:
        endpoints = rel.get("endpoints") if isinstance(rel, dict) else None
        if isinstance(endpoints, list) and len(endpoints) == 2:
            out.add(frozenset(endpoints))
    return out


def evaluate(events: list[dict[str, Any]], index: int) -> Iterable[AssertionTag]:
    event = events[index]
    op = event.get("op")
    if op not in ("integrate", "remove_integration"):
        return
    before = _relation_set(event.get("model_snapshot_before"))
    after = _relation_set(event.get("model_snapshot_after"))

    if op == "integrate":
        new_relations = after - before
        for rel in new_relations:
            endpoint_a, endpoint_b = sorted(rel)
            yield AssertionTag(
                kind="relation_exists",
                strict=False,
                source="delta",
                payload={"endpoint_a": endpoint_a, "endpoint_b": endpoint_b},
            )
    else:
        removed_relations = before - after
        for rel in removed_relations:
            endpoint_a, endpoint_b = sorted(rel)
            yield AssertionTag(
                kind="relation_absent",
                strict=False,
                source="delta",
                payload={"endpoint_a": endpoint_a, "endpoint_b": endpoint_b},
            )
