# Step 2 Starter: libjuju call-site corpus analysis

**Target repo:** `canonical/operator` (the ops library integration-test suite)
**Branch inspected:** `main` (SHA at clone time, June 2026)
**Files read:**

| File | Tests |
|---|---|
| `test/integration/test_relation.py` | 1 |
| `test/integration/test_secrets.py` | 3 + 3 fixtures |
| `test/integration/test_tracing.py` | 2 + conftest tracing setup |
| `test/integration/test_hookcmds.py` | 30+ |
| `examples/k8s-3-postgresql/tests/integration/test_charm.py` | 2 |

---

## Key finding: operator has already migrated to jubilant

**`canonical/operator` no longer uses libjuju for integration tests.**
`pyproject.toml` declares `integration = ["jubilant~=1.5", "jubilant-backports", ...]`
with no libjuju dependency. Every call site in every test file calls
`jubilant.Juju` methods — there is no `Connection.rpc` to tap.

This is the primary result of the step-2 corpus pass: **the planned target has
vacated the use case.** The rest of this document reframes the analysis to answer
the question that still matters: _would the libjuju extension have been useful
before (or during) that migration, and is it still useful for charm repos that
haven't migrated yet?_

---

## Reverse-proxy analysis: jubilant → libjuju bucket mapping

Since jubilant is the canonical replacement for libjuju, each jubilant call
corresponds to one or more libjuju façade RPC calls. We can classify call
sites by how well our tap + correlator would have captured the equivalent
libjuju call.

### Bucket taxonomy

| Bucket | Meaning |
|---|---|
| 1 | Clean: one jubilant call ↔ one libjuju RPC; tap captures it fully |
| 2 | Lossy/decomposed: jubilant call uses multiple RPCs or CLI commands; tap can emit `op: "shell"` with a note |
| 3 | No mapping: operation has no libjuju RPC equivalent (pure CLI or internal Juju mechanism) |

### Per-file tally

#### `test_relation.py` (1 test)

| Call site | jubilant method | libjuju equivalent | Bucket |
|---|---|---|---|
| L28 | `deploy(charm_path)` | `Application.Deploy` | 1 |
| L30 | `add_unit(charm_name, num_units=2)` | `Application.AddUnits` | 1 |
| L35 | `deploy('any-charm', db, num_units=3, ...)` | `Application.Deploy` | 1 |
| L41 | `integrate(f'{charm_name}:db', db)` | `Application.AddRelation` | 1 |
| L45 | `deploy('any-charm', ingress, num_units=2, ...)` | `Application.Deploy` | 1 |
| L49 | `integrate(f'{charm_name}:ingress', ingress)` | `Application.AddRelation` | 1 |
| L53 | `wait(jubilant.all_active)` | AllWatcher.Next + Client.FullStatus loop | 1 |
| L56 | `status()` | `Client.Status` | 1 |
| L61 | `run(f'{charm_name}/0', 'get-units')` | `Action.EnqueueOperation` | 1 |

**9 bucket-1 / 0 bucket-2 / 0 bucket-3**

#### `test_secrets.py` (3 tests + 3 fixtures)

| Call site | jubilant method | libjuju equivalent | Bucket |
|---|---|---|---|
| L29 | `deploy(charm_path, num_units=2)` | `Application.Deploy` | 1 |
| L30 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |
| L34 | `run(leader, 'add-secret')` | `Action.EnqueueOperation` | 1 |
| L37 | `secrets()` | `Secrets.ListSecrets` (libjuju 3.x façade) | 2 |
| L38 | `show_secret(uri, reveal=True)` | `Secrets.GetSecretContentInfo` | 2 |
| L59 | `run(leader, 'add-with-meta', ...)` | `Action.EnqueueOperation` | 1 |
| L68 | `secrets()` | `Secrets.ListSecrets` | 2 |
| L69 | `show_secret(...)` | `Secrets.GetSecretContentInfo` | 2 |
| L110 | `status().model.version` | `Client.Status` | 1 |
| L118 | `run(leader, 'set-secret-flow', ...)` | `Action.EnqueueOperation` | 1 |
| L127 | `secrets()` | `Secrets.ListSecrets` | 2 |
| L128 | `show_secret(...)` | `Secrets.GetSecretContentInfo` | 2 |
| L159 | `exec(f'secret-remove ...', unit=...)` | `Client.RunOnAllMachines` | 2 |
| L162 | `remove_secret(uri)` | `Secrets.DeleteSecrets` | 2 |
| L168 | `exec('secret-add ...', unit=...)` | `Client.RunOnAllMachines` | 2 |
| L169 | `secrets()` | `Secrets.ListSecrets` | 2 |

**6 bucket-1 / 10 bucket-2 / 0 bucket-3**

_Note:_ `Secrets.*` façades do exist in libjuju (added in Juju 3.x), so these
are bucket 2 (capturable but with schema differences) rather than bucket 3.
`juju.exec()` maps to `Client.RunOnAllMachines` which is capturable, but the
command string is opaque — hence bucket 2.

#### `test_tracing.py` (2 tests + conftest fixture)

| Call site | jubilant method | libjuju equivalent | Bucket |
|---|---|---|---|
| L32 | `deploy(charm_path)` | `Application.Deploy` | 1 |
| L33 | `integrate('test-tracing', 'tempo')` | `Application.AddRelation` | 1 |
| L34 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |
| L44 | `run('test-tracing/0', 'one', ...)` | `Action.EnqueueOperation` | 1 |
| L60 | `deploy('self-signed-certificates')` | `Application.Deploy` | 1 |
| L61 | `integrate('tempo:certificates', ...)` | `Application.AddRelation` | 1 |
| L62 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |
| L64 | `deploy(charm_path)` | `Application.Deploy` | 1 |
| L65 | `integrate('test-tracing', ...)` | `Application.AddRelation` | 1 |
| L66 | `integrate('test-tracing', 'tempo')` | `Application.AddRelation` | 1 |
| L67 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |
| conftest L43 | `deploy('minio', ...)` | `Application.Deploy` | 1 |
| conftest L44 | `deploy('s3-integrator')` | `Application.Deploy` | 1 |
| conftest L46 | `integrate('tempo:s3', ...)` | `Application.AddRelation` | 1 |
| conftest L47 | `integrate('tempo:tempo-cluster', ...)` | `Application.AddRelation` | 1 |
| conftest L49 | `wait(...)` | AllWatcher.Next loop | 1 |
| conftest L54 | `status().apps['minio'].address` | `Client.Status` | 1 |
| conftest L66 | `config('s3-integrator', {...})` | `Application.SetConfigs` | 1 |
| conftest L67 | `run('s3-integrator/0', ...)` | `Action.EnqueueOperation` | 1 |
| conftest L81 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |

**20 bucket-1 / 0 bucket-2 / 0 bucket-3**

#### `test_hookcmds.py` (30+ tests)

This file drives almost all behaviour through `juju.run(unit, action, params)`.
I enumerate distinct call-site patterns rather than each parametrized invocation.

| Pattern | jubilant method | libjuju equivalent | Bucket | Count |
|---|---|---|---|---|
| setup | `deploy(charm_path, num_units=2, resources=..., trust=True)` | `Application.Deploy` | 1 | 1 |
| setup | `deploy('any-charm', channel='latest/beta')` | `Application.Deploy` | 1 | 1 |
| setup | `integrate('test-hookcmds:anycharm', 'any-charm')` | `Application.AddRelation` | 1 | 1 |
| setup | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 | 1 |
| all tests | `run(unit, action)` | `Action.EnqueueOperation` | 1 | ~30 |
| all tests | `run(unit, action, params={...})` | `Action.EnqueueOperation` | 1 | ~10 |
| multiple | `status()` via `_juju_major()` / `_is_k8s()` | `Client.Status` | 1 | ~8 |
| test_app_version_set | `status().apps[...].version` | `Client.Status` | 1 | 1 |
| test_juju_reboot | `config('test-hookcmds', {...})` | `Application.SetConfigs` | 1 | 1 |
| test_juju_reboot | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 | 1 |
| test_storage_add | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 | 1 |
| test_secret_full_lifecycle | `secrets()` | `Secrets.ListSecrets` | 2 | 1 |
| test_secret_grant_revoke | `secrets()` | `Secrets.ListSecrets` | 2 | 1 |

**~57 bucket-1 / 2 bucket-2 / 0 bucket-3**

#### `examples/k8s-3-postgresql/test_charm.py` (2 tests)

| Call site | jubilant method | libjuju equivalent | Bucket |
|---|---|---|---|
| L45 | `deploy(charm, app=APP_NAME, resources=...)` | `Application.Deploy` | 1 |
| L46 | `wait(jubilant.all_blocked)` | AllWatcher.Next loop | 1 |
| L55 | `deploy("postgresql-k8s", channel="14/stable", trust=True)` | `Application.Deploy` | 1 |
| L56 | `integrate(APP_NAME, "postgresql-k8s")` | `Application.AddRelation` | 1 |
| L57 | `wait(jubilant.all_active)` | AllWatcher.Next loop | 1 |

**5 bucket-1 / 0 bucket-2 / 0 bucket-3**

---

## Grand tally

| File | Bucket 1 | Bucket 2 | Bucket 3 | Total |
|---|---|---|---|---|
| test_relation.py | 9 | 0 | 0 | 9 |
| test_secrets.py | 6 | 10 | 0 | 16 |
| test_tracing.py | 20 | 0 | 0 | 20 |
| test_hookcmds.py | ~57 | 2 | 0 | ~59 |
| k8s-3-postgresql/test_charm.py | 5 | 0 | 0 | 5 |
| **Total** | **~97 (89%)** | **~12 (11%)** | **0 (0%)** | **~109** |

---

## Finding and recommendation

Across 5 files with ~109 call sites, the distribution was **~97 bucket-1 (89%) /
~12 bucket-2 (11%) / 0 bucket-3 (0%)**.

However, the headline finding is that **`canonical/operator` has already migrated
all integration tests from libjuju to jubilant** (via `jubilant~=1.5` in
`pyproject.toml`). The operator is not a target corpus for the libjuju
extension; it is evidence that migration is both achievable and the direction of
travel for Canonical charm repos.

The 89% bucket-1 figure is reassuring: it confirms that the dominant test
operations (deploy, integrate, wait, run, status, config) all have clean
libjuju ↔ jubilant mappings. The 11% bucket-2 items are secrets-related RPCs
(`Secrets.ListSecrets`, `Secrets.GetSecretContentInfo`) and raw exec calls —
all capturable as `op: "shell"` with a note, not total losses.

**Recommendation: proceed, but retarget the corpus.**

The libjuju extension is technically sound (request-ID capture confirmed,
AllWatcher hook point confirmed, 36 tests green). The value case remains: charm
repos that have NOT yet migrated to jubilant still exist
(e.g. `canonical/juju-backup-all`, older cloud-specific operators). Before Step
3, identify 2–3 concrete repos that still import `python-libjuju` in their
integration-test dependencies and run this analysis against those files. If
bucket-1 stays above 75% there, proceed to Step 3 (correlator wiring into a
recording pass). If the target list is empty — all Canonical charm repos have
migrated — abandon the libjuju extension and archive this subtree as a PoC.
