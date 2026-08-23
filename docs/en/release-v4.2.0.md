# v4.2.0 release notes

## Version

**v4.2.0 (Revision).** This is a backwards-compatible feature release. It adds
one core verb (`unclaim`), certified-premise run classification, synchronized
runner/listener status vocabulary, honest degraded-census evidence and a test
gate that may fail but can no longer hang — without changing the relay file
format, removing a command, or raising the Python 3.12 floor. Existing v4 relays
update without a Generation override. The suite grew from 1435 to 1619 collected tests
(1616 passing, 3 skipped on the release host) across the three arcs below.

## Highlights

### One turn, one producer — and a claim that can be undone (#320)

A listener now reserves the pen *before* launching its provider child, so a
listener and an interactive session of the same identity can no longer both take
charge of one incoming turn; lanes that never author a turn (notify-only,
review-artifact) never reserve. The new core verb **`unclaim`** undoes one's own
unused claim and restores the exact awaiting state without advancing the turn.
A child that already appended makes the reservation non-releasable, and that
refusal is observable, not silent.

### `advanced` certifies an identified premise (#377)

Authorship alone once let a run publish an answer to a superseded premise and be
recorded as a success. The launch snapshot now digests the exact pre-turn block
into the immutable run plan; certification requires the authored turn to be the
sole direct successor of that premise, still backed by the same premise bytes.
An intervening turn, a multi-turn run, or a rewritten/unreadable premise is the
new retryable `premise_superseded` — present in both the runner and listener
catalogs from birth. A launch that cannot read its nonzero premise is refused
before a plan exists. The ping-pong contract is preserved: a peer that consumes
the answer and replies within the run window is success, never supersession.

### A classification with a no-retry doctrine survives everything (#359, #382, #385, #387)

Terminal statuses (a denied headless permission now named
`headless_permission_refused`, a blocked environment, a required approval) stop
the lane after one attempt with a bounded operator notification — never a
recommendation to bypass permissions. Rate-limit and neutral classifications
survive a transport timeout, so a provider that prints its reset and then hangs
still reaches the listener as rate-limited and still places the scoped usage
hold. The runner's five status families and the listener's classification
vocabulary are held in lockstep by an exact-set witness, ending the
twice-named-list family (#368 → #382 → #385 → #387): no literal doubles a closed
set in the dispatch anymore.

### Evidence stays honest under degradation (#360, #361, #363, #380)

An oversized reviewer artifact is truncated on an exact character boundary and
delivered with a digest covering exactly the stored bytes — never destroyed, and
never sealed empty. A dropped usage window leaves a bounded note with its
reason. A local-only branch is visible before it is lost. A width-truncated
process census is marked degraded end to end: a degraded negative is
`unobservable`, never `absent`, and `stop --all` refuses to certify a relay
clean under a census it could not read.

### Lifecycle identity and safe reaping (#283, #327, #328, #329, #370, #379)

Listener lanes are enumerated by the relay they poll, not the agent name they
advertise; duplicates a pid file cannot name are reachable; tombstones are
distinct from live lanes. Failed-start reaping binds the pid to a process
identity revalidated immediately before the first signal, so a reused pid is
never signalled. A runner inside an ephemeral git worktree is refused at arming
time, and a lane whose relay root disappears exits with a stated reason.

### Fleet upgrades, verified kits and drift baselines (#330, #331, #332, #333, #334)

Kit upgrades across a fleet of adopted relays are a re-entrant transaction with
recovery checkpoints; an installed adopter subset can be verified offline
against a source release; doctor records upgrade drift against a pre-update
baseline; and an interactive dashboard exposes loaded-versus-on-disk version
skew instead of letting a stale resident TUI impersonate the new kit.

### The gate may fail; it can no longer hang (#390)

On one host the global suite stalled inside an unbounded installer child and
produced no verdict at all. Every installer-family child now runs through one
bounded, hermetic helper — a stall is a named failure within 120 seconds, the
whole process group dies with it, and inherited relay identity (the measured
carrier of the stall) is stripped from the child environment. Measured on the
affected host: the unfiltered global suite reaches its verdict, entirely green.

## Known boundaries

- The reservation binds producers that go through the relay. Work done entirely
  on external systems is out of its reach; the premise digest narrows, but
  cannot close, that gap (#377's renounced newest-turn rule is documented in the
  classifier).
- The census degradation marker reports the host's inability to read process
  identity; it does not recover it. A host that cannot run `ps -axww` keeps a
  permanently non-certifying `stop --all`, by design.
- The durable-fleet test fixture escape recorded in #396 (a corrupt-lane fixture
  written into a live relay's runtime directory during a full-suite run) is
  diagnosed but not yet fixed; the leaked file class is quarantinable and
  `doctor` names it.

## Upgrade and verification

Use the **new** v4.2.0 source while the adopted relay is paused:

```sh
./m8shift.py pause <you> --reason "kit upgrade to v4.2.0"
python3 <v4.2.0-source>/m8shift.py update \
  --target <relay> --source <v4.2.0-source> \
  --companions context,e2e,headroom,i18n,runtime,worktree,top
./m8shift.py doctor
shasum -a 256 -c checksums.sha256
./m8shift.py resume <you> --reason "kit at v4.2.0, doctor clean"
```

`update` preserves `M8SHIFT.md`, its turn journal and the active session. No
`--allow-generation-change` flag is needed when updating from v4.0.0 or v4.1.0.
