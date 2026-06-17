"""Redaction of sensitive values from telemetry payloads.

Applied at adapter time per SCHEMA.md §Redaction.  Replaces matched
substrings with <redacted:<class>> sentinels and never strips surrounding
context, so downstream consumers still see that e.g. a curl ran — just
not the credential it carried.
"""

from __future__ import annotations

import re
from typing import Any

# Rules ordered from most specific to least.  Each entry is
# (compiled_pattern, sentinel_label).
_RULES: list[tuple[re.Pattern[str], str]] = [
    # "Authorization: Bearer <token>" — HTTP header in args or log lines
    (
        re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
        "bearer",
    ),
    # URL with embedded credentials: https://user:pass@host/…
    (
        re.compile(r"https?://[^\s/:@]+:[^\s/@]+@"),
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
    """Apply redaction to every string (and list-of-string) value in *payload*.

    Returns ``(redacted_payload, any_redacted)``.  The original dict is not
    mutated.
    """
    any_redacted = False
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            new_val, changed = redact_string(value)
            result[key] = new_val
            any_redacted = any_redacted or changed
        elif isinstance(value, list):
            new_list: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    new_item, changed = redact_string(item)
                    new_list.append(new_item)
                    any_redacted = any_redacted or changed
                else:
                    new_list.append(item)
            result[key] = new_list
        else:
            result[key] = value
    return result, any_redacted


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
