# v3.64.0 release notes

## Version

**v3.64.0 (Révision).** Backwards-compatible bootstrap and headless-runtime
hardening. The release turns the bootstrap incident batch into an executable,
versioned contract without changing the relay format or granting companions any
core authority.

## Highlights

### Runner compatibility is checked before launch (#208, #216, #217)

The reference runner now answers a bounded `--handshake` probe using schema
`m8shift.runner.handshake.v1`. Its advertised capabilities include the bounded
TTY tee, environment write probe, and `runner-exit-v2`; supported options are
enumerated so the listener can distinguish current, legacy, broken, and absent
runners before a provider is started. Failed probes neither echo nor persist raw
child output and return a concrete provisioning remedy.

Classification is probe-led. A read-only-looking stderr phrase stays retryable
unless a real write probe in the configured working directory confirms the
environment block. Provider output is counted and reduced to bounded signature
IDs; sensitive raw text is not copied into listener state or notifications.

### Exit codes have one owner (#208)

`runner-exit-v2` is now explicit: 0 success, 1 classified run failure, 2 argparse
refusal, 3 external transition, 4 suspended, and 5 infrastructure failure or
timeout. The listener treats 2 as terminal only when no authoritative run-ledger
classification exists. Existing timeout/non-completion evidence wins over the
fallback exit code, while listener-side launch failures remain retryable.

### One listener truth table (#209, #219)

Core status, runtime status, doctor, and the generated runbook share the same
`listener_snapshot` decision. Lifecycle (`ALIVE`, `HALTED (resident)`,
`UNKNOWN`), coverage (`invoker`, `notifier`, `halted`, `absent`, `unknown`),
attention, and bounded `cause` fields now describe the same evidence everywhere.
The fold reads each listener, PID, presence, and usage-watcher sidecar once.

### Bootstrap is reentrant and useful (#207, #215, #220)

Headless/full init verifies and provisions the version-locked runner, writes a
marker-owned `.m8shift/BOOTSTRAP.md`, and renders self-documenting usage,
listener, handshake, dashboard, and halted-lane recovery commands. Re-init
updates only its generated block and preserves operator prose. Reversed or
duplicate markers refuse cleanly, while the exact pre-marker `# Bootstrap plan`
renderer is migrated once instead of being retained as stale pseudo-prose.

All scaffold mutations pass through the shared write gate. Update also preflights
a conflicting `M8SHIFT_ROOT` before protocol, pack, anchor, companion, runner, or
core writes, so a late companion refusal cannot leave the target half-updated.

## Known work

- #214 tracks the remaining lifecycle-watcher follow-up.
- #218 tracks the remaining `m8shift-top` presentation follow-up.

## Upgrade and verification

Update in place with the source-driven updater or the self-update wrapper. Relay
state remains byte-identical. Verify that `./m8shift.py --version` and every
installed companion/runner report 3.64.0, run both unittest discovery and pytest,
and exercise the release in an independently cloned Linux container before the
annotated tag is published. A final live-relay self-update is the required
dogfood gate.
