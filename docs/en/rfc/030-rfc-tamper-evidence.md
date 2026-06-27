# RFC — Tamper-evident turn ledger (hash-chain)

**Status:** proposed (design / analysis) · **Motivated by:** the turn-forgery / third-party-intervention question — see the declarative-identity verdict (ASI03 / ASI07) in [owasp-agentic-top10-audit.md](owasp-agentic-top10-audit.md) and [security-research-and-frameworks.md](security-research-and-frameworks.md) §1.

## Question

Can M8Shift let an operator **detect** that a third party — another tool, a stray process,
or a person — altered the recorded coordination history (turns that were already closed) and
**warn** about it? The goal is **detection + warning**, explicitly **not** prevention, **not**
authentication, and **not** local encryption.

## Framing — what this is *not* (inherited from the threat model)

M8Shift's identity is **declarative and cooperative** (audit ASI03): any process with write
access can write a turn as any agent. This RFC does **not** change that:

- It does **not authenticate** who wrote a turn (no keys, no signatures, no crypto-identity).
- It does **not prevent** a write or a forge.
- It does **not encrypt** anything — the relay file stays inspectable plaintext.

What it adds is **tamper-evidence**: a way to tell, after the fact, that the *recorded history
was altered*. Prevention via a local key was analysed and rejected — a key the agent can read
to sign is also readable by the same local attacker, so it moves the secret without
authenticating anything, and it breaks the stdlib-only / no-crypto charter (audit ASI07:
"not implemented — and should not be").

## Mechanism — a stdlib hash-chain over turns

Each recorded entry (each closed turn, and optionally each `LOCK` transition) is linked to its
predecessor by a hash:

```text
chain[0] = sha256( canonical(entry[0]) )
chain[n] = sha256( chain[n-1] + canonical(entry[n]) )
head     = chain[last]
```

- `canonical(entry)` is a deterministic serialization of the entry's immutable fields (agent,
  turn number, recipient, `ask`, a digest of the body, timestamp), defined once so the hash is
  reproducible by anyone.
- `sha256` from `hashlib` (stdlib). **No keys, no secret salt** — nothing that needs protecting.
- The chain is **append-only**: a new entry extends the head; the normal write path never
  recomputes past links.

`verify` recomputes the whole chain from entry 0 and compares each link. The **first
divergence** points at the exact entry that was altered, inserted, deleted, or reordered.

## Where the chain lives (design options)

| Option | Chain storage | Pros | Cons |
|--------|---------------|------|------|
| A — inline | an advisory `x_chain:` field per turn in `M8SHIFT.md` | self-contained; travels with the journal | changes the turn surface; co-located with the attacker's write target |
| B — sidecar | `.m8shift/integrity/chain.jsonl` | keeps `M8SHIFT.md` clean | a sidecar can be deleted / rewritten by the same actor |
| C — anchored | the chain head committed to git / surfaced for the operator to record | robust against re-chaining | needs an external anchor step |

**Recommendation:** **B for the working chain + C for robustness.** The sidecar gives a cheap
local `verify`; the head is *anchored* (committed alongside the turn in the dogfooding git flow,
or surfaced for the operator) so a determined re-chain is caught.

## The honest limitation — why this is *evidence*, not *proof*

A hash-chain stored only in local files the attacker can also write is **re-computable by that
attacker**: tamper a past turn, recompute the whole chain and the new head, and a purely local
`verify` passes again. So a pure-local chain reliably catches:

- **accidental / naive tampering** — a tool or person that edits a turn without knowing about,
  or bothering to recompute, the chain;
- **partial tampering** — any modification that does not also re-chain every following entry;
- **the in-progress, uncommitted relay window** between commits.

It does **not**, by itself, defeat a determined local attacker who rewrites the whole chain. For
that, the head must be **anchored outside the attacker's reach**:

- **Git is already a tamper-evident hash-chain.** When turns are committed (the dogfooding
  flow), rewriting a past turn means rewriting git history — detectable via the remote / reflog.
  The native chain then mainly covers the *uncommitted* window.
- An operator can record the head out-of-band (a note, a second location).

This RFC therefore positions the native hash-chain as a **lightweight, git-independent
tamper-evidence + audit layer**, with git/remote as the strong anchor — and says so plainly
rather than overclaiming. Overclaiming "tamper-proof" would contradict the project's honest
security posture.

## Charter constraints

1. **Detection, never prevention.** A broken chain raises a **warning** (via `verify` /
   `doctor`); it never blocks a write, locks the file, or refuses a turn.
2. **Stdlib-only.** `hashlib` only. No crypto-identity, no keys, no encryption.
3. **Advisory & removable.** Deleting the chain loses only the tamper-evidence, never the relay
   log or the mutex.
4. **Passive.** The head is extended on the existing write path; no daemon, no background
   watcher.
5. **Inspectable.** Hashes are plaintext hex; anyone can recompute the chain independently.

## Command surface

```bash
python3 m8shift.py verify     # recompute the chain; report OK, or the first broken link
python3 m8shift.py doctor     # includes a tamper-evidence finding (advisory warning)
```

`verify` exit codes: `0` = chain intact; non-zero = a divergence was found, naming the entry
index and what diverged. `verify` is **read-only** and O(n); the write path extends the head in
O(1).

## What it explicitly does NOT do

- Authenticate the author of a turn (no identity / keys / signatures).
- Prevent or block a forged or malicious write.
- Encrypt the relay file or any field.
- Claim to defeat a determined local attacker without an external anchor.

## Acceptance criteria

- Editing, deleting, reordering, or inserting a closed turn makes `verify` report the exact
  first broken link; an intact ledger reports OK.
- `verify` and the chain use only `hashlib`; no new dependency, no key material on disk.
- Removing the chain degrades to "no tamper-evidence available," never to a relay or mutex
  failure.
- The write path stays O(1); `verify` is O(n) and read-only.
- The documentation states the local-re-chain limitation and the git / remote anchor
  explicitly.

## Open questions (designed solo — flagged for review)

1. **Inline (A) vs sidecar (B).** A keeps everything in one file but changes the turn surface
   and sits next to the attacker's write target; B is cleaner but deletable. Lean **B**.
2. **What to anchor, and when.** Auto-anchor the head into the dogfooding commit (a
   `Chain-Head:` trailer next to `Coordinated-With:`?), or leave anchoring to the operator?
3. **Scope of the chained content.** Turns only, or also `LOCK` transitions / session events?
4. **Cross-check with git.** Should `verify` optionally validate the chain against git history
   when the relay file is tracked, making git the authoritative anchor and the native chain the
   uncommitted-window guard?
