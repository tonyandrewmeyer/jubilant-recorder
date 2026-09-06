"""Redaction of sensitive values from telemetry payloads.

Applied at adapter time.  Replaces matched
substrings with <redacted:<class>> sentinels and never strips surrounding
context, so downstream consumers still see that e.g. a curl ran — just
not the credential it carried.
"""

from __future__ import annotations

import re
from typing import Any, cast

# Rules ordered from most specific to least.  Each entry is
# (compiled_pattern, sentinel_label).
_RULES: list[tuple[re.Pattern[str], str]] = [
    # "Authorization: Bearer <token>" — HTTP header in args or log lines
    (
        re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
        "bearer",
    ),
    # URL with embedded credentials: scheme://user:pass@host/…
    # Any scheme, not just http(s): connection strings for postgresql,
    # mysql, redis, amqp and friends are exactly where charm action
    # results hand back credentials.
    (
        re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"),
        "url-credentials",
    ),
    # Query-string / CLI-flag form: password=VALUE  (case-insensitive key)
    (
        re.compile(r"(?i)password=[^&\s]+"),
        "password",
    ),
    # Query-string / CLI-flag form: token=VALUE
    (
        re.compile(r"(?i)token=[^&\s]+"),
        "token",
    ),
]

_CONFIG_KEY_PATTERN = re.compile(r"(?i)(password|token|secret|key|credential|cert)")


def redact_string(value: str) -> tuple[str, bool]:
    """Apply all redaction rules to *value*.

    Returns ``(result, was_redacted)``; result may equal value if nothing matched.
    """
    changed = False
    for pattern, label in _RULES:
        new_value, n = pattern.subn(f"<redacted:{label}>", value)
        if n:
            changed = True
            value = new_value
    return value, changed


def redact_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Recursively redact sensitive values anywhere in *payload*.

    Walks nested dicts and lists to any depth, applying both key-based
    redaction (a key like ``password`` blanks its string value outright,
    as in :func:`redact_config_dict`) and the pattern rules to every
    string.  Operation *results* — action output, relation data, status
    payloads — are where credentials actually surface, and they are
    deeply nested, so a top-level-only pass is not enough.

    Returns ``(redacted_payload, any_redacted)``.  The original is not mutated.
    """
    result, changed = _redact_value(payload, None)
    return cast("dict[str, Any]", result), changed


def _redact_value(value: Any, key: str | None) -> tuple[Any, bool]:
    """Redact *value*, which arrived under dict key *key* (None at the root)."""
    if isinstance(value, dict):
        any_redacted = False
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[k], changed = _redact_value(v, k)
            any_redacted = any_redacted or changed
        return out, any_redacted
    if isinstance(value, list):
        any_redacted = False
        items: list[Any] = []
        for item in value:
            # Carry the key down: {"uris": [...]} should redact its members.
            new_item, changed = _redact_value(item, key)
            items.append(new_item)
            any_redacted = any_redacted or changed
        return items, any_redacted
    if isinstance(value, str):
        if key is not None:
            m = _CONFIG_KEY_PATTERN.search(key)
            if m:
                return f"<redacted:{m.group(1).lower()}>", True
        return redact_string(value)
    return value, False


def redact_config_dict(values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Redact config values whose key matches sensitive patterns.

    Keys matching ``(?i)(password|token|secret|key|credential|cert)`` have their
    string value replaced with ``"<redacted:<matched_group>>"``.  Non-matching
    keys have ``redact_string`` applied to string values.  Non-string values
    are passed through unchanged.

    Returns ``(redacted_dict, any_redacted)``.  The original dict is not mutated.
    """
    any_redacted = False
    result: dict[str, Any] = {}
    for key, value in values.items():
        m = _CONFIG_KEY_PATTERN.search(key)
        if m and isinstance(value, str):
            result[key] = f"<redacted:{m.group(1).lower()}>"
            any_redacted = True
        elif isinstance(value, str):
            new_val, changed = redact_string(value)
            result[key] = new_val
            any_redacted = any_redacted or changed
        else:
            result[key] = value
    return result, any_redacted
