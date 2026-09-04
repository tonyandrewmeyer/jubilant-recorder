# Examples

Live recording scripts used to drive `jubilant-recorder` against real Juju
controllers during development. Each script imports `jubilant_recorder` and
exercises a different scenario; running it writes a session log that the
codegen then turns into a pytest test file. The captured logs are committed
under `tests/fixtures/` as regression fixtures.

| Script | Scenario | Fixture |
|---|---|---|
| `deploy_ubuntu_live.py` | charm-ubuntu deploy + status (smallest end-to-end) | `deploy_ubuntu.jsonl` |
| `postgresql_integrate_live.py` | postgresql + data-integrator deploy + integrate | `postgresql_integrate.jsonl` |
| `postgresql_config_action_live.py` | as above, plus a config change and a run-action | `postgresql_config_action.jsonl` |
| `k8s_wait_timeout_live.py` | data-integrator on Canonical Kubernetes (wait timeout case) | `k8s_wait_timeout.jsonl` |
| `deliberate_failures_live.py` | deliberate CLIError injection (deploy nonexistent charm, bad integrate) | `deliberate_failures.jsonl` |

Each script expects an existing Juju controller and model. They are *not*
unit tests; they are reference invocations of the recording API.
