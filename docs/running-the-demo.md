# Running the demo

`demo.md` is a [showboat](https://pypi.org/project/showboat/) document: prose
plus code blocks that were really executed, with their real output captured
underneath. It is not a slide deck. It is the demo script, the proof it worked,
and the rehearsal harness, in one file.

## Rehearsing

```
uvx showboat verify docs/demo.md
```

That re-runs every code block and diffs the output against what is recorded. Run
it shortly before presenting: it names the block that broke, rather than the
audience finding it.

Three kinds of block always differ, and none of them mean anything is wrong:

- **Wall-clock time.** The deploy block and the migration block both report
  it.
- **The juju client version.** Two blocks print it, and it is whatever
  client the machine rehearsing has. The document is committed as recorded
  on a 3.6.28 client; a 4.x client differs on those lines and nowhere else.
- **The `--ai` diff.** It is a real call to a real model, so the test name
  and docstring it proposes will not be word-for-word what is recorded.
  What matters is the *shape*: assertions unchanged, one added `any(...)`
  block, and no unit number anywhere.

The unit number used to be the second one. It is not any more - neither the
tagger nor the proposer puts a unit name in the generated test, so a stale
model changes the timing and nothing else. If a unit number does appear in a
diff, that is a regression rather than the usual noise.

Re-recording the whole document, rather than diffing it, is one command:

```
uvx showboat verify docs/demo.md --output docs/demo.md
```

Read the diff before committing it, for the same reason the golden files
exist: an unexplained change there means codegen moved under you.

## What it needs

- A juju model called `jtr-demo`. `juju add-model jtr-demo`. Removing the
  `ubuntu` application between runs is no longer needed to make the output
  match, since no unit name reaches the generated test, but a fresh model
  still deploys faster than one juju has to tear down first.
- An OpenRouter key at `~/.jtr.key`, for section 3. Without it that section
  still runs and shows the no-key path, which is worth showing anyway.
- `uvx`, for showboat itself.
- A reachable controller for section 6, which runs a real `pytest-operator`
  suite (`examples/pytest_operator/`) under the recorder. It builds and
  tears down its own model, so it needs nothing from `jtr-demo`. Budget
  four minutes for it.

## What it does not cover

The shell hook's *hook* lane. It cannot be captured this way - bash-preexec
fires from the DEBUG trap and `PROMPT_COMMAND`, neither of which runs
without a prompt cycle, so a scripted block records zero events whether the
hook works or not. `tests/manual/verify-shell-hook.sh --auto` drives the
same sequence under a pseudo-terminal, which does fire the hooks, and
checks both lanes; run that at rehearsal, and the manual path in a real
terminal when it matters.

The shim lane has no such problem and is covered by `tests/e2e/` on every
release.
