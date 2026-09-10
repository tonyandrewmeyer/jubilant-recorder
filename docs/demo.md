# jubilant-recorder: record a juju session, get a test

*2026-09-04T11:13:16Z by Showboat 0.6.1*
<!-- showboat-id: 90663037-33f8-4018-83a2-c4208d39ecd5 -->

Integration tests for charms are tedious to write and easy to get subtly wrong. The premise here is that you already drive juju by hand when you are working something out, so record that and generate the test from it.

This document is executable: every block below was really run against a live juju model, and `showboat verify` re-runs them all and diffs the output. If something has drifted since it was written, it names the block.

```bash
juju version && uv run jubilant-recorder --help 2>&1 | head -12
```

```output
3.6.28-genericlinux-amd64
usage: jubilant-recorder [-h] [--version] {start,stop,run,generate} ...

Record a jubilant session and generate a pytest integration test.

positional arguments:
  {start,stop,run,generate}
    start               Begin a recording session.
    stop                Finalise the active recording session.
    run                 Start a session, run CMD under the recorder, stop, and
                        generate a test.
    generate            Generate a pytest test file from a session log.

```

## 1. Explicit mode

This is what a person writes. It is ordinary jubilant, plus `RecordingJuju.start` and three gesture calls that say what the generated test should assert. Nothing else about the script changes.

```bash
cat examples/demo_record.py
```

```output
"""What a person writes to record a session.

Ordinary jubilant, with four extra calls: RecordingJuju.start, and the
three gestures that say what the generated test should assert.
"""

from jubilant_recorder import RecordingJuju, assert_status, checkpoint

with RecordingJuju.start("session.json", model="jtr-demo") as juju:
    juju.deploy("ubuntu", channel="stable")
    juju.wait(lambda s: s.apps["ubuntu"].is_active, timeout=900)
    assert_status("ubuntu", "active")
    checkpoint("deployed")

    juju.config("ubuntu", {"hostname": "demo-host"})
    juju.wait(lambda s: s.apps["ubuntu"].is_active, timeout=300)
    assert_status("ubuntu", "active")
    checkpoint("reconfigured")
```

Run it. This is a real deploy against a real model, so it takes a couple of minutes.

```bash
time uv run python examples/demo_record.py && echo '--- session log ---' && python3 -c "import json; d=json.load(open('session.json')); print(len(d['events']), 'events,', d['juju_version'])"
```

```output

real	0m57.644s
user	0m4.910s
sys	0m2.018s
--- session log ---
8 events, 3.6.28-genericlinux-amd64
```

## 2. The generated test

No LLM involved in this step. The tagger infers assertions from what the session log saw, and the gesture calls add the ones it could not infer.

```bash
uv run jubilant-recorder generate session.json --out test_demo.py >/dev/null && cat test_demo.py
```

```output
import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ubuntu', channel='stable')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active, timeout=900)
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, 'ubuntu'))
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        # checkpoint: deployed
        juju.config('ubuntu', values={'hostname': 'demo-host'})
        juju.wait(jubilant.all_active, timeout=300)
        juju.wait(lambda s: jubilant.all_active(s, 'ubuntu'))
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        # checkpoint: reconfigured
```

The `for _u in ...units.values()` loop came from an `assert_status` gesture, and works in any model. The tagger now emits the same shape for what it infers: a recorded unit name is an artefact of the recording, not a fact about the replay, so it never reaches the generated test. Where only some of an app's units reached a status, the tagger emits `any(...)` rather than the loop, so it does not claim more than the recording saw.

"Does that test pass?" is now a fair question to invite rather than one to deflect.

## 3. --ai

Two optional LLM passes: the tagger proposes extra assertions, and a polisher renames the test and adds a docstring. Both go through OpenRouter. With no key set, the flag warns and falls back to deterministic output rather than pretending.

```bash
env -u OPENROUTER_API_KEY uv run jubilant-recorder generate session.json --out /tmp/nokey.py 2>&1 | tail -2
```

```output
/tmp/nokey.py
```

With a key, it makes a real call:

```bash
OPENROUTER_API_KEY=$(cat ~/.jtr.key) uv run jubilant-recorder generate session.json --out test_demo_ai.py --ai 2>&1 >/dev/null | tail -2; diff test_demo.py test_demo_ai.py; echo "(diff exit $?: 0 means --ai changed nothing at all)"
```

```output
4c4,5
< def test_recorded_session():
---
> def test_ubuntu_deploy_config_reaches_active_status():
>     """Deploys ubuntu, waits for active status, then verifies config changes keep it active."""
16a18,21
>         assert any(
>             _u.workload_status.current == 'active'
>             for _u in juju.status().apps['ubuntu'].units.values()
>         )
20c25
<         # checkpoint: reconfigured
---
>         # checkpoint: reconfigured
\ No newline at end of file
(diff exit 1: 0 means --ai changed nothing at all)
```

There are two LLM passes, and they are not equally constrained. The **polisher** may rename the test and add a docstring, and a guard discards its output entirely if the assertions come back different - the prompt already forbade that, but nothing checked until it was tested. The **proposer** is allowed to add assertions, because that is its job.

The proposer is the one to watch. It did not only add assertions: given a gesture that had already asserted a status app-wide, it restated the same claim as a hardcoded `units['ubuntu/1']`, and the generated test carried both - once portably, once in a form that raises `KeyError` in a fresh model. The gesture said what to assert and the proposal talked over it.

Deduplication now compares what a tag *claims* - app and expected status - as well as its exact identity, so a proposal that restates an existing assertion at a different scope is dropped. A proposal about a status nothing has asserted yet is still added, which is the proposer's job.

That fixed the restating half and not the originating one. A proposal no gesture had covered still reached the test pinned to `units['ubuntu/1']`, because the coverage check has nothing to match it against - `uv run pytest` on the `--ai` output failed there for real. Proposals are now converted app-scoped at the point they become tags, so no unit name reaches the generated test by any route; `any(...)` rather than the loop, since a proposal is evidence about the one unit it names and asserting every unit would claim more than the model said. What `--ai` adds above is that shape, and the test it produces passes.

Worth knowing which of the two passes was responsible before blaming the wrong one, as I did at first: the polisher is innocent here, and the guard below proves it is being checked.

Here is the polisher guard refusing a sabotaged polish:

```bash
uv run python -c "
from jubilant_recorder.codegen.ai_polish import polish
original = open('test_demo.py').read()
sabotaged = original.replace(\"== 'active'\", \"== 'blocked'\", 1)
class Bad:
    def polish(self, code, log): return sabotaged
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    out = polish(original, {}, polisher=Bad())
print('LLM output used:', out != original)
print('warning:', str(w[0].message) if w else 'none')
"
```

```output
LLM output used: False
warning: LLM polish changed the test's assertions — using deterministic output
```

## 4. libjuju mode

The same pipeline works for libjuju-driven tests. A tap on `Connection.rpc()` records the RPCs and the AllWatcher deltas, correlates them, and emits the same session-log schema - so the tagger and codegen are reused unchanged. This session log was captured from a live libjuju run:

```bash
python3 -c "import json; d=json.load(open('examples/libjuju/session.json')); print(len(d['events']), 'events'); print([e['op'] for e in d['events']])"
```

```output
4 events
['deploy', 'wait_for_idle', 'config_get', '_libjuju_orphan_deltas']
```

```bash
uv run jubilant-recorder generate examples/libjuju/session.json --out /tmp/libjuju_test.py >/dev/null && head -14 /tmp/libjuju_test.py
```

```output
import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ch:amd64/noble/ubuntu', app='ubuntu')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active)
        juju.config('ubuntu')
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        assert len(juju.status().apps['ubuntu'].units) == 1
```

## 5. The shell hook

There is a third mode that records plain `juju` commands typed at a prompt. It has two lanes: a PATH shim records `juju` itself, and bash-preexec hooks record context commands around it (`kubectl`, `lxc`, `charmcraft`, `curl`). `juju` is the first entry in `_BASENAME_DENYLIST`, so the hook lane drops it deliberately rather than double-recording what the shim already has.

`showboat verify` still cannot cover this section: it runs each block with `bash -c`, and the hook lane fires from the DEBUG trap and `PROMPT_COMMAND`, neither of which runs without a prompt cycle. What does work is a pseudo-terminal. `tests/manual/verify-shell-hook.sh --auto` drives the same sequence under `script -qec` and then checks the log, so the lane is verifiable at rehearsal rather than trusted from a transcript recorded a week earlier.

That is a correction to what this section used to say. It claimed anything driven non-interactively records zero events whether the hook works or not; measured again, the discriminator is the pty and not the person. `script -qec` fires the hooks whether bash-preexec is sourced from an rcfile or typed by hand, and only piping into `bash -i` records nothing.

**Verified 2026-09-10**, both lanes, via `--auto`:

```output
4 events, 3 shell events
   [shim] juju status -m jtr-demo
   [shim] juju models
   [hook] kubectl version --client
PASS: juju commands recorded via the shim lane, and 1 context command(s) via the hook lane.
```

Both `juju` invocations through the shim with the right argv, and the `kubectl` through the hook — the first time that lane has been covered at all. The `echo` is correctly absent: it is in neither `_BASENAME_DENYLIST` nor `_CONTEXT_ALLOWLIST`, and the hook drops anything outside the allowlist. So would a `cat`, for the same reason; the allowlist is `kubectl`, `k8s`, `microk8s`, `lxc`, `lxd`, `charmcraft`, `rockcraft`, `snapcraft`, `curl`, `http`, `wget`.

`--auto` does not retire the manual path. It cannot rule out a difference between this harness and a real login shell, and a person at a prompt remains the stronger evidence — it means the weaker evidence is available every time rather than once a week.

One limit worth knowing before this mode goes on stage: **`jtr shim install` is a required step**, and is in the script's printed sequence. `jtr shell-init` puts `~/.local/share/jtr/shims` on PATH but does not create it. Skip it and `juju` resolves to the real binary: every command works perfectly and the log holds nothing but a `session_end`, which reads exactly like the bash-preexec registration bug and is not it.

There used to be a second limit here, saying this run verified the shim lane and not the hook lane because no context command was typed. That stopped being true when `--auto` grew the `kubectl` line above, and the bullet outlived it.

What the shim records has grown too. It runs the real binary as a child rather than `exec`-ing it, so it knows the exit code — a command that failed during recording is commented out of the generated test rather than emitted as a line claiming it worked. And every `juju status` is a sampling point: the shim captures `juju status --format=json` alongside it, which is what lets the tagger derive assertions from a session nobody scripted. Set `JTR_NO_SNAPSHOT=1` to turn that off and lose them.

## 6. Migrating a pytest-operator suite

This is what libjuju mode is for. A charm has an integration suite written against python-libjuju, and translating it to jubilant by hand is a day of careful work. Run the suite you already have, with one extra flag.

```bash
cat examples/pytest_operator/tests/integration/test_charm.py | sed -n '22,40p'
```

```output
PEER = "ubuntu-peer"


@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest):
    """Deploy the applications under test."""
    await asyncio.gather(
        ops_test.model.deploy(APP, application_name=APP, num_units=1, base="ubuntu@24.04"),
        ops_test.model.deploy(APP, application_name=PEER, num_units=1, base="ubuntu@24.04"),
    )
    await ops_test.model.wait_for_idle(apps=[APP, PEER], status="active", timeout=900)
    assert ops_test.model.applications[APP].status == "active"


async def test_read_config(ops_test: OpsTest):
    """Read an application's configuration."""
    config = await ops_test.model.applications[APP].get_config()
    logger.info("%s config keys: %s", APP, sorted(config))
    assert isinstance(config, dict)
```

Nothing about the suite changes - no conftest edit, no import. The plugin ships with jubilant-recorder and registers itself with pytest, hooking nothing unless one of its options is passed.

```bash
cd examples/pytest_operator && time uv run --with pytest-operator --with pytest-asyncio --with-editable ../.. pytest tests/integration -q --jtr-out=/tmp/test_migrated.py 2>&1 | tail -4
```

```output
.....                                                                    [100%]
jubilant-recorder: wrote /tmp/test_migrated.py

5 passed in 192.12s (0:03:12)

real	3m15.033s
user	0m3.795s
sys	0m5.617s
```

Each test in the suite becomes a test in the output, in the order they ran, sharing a module-scoped juju fixture. That is not decoration: pytest-operator's own ops_test fixture is module-scoped too, so its tests run in order against one model and each builds on what the last left behind. A temp_model() per test would hand every test after the first an empty model.

```bash
cat /tmp/test_migrated.py
```

```output
import jubilant
import pytest


@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju: jubilant.Juju):
    juju.deploy('ch:amd64/noble/ubuntu', app='ubuntu')
    assert len(juju.status().apps['ubuntu'].units) == 1
    juju.deploy('ch:amd64/noble/ubuntu', app='ubuntu-peer')
    assert len(juju.status().apps['ubuntu-peer'].units) == 1
    juju.wait(jubilant.all_active)
    for _u in juju.status().apps['ubuntu'].units.values():
        assert _u.workload_status.current == 'active'
    for _u in juju.status().apps['ubuntu-peer'].units.values():
        assert _u.workload_status.current == 'active'


def test_read_config(juju: jubilant.Juju):
    juju.config('ubuntu')


def test_scale_up(juju: jubilant.Juju):
    juju.add_unit('ubuntu', num_units=1)
    # TODO: manual step — codegen can't represent mixed unit statuses for ubuntu: ubuntu/0=active, ubuntu/1=waiting
    juju.wait(jubilant.all_active)
    for _u in juju.status().apps['ubuntu'].units.values():
        assert _u.workload_status.current == 'active'


def test_scale_down(juju: jubilant.Juju):
    juju.remove_unit('ubuntu/1')
    assert len(juju.status().apps['ubuntu'].units) == 1
    for _u in juju.status().apps['ubuntu'].units.values():
        assert _u.workload_status.current == 'active'
    for _u in juju.status().apps['ubuntu-peer'].units.values():
        assert _u.workload_status.current == 'active'
    assert len(juju.status().apps['ubuntu'].units) == 1
    assert len(juju.status().apps['ubuntu-peer'].units) == 1


def test_remove_peer(juju: jubilant.Juju):
    juju.remove_application('ubuntu-peer')
```

A starting point, not a finished suite. The recorder sees what each test *did* to the model; it cannot see what the test meant, and a test's own assertions live in Python that never reaches the wire - `assert ops_test.model.applications[x].status == "active"` is a comparison on a locally cached object, not an RPC. What survives automatically is the sequence of operations plus whatever the delta tagger can derive from the model actually changing. Read the file and expect to add the checks back; it is still a much shorter job than starting from the original.

## Rehearsing

See [running-the-demo.md](running-the-demo.md) for how to rehearse this
document, what it needs, and which blocks always differ.
