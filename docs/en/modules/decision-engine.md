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
