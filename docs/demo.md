# jubilant-recorder: record a juju session, get a test

*2026-09-04T11:13:16Z by Showboat 0.6.1*
<!-- showboat-id: 90663037-33f8-4018-83a2-c4208d39ecd5 -->

Integration tests for charms are tedious to write and easy to get subtly wrong. The premise here is that you already drive juju by hand when you are working something out, so record that and generate the test from it.

This document is executable: every block below was really run against a live juju model, and `showboat verify` re-runs them all and diffs the output. If something has drifted since it was written, it names the block.

```bash
juju version && uv run jubilant-recorder --help 2>&1 | head -12
```

```output
4.0.14-genericlinux-amd64
usage: recorder [-h] {start,stop,run,generate} ...

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
cat demo_record.py
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
time uv run python demo_record.py && echo '--- session log ---' && python3 -c "import json; d=json.load(open('session.json')); print(len(d['events']), 'events,', d['juju_version'])"
```

```output

real	2m11.440s
user	0m10.150s
sys	0m5.078s
--- session log ---
8 events, 4.0.14-genericlinux-amd64
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
        assert juju.status().apps['ubuntu'].units['ubuntu/1'].workload_status.current == 'active'
        juju.wait(lambda s: jubilant.all_active(s, *['ubuntu']))
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        # checkpoint: deployed
        juju.config('ubuntu', values={'hostname': 'demo-host'})
        juju.wait(jubilant.all_active, timeout=300)
        juju.wait(lambda s: jubilant.all_active(s, *['ubuntu']))
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
        # checkpoint: reconfigured
```

Two things worth pointing at. The `for _u in ...units.values()` loop came from an `assert_status` gesture, and works in any model. The line above it, with the unit name in brackets, came from the automatic tagger and hardcodes whichever unit number happened to be recorded - so the generated test raises `KeyError` in the fresh `temp_model` it opens for itself. That is a real bug rather than a demo artefact, and it is the honest answer to "does that test pass?": not yet.

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
11,12c11
<         for _u in juju.status().apps['ubuntu'].units.values():
<             assert _u.workload_status.current == 'active'
---
>         assert juju.status().apps['ubuntu'].units['ubuntu/1'].workload_status.current == 'active'
15a15
>         assert juju.status().apps['ubuntu'].units['ubuntu/1'].workload_status.current == 'active'
17,18c17
<         for _u in juju.status().apps['ubuntu'].units.values():
<             assert _u.workload_status.current == 'active'
---
>         assert juju.status().apps['ubuntu'].units['ubuntu/1'].workload_status.current == 'active'
(diff exit 1: 0 means --ai changed nothing at all)
```

There are two LLM passes, and they are not equally constrained. The **polisher** may rename the test and add a docstring, and a guard discards its output entirely if the assertions come back different - the prompt already forbade that, but nothing checked until it was tested. The **proposer** is allowed to add assertions, because that is its job.

The proposer is the one to watch, and the diff above is it: it does not only add assertions, it replaces the portable `for _u in ...units.values()` form with a hardcoded `units['ubuntu/1']` one. That is the same bug as in section 2, arriving by a second route - the gesture said what to assert and the proposer overrode it. Worth knowing which of the two passes is responsible before blaming the wrong one, as I did at first: the polisher is innocent here, and the guard below proves it is being checked.

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
python3 -c "import json; d=json.load(open('extensions/libjuju/examples/live/session.json')); print(len(d['events']), 'events'); print([e['op'] for e in d['events']])"
```

```output
4 events
['deploy', 'wait_for_idle', 'config_get', '_libjuju_orphan_deltas']
```

```bash
uv run jubilant-recorder generate extensions/libjuju/examples/live/session.json --out /tmp/libjuju_test.py >/dev/null && head -14 /tmp/libjuju_test.py
```

```output
import jubilant


def test_recorded_session():
    with jubilant.temp_model() as juju:
        juju.deploy('ch:amd64/noble/ubuntu', app='ubuntu')
        assert len(juju.status().apps['ubuntu'].units) == 1
        juju.wait(jubilant.all_active)
        config_3 = juju.config('ubuntu')
```

## 5. The shell hook

There is a third mode that records plain `juju` commands typed at a prompt, via a PATH shim plus bash-preexec hooks. It cannot be demonstrated from a script: bash-preexec fires from the DEBUG trap and PROMPT_COMMAND, which only run on a prompt cycle, so anything driven non-interactively records zero events whether the hook works or not.

Run `scripts/verify-shell-hook.sh` in a real terminal before demonstrating this one.

## Rehearsing

`uvx showboat verify demo.md` re-runs every block above and diffs the output against what is recorded here. Run it shortly before presenting: it will name the block that broke, rather than the audience finding it. It needs a juju model called `jtr-demo` and an OpenRouter key at `~/.jtr.key`.

The deploy block will differ on wall-clock time every run, and the unit number will differ if the model is not fresh. Both are expected.
