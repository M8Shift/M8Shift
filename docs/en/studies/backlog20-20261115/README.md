# Existing backlog batch — twenty-item evidence and disposition

Implementation requested 2026-11-15. This is a branch delivery report, not a claim
that twenty independent implementations or twenty issue closures were performed.
Protocol impact: **yes** for the roster bootstrap command documentation; no new LOCK states or pen authority. Additive advisory status,
explicit roster bootstrap and opt-in local diagnostics. Launch identity wording
clarifies provenance and does not authenticate callers.

## Source and review trace

Engine repository `M8Shift`, work branch `work/backlog20-20261115`,
public integration baseline `3e3b070a667a6c978de0affab5bc48ec853b7549`.
Selected private behavior was compared by function. Exact private-source
provenance is retained in the local project checkpoint; private ancestry was
not imported and private markers are not published as commit provenance.
Original dirty development checkouts and live relays were preserved.

Implementation/reviewer: Codex principal agent, 2026-11-15 CET. Exact runtime
model identifier and reasoning effort unavailable; review traceability is
incomplete on those two fields. Sources read: changed core/runtime/runner,
installer, onboarding/verification scripts, focused tests, canonical guide,
public release documentation, selected private function/test source and all
twenty Forge issue bodies. Changes were uncommitted during the first full run.
The final code commit and verification receipt are recorded separately below.

## Dispositions

| Forge item | Implemented or already present | Remaining acceptance boundary |
| --- | --- | --- |
| #563 integrity | Preserved candidate installer/dedup fixes and adapter manifest coverage. Added checksum-verified runtime delegation with malformed/missing/edited companion refusal and nonduplicated kit findings. | Branch integration, exact combined CI and independent review remain distinct. |
| #564 ownership/lifecycle | Fixed misplaced listener instance environment and detached generation reference. One identity reaches reservation, child, lease refresh/heartbeat and release. Added serialized listener startup and per-agent/root runner singletons with crash-safe kernel ownership. Status corroborates runner pickup through its held kernel lock; a stale PID file is insufficient. Legacy resume remains unbound and a foreign instance halts. Existing takeover and displaced-holder checks preserved. | Native backend lifetime on Windows/Linux and deployed fleet not established by local fixtures. |
| #565 quotas | Nonmeasurement numeric floor at normalization and reads. Managed listener repairs only its own dead desired-running collector with bounded cadence. Durable unnamed checkpoint/cooldown advice, recovery latch and diagnostic dedup. | Token Monitor repository identity requested from owner; no upstream guessed and no credential collection. Real account coverage and fleet activation remain unqualified. |
| #566 evidence/publication | Exact-tip discovery now refuses all dirty source, uses end-of-options revision parsing. Single maintained Python full-suite lane preserved. Reports distinguish skips, fixtures, execution and publication. | Scoped denylist/provenance/privacy and mirror contracts require further selective reconciliation; no invented independent provider review. |
| #567 onboarding/reconciliation | Added read-only terrain and byte-based update probes, executable canonical onboarding, Python 3.15 policy and cross-platform smoke/rollback guidance. Caller inventory below describes the combined source. | Native Windows/Linux smoke, public integration and site deployment remain separate. Historical drafts/archive preserved in their original histories, not bulk merged. |
| #561 stale-lock collision | Already included deterministic replacement/unlink fixture retained. | Complete-suite result applies only to recorded source. |
| #560 routing | Existing deterministic opt-in policy and native bridge retained, always advisory and launch=false. | Independent Advisor invocation, optional JEV, actual providers/effort/quota qualification and outside review remain open. |
| #558 roster/register/block | Distinct missing anchor generated atomically on roster add; existing/shared anchors preserved. Default doctor reports signatures outside the current roster. Status projects open declared blocked_on reasons. | Historical membership is unknown. Advisory blocked declarations are session-unbound and do not prove liveness; no new BLOCKED lock state. |
| #556 runner argv | Existing shell-free argv contract and quoted-command diagnostic retained. | Does not prove every provider CLI accepts a configured argv. |
| #555 append body-file | Existing explicit body-file and stdin help/alias retained; missing-file refusal preserved. | No live relay append performed. |
| #554 retained output | Added explicit --retain-output: private 64 KiB prefixes per stdout/stderr stream, exact digest/count/truncation receipt, base64 raw bytes, exclusive 0600 file; transcript never copied into portable ledger. Default unchanged. | Opt-in local diagnostics can contain sensitive text; not an unlimited transcript or automatic artifact-delivery claim. |
| #553 launch identity | Existing runner M8SHIFT_AGENT launch declaration retained; anchor now explains roster identity/root versus OS user or UI path. | Actual provider instruction following is not proven by environment injection. |
| #552 session lookup | Existing current-session lookup and ambiguous historical refusal retained. | Native cockpit expanded-reader behavior is separate UI qualification. |
| #551 diagnostic freshness | Repeated failure warnings require current session and a nonfuture recent timestamp; later current-session success clears an old sidecar streak. Historical evidence is labelled. | Sidecar evidence is diagnostic, not authority to resume or stop a provider. |
| #550 blocked visibility | status --for peer and JSON expose bounded open task blocked_on declarations, including reason and explicit advisory/session-unbound metadata. Watch signature includes changes. | A declaration does not protect an expired lock or certify a living blocked process. |
| #549 operational diagnostics | Added bare-polling warning and opt-in bounded output; added held-pen pickup coverage and retained existing kit inventory, persisted runner-plan identity and lifecycle diagnostics. | Retention currently keeps prefixes, not failure tails. Comparison of every live runner against the kit, rather than only its persisted plan, remains incomplete. |
| #548 companion versions | Every registered companion tested from the core registry, no-side-effect version queries; TOP forwarded parser errors now name TOP. | This check does not certify deployed companion byte equality. |
| #543 conductor parity | Added bounded engine checker with mutations. Actual repository/site copies match all 8 blocks; site build now calls it and rejects missing evidence. | Site branch must follow engine public integration; no remote deployment performed. |
| #540 lease fixture | Existing synchronized child-lifetime/final-beat witness retained. | Does not establish real provider liveness on an installed fleet. |
| #533 deployment drift | Existing core/companion byte receipts/drift diagnostics retained; onboarding update check compares source manifest bytes even with equal VERSION. | Deploy/tag policy, supervisor-death operational evidence and live fleet redeployment require explicit operational work; no fleet upgrade performed. |

## Effective caller inventory

| Control | Reachable caller/configuration | Evidence boundary |
| --- | --- | --- |
| Dead desired quota collector repair | Invoking managed listener loop -> listener_usage_watch_tick, every 300s at most, never notify-only/halted/DONE. | Disposable real listener restarts a real collector and observes a tick; no live activation inferred. |
| Runtime quota diagnostics from default core doctor | Default collect_doctor_findings -> verified installed runtime doctor; only recorded regular version/hash-matched companion executed. | Edited/missing/symlink/bad-output cases retain refusal evidence; delegated findings advisory. |
| Core/companion kit bytes | Default core doctor _kit_doctor_findings; explicit install/update receipts. | Version equality is insufficient; legacy absent receipts remain unmeasured. |
| Source release manifest | Explicit installer verification, doctor --install, shipped CI/pre-push callers. | A working fixture does not prove a local hook is armed or remote runner active. |
| Stranded-lane notifications | Existing resident listener maybe_notify_stranded. | Deliberate stops respected; no service started to silence findings. |
| Near-limit checkpoint advice | Managed usage watch with current registry lease -> durable latch/audit; doctor recovery. | No peer/model route, capability evaluation or provider launch. |
| Test loading | Dedicated public test-loading workflow and explicit script; all-source clean-tree requirement. | Discovery is not test execution; pre-push successful-suite enforcement not added here. |
| Onboarding site | docs:build -> site wrapper -> reviewed engine checker; workflow supplies explicit public integration checkout. | Local build and mutations measured; public integration/deployment pending. |

## Smoke and rollback guidance

Use a new disposable directory and one maintained Python 3.15 checkout; pin the
source commit and manifest before install. Run the terrain probe before writes.
Execute the canonical sequence with a harmless local stub, select the local
backend explicitly for a fixture, inspect root/agent/can_invoke_agent/coverage and
stop the fixture before deleting it. Windows Bash conductor requires an actual
WSL/Git Bash execution probe; native PowerShell remains the separate installer.
A Linux or Windows fixture passing elsewhere does not establish this host.

For a real adopter, first inventory installed core, companions, runner bytes,
plans, roster, current held window and lifecycle backend. Preserve the existing
kit/receipt and sidecars before a governed paused update; verify copied bytes and
restart only explicitly selected listeners. Rollback restores that verified kit
and its matching plans without reinitializing or rewriting relay history. This
batch performed none of those live operations and did not validate real-fleet
rollback.

## Historical preservation

RFC065/RFC068 historical drafts and v3.58 material remain in the source histories
identified by the prior gap inventory. No history was reset, deleted or merged
wholesale. Their presence in private history is not a claim they are included in
this public candidate; the current release document remains authoritative.

## Validation record

The first full maintained-lane command `python -m pytest -q --tb=short` on the
uncommitted combined tree returned **9 failed, 1753 passed, 3 skipped, 1046 passed
subtests**, in 1410.55s. It is retained as a failed diagnostic run, not a release
gate. Its content manifest SHA-256 is
`152b7e65cab03b703ba256ee43fec800091f544a25142fa196b5a9f596e152b8`.

The nine failures were classified: two stale guide-marker expectations; two
closed snapshot-shape expectations after the additive `declared_blocks` field;
one changed roster bootstrap expectation; one named stale-quota diagnostic
expectation; one source-extraction fixture after the startup helper split; the
macOS lexical/canonical root alias in process census; and the anchor byte ceiling.
State/ownership assertions were retained. The identity floor was shortened to
2004 bytes without raising the 2048-byte ceiling, and its guide marker was
reviewed/refreshed. Schema expectations now explicitly include the new field.

The correction/pickup subset initially returned 61 passed and one test-only
NameError (missing Path import); that assertion now uses a closed file handle.
The roster and singleton group subsequently passed 11 tests, including refusal
through a root alias and independent execution in a distinct relay. The runner
singleton and held-pen pickup additions were not present in the first full run.
They therefore require the final combined verification, not inference from that
older run.

Recorded focused checks before the final commit: listener startup transaction
66 passed/5 subtests; quota/liveness 30 passed/35 subtests; roster/integrity 33
passed/43 subtests; onboarding/version/ambient 19 passed/18 subtests; retained
output/freshness 7 passed/3 subtests. These are separate scopes and must not be
added together as a full-suite count. Compilation, changed-installer ShellCheck
at CI warning severity and Bandit at CI medium severity/confidence passed on the
reviewed source. Final exact-head verification and remote CI are recorded in the
PR/receipt after committing; this document does not claim them in advance.

## Delivery boundaries

Engine and site changes are review branches. No main merge, release tag, live
fleet update or site deployment was performed. The companion cockpit is a
separate private application delivery; it does not turn these advisory engine
observations into execution authority. The site parity branch requires the
engine checker to be integrated publicly before its deploy workflows can pass.

Final pre-commit combined subset: **44 passed, 55 passed subtests** in 29.60s.
Singleton/roster subset: **11 passed** in 7.64s, including canonical-root aliases.
