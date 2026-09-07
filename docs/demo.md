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

real	1m17.362s
user	0m5.066s
sys	0m2.573s
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
        for _u in juju.status().apps['ubuntu'].units.values():
            assert _u.workload_status.current == 'active'
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
16a17,20
>         assert any(
>             _u.workload_status.current == 'active'
>             for _u in juju.status().apps['ubuntu'].units.values()
>         )
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
        config_3 = juju.config('ubuntu')
```

## 5. The shell hook

There is a third mode that records plain `juju` commands typed at a prompt. It has two lanes: a PATH shim records `juju` itself, and bash-preexec hooks record context commands around it (`kubectl`, `lxc`, `charmcraft`, `curl`). `juju` is the first entry in `_BASENAME_DENYLIST`, so the hook lane drops it deliberately rather than double-recording what the shim already has.

`showboat verify` still cannot cover this section: it runs each block with `bash -c`, and the hook lane fires from the DEBUG trap and `PROMPT_COMMAND`, neither of which runs without a prompt cycle. What does work is a pseudo-terminal. `tests/manual/verify-shell-hook.sh --auto` drives the same sequence under `script -qec` and then checks the log, so the lane is verifiable at rehearsal rather than trusted from a transcript recorded a week earlier.

That is a correction to what this section used to say. It claimed anything driven non-interactively records zero events whether the hook works or not; measured again, the discriminator is the pty and not the person. `script -qec` fires the hooks whether bash-preexec is sourced from an rcfile or typed by hand, and only piping into `bash -i` records nothing.

**Verified 2026-09-07**, both lanes, via `--auto`:

```output
4 events, 3 shell events
   [shim] juju status -m jtr-demo
   [shim] juju models
   [hook] kubectl version --client
PASS: juju commands recorded via the shim lane, and 1 context command(s) via the hook lane.
```

Both `juju` invocations through the shim with the right argv, and the `kubectl` through the hook — the first time that lane has been covered at all. The `echo` is correctly absent: it is in neither `_BASENAME_DENYLIST` nor `_CONTEXT_ALLOWLIST`, and the hook drops anything outside the allowlist. So would a `cat`, for the same reason; the allowlist is `kubectl`, `k8s`, `microk8s`, `lxc`, `lxd`, `charmcraft`, `rockcraft`, `snapcraft`, `curl`, `http`, `wget`.

`--auto` does not retire the manual path. It cannot rule out a difference between this harness and a real login shell, and a person at a prompt remains the stronger evidence — it means the weaker evidence is available every time rather than once a week.

Two limits on that result, both worth knowing before this mode goes on stage:

- **It verifies the shim lane, not the hook lane.** The shim is pure PATH resolution and does not need a prompt cycle, so this run says nothing about whether `preexec`/`precmd` fire — no context command was typed. If the demo shows `kubectl` or `charmcraft` being recorded alongside `juju`, add one to the sequence and re-run the check first.
- **`jtr shim install` is a required step**, and is in the script's printed sequence. `jtr shell-init` puts `~/.local/share/jtr/shims` on PATH but does not create it. Skip it and `juju` resolves to the real binary: every command works perfectly and the log holds nothing but a `session_end`, which reads exactly like the bash-preexec registration bug and is not it.

## Rehearsing

See [running-the-demo.md](running-the-demo.md) for how to rehearse this
document, what it needs, and which blocks always differ.
