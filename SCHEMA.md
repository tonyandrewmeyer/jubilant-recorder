# Session Log — JSON schema

*Work-breakdown item #2. Defines the contract before the recorder is written.*
*Designed: 2026-05-30.*

The session log is a single JSON file written by layer (A) (the recorder) and
consumed by layers (B) (assertion inference) and (C) (codegen). It is the
**ground truth** of a recording session — everything that happened, in order,
with model state captured before and after each operation.

Keeping the schema stable and explicit here means (B) and (C) can be developed,
tested, and iterated on against saved logs without running a live Juju model.

---

## Top-level session document

```json
{
  "schema_version": 1,
  "session_id": "0193fc4e-9c3d-7000-8000-1a2b3c4d5e6f",
  "recorded_at": "2026-05-30T09:00:00Z",
  "juju_version": "3.6.23",
  "jubilant_version": "0.3.0",
  "model": "my-model",
  "events": [ ... ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | integer | ✓ | Format version for this file. `1` for this spec. Consumers MUST fail fast if the value is unknown. |
| `session_id` | string (UUIDv7) | ✓ | Unique per recording session. UUIDv7 (time-ordered) so sessions sort chronologically in directory listings. Used as the default filename stem: `session-<session_id>.json`. |
| `recorded_at` | string (RFC 3339 UTC) | ✓ | Timestamp when the session log was finalised and written (i.e. when `jubilant-record stop` completed or the `run` wrapper exited). |
| `juju_version` | string | ✓ | Output of `juju version` at session start. Needed so codegen can emit version-appropriate API calls and so readers can contextualise behaviour differences. |
| `jubilant_version` | string | ✓ | Version of the jubilant package in use. The recorder wraps jubilant; API surface and return-value shapes vary by release. |
| `model` | string | ✓ | Juju model name the session operated against. Recorded for the generated test's fixture docstring and to provide context when `model_snapshot` fields reference apps by name. |
| `events` | array | ✓ | Ordered sequence of event envelopes. May be empty for a session with no jubilant calls. See §"Event envelope". |

---

## Event envelope

Each element of `events` follows this shape:

```json
{
  "seq": 7,
  "op": "deploy",
  "ts": "2026-05-30T09:00:05.123Z",
  "args": { ... },
  "result": { ... },
  "model_snapshot_before": { ... },
  "model_snapshot_after": { ... },
  "assertions": [ ... ],
  "gesture": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `seq` | integer (uint64) | ✓ | Monotonically increasing, starting at 1. No gaps in a valid session log. A gap indicates truncation or corruption. |
| `op` | string | ✓ | Operation name. Closed set — see §"Op taxonomy". |
| `ts` | string (RFC 3339 UTC, ms precision) | ✓ | Wall-clock time at the start of the operation (before the juju CLI call is made). Millisecond precision is sufficient and keeps the log readable. |
| `args` | object | ✓ | Op-specific input arguments. Shape depends on `op` — see §"Op taxonomy". Never null; use `{}` for ops with no arguments (e.g. `status`). |
| `result` | object | ✓ | Op-specific return values. Shape depends on `op` — see §"Op taxonomy". Never null; use `{}` for ops with no meaningful return value. |
| `model_snapshot_before` | object \| null | ✓ | Lightweight model snapshot taken immediately before the operation. Null only for the very first event if a pre-session snapshot fails. See §"Model snapshot (lightweight)". |
| `model_snapshot_after` | object \| null | ✓ | Lightweight model snapshot taken immediately after the operation completes. Null if the operation raised an exception (e.g. CLI error). See §"Model snapshot (lightweight)". |
| `assertions` | array | ✓ | Assertion tags emitted by layer (B). Empty array when the session log is freshly written by layer (A); populated when (B) annotates the log. See §"Assertion tag shape". |
| `gesture` | object \| null | ✓ | Non-null when the user made an explicit assertion or checkpoint call during recording. See §"Gesture shape". Null for ordinary jubilant operations with no explicit annotation. |

---

## Op taxonomy

The `op` field is a closed set corresponding to jubilant's public API surface
(plus `shell` for non-jubilant operations the user runs during a session).

### Summary table

| Op | jubilant method | Args (non-null keys) | Result (non-null keys) |
|---|---|---|---|
| `deploy` | `Juju.deploy()` | `charm`, `app`, `channel`, `num_units`, `config`, `resources` | `app_name` |
| `integrate` | `Juju.integrate()` | `app1_endpoint`, `app2_endpoint` | — |
| `remove_integration` | `Juju.remove_integration()` | `app1_endpoint`, `app2_endpoint` | — |
| `config` | `Juju.config()` (set path) | `app`, `values` | — |
| `config_get` | `Juju.config()` (get path) | `app`, `keys` | `values` |
| `scale` | `Juju.scale()` | `app`, `units` | — |
| `run` | `Juju.run()` | `unit`, `action`, `params` | `success`, `results`, `message` |
| `status` | `Juju.status()` | — | `snapshot` |
| `wait_for_idle` | `Juju.wait_for_idle()` | `apps`, `timeout` | `settled_at` |
| `remove_application` | `Juju.remove_application()` | `app` | — |
| `shell` | (non-jubilant) | `command`, `cwd` | `returncode`, `stdout`, `stderr`, `captured` |

### `deploy`

```json
{
  "args": {
    "charm": "my-charm",
    "app": "my-charm",
    "channel": "edge",
    "num_units": 1,
    "config": {"log-level": "debug"},
    "resources": {}
  },
  "result": {
    "app_name": "my-charm"
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `charm` | args | string | Charm name or local path as passed to `juju deploy`. |
| `app` | args | string \| null | Application name override (`--name`). Null if the caller did not specify (jubilant defaults to the charm name). |
| `channel` | args | string \| null | Channel string e.g. `"edge"`, `"14/stable"`. Null if not specified. |
| `num_units` | args | integer \| null | Requested unit count. Null if not specified (juju default is 1). |
| `config` | args | object | Key/value config options. Empty object `{}` if none. |
| `resources` | args | object | Resource name → path or revision. Empty object `{}` if none. |
| `app_name` | result | string | The application name as registered in the model (may differ from `args.app` if the model already had a name collision). |

### `integrate`

```json
{
  "args": {
    "app1_endpoint": "my-charm:db",
    "app2_endpoint": "postgresql:database"
  },
  "result": {}
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `app1_endpoint` | args | string | `<app>:<endpoint>` format, or bare `<app>` if jubilant infers the endpoint. |
| `app2_endpoint` | args | string | Same. |

### `remove_integration`

Same args shape as `integrate`; empty result.

### `config` (set)

```json
{
  "args": {
    "app": "my-charm",
    "values": {"log-level": "info", "debug": true}
  },
  "result": {}
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `app` | args | string | Application name. |
| `values` | args | object | Config keys to set, with their new values. Value types follow the charm config schema (string, int, bool, float). |

### `config_get`

```json
{
  "args": {
    "app": "my-charm",
    "keys": ["log-level", "debug"]
  },
  "result": {
    "values": {"log-level": "info", "debug": true}
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `app` | args | string | Application name. |
| `keys` | args | array of string \| null | Specific keys requested. Null means all config keys were requested. |
| `values` | result | object | Key/value pairs returned by jubilant. |

### `scale`

```json
{
  "args": {
    "app": "my-charm",
    "units": 3
  },
  "result": {}
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `app` | args | string | Application name. |
| `units` | args | integer | Target unit count. |

### `run`

```json
{
  "args": {
    "unit": "my-charm/0",
    "action": "do-thing",
    "params": {"key": "val"}
  },
  "result": {
    "success": true,
    "results": {"output": "done", "return-code": "0"},
    "message": null
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `unit` | args | string | Unit name `<app>/<n>`. |
| `action` | args | string | Action name. |
| `params` | args | object | Action parameters. Empty object `{}` if none. |
| `success` | result | boolean | True if the action returned `success: true`. |
| `results` | result | object | Action result key/value map. Empty object `{}` if none. |
| `message` | result | string \| null | Action message string. Null if absent. |

### `status`

```json
{
  "args": {},
  "result": {
    "snapshot": { ... }
  }
}
```

`result.snapshot` is an inline lightweight model snapshot (§"Model snapshot").
This is the only op where the result *contains* a snapshot rather than having
one as `model_snapshot_after`. Both are present and should be identical; layer
(B) uses `model_snapshot_after` for consistency across all ops.

### `wait_for_idle`

```json
{
  "args": {
    "apps": ["my-charm", "postgresql"],
    "timeout": 300
  },
  "result": {
    "settled_at": "2026-05-30T09:02:47.850Z"
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `apps` | args | array of string \| null | Apps to wait for. Null means all apps in the model (jubilant default). |
| `timeout` | args | number \| null | Timeout in seconds. Null if caller used jubilant's default. |
| `settled_at` | result | string (RFC 3339 UTC, ms) | Timestamp when `wait_for_idle` returned successfully. Absent (key still present as null) if the wait timed out — in that case the event's `result.error` field carries the timeout message. |

When `wait_for_idle` times out or raises, `model_snapshot_after` captures the
model state at the point of failure. This is intentional: codegen uses the
after-snapshot to determine whether a `wait_for_idle` assertion is appropriate
for the generated test.

### `remove_application`

```json
{
  "args": {
    "app": "my-charm"
  },
  "result": {}
}
```

### `shell`

Records non-jubilant shell commands the user ran during the session. Captured
only when `jubilant-record` is started with `--include-shell`; otherwise the
event is recorded as a stub with `captured: false`.

```json
{
  "args": {
    "command": ["juju", "ssh", "my-charm/0", "cat /var/log/syslog"],
    "cwd": "/home/user/my-project"
  },
  "result": {
    "captured": true,
    "returncode": 0,
    "stdout": "May 30 09:03:12 ...",
    "stderr": ""
  }
}
```

Stub shape (default, no `--include-shell`):

```json
{
  "args": {
    "command": ["juju", "ssh", "my-charm/0", "cat /var/log/syslog"],
    "cwd": null
  },
  "result": {
    "captured": false,
    "returncode": null,
    "stdout": null,
    "stderr": null
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `command` | args | array of string | Full argv as a list. |
| `cwd` | args | string \| null | Working directory at time of the call. Null in the stub. |
| `captured` | result | boolean | False means the shell op was noted but output was not recorded. Codegen emits a `# TODO: manual step` for these. |
| `returncode` | result | integer \| null | Process exit code, or null when `captured: false`. |
| `stdout` | result | string \| null | Captured standard output, or null when `captured: false`. |
| `stderr` | result | string \| null | Captured standard error, or null when `captured: false`. |

`model_snapshot_before` and `model_snapshot_after` are still captured for
`shell` ops (the model may change as a side-effect of a `juju ssh` command).

---

## Model snapshot (lightweight)

`model_snapshot_before` and `model_snapshot_after` carry a **strict subset**
of the full `ModelSnapshot` defined in `[[a sibling project]]/SCHEMA.md`.

The subset carries exactly what the assertion engine (B) needs: unit statuses,
workload messages, agent statuses, and relation membership. Full relation
databags and machine/provider details are excluded from session-log snapshots —
they are too large (a realistic model produces ~10–30 KB of databags) and are
credential-bearing (the plan Open Q#5).

### Shape

```json
{
  "schema_version": 1,
  "captured_at": "2026-05-30T09:02:47.850Z",
  "apps": {
    "my-charm": {
      "units": {
        "my-charm/0": {
          "workload_status": "active",
          "workload_message": "",
          "agent_status": "idle"
        },
        "my-charm/1": {
          "workload_status": "waiting",
          "workload_message": "relation not ready",
          "agent_status": "idle"
        }
      }
    },
    "postgresql": {
      "units": {
        "postgresql/0": {
          "workload_status": "active",
          "workload_message": "Live master (10.5.46)",
          "agent_status": "idle"
        }
      }
    }
  },
  "relations": [
    {"endpoints": ["my-charm:db", "postgresql:database"]}
  ]
}
```

### Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | integer | ✓ | Snapshot subset schema version. Currently `1`. Independent from the session-level `schema_version`. |
| `captured_at` | string (RFC 3339 UTC, ms) | ✓ | Timestamp when this snapshot was taken. |
| `apps` | object | ✓ | Keys are application names. Values are app objects (see below). |
| `apps.<name>.units` | object | ✓ | Keys are unit names (`<app>/<n>`). Values are unit objects (see below). |
| `apps.<name>.units.<unit>.workload_status` | string | ✓ | One of: `active`, `maintenance`, `waiting`, `blocked`, `error`, `unknown`, `terminated`. |
| `apps.<name>.units.<unit>.workload_message` | string | ✓ | Workload status message. Empty string `""` if absent. Not `null` — this makes diff detection unconditional. |
| `apps.<name>.units.<unit>.agent_status` | string | ✓ | One of: `idle`, `executing`, `rebooting`, `failed`, `error`, `lost`, `allocating`. |
| `relations` | array | ✓ | List of relation membership objects. Empty array `[]` if no relations exist. |
| `relations[i].endpoints` | array of string (length 2) | ✓ | `["<app>:<endpoint>", "<app>:<endpoint>"]`. For peer relations both strings reference the same app. Always exactly two elements. |

### Alignment with `a sibling project/SCHEMA.md`

The recorder takes the `a sibling project` extractor as a dependency for
snapshot calls. The lightweight snapshot is produced by calling the extractor
and projecting it down:

| Full `ModelSnapshot` field | Session snapshot | Notes |
|---|---|---|
| `applications[i].name` | `apps.<name>` (key) | Same. |
| `applications[i].units[j].name` | `apps.<name>.units.<unit>` (key) | Same. |
| `applications[i].units[j].workload_status.current` | `workload_status` | Scalar, not the full `{current, message, since}` object. |
| `applications[i].units[j].workload_status.message` | `workload_message` | Promoted to top-level unit field. |
| `applications[i].units[j].agent_status.current` | `agent_status` | Scalar. |
| `relations[i].endpoint_a` + `relations[i].endpoint_b` | `relations[i].endpoints[0]` + `[1]` | Two-element array instead of named fields. |

**Intentionally omitted** from the session snapshot:

- `applications[i].charm` (name, channel, revision, base) — not needed for
  assertion inference; too volatile between test runs.
- `applications[i].config` — full config values are in the `config_get` op
  result, not the snapshot. Avoids duplicating credential-bearing config.
- `applications[i].units[j].workload_status.since` / `agent_status.since` —
  timestamps are non-deterministic and would cause spurious delta detections.
- `machines` — not needed for the v1 assertion rule set.
- `relations[i].id` / `relations[i].interface` — membership (which endpoints
  are related) is sufficient for assertion inference; interface name is a
  charm-metadata concern, not a model-state concern.

---

## Assertion tag shape

The `event.assertions` array is empty in the raw session log produced by layer
(A). Layer (B) annotates the log by populating this array for each event. Each
element is an assertion that (B) decided should appear in the generated test.

```json
{
  "kind": "unit_status",
  "app": "my-charm",
  "unit": "my-charm/0",
  "expected": "active",
  "strict": false,
  "source": "delta"
}
```

### Common envelope fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `kind` | string | ✓ | Closed set — see table below. |
| `strict` | boolean | ✓ | When true, codegen emits an exact-match assertion. When false, codegen emits a status-enum assertion that ignores message text, minor result differences, etc. Default policy: `false` unless the user passed `--strict` or the kind is inherently exact (e.g. `action_result`). |
| `source` | string | ✓ | `"delta"` — inferred from `model_snapshot_before`/`after` diff; `"gesture"` — emitted from an explicit user call during recording. |

### Kind taxonomy

| Kind | When emitted | Kind-specific fields | Codegen output |
|---|---|---|---|
| `unit_status` | Unit `workload_status` differs between before/after snapshots, or user called `recorder.assert_status()` | `app` (string), `unit` (string \| null — null means all units), `expected` (string) | `assert juju.status().apps["<app>"].units["<unit>"].workload_status == "<expected>"` |
| `unit_count` | Unit count in an app changed (deploy, scale, remove_application) | `app` (string), `expected` (integer) | `assert len(juju.status().apps["<app>"].units) == <expected>` |
| `action_result` | Op is `run` and result has non-empty `results` dict | `unit` (string), `action` (string), `expected_success` (bool), `expected_results` (object — only keys layer (B) considers stable) | `result = juju.run(…); assert result.success == True; assert result.results["key"] == "val"` |
| `config_value` | Op is `config_get` and keys differ from a prior `config_get` for the same app, or user called `recorder.assert_config()` | `app` (string), `key` (string), `expected` (string \| int \| bool \| float) | `assert juju.config("<app>", keys=["<key>"])["<key>"] == <expected>` |
| `relation_exists` | A relation appears in `model_snapshot_after.relations` but not in `model_snapshot_before.relations` | `endpoint_a` (string), `endpoint_b` (string) | `assert any(…)` over `juju.status()` relation list |
| `relation_absent` | A relation appears in `model_snapshot_before.relations` but not in `model_snapshot_after.relations` (op is `remove_integration`) | `endpoint_a` (string), `endpoint_b` (string) | `assert not any(…)` over `juju.status()` relation list |
| `user_checkpoint` | User called `recorder.checkpoint("label")` | `label` (string) | `# checkpoint: <label>` comment in generated test |

### Kind-specific field reference

**`unit_status`**

| Field | Type | Notes |
|---|---|---|
| `app` | string | Application name. |
| `unit` | string \| null | Unit name. Null means "all units in the app". |
| `expected` | string | Workload status enum value. |

**`unit_count`**

| Field | Type | Notes |
|---|---|---|
| `app` | string | Application name. |
| `expected` | integer | Expected number of units. |

**`action_result`**

| Field | Type | Notes |
|---|---|---|
| `unit` | string | Unit on which the action was run. |
| `action` | string | Action name. |
| `expected_success` | boolean | Whether `result.success` should be true. |
| `expected_results` | object | Subset of result keys that layer (B) considers assertion-worthy (non-trivial, non-timestamp, non-address). May be empty `{}` if only `success` is asserted. |

**`config_value`**

| Field | Type | Notes |
|---|---|---|
| `app` | string | Application name. |
| `key` | string | Config option name. |
| `expected` | string \| integer \| boolean \| float | Expected value. |

**`relation_exists` / `relation_absent`**

| Field | Type | Notes |
|---|---|---|
| `endpoint_a` | string | `<app>:<endpoint>`. |
| `endpoint_b` | string | `<app>:<endpoint>`. |

**`user_checkpoint`**

| Field | Type | Notes |
|---|---|---|
| `label` | string | Free-form label provided by the user. |

---

## Gesture shape

`event.gesture` is non-null when the user made an explicit assertion or
checkpoint call during the recording session (via the `recorder.*` API). A
gesture is always a first-class source of an assertion tag: layer (B) emits a
corresponding `assertions` entry with `source: "gesture"`.

```json
{
  "kind": "assert_status",
  "label": "deployed and active",
  "params": {"app": "my-charm", "status": "active"}
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `kind` | string | ✓ | Closed set — see table below. |
| `label` | string \| null | ✓ | Human-readable label the user passed to the gesture call. Null if the call had no label argument. |
| `params` | object | ✓ | Gesture-kind-specific parameters. |

### Gesture kinds

| Kind | User call | `params` fields | Notes |
|---|---|---|---|
| `checkpoint` | `recorder.checkpoint("label")` | (none) | Marks a logical step boundary. Emits a `user_checkpoint` assertion tag. |
| `assert_status` | `recorder.assert_status("my-charm", "active")` | `app` (string), `unit` (string \| null), `status` (string) | Emits a `unit_status` assertion tag. `unit` is null when asserting all units in the app. |
| `assert_action_result` | `recorder.assert_action_result(result, success=True, **kv)` | `success` (bool \| null), `expected_results` (object) | Emits an `action_result` tag. Applied to the innermost enclosing `run` event. |
| `assert_config` | `recorder.assert_config("my-charm", key="log-level", value="info")` | `app` (string), `key` (string), `value` | Emits a `config_value` assertion tag. |

Gestures are **not** jubilant operations — they do not invoke the juju CLI. The
event that carries a gesture has `op: "checkpoint"` or sits alongside a real
op. In all cases `model_snapshot_before` and `model_snapshot_after` are both
the same snapshot taken at the moment the gesture was called (no model change
occurred).

---

## On-disk format

### File naming

Default: `session-<session_id>.json` in the current working directory. Override
with `--output <path>`.

### Encoding

UTF-8, no BOM.

### JSON formatting

**Pretty-printed JSON with stable key ordering** (`indent=2`, `sort_keys=True`
in Python terms). This is a deliberate design decision, inspired by syrupy's
Amber format (§5 of the prior-art notes):

- `git diff session.json` produces human-readable, line-oriented output. A
  single changed field appears as a two-line diff (old/new), not an unintelligible
  single-line blob.
- Stable key order means two sessions that produce the same logical content
  produce byte-identical files, making automated comparison and snapshot
  testing reliable.
- Field-per-line formatting makes log review in a terminal viable without
  tooling.

The cost is file size: a pretty-printed 100-event session log is ~150–200 KB,
versus ~50 KB minified. This is acceptable — session logs are ephemeral
development artefacts, not shipped to production.

### One file per session

The session log is written as a complete document at `stop`/`run` completion,
not streamed line-by-line. This is simpler than JSONL (no partial-read
complexity in consumers) and consistent with the use case (post-hoc codegen,
not real-time streaming). Compare with `a sibling project`'s `events.jsonl`
which uses JSONL because the analyser needs incremental ingestion.

If the recorder process is killed mid-session before `stop` is called, any
partial log is written to `session-<id>.partial.json` alongside the final file
name. Consumers can detect incomplete sessions via the missing `recorded_at`
field.

---

## Versioning

### Session-level `schema_version`

- An integer at the top level of the session document.
- **Breaking change** (bump required): rename or remove a required field in the
  session envelope or event envelope; change a field's type; add a new required
  field with no default; remove or rename an op from the op taxonomy.
- **Additive change** (no bump): add optional fields to `args` or `result` for
  an existing op; add a new `kind` to the assertion tag set or gesture set;
  add new optional top-level fields.
- Consumers MUST check `schema_version` at load time and fail with a clear
  error if it is not a version they know.

### Snapshot-level `schema_version`

The `model_snapshot_before`/`after` objects carry their own `schema_version`
(currently `1`). This is **independent** from the session-level version:

- The snapshot format can evolve (e.g. when `a sibling project`'s extractor
  adds new fields) without bumping the session schema version.
- Conversely, the session envelope can be restructured without touching the
  snapshot subset format.
- Consumers that only care about snapshot content (e.g. a standalone snapshot
  viewer) can read snapshot objects from session logs without parsing the full
  session envelope.

### Version table

| `schema_version` | Notes |
|---|---|
| `1` | Initial schema (this document). |

---

## Coupling points

### `a sibling project/SCHEMA.md` — `ModelSnapshot`

The lightweight snapshot (§"Model snapshot") is a strict projection of the full
`ModelSnapshot`. The recorder imports the `a sibling project` extractor at
runtime to produce `juju status` snapshots; the projection step is applied
immediately after extraction, before the event is written.

Any new field that layer (B) needs from the full `ModelSnapshot` must be
explicitly added to the lightweight subset schema and bumps the snapshot-level
`schema_version`. Fields omitted from the lightweight subset (charm version,
machine info, config, relation databags) must not appear in session log
snapshots.

### Layer (B) — assertion inference

The `assertions` array shape (§"Assertion tag shape") and the closed `kind`
taxonomy are this schema's primary contract with layer (B). Layer (B) reads the
session log, evaluates per-op rules against `model_snapshot_before`/`after`,
and writes back annotated events with populated `assertions` arrays.

The `source: "delta"` rules in layer (B) are driven entirely by the field set
present in the lightweight snapshot — if a field is not in the snapshot it
cannot drive a delta assertion.

### Layer (C) — codegen

Each assertion `kind` maps to exactly one jubilant assertion pattern in the
generated test. The mapping is:

| `kind` | Generated jubilant pattern |
|---|---|
| `unit_status` | `juju.status().apps[app].units[unit].workload_status` |
| `unit_count` | `len(juju.status().apps[app].units)` |
| `action_result` | `juju.run(…).success` / `.results[key]` |
| `config_value` | `juju.config(app, keys=[key])[key]` |
| `relation_exists` | membership check over `juju.status()` |
| `relation_absent` | membership check (negated) over `juju.status()` |
| `user_checkpoint` | `# checkpoint: <label>` comment |

Adding a new `kind` to the assertion taxonomy is a breaking change to this
schema (bump `schema_version`) and requires a corresponding emit path in layer
(C). The `kind` closed set is the versioning boundary between (B) and (C).

### Op taxonomy completeness

The `op` taxonomy must cover the full jubilant public API surface. When jubilant
adds new public methods, one of these must happen:

1. A new `op` name is added to this schema (breaking change; bump
   `schema_version`).
2. The new method is captured as `op: "shell"` via the `--include-shell` shim
   and the user receives a `# TODO` comment in the generated test.

The recorder's `RecordingJuju` subclass and this schema must be updated in
lockstep when jubilant's API grows.

---

## Example session log

A complete minimal session: deploy + wait for idle + run action + explicit
checkpoint.

```json
{
  "schema_version": 1,
  "session_id": "0193fc4e-9c3d-7000-8000-1a2b3c4d5e6f",
  "recorded_at": "2026-05-30T09:05:00Z",
  "juju_version": "3.6.23",
  "jubilant_version": "0.3.0",
  "model": "test-model",
  "events": [
    {
      "seq": 1,
      "op": "deploy",
      "ts": "2026-05-30T09:00:05.000Z",
      "args": {
        "charm": "my-charm",
        "app": null,
        "channel": "edge",
        "num_units": 1,
        "config": {},
        "resources": {}
      },
      "result": {
        "app_name": "my-charm"
      },
      "model_snapshot_before": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:00:04.900Z",
        "apps": {},
        "relations": []
      },
      "model_snapshot_after": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:00:05.800Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "maintenance",
                "workload_message": "installing charm software",
                "agent_status": "executing"
              }
            }
          }
        },
        "relations": []
      },
      "assertions": [],
      "gesture": null
    },
    {
      "seq": 2,
      "op": "wait_for_idle",
      "ts": "2026-05-30T09:00:06.100Z",
      "args": {
        "apps": ["my-charm"],
        "timeout": 300
      },
      "result": {
        "settled_at": "2026-05-30T09:01:47.230Z"
      },
      "model_snapshot_before": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:00:06.050Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "maintenance",
                "workload_message": "installing charm software",
                "agent_status": "executing"
              }
            }
          }
        },
        "relations": []
      },
      "model_snapshot_after": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:01:47.300Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "active",
                "workload_message": "",
                "agent_status": "idle"
              }
            }
          }
        },
        "relations": []
      },
      "assertions": [
        {
          "kind": "unit_status",
          "app": "my-charm",
          "unit": "my-charm/0",
          "expected": "active",
          "strict": false,
          "source": "delta"
        }
      ],
      "gesture": null
    },
    {
      "seq": 3,
      "op": "run",
      "ts": "2026-05-30T09:01:50.000Z",
      "args": {
        "unit": "my-charm/0",
        "action": "do-thing",
        "params": {"key": "val"}
      },
      "result": {
        "success": true,
        "results": {"output": "done"},
        "message": null
      },
      "model_snapshot_before": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:01:49.900Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "active",
                "workload_message": "",
                "agent_status": "idle"
              }
            }
          }
        },
        "relations": []
      },
      "model_snapshot_after": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:01:53.100Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "active",
                "workload_message": "",
                "agent_status": "idle"
              }
            }
          }
        },
        "relations": []
      },
      "assertions": [
        {
          "kind": "action_result",
          "unit": "my-charm/0",
          "action": "do-thing",
          "expected_success": true,
          "expected_results": {"output": "done"},
          "strict": false,
          "source": "delta"
        }
      ],
      "gesture": {
        "kind": "assert_action_result",
        "label": "do-thing succeeded",
        "params": {
          "success": true,
          "expected_results": {"output": "done"}
        }
      }
    },
    {
      "seq": 4,
      "op": "status",
      "ts": "2026-05-30T09:02:00.000Z",
      "args": {},
      "result": {
        "snapshot": {
          "schema_version": 1,
          "captured_at": "2026-05-30T09:02:00.500Z",
          "apps": {
            "my-charm": {
              "units": {
                "my-charm/0": {
                  "workload_status": "active",
                  "workload_message": "",
                  "agent_status": "idle"
                }
              }
            }
          },
          "relations": []
        }
      },
      "model_snapshot_before": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:01:59.900Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "active",
                "workload_message": "",
                "agent_status": "idle"
              }
            }
          }
        },
        "relations": []
      },
      "model_snapshot_after": {
        "schema_version": 1,
        "captured_at": "2026-05-30T09:02:00.500Z",
        "apps": {
          "my-charm": {
            "units": {
              "my-charm/0": {
                "workload_status": "active",
                "workload_message": "",
                "agent_status": "idle"
              }
            }
          }
        },
        "relations": []
      },
      "assertions": [],
      "gesture": {
        "kind": "checkpoint",
        "label": "all done",
        "params": {}
      }
    }
  ]
}
```

---

## Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| JSONL (one event per line) | (B) and (C) need random access to the full session for sequence analysis (e.g. inferring `wait_for_idle` placement). A single document is simpler for both consumers. JSONL is appropriate for `a sibling project`'s streaming telemetry; session logs are bounded and complete before (B) runs. |
| Minified JSON | Makes `git diff session.json` useless. Session logs are debugging artefacts; diff-friendliness matters more than bytes. |
| Separate before/after snapshot files | Adds directory management complexity for no benefit. Keeping everything in one file means one artefact to move, share, or archive. |
| Embedding the full `ModelSnapshot` | Full snapshots include relation databags and machine tables. Each snapshot is ~10–30 KB for a realistic model; capturing before+after for 20 operations = ~1 MB of credential-bearing data per session. The lightweight subset is sufficient for (B)'s rule set. |
| Reusing `a sibling project`'s snapshot format verbatim | The full `ModelSnapshot` uses semver `schema_version` strings and includes fields not needed by the assertion engine (charm metadata, machine info, agent version detail, config). A strict subset is cleaner and keeps the session log size manageable. The alignment is explicit in the field mapping table above. |
| VCR.py cassette format | VCR cassettes are request/response pairs with no concept of model state, assertions, or gestures. The session log needs all three. The vocabulary (cassette ≈ session log, record modes) is worth borrowing; the format is not. |

---

## Open questions (for recorder implementers)

1. **Snapshot timing — before vs. at-call.** `model_snapshot_before` is taken
   immediately before invoking `_cli()`. For long-running operations like
   `deploy` the model starts changing before the call returns. This is
   acceptable for v1; the before/after pair captures pre-call and post-return
   state, which is what layer (B) needs for delta inference. A future `--verbose`
   mode could capture snapshots during polling.

2. **`wait_for_idle` internal polling.** `Juju.wait_for_idle()` internally
   calls `_cli('status', ...)` repeatedly. These intermediate `status` calls
   must NOT be recorded as separate events — they are an implementation detail
   of the wait loop, not user-visible operations. The `RecordingJuju` override
   must suppress recording inside the wait loop and emit only the single
   `wait_for_idle` event.

3. **Failed ops.** If `_cli()` raises (e.g. `CLIError` on a failed deploy),
   the event is still recorded with `model_snapshot_after: null` and a
   `result.error` field carrying the error message. Codegen emits a
   `pytest.skip` or `# TODO: failed op` comment for these. Exact shape of
   `result.error` is a step-(3) concern; reserve the key name now.

4. **Gesture injection point.** Gesture calls (`recorder.assert_status()` etc.)
   happen between jubilant operations, not inside them. The recorder should emit
   a synthetic event with a gesture-appropriate `op` (e.g. `op: "checkpoint"`)
   rather than attaching the gesture to the adjacent jubilant call. This keeps
   the `seq` counter strictly increasing and gives layer (B) a clean injection
   point.

5. **Credential redaction in `config_get` results.** `config_get` result values
   may include secrets. Apply the same redaction rules as
   `[[a sibling project]]/SCHEMA.md` §"Redaction" (`*password*`, `*token*`,
   `*secret*`, `*key*`, `*credential*`, `*cert*`). Redaction is applied at
   write time; the sentinel format is `"<redacted:<pattern>>"`.

6. **Session log path when using `jubilant-record run`**. The wrapping mode
   must write the final log atomically (write to `<id>.tmp`, then rename to
   `session-<id>.json`) so that a consumer polling the directory never reads a
   partial file.

---

## Plan deltas

*Changes implied by schema work that the plan does not yet reflect.*

1. **`gesture` is a first-class event field.** the plan §(B) discusses explicit
   gestures as a layer-(B) concept. The schema promotes them to a layer-(A)
   field so the recorder captures user intent at the source. Layer (B) reads
   gestures from the event and emits the corresponding assertion tag.

2. **`op: "checkpoint"` is needed.** Gesture calls happen between jubilant
   operations. The schema requires a synthetic `op` value for them so they fit
   the event envelope (seq, ts, snapshots). the plan does not mention this op
   in the taxonomy.

3. **`shell` op with `captured` flag.** the plan Open Q#4 describes the
   `--include-shell` flag as capturing subprocess calls. The schema formalises
   this as a first-class op with a `captured: false` stub shape so codegen
   always has a record of non-jubilant activity, even when output wasn't
   captured.

4. **Snapshot-level `schema_version` is independent.** the plan speaks of the
   session log's schema version but does not address the snapshot sub-object
   version. Keeping them independent (as formalised here) means snapshot format
   evolution does not force a session-level version bump.
