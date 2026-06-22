# libjuju → jubilant extension (step 1 PoC)

Records a libjuju-driven test session and emits session-log events in the same
SCHEMA.md format that `RecordingJuju` produces — so the existing tagger (B)
and codegen (C) pipeline is reused unchanged.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  existing libjuju test (model.deploy, model.add_relation, …) │
└───────────────────────────────┬─────────────────────────────┘
                                │ calls
                                ▼
              juju.client.connection.Connection.rpc()
                    ↑ monkeypatched by LibjujuTap
                    │
          ┌─────────┴──────────┐
          │                    │
    user-facing RPCs      AllWatcher.Next responses
    (Deploy, AddRelation, (pushed delta bursts)
     Enqueue, Status, …)
          │                    │
          └─────────┬──────────┘
                    │  tap.py captures both streams in memory
                    ▼
             correlate.py
          (pairs each RPC with its delta burst via time-window)
                    │
                    ▼
          SCHEMA.md events  ──→  tagger (B) ──→ codegen (C)
```

## Key finding: request-ID availability

`Connection.rpc()` stamps every outgoing message with a monotonically-increasing
integer `request-id` before the WebSocket send.  Because the msg dict is passed
by reference, our wrapper reads `msg["request-id"]` after the original `rpc()`
sets it — so request-IDs ARE available for user-facing RPC calls.

However, AllWatcher delta bursts are pushed as responses to `AllWatcher.Next`
RPC calls and carry **no reference to the request-id of the operation that
triggered the state change**.

**Conclusion:** request-IDs are captured on outgoing RPCs, but delta → RPC
correlation must use a time-window heuristic (default 2 s).  The correlator
accepts deltas arriving up to 0.5 s *before* the RPC's end timestamp to handle
controller-proactive pushes and minor clock skew.

## AllWatcher hook point

The tap intercepts `AllWatcher.Next` responses inside the same monkeypatch:
when `msg["type"] == "AllWatcher"` and `msg["request"] == "Next"`, the result's
`response.deltas` array is extracted and recorded.  This is the exact path
through which `juju.Model._watch()` → `AllWatcherFacade.Next()` →
`Connection.rpc()` flows — no separate observer registration is needed.

All other `AllWatcher.*` calls (Stop, etc.) are silently dropped — they are
infrastructure, not user operations.

## Facade → op taxonomy

Three buckets (see correlate.py for the full map):

| Bucket | Condition | Event shape |
|---|---|---|
| 1 — clean | `Application.Deploy`, `AddRelation`, `DestroyRelation`, `SetConfigs`, `Get/GetConfig`, `AddUnits`, `ScaleApplications`, `DestroyApplication`; `Action.Enqueue/EnqueueOperation`; `Client.Status` | Full SCHEMA.md event with op name from taxonomy |
| 2 — lossy | `Application.SetCharm`, `Expose`, `Unexpose`, `SetConstraints`, `MergeBindings`, etc. | `op: "shell"` with `note: "libjuju <Facade>.<Method>"` (the existing codegen `# TODO` fallback) |
| 3 — no mapping | Everything else | `op: "_todo"` with `note: "# TODO: manual step — libjuju <Facade>.<Method>"` and raw params attached |

## Usage (when a juju controller is available)

```python
import asyncio
from extensions.libjuju.tap import LibjujuTap
from extensions.libjuju.correlate import correlate
import juju

async def record_session():
    async with juju.model.Model() as model:
        await model.connect_current()

        with LibjujuTap() as tap:
            await model.deploy("ubuntu", application_name="ubuntu")
            await model.wait_for_idle(apps=["ubuntu"], timeout=300)

    events = correlate(tap.rpcs, tap.deltas)
    for ev in events:
        print(ev["op"], ev["args"])

asyncio.run(record_session())
```

## Running the tests

No live juju controller is required.

```bash
# Extension tests only
PYTHONPATH=. uv run --with pytest --no-project python -m pytest extensions/libjuju/tests/ -v

# Extension + existing recorder tests
PYTHONPATH=src:. uv run --with pytest,jubilant --no-project python -m pytest tests/ extensions/libjuju/tests/ -q
```

## Open questions (from the plan)

- **Async correlation:** resolved — request-IDs available on outgoing RPCs but
  NOT on delta payloads; time-window heuristic is the correct approach.
- **AllWatcher hook point:** resolved — intercepting `Connection.rpc` is
  sufficient; no per-model observer registration needed.
- **Worth-it threshold:** see `STEP2-STARTER.md` for the bucket-distribution
  evidence from 5 sampled operator tests.
