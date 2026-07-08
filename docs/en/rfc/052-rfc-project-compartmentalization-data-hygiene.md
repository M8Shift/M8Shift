# RFC 052 — Project compartmentalization and data-hygiene gates

Status: draft
Target: v3.56.0 candidate (PR-staged; see §10)
Related issue: #101 (cloisonnement), #100 (usage adapters, separate), incident INC-2026-0708-M8SHIFT-CROSS-SHIFT-LEAK
Owner: core relay (`doctor` hygiene lint) + generated agent-pack/anchors + optional scrub-check helper + agents-guide
Co-analysis: Claude (4-lens incident analysis) + Codex (adversarial scoping). This draft is for Codex adversarial review **before any code**.

## Summary

An operator and an agent routinely work across **several projects/shifts** on one machine (the product M8Shift-tool, a WordPress site, books…). Incident **INC-2026-0708** showed that a private project's **identifier** ("Project B") and a **real absolute home path** (`/Users/<op>/Documents/Code/internal-web-workspace/Project B`) crossed from one shift into the M8Shift-tool repository — pasted verbatim from a live session capture into `docs/en/rfc/046-…md` — and reached a (private) GitHub repo's content, history, and immutable `refs/pull/*`. It was the **second** such leak in this repo (an earlier "internal-book-workspace" / `/Users/<op>` leak lives in history).

The root cause was not a narrow tooling bug: **no compartmentalization norm existed anywhere in the stack, and no mechanical outbound-hygiene gate existed.** Every existing guard governs the pen/turn or prompt-security; none governs cross-project data boundaries.

This RFC defines **one product policy** (projects are compartmentalized by default) and **one lint/scanner family** that makes it mechanical, all within the M8Shift charter (stdlib-only, no network, no daemon, cooperative-advisory). It also specifies a **session-binding** extension (a shift binds to one named session) so compartmentalization is enforced by binding, not only discipline.

## Problem

1. **No default-deny data boundary.** A fact learned in shift A may legitimately inform shift B (product feedback from a real adopter), but nothing tells the agent to **abstract A's identifiers** before they enter B's durable records.
2. **Runtime output pasted into durable artifacts.** A real `watch`/`status`/JSON capture (real name + real path) became an RFC example; redaction "later" never happened.
3. **No outbound gate.** Nothing inspected content for foreign identifiers or absolute home paths before commit/push. `doctor` lints relay/session hygiene, not data leakage.
4. **Detection was lossy.** The first leak-hunt `grep` was routed through the operator's `rtk` token-optimizer and reported CLEAN (false negative); raw `/usr/bin/grep` found all six lines.
5. **Late detection → irreversible surfaces.** By discovery the string had reached history + `refs/pull/*` (un-rewritable), forcing a `git-filter-repo` scrub + private-repo recreate. **Prevention before the first push is the only real defense.**
6. **Memory is a cross-project substrate.** The harness global auto-memory indexes all projects at once, so foreign identifiers are already "in hand" while working a given shift — making literal cross-reference feel natural rather than transgressive.

## The default invariant

> **Projects/shifts are compartmentalized by default.** No project's records, docs, code, commits, issues, or RFCs may carry another project's **identity** (name/brand), **real paths** (`/Users/<name>/…`, internal program names), or **real session data** (literal `watch`/`status`/log output). A fact learned in shift A may inform reasoning in shift B, but **its identifiers stay in A** — abstracted at intake ("a real adopter frozen at vN", never the project name; a single-adopter pinned version is itself an identifier). **Cross-reference is DENY by default and requires explicit, per-fact operator opt-in.**

Placement matters more than prose (a prose-only rule already failed twice): the invariant is **delivered** (agent-pack + anchor floor marker, §C2), made **standing** (top of the operator's memory index), and made **lintable** (§C1).

## Design

### C1 — `doctor` hygiene path lint (`hygiene.foreign_path`)

A new read-only `doctor` hygiene family that flags **real absolute home-directory roots** in **tracked, publishable** files.

- **Surface**: `doctor --hygiene` (report) and `doctor --lint --hygiene` (gate). Off unless requested.
- **Scope**: files from `git ls-files` limited to publishable trees — `docs/**`, `*.md` (README/CONTRIBUTING/RFCs), `examples/**`. **Exclude** generated relay state, gitignored local sidecars, and the local anchors `CLAUDE.md`/`AGENTS.md` (they legitimately hold the operator's own path — see §Q2).
- **Read**: stdlib `open()` in binary, matched in-process with `re` — **never** shelled out to `grep`/`git grep` and **never** through `rtk`/any optimizer (the detector must read raw bytes on disk; a "clean" via a lossy path is UNVERIFIED). Reuse the existing usage-scan file-size / line-count bounds.
- **Patterns** (high-confidence real home roots):
  ```
  /Users/[^/\s]+/     /home/[^/\s]+/     C:\\Users\\[^\\\s]+     /Volumes/[^/\s]+/
  ```
- **Finding**: `hygiene.foreign_path` with `file:line` + a placeholder-convention hint (`~/code`, `/path/to/project`).
- **Enforcement (Q1)**: `doctor --hygiene` = **warning/report only**; `doctor --lint --hygiene` = **rc 1** for these high-confidence path findings (an absolute home root in a publishable doc is a low-false-positive hygiene violation, and `--lint` is already an explicit gate). Denylist findings (§C3) stay **warning** even under `--lint` unless explicitly promoted (§C3).
- **Verified**: this matches **5 of the 6** leaked lines in RFC 046 at HEAD, zero operator config — it would have caught INC-2026-0708 on the first run.

### C2 — Compartmentalization delivered at first read

- Add a `## Compartmentalization` section to the generated `M8SHIFT.agent-pack.md` carrying the invariant (short enough to be first-read every session).
- Add a `STANZA_FLOOR_MARKER` so a project's anchors (`CLAUDE.md`/`AGENTS.md`) go **stale** (existing `anchor.stanza_stale` `doctor` check) if the compartmentalization rule is absent — the rule is both delivered and lintable.
- Pure doc generation between existing markers; no runtime behavior. Charter-clean.

### C3 — Operator denylist (`hygiene.denylist`)

The path lint cannot know that "Project B"/"internal-web-workspace" are *foreign proper nouns*. An operator-owned denylist covers them.

- **Out-of-repo only** (e.g. `~/.config/m8shift/denylist.txt` or `$M8SHIFT_DENYLIST`), **never committed** — an in-repo denylist would re-leak the very names it protects.
- **Empty by default** → advisory/no-op until the operator populates it (charter-clean).
- Word-boundary or literal match modes; allowlist exceptions; `severity=warning` by default.
- **Never auto-discovers sibling projects (Q4)** — the detector must not itself read across project boundaries (that would violate the rule it enforces). The operator seeds it.
- Shares the C1 raw-read engine.
- ⚠️ Medium false-positive risk (a denied word may be a common noun) → warning-only; hard-block only under `M8SHIFT_SCRUB_ENFORCE=1` or an explicit project-local policy.

### E1/E2 — History + pre-push scrub-check

- **E1** `scripts/scrub-check.py` (stdlib): reads the out-of-repo denylist and, for each term, scans **both** surfaces the working-tree grep misses — the **tip** (`git grep -F <term> HEAD`) and **full history** (`git log --all -S <term>`, optionally `refs/pull/*`), via raw `git` (revisions placed **before** `--`; the incident proved bad argument ordering yields false negatives). Non-zero exit on any hit. Read-only.
- **E2**: wire C1 (and optionally E1) into the shipped opt-in `hooks/pre-commit` and a new `pre-push` by invoking `./m8shift.py doctor --lint --hygiene` **directly** (never via shell grep or rtk). **Advisory by default** (warn, exit 0); **hard-block only under `M8SHIFT_SCRUB_ENFORCE=1`**; fail-open on scanner error, fail-closed on findings; `--no-verify`-bypassable by design. Fires at the last safe moment before content leaves the machine.
- ⚠️ History scan over `refs/pull/*` can be slow on large repos → bound it; keep advisory so it never becomes a de-facto mandatory daemon.

### A1–A5 — Agent operating-model guidance

Delivered in `docs/en/agents-guide.md`, `CONTRIBUTING.md`, and the generated agent-pack (not runtime code):

- **A1** the default project-isolation contract (the invariant above).
- **A2** intake airlock: abstract an adopter/usage fact at ingestion ("a real adopter frozen at vN…"), never the project name; if a load-bearing detail can't be abstracted → **STOP and request opt-in** (A4).
- **A3** runtime output is radioactive for durable artifacts: examples are **fabricated** from a fixed placeholder vocabulary (`My Project`, `/path/to/project`, `~/code`, `agent-a`, `vX.Y.Z`) — never screenshot-then-redact.
- **A4** explicit, fact-scoped opt-in: a recognizable inline token (e.g. `CLOISON-OK: <fact> in <target>`), auditable, non-reusable; silence is never opt-in.
- **A5** detection-integrity: leak/forensic scans run on **raw** tools by absolute path, never through `rtk`/any optimizer; a "clean" via a lossy path is UNVERIFIED and must be re-run raw before any close/APPROVE.

### Session binding (extends RFC 038) — operator requirement, NEW to Codex

A shift is a work session bound to **one** project; compartmentalization is enforced by **binding**, not only discipline:

- **Bind one at start**: a shift connects to a **specific named session** (RFC 038 `M8SHIFT_RELAY_SESSION` / `--relay-session`); it does **not** auto-resume/load *all* sessions the agent holds in memory.
- **Ask when ambiguous**: if **several sessions exist in parallel**, the tool surfaces them and the agent must **ask the operator which one to bind** — no silent default across ambiguous sessions (a single session may bind by default).
- **Scope to the bound shift**: work and authoritative context are the connected shift only; other shifts' identifiers stay out (ties to A1/A3).
- **Tool support**: a relay `session list` / bind step so the *tool* helps enforce one-shift binding (candidate: `status`/`next` refuse to proceed with an ambiguous unbound session set until one is chosen). Memory scoping is partly harness-level (the global auto-memory loads all projects) → at minimum the behavioral rule (A1) plus optional `surface_scope` / `do-not-surface-in` note frontmatter keyed on the existing `originSessionId`.

> **Open design question for Codex**: how much of session-binding is an RFC 038 *tool* extension (session list + ambiguity refusal + bind step) vs. agent-operating-model, and how far memory-scoping can realistically go given the harness loads all projects. Should session-binding be its own PR slice (PR 4) or folded into PR 1?

## Answers to the co-analysis open questions

- **Q1 enforcement posture** — C1 high-confidence paths: **rc 1 under `--lint`**, warning under plain `--hygiene`. C3 denylist: **warning** even under `--lint` unless `M8SHIFT_SCRUB_ENFORCE=1`.
- **Q2 anchor paradox** — exclude anchors (`CLAUDE.md`/`AGENTS.md`) from the default C1 scan (they hold the operator's own path); ship an **optional PR 3 anchor mode** with an **explicit allowed-root** config (username-pin the operator's own `/Users/<name>` so *foreign* home roots in anchors are still flagged). No default `rc 1` for anchors.
- **Q3 immutable-refs remediation** — **prevention is primary**; post-leak remediation (`git-filter-repo` + delete/recreate for `refs/pull/*`) is operator-driven and stays **out of product runtime**. Ship at most a **documented runbook** (docs), not tooling.
- **Q4 denylist bootstrapping** — operator-seeded, **never auto-discovered** by the product (auto-discovery would require the detector to read across projects — a compartmentalization violation).

## Charter fit

- C1, C2, D-guidance, E1 are cleanly **stdlib-only / no-network / read-only-advisory**.
- C3 + E2 hard-block only under an explicit env flag; default advisory. No daemon, no network.
- No provider/network behavior anywhere in core `m8shift.py`.

## PR staging (§10)

- **PR 1** — C2 (agent-pack section + floor marker) + C1 (`doctor --hygiene` path lint) + tests (RFC046-style path fixtures) + docs/agents-guide/CONTRIBUTING. *Catches 5/6 leaked lines; highest coverage per effort.*
- **PR 2** — C3 out-of-repo denylist + `scripts/scrub-check.py` (tip + history) + optional pre-push hook + tests (argument-order safety, RTK-bypass rule). *Catches proper nouns.*
- **PR 3** — optional anchor hygiene (explicit allowed roots, advisory, no default rc 1). Only after PR 1/2 prove stable.
- **PR 4 (open)** — session-binding (RFC 038 extension) — scope TBD with Codex.

Order: **PR 1 first**, then #100 (RFC 040 Phase 4 usage adapters), unless the operator prioritizes usage adapters.

## Acceptance criteria

- `doctor --lint --hygiene` returns rc 1 on a tracked publishable file containing a real home root; rc 0 on placeholders; anchors excluded by default.
- The compartmentalization section is generated into the agent-pack and its absence makes anchors stale (`anchor.stanza_stale`).
- The denylist is read only from an out-of-repo path, empty-default no-op, warning-only unless enforced.
- `scrub-check.py` flags a denied term on both tip and history; revisions precede `--`; exits non-zero on hit; never routes through rtk.
- No new network/daemon surface; core `m8shift.py` unchanged in network posture.

## Open questions for Codex (adversarial review)

1. Session-binding placement (own PR vs. PR 1) and how far memory-scoping is achievable given the harness auto-memory — this requirement is **new since turn 371**; please weigh in.
2. C1 pattern set: are the four home-root patterns enough, or add Windows `%USERPROFILE%` / UNC `\\host\share` / WSL `/mnt/<drive>/Users/…`? False-positive risk of `/Volumes/` (legit external drives in examples)?
3. Should PR 1's C1 default-exclude `examples/**` that legitimately demonstrate absolute paths, or require placeholders there too (I lean: require placeholders everywhere)?
4. `scrub-check.py` as a `scripts/` helper vs. a `m8shift-context.py`/companion subcommand — where does it belong given it shells to `git`?
