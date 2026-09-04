"""LLM-augmented assertion proposer for the tagger pipeline.

When --ai is set, send the session log to an LLM and ask
"what was the user verifying at each step?" Output slots into the existing
tagged-event format alongside the deterministic delta rules. Assertions
proposed by the LLM carry source="llm" to distinguish them from
source="delta" tags produced by the deterministic rules.

Safety rail: any proposal whose seq doesn't match a real event, or that
references an app/unit not present anywhere in the session's model snapshots,
or whose kind is unknown, is dropped with a warning. This prevents LLM
hallucinations from silently corrupting the generated test.
"""

from __future__ import annotations

import copy
import json
import warnings
from typing import Any, Protocol, TypeAlias, runtime_checkable

SessionLog: TypeAlias = dict[str, Any]

_VALID_KINDS = frozenset({"unit_status", "unit_count", "action_result", "relation_exists"})

# Mirrors engine._IDENTITY_FIELDS for deduplication against existing assertions.
_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "unit_status": ("app", "unit"),
    "unit_count": ("app",),
    "action_result": ("unit", "action"),
    "relation_exists": ("endpoint_a", "endpoint_b"),
}

_PROMPT = """\
You are analyzing a recorded juju charm deployment session log.
Your job is to identify what assertions should be made about the model state after each step.

Return ONLY a JSON object in exactly this format (no markdown fences, no other text):
{{
  "proposals": [
    {{
      "seq": <integer event seq number>,
      "kind": "<one of: unit_status | unit_count | action_result | relation_exists>",
      <kind-specific fields below>
    }}
  ]
}}

Kind-specific required fields:
  unit_status:    "app" (str), "unit" (str, e.g. "my-charm/0"),
                  "expected" (str, one of: active | blocked | waiting | maintenance | error)
  unit_count:     "app" (str), "expected" (int, number of units)
  action_result:  "unit" (str), "action" (str), "expected_success" (bool),
                  "expected_results" (dict, key/value pairs from the result; may be empty)
  relation_exists:"endpoint_a" (str, e.g. "my-charm:db"),
                  "endpoint_b" (str, e.g. "postgresql:database")

Rules:
- Only propose assertions strongly implied by what the user was doing.
- Prefer asserting on events where something meaningful changed.
- Do NOT propose assertions for timestamps, IP addresses, or large text blobs.
- If a step has no clear verifiable outcome, omit it from proposals.

Session log (JSON):
{log}
"""


@runtime_checkable
class AssertionProposer(Protocol):
    """The interface an LLM-backed assertion proposer must provide."""

    def propose(self, log: SessionLog) -> list[dict[str, Any]]:
        """Return raw assertion proposals for the session.

        Each proposal must have at minimum a "seq" (int) and "kind" (str).
        The safety filter in llm_augment() validates and drops bad proposals.
        """
        ...


class StubProposer:
    """Deterministic, offline stand-in for an LLM proposer.

    Returns no proposals — the safe default for tests and when the API key
    is absent. Mirrors StubPolisher's role in ai_polish.py.
    """

    def propose(self, log: SessionLog) -> list[dict[str, Any]]:
        return []


class AnthropicProposer:
    """Real LLM proposer using the Anthropic API (claude-sonnet-4-6).

    Requires an anthropic.Anthropic() client built with ANTHROPIC_API_KEY.
    API errors are caught and surfaced as warnings; the empty-list fallback
    keeps the rest of the pipeline intact.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def propose(self, log: SessionLog) -> list[dict[str, Any]]:
        log_json = json.dumps(log, indent=2, sort_keys=True)
        prompt = _PROMPT.format(log=log_json)
        try:
            message = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # anthropic.APIError and network errors
            warnings.warn(
                f"LLM assertion proposer API call failed: {exc} — skipping LLM pass",
                stacklevel=2,
            )
            return []

        raw = message.content[0].text if message.content else ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            warnings.warn(
                f"LLM assertion proposer returned non-JSON response: {exc} — skipping",
                stacklevel=2,
            )
            return []

        proposals = parsed.get("proposals")
        if not isinstance(proposals, list):
            warnings.warn(
                "LLM assertion proposer response missing 'proposals' list — skipping",
                stacklevel=2,
            )
            return []
        return proposals


def _identity(proposal: dict[str, Any]) -> tuple[Any, ...]:
    kind = proposal.get("kind", "")
    fields = _IDENTITY_FIELDS.get(kind, ())
    return (kind, *(proposal.get(f) for f in fields))


def _collect_known_entities(log: SessionLog) -> tuple[set[str], set[str]]:
    """Return (known_apps, known_units) from all model snapshots in the log."""
    known_apps: set[str] = set()
    known_units: set[str] = set()
    for event in log.get("events") or []:
        for key in ("model_snapshot_before", "model_snapshot_after"):
            snap = event.get(key) or {}
            apps = (snap.get("apps") or {}) if isinstance(snap, dict) else {}
            for app_name, app_data in apps.items():
                known_apps.add(app_name)
                for unit_name in (app_data or {}).get("units") or {}:
                    known_units.add(unit_name)
    return known_apps, known_units


def _validate_proposal(
    proposal: dict[str, Any],
    seq_to_event: dict[int, dict[str, Any]],
    known_apps: set[str],
    known_units: set[str],
) -> str | None:
    """Return an error string if the proposal is invalid, else None."""
    seq = proposal.get("seq")
    kind = proposal.get("kind")

    if not isinstance(seq, int) or seq not in seq_to_event:
        return f"unknown seq={seq!r}"

    if kind not in _VALID_KINDS:
        return f"unknown kind={kind!r}"

    if kind == "unit_status":
        app = proposal.get("app")
        unit = proposal.get("unit")
        expected = proposal.get("expected")
        if not isinstance(app, str) or app not in known_apps:
            return f"app={app!r} not in session log"
        if not isinstance(unit, str) or unit not in known_units:
            return f"unit={unit!r} not in session log"
        if not isinstance(expected, str):
            return f"expected={expected!r} is not a string"

    elif kind == "unit_count":
        app = proposal.get("app")
        expected = proposal.get("expected")
        if not isinstance(app, str) or app not in known_apps:
            return f"app={app!r} not in session log"
        if not isinstance(expected, int):
            return f"expected={expected!r} is not an int"

    elif kind == "action_result":
        unit = proposal.get("unit")
        action = proposal.get("action")
        event = seq_to_event[seq]
        if event.get("op") != "run":
            return f"seq={seq} is not a 'run' event (op={event.get('op')!r})"
        event_unit = (event.get("args") or {}).get("unit")
        event_action = (event.get("args") or {}).get("action")
        if unit != event_unit:
            return f"unit={unit!r} does not match event unit={event_unit!r}"
        if action != event_action:
            return f"action={action!r} does not match event action={event_action!r}"

    elif kind == "relation_exists":
        ep_a = proposal.get("endpoint_a")
        ep_b = proposal.get("endpoint_b")
        if not isinstance(ep_a, str) or ":" not in ep_a:
            return f"endpoint_a={ep_a!r} is not a valid app:endpoint string"
        if not isinstance(ep_b, str) or ":" not in ep_b:
            return f"endpoint_b={ep_b!r} is not a valid app:endpoint string"

    return None


def _proposal_to_tag_dict(proposal: dict[str, Any]) -> dict[str, Any]:
    """Convert a validated proposal to an AssertionTag-compatible dict."""
    kind = proposal["kind"]
    base: dict[str, Any] = {"kind": kind, "source": "llm", "strict": False}

    if kind == "unit_status":
        return {
            **base,
            "app": proposal["app"],
            "unit": proposal["unit"],
            "expected": proposal["expected"],
        }
    elif kind == "unit_count":
        return {**base, "app": proposal["app"], "expected": proposal["expected"]}
    elif kind == "action_result":
        return {
            **base,
            "unit": proposal["unit"],
            "action": proposal["action"],
            "expected_success": proposal.get("expected_success", True),
            "expected_results": proposal.get("expected_results") or {},
        }
    elif kind == "relation_exists":
        ep_a, ep_b = sorted([proposal["endpoint_a"], proposal["endpoint_b"]])
        return {**base, "endpoint_a": ep_a, "endpoint_b": ep_b}
    else:
        return base  # unreachable after validation


def llm_augment(log: SessionLog, proposer: AssertionProposer) -> SessionLog:
    """Run *proposer* over *log* and merge valid proposals into event assertions.

    This function assumes *log* has already passed through the deterministic
    tagger (engine.tag()). It runs the proposer, validates each proposal
    against the session log contents, deduplicates against existing assertions,
    and inserts valid new assertions with source="llm".

    The input log is not mutated; a deep copy is returned.
    """
    proposals = proposer.propose(log)
    if not proposals:
        return log  # nothing to do — skip the copy

    out = copy.deepcopy(log)
    events: list[dict[str, Any]] = out.get("events") or []
    seq_to_event: dict[int, dict[str, Any]] = {
        e["seq"]: e for e in events if isinstance(e.get("seq"), int)
    }
    known_apps, known_units = _collect_known_entities(log)

    for proposal in proposals:
        if not isinstance(proposal, dict):
            warnings.warn(
                f"LLM proposal is not a dict: {proposal!r} — dropped",
                stacklevel=2,
            )
            continue

        error = _validate_proposal(proposal, seq_to_event, known_apps, known_units)
        if error is not None:
            warnings.warn(
                f"LLM proposal dropped ({error}): {proposal!r}",
                stacklevel=2,
            )
            continue

        event = seq_to_event[proposal["seq"]]
        if "assertions" not in event or event["assertions"] is None:
            event["assertions"] = []

        # Deduplicate: skip if an assertion with the same identity already exists.
        ident = _identity(proposal)
        existing_identities = {_identity(a) for a in event["assertions"] if isinstance(a, dict)}
        if ident in existing_identities:
            continue

        event["assertions"].append(_proposal_to_tag_dict(proposal))

    return out
