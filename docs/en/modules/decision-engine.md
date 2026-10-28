# Advisory decision engine

Version: 4.2.0 source companion. Protocol impact: **no**.

The engine and bridge are opt-in command-line companions. They do not acquire
or route the pen, launch a provider, change permissions, write the relay or
approve a merge. Their JSON always carries `authority: advisory`, `launch:
false`, and the bridge also emits `execution_authorized: false`.

## Offline policy

```sh
python3 m8shift-decision.py "Implement a scoped fix" --complexity moderate --has-tests
python3 m8shift-decision.py "Review a migration" --risk critical --budget economy
```

The caller supplies risk and complexity; there is no hidden task classifier.
Two failures require an advisor and advanced tier; four require maximum effort.
Critical risk additionally requires human approval. Cost preference cannot lower
these floors. Parallel work is recommended only for declared independent parts
at low/moderate effective severity, never after an escalation. Task text is
neither sent to a provider nor copied into the recommendation.

`economy`, `balanced` and `quality` are policy preferences, not monetary budgets.
The first two currently share the same safety floors; `quality` raises the
minimum policy tier to balanced. There are no prices or savings claims.

## Bridge to the real runtime

Use the source checkout with `m8shift-decision.py`, `m8shift-routing-bridge.py`
and `m8shift-runtime.py` alongside each other. The selected relay must already
be initialized and contain `m8shift.py`. This optional source companion is not
silently enabled in an existing installation or listener.

```sh
python3 -B m8shift-routing-bridge.py "Review a scoped change" \
  --project-root /path/to/initialized-relay \
  --task-type review-critique --input-tokens 24000 --has-tests
```

The bridge calls the shipped `route recommend` command, with the explicit
instance root and input-token estimate. It uses the instance's existing
`.m8shift/routing/models.json` and `skills.json`, not a second model database.

Root selection is: explicit `--project-root`, then `M8SHIFT_ROOT`, then the
current working directory. A conflicting explicit/environment pair, an empty
environment root, or an uninitialized root is refused. **There is no fallback
to the engine's own directory.** This prevents a shared checkout from silently
reading the coordinating relay instead of the intended instance.

The model catalog must be explicitly enabled (`"enabled": true`). The runtime's
initial empty/disabled catalog is not an invitation to invent a model. Skills
may also be explicitly disabled. Supply actual provider/model identifiers and
capabilities in the existing catalog, for example:

```json
{
  "id": "operator-selected-model",
  "provider": "operator-selected-provider",
  "tier": "balanced",
  "cost_band": "$$",
  "latency": "medium",
  "context_class": "large",
  "capabilities": ["read_repo", "write_repo", "review"]
}
```

This example is a row, not a complete catalog and not a vendor recommendation.
The full catalog retains the native `m8shift.routing.models.v1` schema and its
ordered bands. Never paste credentials into either manifest.

## Conservative reconciliation

| Policy tier | Native catalog floor |
| --- | --- |
| economy | economy |
| balanced | balanced |
| advanced | flagship |

The native floor and the policy floor are combined by taking the stronger.
Only models in the runtime's feasible set may be selected. Every candidate must
also agree with its catalog entry on tier, context, cost band and latency, and
satisfy the required capabilities and context. A forged, missing or duplicate
candidate fails closed. Native candidate order remains the cost/latency order;
this bridge does not introduce a competing price algorithm.

The current bridge supports the native canonical tier order above. A custom
order is refused rather than silently reinterpreted. Native context-class order
is retained. Unknown efforts are refused; recognized efforts are reconciled by
taking the stronger of `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`.
A pinned native route requires an advisor and direct execution strategy even
when the caller supplies a low-risk hint.

Capability evidence means **agreement with an operator-maintained local
manifest**, not an empirical model benchmark. The output says
`provider_availability: not_probed` and `provider_effort: not_applied`.
Provider-specific effort translation, quota admission and actual availability
must be verified by the execution path. No claim of live-provider validation is
made by a successful advisory result.

## Result and exit status

| Exit | Meaning |
| --- | --- |
| 0 | Internally resolved advisory plan, with no outstanding policy review requirement. **Not launch authority.** |
| 1 | Invalid input/configuration, unavailable native runtime, changed manifests, timeout or no compatible model. |
| 2 | Command-line syntax error from argparse. |
| 3 | Compatible advisory plan exists, but advisor and/or human review is required. |

Structured refusals go to stderr; plans go to stdout. `resolution_status`
distinguishes `resolved`, `blocked` and `review_required`. A native `ok: true`
fallback with no feasible candidate can never become bridge success. Provider
stderr, real root paths and task prose are not copied into a refusal.

Both manifest digests are captured before the native call and checked again
after it. This detects ordinary concurrent edits, not an adversary rewriting
and restoring both files between reads. The data is a local consistency
observation, not a signature or a transactional lock. Reads do not create
bytecode or change application-controlled relay files; bounded-lifetime scratch
output is kept outside the relay and discarded. JSON input/consumed output is
limited to 1 MiB, model catalogs to 512 rows, and runtime execution to at most
60 seconds (`--timeout`, default 15). Duplicate JSON keys and non-finite JSON
numbers are rejected.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_decision_engine.py' -v
python3 -m unittest discover -s tests -p 'test_routing_bridge.py' -v
python3 -m pytest -q
sha256sum -c checksums.sha256
```

The targeted suite exercises the **real shipped core and runtime** on disposable
initialized relays, including cross-root refusal, native capability/context
filtering, unknown-task fallback, critical-risk review, and unchanged relay
bytes/mtime. Unit tests cover effort combinations, malformed evidence, manifest
mutation, duplicate keys, timeouts and authority validation. As with every test
module in this repository, ambient relay settings are purged before loading the
product. Both new companions and their tests are included in the checksum
manifest.

## Scope boundary

This is the completed local recommendation path, not an autonomous orchestrator.
JEV network routing, provider invocation, advisor response collection, pricing,
quota telemetry and an independent merge review are separate work. The bridge
exposes review requirements but cannot fabricate the missing review or dismiss
it. A native read-only consultation may be used by the operator; no consultation
is started implicitly and no task data leaves the host through this feature.
