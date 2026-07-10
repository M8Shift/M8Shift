# RFC 052 — Project compartmentalization and data-hygiene gates

Status: draft (rev 3 — folds in Codex adversarial review, turn 374)
Target: v3.56.0 candidate (PR-staged; see §PR staging)
Related issue: #101 (cloisonnement), #100 (usage adapters, separate → RFC 040 Phase 4), incident INC-2026-0708-M8SHIFT-CROSS-SHIFT-LEAK
Owner: core relay (`doctor` hygiene lint) + generated agent-pack/anchors + optional `scripts/scrub-check.py` + agents-guide
Co-analysis: Claude (4-lens incident analysis) + Codex (adversarial scoping + RFC review). Design-only; no code until PR1 boundaries are confirmed.

## Summary

An operator and an agent routinely work across **several projects/shifts** on one machine (call them Project A = this M8Shift-tool repo, Project B = a private client-facing web project, Project C = an earlier project). Incident **INC-2026-0708** showed Project B's **identifier** and a **real absolute home path** (`/Users/<operator>/…/Project B`) crossing into Project A's repo — pasted verbatim from a live session capture into `docs/en/rfc/046-…md` — reaching a (private) GitHub repo's content, history, and immutable `refs/pull/*`. It was the **second** such leak (Project C's name + a real home path already live in Project A's history): a prose feedback note did not become a product invariant. *(This RFC deliberately uses placeholders for the foreign projects — naming them here would be the very violation it defines.)*

Root cause: **no compartmentalization norm existed anywhere, and no mechanical outbound-hygiene gate existed.** Every existing guard governs the pen/turn or prompt-security; none governs cross-project data boundaries.

This RFC defines **one product policy** (projects compartmentalized by default) + **one lint/scanner family** making it mechanical, within the charter (stdlib-only, no network, no daemon, cooperative-advisory). Session-binding (a shift binds to one named session) is specified but **deferred to a later slice / RFC 038 amendment** (§Session binding), because it changes relay/session selection semantics.

## Problem

1. **No default-deny data boundary** — nothing tells the agent to abstract project A's identifiers before they enter project B's durable records.
2. **Runtime output pasted into durable artifacts** — a real `watch`/`status`/JSON capture became an RFC example; "redact later" never happened.
3. **No outbound gate** — nothing inspected content for foreign identifiers or absolute home paths before commit/push.
4. **Detection was lossy** — the first leak-hunt `grep` ran through the `rtk` optimizer and reported CLEAN (false negative); raw `/usr/bin/grep` found all six lines.
5. **Late detection → irreversible surfaces** (`refs/pull/*`) → **prevention before the first push is the only real defense.**
6. **Memory is a cross-project substrate** — the harness global auto-memory indexes all projects at once (see §Enforcement boundaries for what M8Shift can and cannot do about this).

## The default invariant

> **Projects/shifts are compartmentalized by default.** No project's records, docs, code, commits, issues, or RFCs may carry another project's **identity** (name/brand), **real paths** (`/Users/<name>/…`, internal program names), or **real session data** (literal `watch`/`status`/log output). A fact learned in shift A may inform reasoning in shift B, but **its identifiers stay in A** — abstracted at intake ("a real adopter frozen at vN", never the project name; a single-adopter pinned version is itself an identifier). **Cross-reference is DENY by default and requires explicit, per-fact operator opt-in.**

Placement matters more than prose (a prose-only rule failed twice): **delivered** (agent-pack + anchor floor marker, §C2), **standing** (top of the operator's memory index), **lintable** (§C1).

## Enforcement boundaries (honest scope — Codex review #2)

M8Shift can mechanically enforce compartmentalization **only for M8Shift-owned artifacts**: relay files, the generated agent-pack, anchors, session ledgers/reports, context packs, and optional note frontmatter. It **cannot** technically prevent the Claude/Codex/harness **global memory** from surfacing foreign identifiers — that store is outside M8Shift's boundary. For that layer this RFC provides only: (a) first-read behavioral rules (agent-pack/anchors), (b) generated-pack delivery + staleness lint, (c) optional metadata (`originSessionId` already exists; future `surface_scope` / `do-not-surface-in`), (d) operator-facing warnings. **No claim of full memory isolation is made.**

## Design

### C1 — `doctor` hygiene path lint (`hygiene.foreign_path`)

Read-only lint flagging **real absolute home roots** in **tracked, publishable** files.

- **Surface**: `doctor --hygiene` (report/warning) and `doctor --lint --hygiene` (gate, **rc 1** on high-confidence path findings). Off unless requested.
- **Scope**: `git ls-files` limited to publishable trees — `docs/**`, top-level `*.md` (README/CONTRIBUTING/RFCs), `examples/**`. **Exclude** generated relay state, gitignored local sidecars, and the anchors `CLAUDE.md`/`AGENTS.md` by default (they legitimately hold the operator's own path — see Q2). **`examples/**` is NOT excluded** — publishable examples must use placeholders (Codex #3/Q3).
- **Read** (Codex #4, hardened): stdlib `open()` in **binary**, matched in-process with `re` on bytes — **never** shelled to `grep`/`git grep`, **never** through `rtk`/any optimizer. Skip binary-looking files (report `hygiene.unreadable_binary_skipped` at info; never crash). Cap max file size and max line length (reuse the usage-scan bounds). Decode for display with `errors="replace"` **only after** a byte match; never print large raw lines.
- **Patterns** (Codex #3 — documented detection candidates):
  - high-confidence (→ rc 1 under `--lint`): `/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>`, WSL `/mnt/<drive>/Users/<name>/`;
  - lower-confidence / advisory (warning only): `/Volumes/<name>/` (legit external drives), UNC `\\host\share`, env-var home forms `%USERPROFILE%` / `%HOMEDRIVE%%HOMEPATH%`.
  ```
  /Users/[^/\s]+/    /home/[^/\s]+/    C:\\Users\\[^\\\s]+    /mnt/[a-z]/Users/[^/\s]+/
  ```
- **Finding**: `hygiene.foreign_path` with `file:line` + a placeholder hint (`~/code`, `/path/to/project`).
- **Verified**: matches **5 of the 6** leaked lines in RFC 046 at HEAD, zero config — would have caught INC-2026-0708 on the first run.

### C2 — Compartmentalization delivered at first read

- `## Compartmentalization` section in the generated `M8SHIFT.agent-pack.md` carrying the invariant + the behavioral session rule ("bind to one active shift at start; if ambiguous, ask; do not import identifiers from other shifts").
- A `STANZA_FLOOR_MARKER` so anchors go stale (existing `anchor.stanza_stale` check) if the rule is absent. Pure doc generation between markers; charter-clean.

### C3 — Operator denylist (`hygiene.denylist`) — confidential

Covers foreign proper nouns the path lint can't know (a private project name like `PrivateProjectName`, an internal program name like `InternalProgramName`, a client code name like `ClientCodeName`).

- **Out-of-repo only**, never committed. **Precedence** (Codex #5): `$M8SHIFT_DENYLIST` if set → else a documented config path (`~/.config/m8shift/denylist.txt`) → else empty/missing = **no-op**.
- **Empty by default** → advisory no-op until populated (charter-clean).
- **Confidential (Codex #5)**: denied terms are sensitive. Default output shows `file:line` + a **redacted/hashed label**, NOT the protected identifier; a `--verbose`/forensic mode may show matched terms **locally**. Never print the full denied-term list or large raw lines in normal output.
- Word-boundary or literal modes; allowlist exceptions; `severity=warning` by default (higher FP risk). Hard-block only under `M8SHIFT_SCRUB_ENFORCE=1` or explicit project policy.
- **Never auto-discovers sibling projects (Q4)** — auto-discovery would require the detector to read across projects, violating the rule it enforces. Operator-seeded.
- Shares the C1 raw-read engine.

### E1/E2 — History + pre-push scrub-check (layering clarified — Codex #7)

- **E1** `scripts/scrub-check.py` (stdlib; stays in `scripts/`, Codex #6/Q4 — not the context companion): reads the out-of-repo denylist and scans **tip** (`git grep -F <term> HEAD`) + **history** (`git log --all -S <term>`, optionally `refs/pull/*`) via raw `git`, **revisions before `--`** (bad ordering yields false negatives — proven this incident). **Direct invocation exits non-zero on any hit.** Read-only.
- **E2** shipped hook wrapper (opt-in `hooks/pre-commit` + new `pre-push`): invokes `./m8shift.py doctor --lint --hygiene` (and optionally E1) **directly** (never via shell grep/rtk). **Layering**: the hook **catches** a non-zero scanner result and **exits 0 unless `M8SHIFT_SCRUB_ENFORCE=1`** (advisory by default); scanner **errors fail open but are printed/visible**; `--no-verify`-bypassable by design. Fires at the last safe moment before content leaves the machine.
- ⚠️ History over `refs/pull/*` can be slow → bound it; keep advisory (never a de-facto daemon).

### A1–A5 — Agent operating-model guidance

In `docs/en/agents-guide.md`, `CONTRIBUTING.md`, and the generated agent-pack (not runtime code):

- **A1** default project-isolation contract (the invariant).
- **A2** intake airlock — abstract an adopter/usage fact at ingestion; if a load-bearing detail can't be abstracted → **STOP, request opt-in** (A4).
- **A3** runtime output is radioactive for durable artifacts — examples are **fabricated** from placeholders (`My Project`, `/path/to/project`, `~/code`, `agent-a`, `vX.Y.Z`), never screenshot-then-redact.
- **A4** explicit, fact-scoped opt-in — a recognizable inline token (`CLOISON-OK: <fact> in <target>`), auditable, non-reusable; silence is never opt-in.
- **A5** detection-integrity — leak/forensic scans run on **raw** tools by absolute path, never through `rtk`; a "clean" via a lossy path is UNVERIFIED, re-run raw before any close/APPROVE.

## Session binding (deferred to PR4 / RFC 038 amendment — Codex #1, #8)

Operator requirement: a shift is a work session bound to **one** project. **PR1 carries only the behavioral rule** (in the agent-pack): *"bind to one active shift/session at start; if ambiguous, ask the operator; do not import identifiers from other shifts."* The **mechanical** parts — tool refusal on ambiguity, relay-namespace listing, `--relay-session` binding — belong in **PR4 / an RFC 038 amendment**, not PR1, because they change relay/session selection semantics.

⚠️ **Naming (Codex #8)**: `m8shift.py session …` already means read-only session **reports/decisions**. RFC 038 relay namespaces use `--relay-session` / `M8SHIFT_RELAY_SESSION`. The mechanical listing/bind command (PR4) must use RFC 038's exact term (e.g. `sessions list`) or be explicitly marked future RFC 038 surface — do NOT overload `session`.

Memory scoping for the bound shift is bounded by §Enforcement boundaries (M8Shift-owned artifacts only).

## Answers to the open questions (Claude ↔ Codex)

- **Q1 posture** — C1 high-confidence paths: **rc 1 under `--lint`**, warning under plain `--hygiene`. C3 denylist: **warning** even under `--lint` unless `M8SHIFT_SCRUB_ENFORCE=1`.
- **Q2 anchor paradox** — exclude anchors from the default C1 scan; ship an **optional PR3 anchor mode** with an **explicit allowed-root** (username-pin the operator's own `/Users/<name>`) so *foreign* home roots in anchors are still flagged. No default `rc 1` for anchors.
- **Q3 examples** — do **not** exclude `examples/**`; require placeholders there.
- **Q4 denylist bootstrapping + scrub-check home** — operator-seeded, never auto-discovered; `scrub-check.py` lives in `scripts/`.
- **Q(immutable refs)** — prevention is primary; post-leak remediation (`git-filter-repo` + delete/recreate for `refs/pull/*`) is operator-driven, out of product runtime; ship at most a documented runbook.

## Charter fit

C1, C2, A-guidance, E1 are stdlib-only / no-network / read-only-advisory. C3 + E2 hard-block only under `M8SHIFT_SCRUB_ENFORCE=1`; default advisory. No daemon, no network; core `m8shift.py` network posture unchanged.

## PR staging

- **PR 1** (small, testable): C2 (agent-pack `## Compartmentalization` section + `STANZA_FLOOR_MARKERS` + stale-anchor tests) + C1 (`doctor --hygiene` / `--lint --hygiene`, exclude anchors by default, scan `examples/**`) + fixtures (real home paths **fail**, placeholders **pass**, `examples/**` scanned) + docs/agents-guide/CONTRIBUTING. **The behavioral session rule (text only) rides in the agent-pack. No session-binding code.** *Catches 5/6 leaked lines.*
- **PR 2** *(implemented — baseline post-v3.56.0)*: C3 out-of-repo confidential denylist (`$M8SHIFT_DENYLIST` -> `~/.config/m8shift/denylist.txt` -> no-op; redacted hashed labels, `--hygiene-verbose` local forensics; warning that never gates `--lint` unless `M8SHIFT_SCRUB_ENFORCE=1`) + `scripts/scrub-check.py` (tip via `git grep -F`, history via `git log --all --pickaxe-regex -i -S`; revisions before `--`; word semantics post-filtered in-process because `\b` in `git grep -E` is silently CLEAN on BSD/macOS regex — an empirically-caught false negative) + `hooks/pre-push` (new) and a `hooks/pre-commit` advisory hygiene stage (the #39 pen guard is unchanged) + 15 tests (argument-order safety, redaction/precedence, parser-drift core-vs-script, hook layering, scanner-error fail-open).
- **PR 3** *(implemented)*: opt-in `doctor --hygiene-anchors` re-scans the generated anchors (excluded from C1 by default — the Q2 paradox) with an explicit allowed-root pin (`M8SHIFT_HYGIENE_ALLOWED_ROOTS`, comma-separated, case-insensitive comparison — a case-variant of the operator's own root on a case-insensitive filesystem is not foreign); only FOREIGN home roots are flagged (`hygiene.anchor_foreign_path`, advisory — never gates `--lint` unless `M8SHIFT_SCRUB_ENFORCE=1`); unset roots yield an info notice, never a guess. The generated stanza's own `/Users/…` (real UTF-8 ellipsis) is now a recognized placeholder.
- **PR 4** *(design drafted — RFC 038 §9 amendment, under Codex review)*: session-binding mechanics — A1 write-refusal on two-candidate relay ambiguity (leftover `M8SHIFT_ROOT` + cwd-local relay = the recorded leak vector), A2 penless per-agent `bind` record, A3 fail-closed binding verification in `may-i-write`/`claim`/`append` (foreign path redacted), A4 read-only `sessions list` (RFC 038 surface, single-project), A5 agent-pack mechanical line + floor marker. Zero-config path byte-identical.

Order: **PR 1 first**, then #100 (RFC 040 Phase 4), unless the operator prioritizes usage adapters.

## Acceptance criteria

- `doctor --lint --hygiene` → rc 1 on a tracked publishable file (incl. under `examples/**`) containing a high-confidence real home root; rc 0 on placeholders; anchors excluded by default; binary files skipped (`hygiene.unreadable_binary_skipped`), never crashing.
- The compartmentalization section (incl. the behavioral session rule) is generated into the agent-pack; its absence makes anchors stale (`anchor.stanza_stale`).
- The denylist reads only from `$M8SHIFT_DENYLIST` → config path → empty no-op; output is redacted by default; warning-only unless enforced.
- `scrub-check.py` flags a denied term on tip and history; revisions precede `--`; exits non-zero on hit; the shipped hook exits 0 unless `M8SHIFT_SCRUB_ENFORCE=1`; never routes through rtk.
- No new network/daemon surface.

## Status / next

Rev 3 addresses all 8 Codex findings + the four open questions. **PR1 implemented** (baseline v3.56.0): agent-pack stanza + floor marker, `doctor --hygiene`/`--lint --hygiene`/`--hygiene-only`, anchors excluded, placeholder-aware fixtures. **PR2 implemented** (baseline post-v3.56.0): C3 denylist + E1 `scripts/scrub-check.py` + E2 hooks, per the PR-staging entry above. **PR3 implemented** (opt-in anchor mode per the PR-staging entry above). **Next: PR4 (session-binding mechanics, RFC 038 amendment).**
