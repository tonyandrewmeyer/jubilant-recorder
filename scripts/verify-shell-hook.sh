#!/bin/bash
# Shell-hook verification — MUST be run by a person, in a real terminal.
#
# The hook has never been exercised in an interactive terminal. The 2026-07-16
# validation drove bash and zsh under `script -qec`, which is a pty but not a
# person at a prompt, and that distinction turns out to matter: bash-preexec
# fires from the DEBUG trap and PROMPT_COMMAND, which only run on a prompt
# cycle. A script body has no prompt cycle, and driving `bash -i` over a pipe
# does not reliably produce one either. Three harness shapes were tried; all
# recorded zero events for that reason, which is indistinguishable from the
# hook being broken, and so tells you nothing.
#
# Usage: open a terminal, cd to a jubilant-recorder checkout, run:
#     bash verify-shell-hook.sh /path/to/checkout <juju-model>
# then follow the printed instructions and type the commands yourself.

set -uo pipefail
CHECKOUT="${1:-$PWD}"
MODEL="${2:-}"
LOG="${CHECKOUT}/hook-verify.jsonl"

if [ -z "$MODEL" ]; then
    echo "usage: bash verify-shell-hook.sh <checkout> <juju-model>" >&2
    exit 64
fi

# --check must not touch the log it is about to read. Everything from here to
# the end of the instructions block is setup for a *fresh* run, and running it
# on the check pass deleted the evidence and then reported it missing.
if [ "${3:-}" = "--check" ] || [ "${MODEL}" = "--check" ]; then
    CHECK_ONLY=1
else
    CHECK_ONLY=0
fi

if [ "$CHECK_ONLY" = "0" ]; then
if [ ! -f ~/bash-preexec.sh ]; then
    echo "fetching bash-preexec…"
    curl -fsSL https://raw.githubusercontent.com/rcaloras/bash-preexec/master/bash-preexec.sh \
        -o ~/bash-preexec.sh || { echo "could not fetch bash-preexec" >&2; exit 1; }
fi

rm -f "$LOG"

cat <<INSTRUCTIONS

Run these, by hand, at your own prompt - do not paste them all at once, and do
not run them from a script. The point is that a human prompt cycle happens
between each one.

    export PATH="${CHECKOUT}/.venv/bin:\$PATH"
    source ~/bash-preexec.sh
    eval "\$(jtr shell-init --shell bash)"
    jtr start verify --output ${LOG}
    juju status -m ${MODEL}
    juju models
    echo this-is-not-juju
    jtr stop

Then run:

    bash verify-shell-hook.sh ${CHECKOUT} ${MODEL} --check

WHAT TO LOOK FOR. The log should carry a shell event for each of the two juju
commands and NOT for the echo. Zero events means the hook is not wired up (bash-preexec
ignoring a bare preexec/precmd function) and means the hook is not wired up,
even though every command appeared to work.

Note that 'jtr start' must be called directly, not as eval "\$(jtr start …)".
shell-init defines a jtr shell function that applies the env changes itself; the
eval form runs it in a subshell and silently loses JTR_SESSION, after printing a
cheerful "session started" message. SHELL-HOOK-IMPL-STATUS.md's table says
'prints export JTR_SESSION=…', which invites exactly that mistake.

INSTRUCTIONS
fi

if [ "$CHECK_ONLY" = "1" ]; then
    echo "--- checking ${LOG} ---"
    if [ ! -f "$LOG" ]; then
        echo "FAIL: no log at ${LOG}. jtr start did not take effect."
        exit 1
    fi
    python3 - "$LOG" <<'PY'
import json, sys
events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
shell = [e for e in events if e.get("op") in ("shell", "shell_context")]
cmds = [(e.get("args") or {}).get("cmd", "") for e in shell]
print(f"{len(events)} events, {len(shell)} shell events")
for c in cmds:
    print("  ", c)
juju = [c for c in cmds if c.strip().startswith("juju ")]
echoes = [c for c in cmds if c.strip().startswith("echo ")]
if not shell:
    print("FAIL: zero shell events - the hook is not wired up.")
    sys.exit(1)
if len(juju) < 2:
    print(f"FAIL: expected 2 juju commands, recorded {len(juju)}.")
    sys.exit(1)
if echoes:
    print("WARN: a non-juju command was recorded; the shim should only see juju.")
print("PASS: juju commands recorded, hook is live.")
PY
fi
