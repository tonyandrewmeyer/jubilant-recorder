# jubilant-recorder

Record a live jubilant session and replay it as a pytest integration test.

`jubilant-recorder` wraps `jubilant.Juju`, captures every CLI call plus a
lightweight model snapshot before and after, and turns the resulting session
log into an idiomatic pytest test file. The intent is to collapse integration
test authoring from "an hour of careful translation" to "do the thing, save
the test."

## Install

```bash
uv add jubilant-recorder            # or: pip install jubilant-recorder
```

Requires Python 3.11+ and `jubilant>=1.0`.

## Gesture API

The recorder captures every jubilant call, but the codegen is conservative
about what to assert. Call the gesture API from your recording script to
emit explicit assertions that survive into the generated test.

```python
from jubilant_recorder import (
    RecordingJuju,
    assert_action_result,
    assert_status,
    checkpoint,
)

with RecordingJuju.start("session.json") as juju:
    juju.deploy("my-charm", channel="edge")
    juju.wait_for_idle()
    assert_status("my-charm", "active")
    checkpoint("deployed")

    juju.run("my-charm/0", "do-thing", {"key": "val"})
    assert_action_result("latest", key="output", value="done")
```

Available calls:

| Call | What it does |
|---|---|
| `checkpoint(name, *, comment=None)` | Inject a checkpoint event. Renders as a `# checkpoint: <name>` comment in the generated test, used to delineate phases. |
| `assert_status(app=None, status=None, message=None, *, unit=None)` | Snapshot model status and emit an explicit `assert juju.status()…workload_status == <status>` line. With no args, emits a `# TODO: tighten this assertion` placeholder. |
| `assert_action_result(action_id, *, key=None, value=None)` | Attach an assertion to the most recent `juju.run(...)` event. Pass `"latest"` as `action_id`; codegen renders `assert result_<seq>.results[<key>] == <value>`. |

All gesture calls require an active `RecordingJuju.start(...)` context. Calling
one outside raises `RuntimeError`.

## CLI

The `jubilant-recorder` command provides four subcommands:

| Subcommand | Description |
|---|---|
| `jubilant-recorder start [--session-log PATH] [--model NAME]` | Begin a recording session. Writes `{pid, session_log_path, model, started_at}` to `$XDG_CACHE_HOME/jubilant-recorder/active.json` (or `~/.cache/jubilant-recorder/active.json`). Prints the session log path to stdout. |
| `jubilant-recorder stop` | Read the state file, finalise the session log if necessary, remove the state file. |
| `jubilant-recorder run [--session-log PATH] [--out TEST.py] [--name NAME] [-- CMD ARGS…]` | All-in-one: start a session, run `CMD` under the recorder (or `$SHELL` if no command given), stop, and generate a test alongside the session log. |
| `jubilant-recorder generate SESSION_LOG [--out TEST.py] [--name TEST_NAME]` | Pure post-processing: read a completed session log, run the tagger over it, and produce a pytest test file. |

`jubilant-recorder run` exports `JUBILANT_RECORDER_SESSION_LOG` into the
child process environment so user scripts can locate the active log.

## Repo layout

```
src/jubilant_recorder/   the package
tests/                   unit suite + fixture session logs
examples/                live recording scripts used during development
docs/ci-template/        GHA workflows for the standalone repo
```

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check
uv run pyright
```

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
