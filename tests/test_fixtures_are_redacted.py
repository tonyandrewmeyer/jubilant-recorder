"""Guard: no committed fixture may carry a real credential.

Fixtures are captured from live Juju models, so an unredacted secret can
walk into the repository attached to an otherwise ordinary recording. That
happened once — a charm-generated PostgreSQL password reached
``postgresql_config_action.jsonl`` because redaction was applied to
operation *args* but never to *results*. This test fails the build rather
than the review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Patterns that indicate a live credential rather than a redaction sentinel.
# Each must not match "<redacted:...>", which is what a scrubbed value becomes.
CREDENTIAL_PATTERNS = [
    # scheme://user:pass@host — connection strings of any scheme.
    (
        "url-credentials",
        re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/:@\"]+:(?!//)[^\s/@\"]+@"),
    ),
    # "password": "value" as a JSON member, unless already redacted.
    (
        "json-password",
        re.compile(r'"[^"]*password[^"]*"\s*:\s*"(?!<redacted:)[^"]+"', re.IGNORECASE),
    ),
    (
        "json-token",
        re.compile(r'"[^"]*token[^"]*"\s*:\s*"(?!<redacted:)[^"]+"', re.IGNORECASE),
    ),
    ("bearer", re.compile(r"Authorization:\s*Bearer\s+(?!<redacted:)\S", re.IGNORECASE)),
]


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES_DIR.rglob("*") if p.suffix in {".json", ".jsonl"})


def test_fixtures_exist():
    """Guard against the guard silently passing on an empty glob."""
    assert _fixture_files(), f"no fixtures found under {FIXTURES_DIR}"


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_contains_no_credentials(path: Path):
    text = path.read_text()
    for label, pattern in CREDENTIAL_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"{path.relative_to(FIXTURES_DIR.parent.parent)} matches {label!r}: "
            f"{match.group(0)[:80]!r}. Scrub it, or if this is a false positive, "
            f"narrow the pattern in {Path(__file__).name}."
        )
