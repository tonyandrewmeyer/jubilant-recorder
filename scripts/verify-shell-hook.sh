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
    echo "usage: bash $0 <checkout> <juju-model>" >&2
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
    jtr shim install
    source ~/bash-preexec.sh
    eval "\$(jtr shell-init --shell bash)"
    jtr start verify --output ${LOG}
    juju status -m ${MODEL}
    juju models
    echo this-is-not-juju
    jtr stop

Then run:

    bash $0 ${CHECKOUT} ${MODEL} --check

WHAT TO LOOK FOR. The log should carry a shell event for each of the two juju
commands and NOT for the echo. Zero juju events means the recording is not wired
up, even though every command appeared to work.

WHY 'jtr shim install' IS IN THAT LIST. juju is recorded by the PATH shim, not
by the preexec/precmd hook - 'juju' is the first entry in _BASENAME_DENYLIST, so
the hook path drops it deliberately and the two lanes are complementary: the
shim records juju, the hook records context commands (kubectl, lxc, charmcraft,
curl). 'jtr shell-init' puts ~/.local/share/jtr/shims on PATH but does not
create it; 'jtr shim install' is what materialises the shim. Skip that step and
juju resolves to the real binary, every command works perfectly, and the log
carries nothing but a session_end - which reads exactly like the B1 bug and is
not it. That is what happened on 2026-09-06.

Two failures this distinguishes, since they look alike in the log:

  - zero events of ANY kind, with context commands typed too: the hook is not
    wired up (bash-preexec ignoring a bare preexec/precmd function - the B1
    shape).
  - context commands recorded but no juju: the shim is not installed, or is
    installed but not first on PATH.

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

# Neither lane writes an "args.cmd" key: the shim records args.argv as juju's
# own argv with source "shim", and the hook records args.argv as a
# single-element list holding the whole command line, with source "hook".
# Reading "cmd" gave every event an empty string, so the juju count was always
# zero and this check could never pass, however healthy the run.
def describe(e):
    args = e.get("args") or {}
    argv = args.get("argv") or []
    basename = args.get("basename") or ""
    if args.get("source") == "shim":
        return " ".join([basename, *argv]).strip()
    return " ".join(str(a) for a in argv).strip() or basename

def basename_of(e):
    return ((e.get("args") or {}).get("basename") or "").strip()

print(f"{len(events)} events, {len(shell)} shell events")
for e in shell:
    print(f"   [{(e.get('args') or {}).get('source', '?')}] {describe(e)}")

juju = [e for e in shell if basename_of(e) == "juju"]
echoes = [e for e in shell if basename_of(e) == "echo"]

if not shell:
    print("FAIL: zero shell events. Either jtr start did not take effect, or")
    print("      neither lane is wired up - see WHY 'jtr shim install' above.")
    sys.exit(1)
if len(juju) < 2:
    print(f"FAIL: expected 2 juju commands, recorded {len(juju)}.")
    print("      juju is the shim's lane, not the hook's. Check that")
    print("      `jtr shim install` ran and that `which juju` resolves to")
    print("      ~/.local/share/jtr/shims/juju rather than the real binary.")
    sys.exit(1)
if echoes:
    print("WARN: the echo was recorded. It should be filtered - echo is in")
    print("      neither _BASENAME_DENYLIST nor _CONTEXT_ALLOWLIST, and the")
    print("      hook lane drops anything outside the allowlist.")
print("PASS: juju commands recorded, recording is live.")
PY
fi
