# Existing backlog batch: twenty tracked items

Status: implementation requested by the operator on 2026-11-15; cockpit work is a separate parallel repository. Protocol impact: yes for the documented roster anchor-bootstrap side effect; preserve the existing one-pen states and authority; proposals that would change that contract need an explicit separate disposition.

## Scope and order

Tracked items: integrity563, ownership564, quotas565, delivery evidence566, onboarding567, stale-lock fixture561, advisory routing560, roster/blocked visibility558, runner argv556, body-file help555, retained output554, launch identity553, diagnostic freshness551, blocked visibility550, operational diagnostics549, session lookup552, companion version548, onboarding parity543, lease fixture540 and deployment drift533.

Parent lots and their original issues overlap. Twenty evaluated items do not imply twenty distinct implementations. For each item record exact criteria, candidate inclusion, validation and residual acceptance. Preserve fixes already in the public candidate and do not replay private history.

## Invariants

- Core remains self-contained and stdlib-only; Python3.15 is the maintained validation lane.
- Never change a live relay, installed fleet, service or provider account as a side effect of this batch's fixture checks.
- Preserve current source and dirty checkouts; work in an isolated candidate checkout.
- A successful provider exit is not relay completion; review/advice is not authorization.
- Missing, old-session or stale observations must not claim present failure or health.
- Retain bounded diagnostic evidence without placing provider transcripts or private project identifiers into portable records.
- No bulk merge of private/public histories, release tag or main merge.

## Acceptance

1. Reproduce the candidate's listener errors using disposable fixtures before fixing them.
2. One managed instance identity propagates through reservation, child launch, heartbeat and unused-reservation cleanup. Detached startup must not access foreground-only locals.
3. Existing listener failure and protection assertions retain their strength; update a mock only when its signature intentionally changed, and assert propagated identity.
4. Run focused checks per changed subsystem, then the maintained complete suite on the combined source. Classify failures rather than suppressing or retrying them into green.
5. Resolve each tracked item's criteria as verified, partial, already included, deferred or externally blocked, with proof boundaries. Do not close a parent merely because a related slice passed.
6. Provide exact source revision, uncommitted changes, agent identity, available model/effort fields, observation time and delivery status in the batch report.
