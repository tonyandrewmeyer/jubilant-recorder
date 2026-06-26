# Step 3 results — `RecordingLibjuju` driver

**Branch:** `claude/libjuju-extension-step-3` (stacked on
`claude/libjuju-extension-step-1`).
**Date:** 2026-06-25.

## What landed

* **`extensions/libjuju/recording.py`** — `RecordingLibjuju`, the libjuju
  → SessionLog driver. Context manager, mirrors `RecordingJuju.start()`
  on the canonical side. Takes `output_log_path`, `model`, an optional
  `tap`, and an optional `correlator` (defaults to the Step 1 PoC's tap
  and correlator). On exit it tears the tap down, runs the correlator
  over the captured RPCs + AllWatcher deltas, converts each event into
  an `EventEnvelope`, and appends it to a `SessionLog` — producing a
  log byte-compatible with the canonical SCHEMA.
* **`extensions/libjuju/tests/test_recording.py`** — 12 unit tests
  driving a `FakeConnection` through the recorder, covering
  schema-compliance, seq monotonicity, snapshot propagation, the
  bucket-2 (`shell`) and bucket-3 (`_todo`) surface ops, exception
  safety, tap restoration on raise, empty-session output, and the
  `session_log` accessor's outside-context guard.
* **`extensions/libjuju/tests/test_codegen_smoke.py`** — 2 smoke tests
  that feed a `RecordingLibjuju`-produced log through the existing
  `jubilant_recorder.codegen.generate` pipeline. Both assert the
  emitted Python parses (`ast.parse`); one drives a clean bucket-1
  session (deploy + integrate + run), the other mixes a bucket-2
  `Application.SetCharm` in and asserts codegen falls back to a `#
  TODO` comment rather than crashing.
* **`extensions/libjuju/correlate.py`** — Step 3 also fixes one bug in
  the Step 1 PoC's `_extract_args` for `Action.Enqueue`/`EnqueueOperation`:
  `unit-my-charm-0` was being converted to `my/charm-0` (splitting on
  the first `-`) instead of `my-charm/0` (splitting on the last `-`).
  Added `_unit_tag_to_name()` and 6 regression tests under a new
  `TestUnitTagConversion` class. Without this fix the codegen smoke
  test for `juju.run` failed.
* Two pre-existing ruff warnings in step-1 code (one `SIM103` in
  `correlate._is_internal`, one `F841` unused-`as` in `test_tap.py`)
  cleaned up so the branch is lint-clean.

## Test count delta

| Suite | Before (step-1) | After (step-3) | Delta |
|---|---|---|---|
| `extensions/libjuju/tests/` | 36 | 56 | **+20** |
| `tests/` (canonical) | 175 | 175 | 0 |
| **Total** | **211** | **231** | **+20** |

`ruff check` and `ruff format --check` are clean on
`extensions/libjuju/`.

`pytest -W error` reports two pre-existing failures in
`tests/test_cli_ai_flag.py` that promote a non-Step-3
`ANTHROPIC_API_KEY` `UserWarning` to an error. Verified by stashing the
Step 3 changes and re-running — both still fail. Out of scope for this
step; flagged here so the next pass picks it up.

## Bucket-2 ops stubbed

No new bucket-2 stubs were introduced in Step 3. The Step 1 PoC's
correlator already handles all bucket-2 facade/method pairs
(`Application.SetCharm`, `Expose`, `Unexpose`, `SetConstraints`,
`MergeBindings`, `SetRelationsSuspended`, `UnsetApplicationsConfig`,
`UpdateApplicationBase`) by emitting `op: "shell"` with the original
facade/method captured in `args.command[0]`. Step 3's smoke test for
bucket-2 confirms the canonical codegen's `fallback.emit()` renders
these as `# TODO: manual step` comments, the same way it renders any
unknown op, so no schema or codegen change is required.

## Codegen smoke output

The bucket-1 smoke test drives this libjuju session:

* `Application.Deploy` (`ch:my-charm`)
* `AllWatcher.Next` (the unit's active-status delta burst)
* `Application.AddRelation` (`my-charm:db`, `postgresql:database`)
* `Action.EnqueueOperation` (action `do-thing` on `unit-my-charm-0`)

`RecordingLibjuju` records three events (the AllWatcher delta folds
into the deploy's `model_snapshot_after`). Feeding the resulting log to
`jubilant_recorder.codegen.generate` emits:

```python
import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ch:my-charm', app='my-charm')
        juju.integrate('my-charm:db', 'postgresql:database')
        result_3 = juju.run('my-charm/0', 'do-thing')
```

This parses (`ast.parse`), uses the canonical `jubilant.temp_model()`
idiom, and contains every operation the libjuju session performed —
without any change to the existing codegen.

## Carries for Step 4

1. **`duration_ms` is zero on libjuju events.** `correlate()` does not
   currently surface per-RPC duration (it has `ts_start_iso` and
   `ts_end_iso` on the source rpcs but discards `ts_end` when building
   the event). Downstream consumers (tagger, codegen) do not read the
   field, so this is producer-only metadata loss. Worth threading
   through if Step 4 wires in profiling or replay-pacing.
2. **`wait_for_idle` is not synthesised.** The Step 1 correlator emits
   no `wait_for_idle` op — `Juju.wait_for_idle()` in libjuju manifests
   as a long sequence of `AllWatcher.Next` calls with no distinguishing
   user-facing RPC, so the natural gesture is missing from the
   generated test. Step 4 could heuristically inject a `wait_for_idle`
   event between bucket-1 events whose gap exceeds a threshold and
   whose intervening delta bursts show units transitioning to `active`.
3. **Bucket-2 secrets ops are still rendered as opaque `shell` stubs.**
   `Secrets.ListSecrets` and `Secrets.GetSecretContentInfo` were the
   ~11% bucket-2 share in the corpus pass; the human has to fill these
   in by hand today. Step 4 could promote `Secrets.*` to bucket 1 if
   the canonical SCHEMA grows `op: "secrets_list"` /
   `op: "show_secret"` ops, OR keep them in bucket 2 and emit a
   richer note (the secret URI, the reveal flag) so the manual TODO
   carries enough context.
4. **No live-juju example yet.** Step 3 intentionally fixture-mocks the
   websocket because Step 2 already established that pattern and we
   don't have a juju controller in this environment. A future
   `examples/libjuju_live.py` driving a real `juju.Model.connect()`
   would close the loop end-to-end.
