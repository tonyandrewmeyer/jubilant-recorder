# Examples

Live recording scripts used to drive `jubilant-recorder` against real Juju
controllers during development. Each script imports `jubilant_recorder` and
exercises a different scenario; running it writes a session log that the
codegen then turns into a pytest test file. The captured logs are committed
under `tests/fixtures/` as regression fixtures.

| Script | Scenario | Fixture |
|---|---|---|
| `step3_live.py` | charm-ubuntu deploy + status (smallest end-to-end) | `step3_live_charm_ubuntu.jsonl` |
| `step9_session2_live.py` | postgresql + data-integrator deploy + integrate | `step9_session2_postgres_data_integrator.jsonl` |
| `step9_session3_live.py` | session 2 + config change + run-action | `step9_session3_postgres_data_integrator_full.jsonl` |
| `step9_real_world_k8s_live.py` | data-integrator on Canonical Kubernetes (wait timeout case) | `step9_real_world_k8s_data_integrator.jsonl` |
| `step10_failure_live.py` | deliberate CLIError injection (deploy nonexistent charm, bad integrate) | `step10_deliberate_failures.jsonl` |

Each script expects an existing Juju controller and model. They are *not*
unit tests; they are reference invocations of the recording API.
