# Secrets facade — libjuju → jubilant gaps

Documented during carry (c): `Secrets.*` bucket-2 → bucket-1 promotion.

## Closed 2026-08-18: `Secrets.RevokeSecret` is bucket-1

**libjuju method:** `Secrets.RevokeSecret`

**jubilant API:** jubilant still does not expose a `revoke_secret()` method
— checked at **1.12.0**, not just the 1.10 this document was originally
written against. The surface is `add_secret`, `grant_secret`,
`remove_secret`, `secrets`, `show_secret`, `update_secret`.

**Why this is no longer a blocker.** The original resolution condition below
("when jubilant adds `revoke_secret()`") was written before the project
adopted `juju.cli()` as the answer to "jubilant has no client method" — on
2026-07-21 for the 4 CMR ops and on 2026-07-24 for the 8 `Application.*`
ops. `Juju.cli()` is a public escape hatch (`jubilant/_juju.py:527`) already
used by jubilant's own `bootstrap()`. Under that precedent this RPC's gap
was never the kind that requires waiting.

Worth recording, because it is the reason this sat here as long as it did:
`Secrets.RevokeSecret` became the test suite's canonical bucket-2 example
*because* `SetCharm` was promoted out via the escape hatch — it inherited
its status from an op that the current rule would not have left in bucket 2
either.

**Current handling:** bucket-1, op name `secret_revoke`, emitted as
`juju.cli("revoke-secret", <identifier>, <app>)` by
`src/jubilant_recorder/codegen/operations/secret_revoke.py`.
`juju revoke-secret [options] <ID>|<name> <application>[,<application>...]`
was verified against `juju 3.6.27` rather than assumed — the `SetCharm`
lesson (its naive mapping `juju set-charm` is not a real subcommand in
modern Juju; the target is `juju refresh --switch`).

**Known limitation, inherited from `secret_grant`:** the extractor takes the
first entry of the RPC's `applications` list, so a multi-application revoke
records only its first target. The CLI accepts a comma-joined list, so this
is a correlator-side narrowing, not a CLI one.

**Remaining future simplification (not a blocker).** If jubilant later grows
a typed `revoke_secret()`, swap the `juju.cli(...)` call in
`operations/secret_revoke.py` for it — the same note already attached to the
CMR ops in `operations/__init__.py`. Nothing else changes: the correlator
mapping, op name, and extracted args stay as they are.

## Bucket 2 is now empty on this surface

With this promotion and `ApplicationOffers.FindApplicationOffers`'s,
`correlate.py`'s `_BUCKET2_FACADES` is empty by design. That is the correct
end state for the RPC surface rather than a collapsed taxonomy — see the
set's own comment, and
`canonical-work-queue non-roadmap/jubilant-test-recorder/BUCKET2-EMPTY-DESIGN.md`
for the full reasoning and the rule that keeps the escape hatch from being
over-applied. The bucket-2 branch stays live and is exercised by a synthetic
member (`extensions/libjuju/tests/conftest.py`).
