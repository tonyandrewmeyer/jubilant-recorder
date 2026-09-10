# Session log — JSON schema

The reference for the session-log format that every recording mode writes and
that the tagger and codegen consume. This is a public contract: changing an
event shape means bumping `schema_version` and updating codegen in lock-step.

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
| `recorded_at` | string (RFC 3339 UTC) | ✓ | Timestamp when the session log was finalised and written (i.e. when `jubilant-recorder stop` completed or the `run` wrapper exited). |
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
| `scale` | `Juju.add_unit()` (relative) / `juju.cli("scale-application")` (absolute) | `app`, `units`, `mode` | — |
| `run` | `Juju.run()` | `unit`, `action`, `params` | `success`, `results`, `message` |
| `status` | `Juju.status()` | — | `snapshot` |
| `wait_for_idle` | `Juju.wait_for_idle()` | `apps`, `timeout` | `settled_at` |
| `remove_application` | `Juju.remove_application()` | `app` | — |
| `shell` | see [`shell`](#shell) below | `argv`, `basename`, `source` | `exit_code`, `captured`, `stdout`, `status_json` |
| `shell_context` | (none — rendered as a comment) | `argv`, `basename`, `source` | `exit_code`, `stdout` |
| `note` | (none — rendered as a comment) | `text` | — |
| `tag` | (none — rendered as a `# step:` comment) | `label` | — |

Two more ops are written by `jtr` for its own bookkeeping and are not steps
to translate: `config_override` (an `include`/`exclude`/`redact` the operator
registered mid-session) and `cap_reached` (the shell hook stopped recording).
Codegen skips the first and renders the second as a warning comment.

The ops above are the ones a *recorder* writes. Codegen introduces further
ops of its own when it translates a `shell` event's argv into a jubilant
call — `status_call`, `add_model`, `ssh`, `refresh`, `cli_passthrough` and
the rest of the set in `codegen/operations/__init__.py`. Those never appear
in a session log; they exist only between `cli_translate.classify()` and the
emitter it dispatches to.

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
    "units": 3,
    "mode": "relative"
  },
  "result": {}
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `app` | args | string | Application name. |
| `units` | args | integer | Unit delta (`mode: "relative"`) or target count (`mode: "absolute"`). |
| `mode` | args | `"relative"` \| `"absolute"` | `"relative"` (`Application.AddUnits`, `juju add-unit`) emits `Juju.add_unit(app, num_units=units)`. `"absolute"` (`Application.ScaleApplications`, K8s-only `juju scale-application`) has no jubilant client method, so it emits `juju.cli("scale-application", app, str(units))`. Missing/absent defaults to `"relative"` for events recorded before this field existed. |
| `to` | args | string, optional | `mode: "relative"` only. Placement directive(s) from `juju add-unit --to`, forwarded verbatim (comma-joined string, matching jubilant's own `add_unit(to=...)` handling) to `Juju.add_unit(app, num_units=units, to=to)`. Set by both the CLI/shim translation path (`cli_translate._classify_add_unit`, from the raw `--to` argv string) and the RPC path (`correlate._extract_args` for `Application.AddUnits`, reconstructed from the wire's `placement` list of `{"scope", "directive"}` dicts) — both produce the same comma-joined string shape, so the emitter's output is identical regardless of source. Ignored (never present) when `mode: "absolute"`, since `scale-application` has no `--to` flag. |
| `attach_storage` | args | string, optional | `mode: "relative"` only. From `juju add-unit --attach-storage`, forwarded verbatim to `Juju.add_unit(app, num_units=units, attach_storage=attach_storage)`. Set by both the CLI/shim translation path and the RPC path (reconstructed from the wire's `attach-storage` list of `storage-<id>` tags) — same shape from either source. |

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

Records a `juju` command the PATH shim intercepted during a shell-capture
session (see [shell-hook.md](shell-hook.md)). The shim records what was
typed, what it exited with, and — for read-only subcommands — what it
printed.

```json
{
  "args": {
    "argv": ["deploy", "ubuntu", "--channel", "stable"],
    "basename": "juju",
    "source": "shim",
    "session_id": "6f1c…"
  },
  "result": {
    "captured": false,
    "exit_code": 0,
    "stdout": null,
    "stderr": null,
    "stdout_truncated": false,
    "status_json": null
  }
}
```

| Field | Location | Type | Notes |
|---|---|---|---|
| `argv` | args | array of string | The `juju` argv, **without** the `juju` binary itself. Redacted (see below). |
| `basename` | args | string | Always `"juju"`: the shim is only ever installed as the juju intercept. |
| `source` | args | string | `"shim"` for the PATH shim. Its absence marks a libjuju bucket-2 event, which shares the op name but not the shape. |
| `session_id` | args | string | The `JTR_SESSION` the event belongs to. |
| `captured` | result | boolean | Whether `stdout` holds the command's output. True only for the read-only subcommands in the shim's `_CAPTURE_STDOUT`. |
| `exit_code` | result | integer \| null | The real exit status. Non-zero means codegen comments the translated call out rather than emitting a line that claims the command worked. |
| `stdout` | result | string \| null | Captured standard output when `captured`, redacted, truncated to 64 KiB. |
| `stdout_truncated` | result | boolean | Whether `stdout` was cut at the cap. |
| `status_json` | result | string \| null | Raw `juju status --format=json`, captured alongside every recorded `juju status`. `shim_snapshots.attach_status_snapshots()` turns it into `model_snapshot_after`; it is the only sampling point a shell session has. |

`model_snapshot_before`/`model_snapshot_after` are null as written by the
shim — it sees argv, not a model — and are filled in for `status` events by
`shim_snapshots` before tagging.

**Redaction.** `argv` and `stdout` are redacted as they are written, by the
shared rules in `jubilant_recorder.redaction` plus any pattern the operator
registered with `jtr redact`. A `key=value` token whose key names a
credential (`juju add-secret mine token=hunter2`) becomes
`token=<redacted:token>`. This is a safety net, not a guarantee — read a
session log before you share it.

### `shell_context`

The same shape, for commands the *shell hook* lane recorded: the
`kubectl`/`lxc`/`charmcraft` calls surrounding the juju work. `args.source`
is `"hook"`, `args.argv` is a single-element list holding the command line as
typed, and codegen renders these as `# context:` comments — they are what the
operator was doing, not a step to replay.

A shim event also takes this op when `JTR_PYTHON_ACTIVE` is set, which is how
a `juju` call made *by* a recorded Python script avoids being counted twice.

---

## Model snapshot (lightweight)

`model_snapshot_before` and `model_snapshot_after` carry a **strict subset**
of a fuller model-snapshot shape used for full model introspection.

The subset carries exactly what the assertion engine needs: unit statuses,
workload messages, agent statuses, and relation membership. Full relation
databags and machine/provider details are excluded from session-log snapshots —
they are too large (a realistic model produces ~10–30 KB of databags) and are
credential-bearing.

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

### Derived from `juju status --format json`

The lightweight snapshot is produced by calling `juju status --format json`
and projecting jubilant's own parsed `Status` object down to just what the
assertion engine needs:

| `jubilant.Status` field | Session snapshot | Notes |
|---|---|---|
| `apps[name]` (key) | `apps.<name>` (key) | Same. |
| `apps[name].units[unit]` (key) | `apps.<name>.units.<unit>` (key) | Same. |
| `apps[name].units[unit].workload_status.current` | `workload_status` | Scalar, not the full `StatusInfo` object. |
| `apps[name].units[unit].workload_status.message` | `workload_message` | Promoted to top-level unit field. |
| `apps[name].units[unit].juju_status.current` | `agent_status` | Scalar. |
| `apps[name].relations` (local endpoint → related apps) | `relations[i].endpoints` | Deduplicated pairs, each rendered as a two-element `["<app>:<endpoint>", ...]` array instead of named fields. |

**Intentionally omitted** from the session snapshot:

- `apps[name].charm_name` / `charm_channel` / `charm_rev` / `base` — not
  needed for assertion inference; too volatile between test runs.
- Full application config — config values are captured in the `config_get`
  op result instead, not the snapshot. Avoids duplicating credential-bearing
  config.
- `StatusInfo.since` on workload/agent status — timestamps are
  non-deterministic and would cause spurious delta detections.
- `Status.machines` — not needed for the v1 assertion rule set.
- Relation interface names — membership (which endpoints are related) is
  sufficient for assertion inference; interface name is a charm-metadata
  concern, not a model-state concern.

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
Amber format:

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
not real-time streaming), unlike tools that need incremental ingestion and so
stream events as JSONL instead.

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

- The snapshot format can evolve (e.g. when the projection from
  `jubilant.Status` adds new fields) without bumping the session schema
  version.
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

### `juju status --format json` — snapshot source

The lightweight snapshot (§"Model snapshot") is a strict projection of
jubilant's own parsed `Status` object. The recorder calls `juju status
--format json` at runtime to produce this status; the projection step is
applied immediately after parsing, before the event is written.

Any new field that layer (B) needs from `Status` must be
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
2. The scripted front-end goes on recording it as whatever op its underlying
   `_cli()` call maps to, and shell capture keeps recording it as a `shell`
   event, which codegen renders as `juju.cli(...)` — a real call, not a TODO.
   Codegen picks up the typed method later by adding a classifier to
   `codegen/cli_translate.py`, without a schema change.

The recorder's `RecordingJuju` subclass and this schema must be updated in
lockstep when jubilant's API grows.

### Diagnostic-only ops (`_libjuju*` prefix)

Some extension correlators synthesise trailer events that carry debugging
information about the recording itself rather than a step the user
performed — e.g. the libjuju extension's `_libjuju_orphan_deltas`, emitted
when AllWatcher deltas arrive that can't be attributed to any captured RPC.
Any `op` beginning with `_libjuju` is by this convention diagnostic-only:
codegen drops these events entirely (no comment, no TODO) rather than
asking the user to translate them.

This is narrower than "any op starting with an underscore" — the libjuju
extension's bucket-3 fallback op, `_todo`, also has a leading underscore
but is not diagnostic: it marks a genuinely unmapped RPC with no jubilant
equivalent, and must still render as a `# TODO: manual step` comment so
the user notices and translates it by hand. Only the `_libjuju`-prefixed
family is suppressed.

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
| JSONL (one event per line) | (B) and (C) need random access to the full session for sequence analysis (e.g. inferring `wait_for_idle` placement). A single document is simpler for both consumers. JSONL is the right shape for streaming telemetry that needs incremental ingestion; session logs are bounded and complete before (B) runs. |
| Minified JSON | Makes `git diff session.json` useless. Session logs are debugging artefacts; diff-friendliness matters more than bytes. |
| Separate before/after snapshot files | Adds directory management complexity for no benefit. Keeping everything in one file means one artefact to move, share, or archive. |
| Embedding jubilant's full `Status` object verbatim | Full `juju status` output includes relation databags and machine tables. Each snapshot is ~10–30 KB for a realistic model; capturing before+after for 20 operations = ~1 MB of credential-bearing data per session. The lightweight subset is sufficient for (B)'s rule set, and keeps the session log size manageable. The projection is explicit in the field mapping table above. |
| VCR.py cassette format | VCR cassettes are request/response pairs with no concept of model state, assertions, or gestures. The session log needs all three. The vocabulary (cassette ≈ session log, record modes) is worth borrowing; the format is not. |

---

## Decisions

These were open when the format was designed. All are settled by the
implementation; they are recorded here because the reasoning is still the
reason the format looks like this.

1. **Snapshot timing — before vs. at-call.** `model_snapshot_before` is taken
   immediately before invoking `_cli()`. For long-running operations like
   `deploy` the model starts changing before the call returns. This is
   acceptable; the before/after pair captures pre-call and post-return
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
   `pytest.skip` or `# TODO: failed op` comment for these. `result.error`
   carries the message as a string.

4. **Gesture injection point.** Gesture calls (`recorder.assert_status()` etc.)
   happen between jubilant operations, not inside them. The recorder should emit
   a synthetic event with a gesture-appropriate `op` (e.g. `op: "checkpoint"`)
   rather than attaching the gesture to the adjacent jubilant call. This keeps
   the `seq` counter strictly increasing and gives layer (B) a clean injection
   point.

5. **Credential redaction in `config_get` results.** `config_get` result values
   may include secrets. Apply redaction rules matching keys such as
   `*password*`, `*token*`, `*secret*`, `*key*`, `*credential*`, `*cert*`.
   Redaction is applied at write time; the sentinel format is
   `"<redacted:<pattern>>"`.

6. **Session log path when using `jubilant-recorder run`**. The wrapping mode
   must write the final log atomically (write to `<id>.tmp`, then rename to
   `session-<id>.json`) so that a consumer polling the directory never reads a
   partial file.

---

## Design notes

*Schema decisions worth recording, beyond the base event shape above.*

1. **`gesture` is a first-class event field.** Gestures capture user intent
   at the recording layer itself, so the schema promotes them to a top-level
   event field. The tagging layer reads gestures from the event and emits
   the corresponding assertion tag.

2. **`op: "checkpoint"` is needed.** Gesture calls happen between jubilant
   operations. The schema requires a synthetic `op` value for them so they fit
   the event envelope (seq, ts, snapshots).

3. **`shell` op with `captured` flag.** The PATH shim records every `juju`
   invocation, but only captures the *output* of read-only subcommands —
   holding back a `juju deploy`'s progress until it finished would change
   what the operator sees at their own terminal. `captured` says which of
   the two happened, so a reader can tell "no output" from "output not
   recorded".

4. **Snapshot-level `schema_version` is independent.** Keeping the snapshot
   sub-object's version independent of the session log's own schema version
   means snapshot format evolution does not force a session-level version
   bump.

---

## Shell-hook ops

*Added 2026-06-28. Additive change; session `schema_version` stays at `1`.*

Three new op kinds are produced by the `jtr` shell-hook layer and consumed by
codegen layer (C). They never appear in session logs produced by the Python
`RecordingJuju` wrapper — they are shell-side annotations only.

### New ops summary

| Op | Source | Args (non-null keys) | Result (non-null keys) | Codegen output |
|---|---|---|---|---|
| `shell_context` | `jtr` hook or PATH shim | `argv`, `basename`, `source`, `session_id` | `exit_code`, `stdout`, `stderr`, `stdout_truncated` | `# context: <cmd>` comment |
| `note` | `jtr note <text>` | `text` | — | `# note: <text>` comment |
| `tag` | `jtr tag <label>` | `label` | — | `# step: <label>` comment before next jubilant op |

### `shell_context`

Records a shell command that ran during the session. Produced by:

- The PATH shim (`juju_shim.py` installed as `~/.local/share/jtr/shims/juju`)
  when `JTR_PYTHON_ACTIVE` is set.
- The `_hook_event` internal command, invoked from the `precmd` shell hook,
  for commands in `_CONTEXT_ALLOWLIST` (kubectl, helm, curl, charmcraft, …).

```json
{
  "args": {
    "argv": ["kubectl", "get", "pods"],
    "basename": "kubectl",
    "source": "hook",
    "session_id": "abc123"
  },
  "result": {
    "exit_code": 0,
    "stdout": null,
    "stderr": null,
    "stdout_truncated": false
  }
}
```

`source` is `"shim"` for PATH-shim events, `"hook"` for precmd-hook events.

`model_snapshot_before` and `model_snapshot_after` are always `null` for
`shell_context` events (no jubilant call was made).

Codegen renders `shell_context` as a comment: `# context: <argv joined>`.
If `result.exit_code` is non-zero and non-null, an extra `# exit <N>` line
follows. If `result.stdout` is non-null, up to 5 lines are shown as
`# | <line>` comments.

### `note`

Free-text annotation injected by the user running `jtr note <text>`. Useful
for marking what a block of shell activity was for.

```json
{
  "args": {
    "text": "deployed the charm manually to check upgrade path"
  },
  "result": {}
}
```

`text` is truncated to 500 characters (Unicode-aware; truncation sentinel is `…`).

Codegen renders as: `# note: <text>`

### `tag`

Step-boundary label injected by `jtr tag <label>`. Codegen inserts
`# step: <label>` immediately before the next non-skipped jubilant op.
If no jubilant op follows, the tag is silently dropped.

```json
{
  "args": {
    "label": "scale up"
  },
  "result": {}
}
```

`label` must match `^[a-zA-Z0-9 ]+$` and be 1–80 characters.

Codegen renders as: `# step: <label>` (inserted before the next jubilant call).

### Codegen integration (`interleave_context`)

`shell` events — the PATH shim's `juju` invocations — are *not* on this
list: they are translated into jubilant calls rather than rendered as
comments. See [`shell`](#shell) above and
[shell-hook.md](shell-hook.md#what-the-generated-test-looks-like).

Layer (C) codegen calls `interleave_context(events, indent)` from
`jubilant_recorder.codegen.context` instead of the original flat loop when
the log contains any `shell_context`, `note`, or `tag` events. The function:

1. Emits `shell_context` events as `# context:` comment blocks (never as
   jubilant calls).
2. Emits `note` events as `# note:` comments inline.
3. Buffers `tag` events and flushes the label as `# step:` before the next
   non-skipped jubilant op.
4. For `status` events with no assertions and no gesture, renders a
   `# juju status:` summary comment instead of a jubilant call.
5. For `config` (set) events, appends a `# result:` comment showing
   workload-status deltas from before/after snapshots.
6. All other events go through the existing emitter table unchanged.

### Filtering and privacy

The `_hook_event` path applies a two-layer filter before writing a
`shell_context` event:

1. **Denylist** (`_BASENAME_DENYLIST`): `juju`, common navigation commands,
   editors, credential tools. Matched by `os.path.basename(argv[0])`.
2. **Allowlist** (`_CONTEXT_ALLOWLIST`): `kubectl`, `helm`, `curl`,
   `charmcraft`, `rockcraft`, `snapcraft`, `lxc`, `lxd`, `microk8s`,
   `terraform`, `jq`, `yq`, `wget`, `http`, `k8s`. A command must be in
   this set — or match a per-session `include` **regular expression**,
   registered with `jtr include <pattern>` — to be recorded. A per-session
   `exclude` pattern wins over both.
3. **Redact patterns** (per-session, via `jtr redact <regex>`): applied to
   the full command string before writing, on top of the shared
   `jubilant_recorder.redaction` rules. `jtr note` text and the PATH shim's
   `juju` argv go through the same pass.

The `_ARGV_DENYPATS` list blocks secret-bearing invocations even if the
basename would otherwise pass (e.g. `kubectl create secret`, `gh auth`).

The 1 000-event cap (`cap_reached` sentinel op) prevents unbounded log growth.
