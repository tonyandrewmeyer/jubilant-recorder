# Recording libjuju-driven sessions

Records a libjuju-driven test session and emits session-log events in the same
docs/schema.md format that `RecordingJuju` produces — so the existing tagger
and codegen pipeline is reused unchanged.

## Migrating a charm's integration suite

This is what the mode is for. You have a `pytest-operator` suite written
against python-libjuju, you want the same coverage in jubilant, and
translating it by hand is a day's careful work.

Run the suite as you always do, with one extra flag:

```bash
pytest tests/integration --jtr-out=tests/integration/test_migrated.py
```

Nothing about the suite changes — no conftest edit, no import. The plugin
ships with `jubilant-recorder` and registers itself with pytest; it hooks
nothing unless one of its options is passed.

| Flag | Effect |
|---|---|
| `--jtr-out=PATH` | write the generated jubilant test module to PATH |
| `--jtr-record=DIR` | keep the per-test session logs in DIR (implied by `--jtr-out`, which puts them next to the output) |
| `--jtr-ai` | also run the LLM assertion and polish passes (needs `OPENROUTER_API_KEY`) |

Each test function is recorded as its own session and becomes its own
generated test, in the order pytest ran them:

```python
import jubilant
import pytest


@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju: jubilant.Juju):
    juju.deploy('postgresql', channel='14/stable')
    juju.wait(lambda s: jubilant.all_active(s, 'postgresql'))


def test_relate(juju: jubilant.Juju):
    juju.deploy('data-integrator')
    juju.integrate('postgresql', 'data-integrator')
```

The module-scoped fixture is not decoration. A pytest-operator suite's
`ops_test` fixture is module-scoped too: its tests run in order against one
model, each building on what the last left behind. Generating a
`temp_model()` per test would hand every test after the first an empty
model.

Only each test's **call** phase is recorded. Setup and teardown are where
pytest-operator makes and destroys the model, which is the fixture's job in
the generated file rather than a step in every test.

### What you get, and what you have to add

A starting point, not a finished suite. The recorder sees what each test
*did* to the model; it cannot see what the test meant, and a test's real
assertions live in Python that never reaches the wire — `assert
ops_test.model.applications[x].status == "active"` is a comparison on a
locally cached object, not an RPC.

What survives automatically is the sequence of operations, and whatever
assertions the delta tagger can derive from the model actually changing.
Read the generated file and expect to add the checks back. That is still a
much shorter job than starting from the original.

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
          docs/schema.md events  ──→  tagger ──→ codegen
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
| 1 — clean | `Application.Deploy`, `AddRelation`, `DestroyRelation`, `SetConfigs`, `Get/GetConfig`, `AddUnits`, `ScaleApplications`, `DestroyApplication`, `SetCharm`, `Expose`, `Unexpose`, `SetConstraints`, `MergeBindings`, …; `Action.Enqueue/EnqueueOperation`; `Client.Status`; the `Secrets.*` and `ApplicationOffers.*` families | Full docs/schema.md event with op name from taxonomy |
| 2 — lossy | **Empty by design.** "jubilant has no client method" is not a reason to give up on an operation — `juju.cli()` answers it — so everything that used to sit here was promoted to bucket 1 and emits a real call. The branch stays live for a facade that is genuinely lossy. |
| 3 — no mapping | Everything else | `op: "_todo"` with `note: "# TODO: manual step — libjuju <Facade>.<Method>"` and raw params attached |

## Recording something other than a pytest suite

`RecordingLibjuju` is the context manager the plugin uses; drive it directly
for a one-off script.

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

No live Juju controller is required.

```bash
uv run pytest tests/libjuju/       # this extension only
uv run pytest                      # everything
```

## Design notes

Two questions shaped the implementation, both settled:

- **Correlating deltas with calls.** Request IDs are available on outgoing
  RPCs but not on delta payloads, so there is nothing to join on. The
  time-window heuristic in `correlate.py` is the correct approach rather
  than a workaround.
- **Where to hook.** Intercepting `Connection.rpc` is sufficient; no
  per-model observer registration is needed.

## Install

The extension needs python-libjuju, which is not a base dependency:

```bash
pip install 'jubilant-recorder[libjuju]'
```
