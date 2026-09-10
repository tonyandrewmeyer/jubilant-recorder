"""Guard: no committed recording may carry a real credential.

Recordings are captured from live Juju models, so an unredacted secret can
walk into the repository attached to an otherwise ordinary session. That
happened once — a charm-generated PostgreSQL password reached
``postgresql_config_action.jsonl`` because redaction was applied to
operation *args* but never to *results*. This test fails the build rather
than the review.

It covers every committed session log, not just the ones under
``tests/fixtures``: ``examples/`` holds live recordings too, and a secret
does not care which directory it landed in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDING_DIRS = [REPO_ROOT / "tests" / "fixtures", REPO_ROOT / "examples"]

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
    # The key set `jubilant_recorder.redaction` itself treats as sensitive.
    # `credential` was missing here and present there, which is how a
    # controller password in an `Admin.Login` payload got past this guard.
    (
        "json-credential",
        re.compile(r'"[^"]*credential[^"]*"\s*:\s*"(?!<redacted:)[^"]+"', re.IGNORECASE),
    ),
    (
        "json-secret",
        re.compile(r'"[^"]*secret[^"]*"\s*:\s*"(?!<redacted:)[^"]+"', re.IGNORECASE),
    ),
    ("bearer", re.compile(r"Authorization:\s*Bearer\s+(?!<redacted:)\S", re.IGNORECASE)),
]


def _recording_files() -> list[Path]:
    return sorted(
        path
        for directory in RECORDING_DIRS
        for path in directory.rglob("*")
        if path.suffix in {".json", ".jsonl"}
    )


def test_recordings_exist():
    """Guard against the guard silently passing on an empty glob."""
    assert _recording_files(), f"no recordings found under {RECORDING_DIRS}"


def test_every_recording_directory_is_covered():
    """A new home for committed recordings must be added to RECORDING_DIRS."""
    for directory in RECORDING_DIRS:
        assert directory.is_dir(), f"{directory} does not exist"


@pytest.mark.parametrize("path", _recording_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_recording_contains_no_credentials(path: Path):
    text = path.read_text()
    for label, pattern in CREDENTIAL_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"{path.relative_to(REPO_ROOT)} matches {label!r}: "
            f"{match.group(0)[:80]!r}. Scrub it, or if this is a false positive, "
            f"narrow the pattern in {Path(__file__).name}."
        )
