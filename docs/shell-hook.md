# Shell capture (`jtr`)

Recording at a real prompt: you type `juju` commands as you normally would,
and `jtr` writes a session log you can turn into a pytest test.

This is the mode to use when you are exploring rather than scripting — when
you do not yet know what the deployment looks like, so writing it in Python
first is not an option.

## Two lanes

Shell capture is two independent mechanisms, and knowing which is which
saves a lot of confusion when something does not appear in the log:

| Lane | Records | How |
|---|---|---|
| **PATH shim** | `juju` itself | a small executable named `juju`, earlier on `PATH` than the real one, which records the command and then runs the real binary |
| **shell hook** | surrounding context commands (`kubectl`, `lxc`, `charmcraft`, `curl`) | `preexec`/`precmd` hooks in your shell |

`juju` is deliberately excluded from the hook lane — it is the first entry
in the hook's denylist — so the two never double-record. That means **if you
install the shell hook but not the shim, every juju command works perfectly
and none of them are recorded.** That is the most common way to get an empty
log.

The two lanes are independently useful, and they produce different things.
The shim's `juju` commands become jubilant calls. The hook's context
commands become comments, and only comments:

```python
        # context: kubectl get pods -n my-model
        # context: charmcraft pack
```

That is deliberate. A jubilant test drives juju, and `kubectl get pods`
has no jubilant equivalent to translate to — the closest thing is
`juju.ssh(unit, ..., container=…)` or `juju.exec(...)`, and which one you
meant is a judgement the recorder cannot make for you. The hook lane's job
is to tell you what you were doing around the juju work, so you can decide.

The hook records the command line and its exit status, never its output.

## Setup

```bash
jtr shim install          # materialises the juju shim
jtr shell install         # wires the hook into your shell rc file
```

`jtr shell install` edits your shell rc file. To see what it would add
without committing to it, use `jtr shell-init --shell bash` and eval it in
the current shell only:

```bash
source ~/bash-preexec.sh          # bash only; zsh has preexec built in
eval "$(jtr shell-init --shell bash)"
```

bash needs [bash-preexec](https://github.com/rcaloras/bash-preexec) for the
hook lane. The shim lane does not.

## Recording

```bash
jtr start my-session --output session.jsonl
juju deploy postgresql --channel 14/stable
juju integrate postgresql data-integrator
jtr note "waiting for the relation to settle"
juju status
jtr stop
jtr generate --session-log session.jsonl --out test_my_session.py
```

Call `jtr start` directly — not as `eval "$(jtr start …)"`. `shell-init`
defines a `jtr` shell function that applies the environment changes itself;
the `eval` form runs it in a subshell, which silently loses `JTR_SESSION`
after printing a cheerful "session started".

## What the generated test looks like

Every `juju` command you type becomes a jubilant call. Where jubilant has a
method for it, you get the typed method; where it does not, you get
`juju.cli(...)`, which is jubilant's own escape hatch and returns the
command's standard output. Nothing is left as a comment for you to retype.

```python
import jubilant


def test_my_session():
    with jubilant.temp_model() as juju:
        juju.deploy("postgresql", channel="14/stable")
        juju.integrate("postgresql", "data-integrator")
        # note: waiting for the relation to settle
        juju.status()
        for _u in juju.status().apps["postgresql"].units.values():
            assert _u.workload_status.current == "active"
```

Three things are worth knowing about how that is produced.

**`juju status` is the sampling point.** The shim captures `juju status
--format=json` alongside every `juju status` you run, and the tagger turns
the difference between two of those into an assertion — "between these two
looks, postgresql went from waiting to active". So the more often you check
status while you work, the more assertions the generated test has. Set
`JTR_NO_SNAPSHOT=1` to turn the extra call off; you lose the assertions.

**A command that failed is commented out.** The shim records the real exit
code, and a non-zero one means the recorded run did not do what the command
says. Rather than emit a line that claims otherwise, codegen renders it as
a comment with the exit code, so you can decide whether you meant it:

```python
        # `juju deploy nosuchcharm` exited 1 when recorded — left commented out:
        # juju.deploy('nosuchcharm')
```

**Model lifecycle is the fixture's job.** `juju add-model`, `destroy-model`
and `switch` naming the model you were working in render as a note rather
than a call, because `jubilant.temp_model()` in the generated test already
does that job — and `juju.add_model()` would point every later step at a
model the test never cleans up. A *different* model named in the same
session is translated literally.

A recorded `-m`/`--model` flag is dropped for the same reason: the test runs
in the model `temp_model()` made for it, and the model you recorded against
does not exist when the test runs.

## Annotating as you go

| Command | Effect |
|---|---|
| `jtr note TEXT` | a free-text note, rendered as a comment |
| `jtr tag LABEL` | marks the next operation as the start of a step |
| `jtr pause` / `jtr resume` | stop and restart recording without ending the session |
| `jtr status` | what is being recorded, and where |
| `jtr tail` | follow the log as it is written (`--jubilant-only` / `--context-only` to see one lane) |

## Controlling what is captured

The hook lane records an allowlist of context commands. Adjust it per
session — `include` and `exclude` take regular expressions, matched against
the whole command line:

```bash
jtr include 'terraform .*'     # also record these
jtr exclude 'kubectl logs .*'  # never record these
jtr redact 'cust-[0-9]+'       # keep the command, mask the match
```

`exclude` wins over `include`.

## Secrets

Command lines carry credentials — `juju add-secret mine token=hunter2` puts
one in argv, and argv is what gets recorded. The shim redacts as it writes:
a `key=value` whose key names a credential, a URL with embedded credentials,
a bearer token, and anything matching a `jtr redact` pattern are replaced
with a `<redacted:…>` marker before the event reaches the log. `jtr note`
text and captured command output go through the same pass.

Redaction is a safety net, not a guarantee. **Read a session log before you
commit it or attach it to a bug report.** See the note on secrets in the
[README](../README.md#session-logs-and-secrets).

## Sharing a session between terminals

```bash
jtr start deploy --shared      # in the first terminal
jtr attach                     # in the second
```

## If the log comes back empty

The two failure shapes look alike, so check in this order:

1. **No events at all**, including context commands: the hook is not wired
   up. Confirm `preexec`/`precmd` are defined, and on bash that
   `bash-preexec.sh` was sourced *before* `jtr shell-init` was eval'd.
2. **Context commands recorded, no juju**: the shim is not installed, or is
   not first on `PATH`. `which juju` should resolve to
   `~/.local/share/jtr/shims/juju`, not `/snap/bin/juju`.

`tests/manual/verify-shell-hook.sh` walks through this by hand and reports which
of the two you are looking at. It has to be run by a person at a terminal:
bash-preexec fires from the `DEBUG` trap and `PROMPT_COMMAND`, which only
run on a prompt cycle, so a scripted harness records nothing whether the
hook works or not.

The shim lane has no such constraint — it is just a binary on `PATH`, so it
records the same whether a person or a script is typing.
