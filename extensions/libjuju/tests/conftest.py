"""Shared fixtures for the libjuju extension tests.

``_BUCKET2_FACADES`` is empty as of 2026-08-18 — its last two members,
``Secrets.RevokeSecret`` and ``ApplicationOffers.FindApplicationOffers``,
were promoted to bucket 1 via ``juju.cli()`` emitters.  That is the correct
end state for the RPC surface (see the set's own comment in
``correlate.py``), but it leaves the bucket-2 branch with no real member to
exercise it, and the branch must not rot: any future facade with genuinely
unreconstructable arguments still lands there.

``bucket2_facade`` supplies a synthetic member for exactly that purpose.
Tests that are *about* bucket-2 behaviour in general (the ``shell`` op, the
``note`` field, ``args.command`` capture, duration recording, codegen's
fallback rendering) use this instead of naming a real RPC — which also means
they no longer break when a real RPC is promoted out, the way twelve tests
did in this change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from extensions.libjuju import correlate

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A facade/method pair that does not exist in Juju, deliberately: nothing
#: should ever be tempted to give it a real mapping.
SYNTHETIC_BUCKET2 = ("SyntheticFacade", "UnmappableMethod")


@pytest.fixture
def bucket2_facade(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    """Pin one synthetic member into ``_BUCKET2_FACADES`` for the test's life."""
    monkeypatch.setattr(
        correlate,
        "_BUCKET2_FACADES",
        frozenset({SYNTHETIC_BUCKET2}),
    )
    yield SYNTHETIC_BUCKET2
