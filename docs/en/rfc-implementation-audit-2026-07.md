# RFC implementation audit — 2026-07

Audit baseline: repository commit `421e935` (v3.64.0 plus RFC 077 Slice B),
2026-07-19. This is a repository/code audit, not a claim about unexported forge
issue bodies or operator infrastructure.

## Method and status vocabulary

The implementation table in [the specification](specification.md) §4 is the
positive source of truth. Its EF-1…EF-46 rows name the shipped contract and the
tests that verify it. RFC prose supplies intent; an RFC header that still says
`draft` does not outweigh a later EF row and executable tests. Conversely,
checked-in design prose, examples, or manually stamped turn fields are not
product implementation without a parser/validator/consumer and tests.

The five requested statuses mean:

- **implemented** — the RFC's authorized product/policy scope is represented in
  code or generated policy and its acceptance surface is tested. Explicit
  non-goals and separately gated future work do not make it partial.
- **partial** — at least one promised or authorized slice is shipped and at
  least one remains absent.
- **design-only** — the document is intentionally a proposal, principle,
  research result, input catalogue, or separately gated design; it grants no
  implementation authority.
- **superseded** — a later RFC/specification owns the contract.
- **abandoned** — the proposal was explicitly rejected for the product.

Absence checks used raw repository search over `m8shift*.py`, `scripts/`,
`examples/`, and `tests/`. In particular, there is no implementation match for
`m8shift.exchange.turn/1`, `session exchange`, `--stage`, `route delegate`,
`wait-operator`, `M8SHIFT.rules.md`, or a gateway-event schema. The only
standardized turn validator is the older Stage-4 surface in
`m8shift.py:cmd_contract_validate`; the only model/task router is the advisory
`m8shift-runtime.py:route_recommendation` / `cmd_route_recommend` path.

## Complete RFC inventory

| RFC | Status | Implementation evidence or disposition |
|---:|---|---|
| 001 | superseded | Shipped pair configuration was generalized by RFC 002 and the current specification; the RFC labels itself historical. |
| 002 | superseded | The N-agent, one-pen result is implemented by EF-1…EF-16, then superseded as the normative source by `specification.md` and `architecture.md`. |
| 003 | implemented | `m8shift-i18n.py:validate_pack` and `TestI18n`/`TestI18nFR` implement deterministic EN-core plus injected packs, despite the stale `Proposed` header. |
| 004 | implemented | `m8shift.py:cmd_remember` implements the append-only memory ledger. |
| 005 | implemented | `m8shift.py:cmd_claim_check` implements the advisory overlap probe without changing claim authority. |
| 006 | implemented | `m8shift.py:cmd_task` implements the RFC's deliberately ship-reduced append-only task board. Rejected dependency-engine features are not missing scope. |
| 007 | abandoned | The RFC explicitly rejects `subturn`; no product surface should exist. |
| 008 | implemented | `m8shift-worktree.py:cmd_claim` and the worktree test suite implement opt-in degree-2 worktrees with serialized integration. |
| 009 | implemented | Runtime presence, inbox, progress, and lifecycle sidecars are implemented; EF-24 is the composed read contract. |
| 010 | design-only | This is an accepted retain/reject filter, not one implementation contract. Its retained items were split into RFCs 024–029 and later runtime RFCs; its rejected gateway/core-authority patterns remain absent intentionally. |
| 011 | implemented | EF-14 and `m8shift.py:cmd_history` implement the folded append-only session history. |
| 012 | implemented | EF-18 and `m8shift.py:cmd_contract_validate` implement Stage-4 metadata plus advisory/strict validation. |
| 013 | design-only | The optional hosted control plane in §§5–12 is wholly unimplemented; the RFC explicitly says future companion and preserves the local passive core. |
| 014 | implemented | `m8shift-runtime.py:cmd_providers_init/list/show/check/render` implements the local provider registry. |
| 015 | abandoned | True degree >1 writes in one shared checkout are explicitly rejected; RFC 008 worktrees are the accepted alternative. |
| 016 | implemented | `cmd_request_turn`, `cmd_yield_turn`, `cmd_decline_turn`, and `cmd_steer_turn` implement the cooperative baton request/steering state machine. |
| 017 | implemented | The authorized local Stage-6 layer is covered by EF-17, EF-19, and EF-20. §4B labels IDE/MCP/hosted integrations post-Stage-6 future companions, not unfinished Stage 6. |
| 018 | implemented | The v1 local roles/workflows/approvals/providers/report scaffold is shipped; the broader hosted control plane is separately RFC 013. |
| 019 | design-only | This is a curated input inventory. §§3–6 deliberately defer persistent registries, approvals, artifact tracking, and candidate follow-up RFCs; it is not an implementation plan. |
| 020 | implemented | EF-20 and `TestRFC047PhaseA` subsume and harden the reference runner contract. |
| 021 | implemented | EF-21 and `cmd_pause`/`cmd_resume` implement explicit `PAUSED` semantics. |
| 022 | implemented | EF-22 and `m8shift.py:cmd_session` implement derived reports and structured decision extraction. |
| 023 | implemented | The protocol/pack split is shipped; the formerly deferred brief surfaces are also implemented by EF-23. |
| 024 | implemented | EF-24 plus the two doctor commands implement the stated baseline ownership split. The RFC's final questions are optional design questions, not requirements. |
| 025 | implemented | EF-24 implements `status-runtime` composition and its advisory/JSON/brief contract. |
| 026 | implemented | `cmd_retention_prune`, `cmd_retention_policy_show`, and `cmd_retention_apply` implement fixed-count and opt-in manifest policy retention. |
| 027 | implemented | EF-24b and `cmd_notify*` implement bounded local stdout/file/bell/OS/hook notification tiers. |
| 028 | implemented | Provider argv templates and the immutable runner plan are covered by EF-20 and the provider/runner tests. |
| 029 | design-only | The richer `m8shift-board.py` workboard in §§2–3 is absent and explicitly awaits operator authorization; the small RFC 006 task ledger is not that workboard. |
| 030 | design-only | The proposed turn-ledger hash chain, verification command, and chain storage in §§3–6 are absent. Git remains the stronger external anchor named by the RFC. |
| 031 | implemented | EF-22b and `m8shift.py:cmd_decisions` implement forge/git/Markdown fallback traceability and structured contradictory decisions. |
| 032 | partial | Phase-1 recommendation is EF-28; actual delegated launch remains absent. See the gap register. |
| 033 | design-only | The Task Packet/context-layer/gatekeeper/result-format policy in §§3–8 has no dedicated product schema or gatekeeper. Compression mechanics were intentionally delegated to RFCs 034/037/042. |
| 034 | implemented | EF-26 implements identity-pinned argv adapters, bounded output, project-local provenance checks, RTK fallback, and status/doctor visibility. |
| 035 | superseded | RFC 047 implements the resident listener lifecycle; the generated host-wakeup guard now explicitly distinguishes waiter, listener, notification, and invocation. |
| 036 | implemented | EF-25 and `m8shift-runtime.py:cmd_headroom` implement proxy pressure, checkpoints, status/doctor visibility, and explicit holder-gated pause. |
| 037 | partial | EF-29 implements safe records, digest emission, compression, and bounded retrieval, but not every accepted reporting/integration surface. See the gap register. |
| 038 | partial | The §9 ambiguity/binding amendment is implemented by `m8shift.py:cmd_bind`; the original parallel named-relay design remains absent. |
| 039 | partial | EF-28 implements advisory `route recommend`; confirmed `route delegate`, routed execution records, and escalation telemetry remain absent. |
| 040 | implemented | EF-27 and EF-33 plus the RFC 040 test classes implement normalized snapshots, guard/watch/wait/resume, disabled adapters, cooldown, and hardened provider examples. |
| 041 | superseded | RFC 050 explicitly replaces the bespoke flat-file skill format with the open Agent Skills format and ships the new seeds/doctor validation. |
| 042 | partial | EF-29 records Phase-B routing signals; the measured Headroom evidence gate and signal-driven automatic routing remain closed. |
| 043 | design-only | The RFC explicitly introduces only a canonical routing principle. No common executable six-stage engine is promised; instance RFCs remain authoritative. |
| 044 | implemented | `plan_companions`/`apply_companions`, kit metadata, doctor checks, and `TestRFC044CompanionInstall` implement all three phases despite the stale `draft` header. |
| 045 | partial | Hand-authored module pages exist, but the generator/smoke/site phases remain incomplete. |
| 046 | implemented | Status project/cwd/mode honesty, generated instructions, runner install/profile handling, and doctor checks are covered by `TestRFC046ProjectIdentity`, EF-15/16/20, and bootstrap tests. |
| 047 | implemented | EF-20 and EF-30 implement runner final-state classification and listener lifecycle, including the v3.64 compatibility amendment. |
| 048 | implemented | EF-10c/10d/10e and `TestRFC048PRA/PRB` implement the pack, source-driven update, adoption/install health, re-entrant runbook, and preflight write gate. |
| 049 | implemented | EF-7/8/30 implement claim-on-pickup, protective heartbeat, stale recovery, and listener producer liveness. |
| 050 | partial | Phase 1/1b skill seeds and `skills.*` doctor checks ship; Phase 2 is explicitly future. |
| 051 | implemented | EF-33 plus `TestRFC051UsageAdvisory` implement read-only usage display and the absent-vs-unavailable window distinction. |
| 052 | implemented | `doctor --hygiene`, `scripts/scrub-check.py`, hooks, confidential denylist, anchor mode, and `cmd_bind` implement PRs 1–4. `--refs-pull` exists; remediation is explicitly operator-driven/out of runtime. |
| 053 | design-only | `M8SHIFT.rules.md`, its governed lifecycle, and optional `m8shift-rules.py` verbs in §§3–8 are absent, exactly matching the RFC's design-only scope. |
| 054 | design-only | Phases A–E (§13)—normalized exact signals, rotation advice, bounded rotation bundle, explicit pause/confirmation, and measured adoption—are not implemented. |
| 055 | design-only | The holder-only `wait-operator` mutation, TTL/liveness semantics, distinct status/watch/top display, and typed-host integration in §§4–8 are absent. |
| 056 | implemented | EF-34 implements bounded self-declared model provenance in LOCK, turns, snapshots, dashboard, and commit trailer. |
| 057 | implemented | EF-19 implements index-blob checksum refresh and deletion/drift safeguards. |
| 058 | implemented | EF-35 implements same-change RFC/index policy with advisory doctor/pre-commit enforcement. |
| 059 | implemented | EF-36 implements capability-tiered semantic terminal colour with non-colour redundancy. |
| 060 | implemented | EF-37 implements deterministic adaptive geometry and self-pipe resize handling. |
| 061 | implemented | Snapshot activity provisioning and bounded adaptive activity are tested in `tests/test_m8shift_top.py`; RFC 064's row adjustment is additive. |
| 062 | implemented | The protocol, pack, and stanza carry the invariant that only `DONE` ends listening; protocol budget/invariant tests cover it. |
| 063 | implemented | `m8shift-top` point-fetch reader and expanded activity tests implement the `e` toggle, wrapping, navigation, and paging. |
| 064 | implemented | `m8shift.py:fold_time_accounting` and `m8shift-top.py:render_time_strip` implement Phases A–C, including honest unclassified legacy time. Ticket #218 is an additive presentation request, not an unmet RFC 064 acceptance item. |
| 065 | implemented | The generated discipline and `TestRFC065DeliveryAdvisories` implement ticket/commit/push/gateway-pending policy and offline reminders. Ticket #229 adds observability not promised by RFC 065. |
| 066 | design-only | The solo-episode state, reconciliation ledger, eligibility/bounds, return detection, and command sketch in §§5–10 are absent and explicitly separately gated. |
| 067 | partial | RFCs 072/073 implement much of Phases 1–2 and one Phase-4 provider, but the accepted orchestration program is not complete. |
| 068 | design-only | **No RFC 068 file exists in the index or tree.** The only local record says rotation-token design remains operator-gated; there is no text precise enough to audit or implement. |
| 069 | implemented | EF-44 plus incremental-fold oracle/invalidation tests implement byte-equivalent O(delta) dashboard refresh. |
| 070 | implemented | Provider/model pins and immutable runner-plan propagation are covered by EF-40/42 and exact argv tests; unsupported native resume correctly fails closed. |
| 071 | implemented | `m8shift.py:cmd_roster_add` implements holder-only, byte-preserving live roster addition; templated enrollment is explicitly outside this RFC. |
| 072 | implemented | EF-38/39 implement slices 1–6: plan/health/apply/reconcile, durable fleet jobs, bounded worktrees, verification, and integrator-only integration. |
| 073 | partial | EF-40…43 implement slices 1–3 and routing phase 1; the RFC's completion conditions and later routing/provider work remain open. |
| 074 | design-only | All proposed slices are separately unauthorized. Existing `stage4.v1` fields do not implement the 15-stage taxonomy, successor schema, consumers, or exchange export. |
| 075 | design-only | The comparative vendor matrix is the authorized Phase-1 research output. It intentionally selects no base class, live adapter, policy, threshold, or re-verification mechanism. |
| 076 | design-only | The incident-first/deterministic/re-entrant contract is currently review-enforced policy. §9 explicitly leaves templates/doctor findings for a later authorization. |
| 077 | partial | Slice A schemas/base fixtures and Slice B disabled vendor subclasses ship; Slices C–E remain gated. |

Inventory totals: **46 implemented, 10 partial, 15 design-only, 4
superseded, and 2 abandoned**. All integers 001–077 are represented; 068 is an
intentional audit row for the missing RFC artifact.

## Precise gap register

This section expands every `partial` row. Design-only rows are also enumerated
afterward so that intentional non-implementation is not mistaken for backlog.

### RFC 032 / RFC 039 — delegated routing execution

Implemented: RFC 032 header / RFC 039 §9 item 1 and EF-28's advisory
`route recommend`, including capability floors and fail-safe-to-self behavior in
`m8shift-runtime.py:route_recommendation`.

Missing:

1. RFC 039 §9 item 2 `route delegate` (recommend, render argv, isolated
   worktree, and hardened runner) has no parser or command function.
2. The explicit `--confirm-route <id>` / `--yes` launch gate and RFC 031
   decision record do not exist.
3. RFC 039 §10 routed-run ledger fields—resolved tier/floor, verification
   outcome, and `saved_vs`—are not emitted.
4. The optional start-cheap/escalate path and escalation-rate feedback are not
   implemented.

Evidence: EF-28 names only `route recommend`; raw search finds
`cmd_route_recommend` and no `cmd_route_delegate` or `route delegate` command.

### RFC 037 — context compression completion

Implemented: RFC 037 Phases A–D and most of E are represented by EF-29 and
`m8shift-context.py:cmd_compress` / `cmd_retrieve`; `compress` emits both
`context_digest` and `handoff_digest` and keeps bounded raw retrieval.

Missing:

1. RFC 037 Phase F and acceptance criterion 7 call for `context stats` with
   estimated raw/sent/avoided tokens and counts by backend. No stats parser or
   command exists.
2. The command-surface draft's standalone `measure`, `show`, `grep`,
   `digest update`, and `handoff create` verbs do not exist. Bounded retrieval
   does cover show/grep mechanics, while digest creation occurs only as a
   by-product of `compress`; the audit therefore treats the semantic core as
   shipped but the named surfaces as unfinished.
3. Phase E's “agents receive digests/raw refs by default” is guidance, not an
   automatic handoff integration in `append` or the runtime.

### RFC 038 — parallel named relay sessions

Implemented: §9's two-candidate physical-identity ambiguity gate and per-agent
binding are in `m8shift.py:cmd_bind` and the centralized pre-write checks.

Missing: §§3–8 named relay namespaces, exact per-session file mapping,
`--relay-session` / `M8SHIFT_RELAY_SESSION` selection, multi-session
create/list/close commands, and isolation acceptance tests. Current `session`
commands are report views over sequential session history, not simultaneous
independent relays.

### RFC 042 — signal-driven Headroom routing

Implemented: Phase B fields `access_mode` and `whole_content` are recorded by
EF-29. Explicit/manual `headroom_ext` remains available and identity-pinned.

Missing: Phase C's representative no-retrieval/whole-content measurement and
Phase D's evidence-approved automatic Headroom choice. In
`m8shift-context.py:select_context_adapter`, broad context stays builtin unless
the operator explicitly enables Headroom. This is the intended closed gate,
not a silent implementation failure; opening it without Phase-C evidence would
violate the RFC.

### RFC 045 — module-reference automation

Implemented: Phase A's `docs/en/modules/README.md` and one page for each shipped
module; `TestRFC045ModuleReference` covers the hand-authored inventory.

Missing:

1. Phase B generator-owned help markers and stale-output gates.
   `scripts/gen_docs.py:main` still generates only protocol and protocol-reference.
2. Phase C temp-project execution of examples tagged `safe` and confinement
   refusal tests.
3. Phase D VitePress mirroring/sidebar parity. The site repository is outside
   this checkout, so its current remote state is **unknown**; there is no local
   parity manifest/test proving it.

### RFC 050 — specialist Phase 2

Implemented: Phase 1/1b open-format `skills/` seeds, manual lane guidance,
examples, and `skills.*` doctor validation (`TestRFC050SkillsDoctor`).

Missing: runtime request/report indexing and the RFC 034 identity-pinned argv
verification-hook integration stated in the header and implementation phases.
There is no automatic specialist launcher or hidden write authority, by design.

### RFC 067 — detached orchestration program

Implemented through RFCs 072/073: provider-keyed adapter spine, exact identities,
durable fleet/lane/job records, native service plans plus honest local fallback,
restart reconciliation, Gemini fresh launch, and sequential/integrator gates
(EF-38…EF-43).

Missing against RFC 067 §13:

1. Phase 3's general sequential bounded queue with cancellation/retry/approval
   semantics, then evidence-gated bounded DAG scheduling. RFC 072 fleet jobs are
   bounded orchestration, but do not implement RFC 067's general routed scheduler.
2. Automatic routing for preauthorized task classes. The matrix remains
   advisory and `launch=false`.
3. Phase 4's fully managed Mistral Vibe onboarding. It remains a source-validated
   declarative stub (`m8shift-runtime.py:MistralVibeAdapter`) without managed
   model/resume/health/completion evidence.
4. RFC 073 §8's end-state proof that a native-service-backed control plane has
   survived frontend loss and its own restart in a live acceptance run is not
   captured as an EF requirement; deterministic plan/reconciliation tests are
   present, but live native-service acceptance remains environment-dependent.

Native Gemini resume is **not** counted as a defect: RFC 067 D6 allows fresh
fallback and RFC 073 §6 Slice 3 documents why the upstream index/`latest`
surface cannot prove project/identity/job ownership.

### RFC 073 — delivery-slice completion

Implemented: Slices 1–2, Slice 2C, Gemini fresh launch in Slice 3, and Slice-4
phase 1 (EF-40…EF-43).

Missing:

1. Slice 3 live Mistral lifecycle onboarding remains gated on a local
   version/capability probe; the checked-in class is a stub.
2. Slice 4's evidence-driven vendor/model catalogue, immutable attempt-plan
   choice/source/reason/override fields, stale-evidence escalation, and any
   operator-preauthorized automatic launch remain future work.
3. §8's backlog completion proofs (live third provider through D16 and a live
   native-service durability exercise) are not represented in EF-40…EF-43.

This answers the “routing matrix phase 1” question: later goals are defined in
RFC 073 §6 Slice 4 and RFC 067 §§10/13, but no later implementation phase has
shipped.

### RFC 077 — safe-boundary model-line routing

Implemented: §8 Slice A schemas/base conformance and §9 Slice B fixture-only
Anthropic/OpenAI/Google/Mistral subclasses. Evidence is
`examples/model_line_budget_adapter/base.py:ModelLineBudgetAdapter`, the four
classes in `vendors.py`, the disabled `VENDOR_ADAPTER_REGISTRY`, and
`tests/test_model_line_vendor_adapters.py`.

Missing, exactly as RFC 077 §10 gates it:

1. **Slice C:** pure decision-table state machine plus dry-run immutable
   route/audit plan, including stale target, ordered fallback, oscillation cap,
   active/corrupt usage hold, adapter-error, and partial-effect refusal cases.
2. **Slice D:** opt-in listener integration only at the next safe invocation
   boundary, with hold precedence, halt/notify, durable reconstruction, exact
   RFC 070 argv, and byte-for-byte relay/ownership non-mutation tests.
3. **Slice E:** one live-vendor pilot after separate operator authorization and
   fresh contract verification. All four registry rows currently remain
   `enabled=false`, `retrieval=fixture_only`.

No live credential, SDK, socket, subprocess, policy, listener switch, or relay
mutation exists in the Slice-B package. That is the correct current security
boundary, not an implied live capability.

## Design-only non-implementation (excluded from the real-gap backlog)

For completeness, these are the precise absent surfaces behind every
`design-only` row:

- **010:** no direct surface; it is a retain/reject filter. The workboard idea
  was split to RFC 029 and hosted/gateway ownership was rejected or deferred.
- **013:** hosted service/API, remote lanes, hosted progress/notifications,
  auth boundary, and its acceptance suite (§§5–12).
- **019:** persistent run/agent/role registries, approval model, artifact
  reports, and candidate companion RFCs (§§3–6); the document is input only.
- **029:** `m8shift-board.py`, richer item schema, views, and commands (§§2–3).
- **030:** hash-chain fields/storage plus `verify-ledger`/doctor surfaces
  (§§3–6); unresolved design questions remain in §8.
- **033:** canonical Task Packet, three-layer context manifest, gatekeeper role,
  and machine-readable result envelope (§§3–8). Advisory budgets are explicitly
  non-enforced.
- **043:** no missing behavior; the six-stage pipeline is a normative principle
  for future routers, explicitly not a runtime feature.
- **053:** governed rules artifact/state lifecycle and optional rules companion
  (§§3–8).
- **054:** all delivery Phases A–E in §13, including exact signals and the
  operator-confirmed rotation bundle.
- **055:** all marker/state/display work in §§4–8, including `wait-operator`.
- **066:** solo episode, debt ledger, eligibility/bounds, reconciliation, and
  command surfaces (§§5–10).
- **068:** the RFC document itself. Without it, the “rotation token” contract,
  relation to other rotation/session work, acceptance criteria, and authority
  boundary are unknown.
- **074:** 15-stage taxonomy, `m8shift.exchange.turn/1`, consumers,
  `m8shift.exchange.shift/1` export, and strict profile (§§3–8).
- **075:** live vendor access, normalized operational schema, forecast/policy,
  thresholds, and recurring contract verification. The static research matrix
  is the only authorized output.
- **076:** optional incident templates and doctor findings (§9). The accepted
  initial posture is review-enforced, so their absence is not yet a defect.

## Adjacent accepted work not promised by the RFC rows

The repository records several accepted issue-level follow-ups. They should not
retroactively make an otherwise complete RFC `partial`, but they are real work:

- **#229 gateway visibility:** RFC 065 requires a named gateway-pending handoff
  but not a runtime gateway ledger. No `m8shift.gateway.event.v1`,
  `gateway.jsonl`, or top `GATEWAY` consumer exists. The accepted side-ledger
  addition is therefore unimplemented.
- **#222 scrub HISTORY reachability:** RFC 052's scanner uses
  `scripts/scrub-check.py:history_cmd` with `git log --all`; it can report
  commits retained only by stale local refs without naming the carrier refs.
  The accepted reachability scoping/ref-attribution follow-up is absent. By
  contrast, `--refs-pull` scanning is already implemented, and RFC 052 §Q says
  delete/recreate remediation is operator-driven and outside product runtime;
  the RFC text is the only current runbook.
- **#218 dashboard presentation:** RFC 064 correctly renders honest legacy
  `unknown`/unclassified time. The follow-up requesting a TIME legend,
  window-scoped interpretation, and window-roll escalation is not implemented.
  These are additive semantics; the RFC 064 fold and strip themselves satisfy
  §4–§8.
- **#214 watcher lifecycle:** the repository exports only the issue number and a
  release-note sentence. Existing usage-watch lifecycle evidence is implemented
  by `m8shift-runtime.py:write_usage_watch` and consumed by
  `producer_evidence`, but the accepted issue's claimed four watcher variants
  and `HUNG` mode are not present in any checked-in RFC/specification or issue
  export. Exact per-variant acceptance criteria are therefore **unknown from
  this checkout**; implementing from the relay summary alone would be unsafe.
- **#212 recurring vendor verification:** RFC 075 is a dated research ledger
  and RFC 077 Slice E requires fresh contract re-verification before a live
  pilot. There is no scheduled/manual verification command, source-date expiry,
  or drift finding for provider contracts. A mechanism must be specified before
  live enablement; it must not turn official-doc URLs into an implicit network
  dependency of the passive core.

## Prioritized real-gap backlog

Priority reflects safety/dependency impact, not estimated implementation size.
Voluntary design-only proposals above are excluded.

| Priority | Gap | Why now / completion signal |
|---:|---|---|
| P0 | Specify and implement RFC 077 Slice C | A pure, fixture-complete state machine and immutable dry-run plan are prerequisites for any switch; no credentials or live calls needed. |
| P0 | Resolve RFC 068 as a real RFC artifact | The current “rotation token” dependency has no auditable contract. Write/arbitrate it (or explicitly abandon/renumber it) before allowing dependent rotation/routing work to cite it. |
| P0 | #212 vendor-contract re-verification gate | Slice E must not rely on a stale 2026-07 matrix. Define source-date/expiry/drift evidence and keep live enablement fail-closed. |
| P0 | #222 HISTORY reachability and carrier-ref findings | Current full-history scrub can false-block delivery on unreachable commits retained by stale refs. Scope reachable history deliberately and name the refs that keep a hit alive. |
| P1 | RFC 077 Slice D | Only after Slice C: integrate at the safe listener boundary with hold precedence, reconstruction, exact argv, halt/notify, and relay-byte invariance. |
| P1 | #229 gateway side ledger/top visibility | A delivery in flight is currently visible only in prose; add the accepted digest-only event schema and advisory dashboard consumer without granting pen authority. |
| P1 | #218 TIME explanation/window roll | Make legacy unknown time and rolled-window semantics intelligible without changing RFC 064 accounting or implying productivity. |
| P1 | #214 watcher lifecycle contract | First export the issue's four variants and HUNG semantics into an RFC/spec amendment; then implement uniform lifecycle evidence and tests. Exact scope is currently unknown locally. |
| P1 | RFC 073 routing-matrix continuation | Add dated evidence-driven vendor/model rows and immutable choice provenance before any preauthorized automatic launch. |
| P2 | RFC 039 delegated launch | Implement only with explicit confirmation, isolated worktree, hardened runner, verification record, and fail-safe-to-self behavior. |
| P2 | RFC 037 stats/handoff completion | Add measured/labelled context statistics and decide whether automatic digest handoff is authorized; keep raw-proof retrieval mandatory. |
| P2 | RFC 045 generator and safe-example gates | Eliminate hand-maintained command drift and add confined example smoke tests; site parity remains separately verifiable. |
| P2 | RFC 050 specialist request/report indexing | Finish the explicitly future phase without creating hidden specialist launch or write authority. |
| P3 | RFC 067/073 live durability/provider proofs | Run the D16 third-provider and native-service survival/restart acceptance only on suitable operator-controlled hosts. |
| gated | RFC 077 Slice E | One live-vendor pilot only after P0/P1 predecessors, explicit operator authorization, fresh vendor verification, and a reversible disabled-default plan. |

## Audit limits

- No network/forge query was available. Issue-level claims are limited to the
  checked-in release notes and relay handoff; #214's detailed issue body is the
  only material unknown called out above.
- The separate documentation-site repository was not inspected; RFC 045 Phase D
  is therefore unknown remotely and unproven locally.
- This audit does not treat comments, manual dogfood fields, or a deterministic
  fixture as live capability. It also does not penalize a documented fail-closed
  refusal (for example unsafe native Gemini resume) as a missing feature when the
  RFC explicitly accepts fresh reconstruction fallback.
