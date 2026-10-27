# Decision engine P1 (experimental)

`m8shift-decision.py` is a **read-only, offline, provider-neutral recommendation layer**.
It does not change the M8Shift mutex, handoffs, permissions, agent selection or runtime.
No network, credentials or AI API calls are required.

## Usage

```sh
python3 m8shift-decision.py "Implement scoped fix" --complexity moderate --has-tests
python3 m8shift-decision.py "Production migration" --risk critical --budget economy
python3 -m unittest discover -s tests -p 'test_decision_engine.py'
```

JSON output follows `m8shift.routing.v1`. Its `status: proposed` means **advisory only**.
The `model_tier` values are generic, not model identifiers: economy, balanced, advanced.
Effort values are advisory and require provider-specific mapping.

## Safety and limitations

- A critical-risk task requires human approval and max effort even under economy budget.
- Two consecutive failures request advisor escalation; four select max effort.
- Parallel is recommended only when independent parts are declared and risk is below high.
- No task text or other sensitive content is sent to a third party.
- The module does **not** execute, price, or validate recommendations.
- No LLM-based risk classification is implemented: the caller supplies risk and complexity.
- A runtime adapter, external JEV advisor, audit log and benchmarks are deferred to later phases.
- The existing pen remains the sole authority for write access.

## P2: bridge to the existing runtime router

The repository already has an authoritative **advisory** recommendation implementation:
`m8shift-runtime.py route recommend`, backed by
`.m8shift/routing/models.json` and `.m8shift/routing/skills.json`.
The new deterministic policy must **not** replace that model registry or its
capability/context floor checks.

`m8shift-routing-bridge.py` is a read-only composition layer:

```sh
python3 m8shift-routing-bridge.py "Review an auth migration" \
  --task-type review --risk high --complexity high
python3 -m unittest discover -s tests -p 'test_routing_bridge.py'
```

Use a task type declared by the project's `routing/skills.json`.
The bridge asks the existing runtime for a recommendation, then combines it with
risk/effort/approval advice from `m8shift-decision.py`. Its output is never
launch authority. Runtime manifest errors produce `runtime_ok=false` and
`requires_manual_resolution=true`. The caller must separately validate model
availability, provider mapping, approvals, and actual pen ownership.

**P2 limitation:** the two policies are composed, not automatically reconciled.
The bridge may report different effort levels from the native runtime and the
risk policy. A future explicit policy arbitration step must fail closed on
disagreement, never silently downgrade the stronger safety requirement.
