# Secrets facade — libjuju → jubilant gaps

Documented during carry (c): `Secrets.*` bucket-2 → bucket-1 promotion.

## Gap: `Secrets.RevokeSecret` — no jubilant 1.10 equivalent

**libjuju method:** `Secrets.RevokeSecret`

**jubilant 1.10 API:** jubilant does not expose a `revoke_secret()` method.
The CLI command `juju revoke-secret` exists but is not wrapped by jubilant
in the 1.10 release.

**Current handling:** `Secrets.RevokeSecret` remains in **bucket-2**.
The correlator emits it as `op: "shell"` with the facade/method recorded in
`args.command` for the human reviewer.  Codegen renders a `# TODO: manual step`
comment via the fallback path.

**Resolution:** When jubilant adds `revoke_secret()`, promote this RPC to
bucket-1 by:

1. Moving `("Secrets", "RevokeSecret")` from `_BUCKET2_FACADES` to
   `_BUCKET1_MAP` in `extensions/libjuju/correlate.py` with op name
   `"secret_revoke"`.
2. Adding `_extract_args` handling for the `GrantRevokeSecretArg` params
   (same shape as `GrantSecret`: `uri`, `scope-tag`, `applications`).
3. Adding `src/jubilant_recorder/codegen/operations/secret_revoke.py`
   that emits `juju.revoke_secret(identifier, app)`.
4. Registering `"secret_revoke": secret_revoke.emit` in
   `src/jubilant_recorder/codegen/operations/__init__.py`.
5. Removing this entry from SECRETS-GAPS.md.
