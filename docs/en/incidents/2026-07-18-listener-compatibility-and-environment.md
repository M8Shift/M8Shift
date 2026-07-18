# Listener compatibility and environment-block incident

Status: reproduced; corrective implementation tracked by #208 and #209.

## Scope

A listener can supervise a headless runner from a different kit generation. The
runtime currently checks only that the runner path exists. It then sends the
current option set to that runner. Some options are conditional: for example,
`--agent-model` is present only when the profile pins a model.

A pre-handshake runner rejects an unknown option in `argparse` before it can
start the provider. Exit code 2 is currently treated as a retryable
infrastructure failure, so the listener repeats an incompatibility that cannot
heal and eventually persists `halted` after exhausting its retry budget.

Separately, a provider can be unable to write in its configured project or
runtime directory. The runner does not capture the provider streams and its
post-run classifier inspects relay progress rather than the execution
environment. A deterministic environment refusal is consequently recorded as
retryable `non_completion`. Raw provider output can also flow into a detached
listener's durable service log.

The two causal paths are:

```text
runtime generation > runner generation
  -> unsupported conditional flag
  -> argparse rc 2 before provider launch
  -> retryable infrastructure classification
  -> repeated launch attempts -> halted

project/runtime directory is not writable
  -> provider refuses before relay progress
  -> child streams are not classified
  -> non_completion
  -> repeated provider attempts -> halted
```

## Hermetic reproductions

`TestListenerCompatibilityIncident` uses only synthetic names and temporary
paths:

- a small legacy `ArgumentParser` runner proves that the conditional model flag
  exits 2 before the provider marker is written;
- a writable-directory provider proves that merely quoting words such as
  "read-only file system" remains ambiguous and retryable;
- a permission-denied working directory plus the same synthetic provider output
  specifies the corrected terminal classification and redaction behavior.

The corrected contracts use `unittest.expectedFailure`. This is intentional:
the current defects are visible without making the regression suite red, while
a fix produces an unexpected success and therefore fails CI until Slice C
removes the matching decorator. Both unittest discovery and pytest collect the
same methods.

## Corrective boundaries

The compatibility probe must execute the runner with the current Python
interpreter, never launch a provider, time out within 10 seconds, and inspect at
most the first 4 KiB. A new runner returns one JSON line with schema
`m8shift.runner.handshake.v1`. A file that exists, exits 2, and writes no stdout
is legacy. Missing, unlaunchable, timed-out, or otherwise malformed runners are
reported separately with an actionable provisioning command.

Environment classification is probe-led, not text-led. It checks both the
provider working directory and runtime directory with permission inspection and
an exclusive create/unlink attempt. Text signatures are advisory only. A
signature without a confirming probe remains retryable `non_completion`; any
ambiguity remains retryable. A confirmed block becomes terminal
`environment_blocked` after one attempt.

Provider streams are drained without deadlock and decoded with replacement.
They may be echoed only to an interactive TTY. Durable logs, run ledgers,
listener state, fleet state, and notifications receive closed enums, signature
identifiers, and byte/line counts only—never provider-derived text.

## PR boundary

This incident record and its repros form Slice A as a standalone PR. Slice C
implements handshake, provisioning, bounded teeing, and terminal environment
classification, removing the two expected-failure decorators atomically with
the fixes. Slice D then unifies status projection and adds the reason slot.
