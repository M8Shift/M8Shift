# Usage checkpoint advisor (experimental)

The optional `m8shift-usage-advisor.py` companion accepts JSON from the existing
`m8shift-runtime.py usage guard --json` command and emits **read-only**
checkpoint/cooldown advice when a named agent has a fresh `near_limit`
classification and a valid usage ratio.

Example:

```sh
python3 m8shift-runtime.py usage guard --json > /tmp/usage-guard.json
python3 m8shift-usage-advisor.py --input /tmp/usage-guard.json
```

The advisor never selects a replacement agent, claims the pen, starts a provider,
places a usage hold, or writes to the relay. It does not send data to an API.
Unknown, stale, malformed or limit-hit measurements do not generate
near-limit advice. Its recommendation key is only a deterministic local
identifier, **not** a durable notification latch.

This is an initial optional feature, **not** the full Forgejo #412 port:
lease-owned publication, deduplication across process restarts, and doctor
recovery are not implemented. Existing M8Shift safety and release gates remain
authoritative.

Protocol impact: no.
