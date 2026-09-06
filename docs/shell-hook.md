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
| **PATH shim** | `juju` itself | a small executable named `juju`, earlier on `PATH` than the real one, which records and then `exec`s the real binary |
| **shell hook** | surrounding context commands (`kubectl`, `lxc`, `charmcraft`, `curl`) | `preexec`/`precmd` hooks in your shell |

`juju` is deliberately excluded from the hook lane — it is the first entry
in the hook's denylist — so the two never double-record. That means **if you
install the shell hook but not the shim, every juju command works perfectly
and none of them are recorded.** That is the most common way to get an empty
log.

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
jtr stop
jtr generate session.jsonl --out test_my_session.py
```

Call `jtr start` directly — not as `eval "$(jtr start …)"`. `shell-init`
defines a `jtr` shell function that applies the environment changes itself;
the `eval` form runs it in a subshell, which silently loses `JTR_SESSION`
after printing a cheerful "session started".

## Annotating as you go

| Command | Effect |
|---|---|
| `jtr note TEXT` | a free-text note, rendered as a comment |
| `jtr tag LABEL` | marks the next operation as the start of a step |
| `jtr pause` / `jtr resume` | stop and restart recording without ending the session |
| `jtr status` | what is being recorded, and where |
| `jtr tail` | follow the log as it is written |

## Controlling what is captured

The hook lane records an allowlist of context commands. Adjust it per
session:

```bash
jtr include 'terraform .*'     # also record these
jtr exclude 'kubectl logs .*'  # never record these
jtr redact 'password=\S+'      # keep the command, mask the match
```

Session logs can contain whatever you typed, so read one before you commit
it. See the note on secrets in the [README](../README.md#session-logs-and-secrets).

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

`scripts/verify-shell-hook.sh` walks through this by hand and reports which
of the two you are looking at. It has to be run by a person at a terminal:
bash-preexec fires from the `DEBUG` trap and `PROMPT_COMMAND`, which only
run on a prompt cycle, so a scripted harness records nothing whether the
hook works or not.
