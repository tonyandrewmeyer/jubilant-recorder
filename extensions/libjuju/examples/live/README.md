# Live libjuju → jubilant example

End-to-end proof that the `RecordingLibjuju` → correlator → codegen pipeline
works against a live juju controller.

## What's here

| File | Origin |
|---|---|
| `record.py` | The libjuju driver script. Deploys `ubuntu`, waits for idle, reads config; the middle two calls bracket `wait_for_idle` so trailing synthesis has bracketing bucket-1 RPCs. |
| `session.json` | Recorded SessionLog from the live run (juju 4.0.12 client, controller 3.6.23, libjuju 3.6.1.3, jubilant 1.10.0, LXD localhost). |
| `generated_test.py` | Output of `python -m jubilant_recorder.cli generate session.json` on `session.json`. |

## Reproducing

```bash
# In a VM with juju + jubilant + libjuju installed and a controller bootstrapped:
cd /path/to/jubilant-recorder
juju add-model jtr-live-example
PYTHONPATH=src:. uv run --with juju --with jubilant python \
    extensions/libjuju/examples/live/record.py /tmp/session.json jtr-live-example

PYTHONPATH=src uv run --with jubilant python -m jubilant_recorder.cli \
    generate /tmp/session.json --out /tmp/generated_test.py --name test_ubuntu_deploy

juju destroy-model jtr-live-example --force --no-prompt --release-storage
uv run --with pytest --with jubilant python -m pytest /tmp/generated_test.py -v
```

The generated test replays cleanly against a fresh model in ~90 s.

## Live findings (fixed in this commit)

Five real bugs surfaced by the first live run — none was exercised by the
unit-test corpus because the fake `Connection` never emitted them:

1. **`Base` object crashes JSON serialization.** libjuju leaves typed
   `juju.client._definitions.Base` instances (and similar) in outgoing
   `msg["params"]` and in AllWatcher delta payloads; the WebSocket encoder
   only sees the wire form. The tap was doing a plain `copy.deepcopy(params)`
   and later `json.dumps` blew up on close. Added `_normalise()` in
   `tap.py` that recursively converts libjuju-typed objects to
   `dict`/`list`/scalar shapes; used at both capture sites.
2. **`Application.DeployFromRepository` unmapped.** libjuju 3.6.1+ talking
   to juju 3.6+ controllers uses this facade method rather than the older
   `Application.Deploy`. Added the mapping in the bucket-1 table plus a
   dedicated `_extract_args` branch that JSON-decodes libjuju's
   `{"Args": ["<json-string>"]}` packaging.
3. **`Client.FullStatus` polling floods the event stream.** Both
   `model.get_status()` and `model.wait_for_idle()` are backed by
   `Client.FullStatus`; a single wait can fire it 100+ times. Added to
   `_INTERNAL_FACADE_METHODS`. Same treatment for `ModelConfig.ModelGet` /
   `ModelConfig.GetModelConstraints` / `Charms.ResolveCharms` /
   `Charms.AddCharm` — connection-setup and deploy plumbing rather than
   user intent.
4. **Charm URL with revision suffix rejected by jubilant CLI.**
   `DeployFromRepository` reports the resolved URL
   `ch:amd64/noble/ubuntu-26`; jubilant's `juju deploy` refuses
   revision-in-name. Added `_strip_charm_url_revision()` that removes a
   trailing `-<digits>` from the URL's final segment.
5. **`base.channel` conflated with charm channel.** The
   `DeployFromRepository` request carries `base = {name: ubuntu, channel:
   24.04/stable}` — the Ubuntu release channel, not the charm's tracking
   channel. Passing that to jubilant's `--channel` yields
   `charm or bundle not found for channel "24.04/stable"`. Fixed by
   dropping the `base.channel` fallback and letting the CLI default when
   the caller never pinned a charm channel.

## Known follow-ups (not addressed in this commit)

- `config_get` (bucket-1) still renders as `# TODO: manual step` in the
  generated test — the codegen op-emitter table is missing a
  `config_get` case.
- The synthetic trailer event `_libjuju_orphan_deltas` also renders as a
  `# TODO: manual step`. It's a diagnostic marker; codegen should suppress
  it.
