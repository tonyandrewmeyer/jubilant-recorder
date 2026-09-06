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

Two blocks will always differ and that is expected: the deploy block reports
wall-clock time, and the unit number in the generated test depends on whether
the model is fresh.

## What it needs

- A juju model called `jtr-demo`. `juju add-model jtr-demo`, and remove the
  `ubuntu` application between runs if you want the unit numbering to match.
- An OpenRouter key at `~/.jtr.key`, for section 3. Without it that section
  still runs and shows the no-key path, which is worth showing anyway.
- `uvx`, for showboat itself.

## What it does not cover

The shell hook. It cannot be captured this way - bash-preexec fires from the
DEBUG trap and `PROMPT_COMMAND`, neither of which runs without a prompt cycle,
so a scripted run records zero events whether the hook works or not. Use
`scripts/verify-shell-hook.sh` in a real terminal instead.
