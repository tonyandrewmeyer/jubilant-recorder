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

One block will always differ and that is expected: the deploy block reports
wall-clock time.

The unit number used to be the second one. It is not any more - neither the
tagger nor the proposer puts a unit name in the generated test, so a stale
model changes the timing and nothing else. If a unit number does appear in a
diff, that is a regression rather than the usual noise.

## What it needs

- A juju model called `jtr-demo`. `juju add-model jtr-demo`. Removing the
  `ubuntu` application between runs is no longer needed to make the output
  match, since no unit name reaches the generated test, but a fresh model
  still deploys faster than one juju has to tear down first.
- An OpenRouter key at `~/.jtr.key`, for section 3. Without it that section
  still runs and shows the no-key path, which is worth showing anyway.
- `uvx`, for showboat itself.

## What it does not cover

The shell hook. It cannot be captured this way - bash-preexec fires from the
DEBUG trap and `PROMPT_COMMAND`, neither of which runs without a prompt cycle,
so a scripted run records zero events whether the hook works or not. Use
`tests/manual/verify-shell-hook.sh` in a real terminal instead.
