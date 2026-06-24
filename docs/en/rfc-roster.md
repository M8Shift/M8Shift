# RFC — Configurable agent pair (roster) for M8Shift

> **Status**: `Superseded` (historical design record) · **Shipped in**: v2.1, then generalized · **Author**: Claude (synthesized from a 3-proposal design panel) · **Date**: 2026-06-21
>
> ⚠️ **Historical.** This RFC framed stage 1 as a *configurable pair* (first two active). The
> shipped model is broader: an **active roster of ≥2 agents, all of which relay**, with **one
> pen** (degree-1) — the holder hands off to any other member via `--to`. For the live model
> see [the protocol](protocol.md) §1–2 and the README. "Stage 2" below = **N *concurrent*
> writers** (degree-2, isolated worktrees) — see [rfc-n-agents.md](rfc-n-agents.md). The text
> below is kept as the original design record; read it as historical.

## 1. Summary

Today M8Shift hard-wires the pair **claude ⇄ codex**. This RFC generalizes the
**participants** to a configurable pair drawn from an **extensible roster**
(`claude`, `codex`, `lechat`, `gemini`, …) **without changing the concurrency
model**: it stays a **degree-1 mutex** (one pen, strict alternation between the two
chosen agents). It is a *minimal delta* — the lock, the `O_EXCL` serialization, the
TTL lease and the turn journal are untouched.

> See [architecture §1.8](architecture.md) — *a mutex, not a semaphore*. This RFC
> keeps the degree at 1; it widens the **alphabet** of agent names, not the number
> of simultaneous holders.

## 2. Goals / Non-goals

**Goals**
- Pick *which two agents* relay, at `init` time: `m8shift.py init --agents claude,lechat`.
- Default (no `--agents`) = `claude,codex` → **behaviorally identical** to today (the
  generated `M8SHIFT.md` gains one `agents:` line and the seed turn names the active
  pair; relay transitions and anchor injection are unchanged).
- Per-agent **anchor mapping** so each tool auto-loads its own instruction file.
- Honest handling of agents whose tool **does not auto-load any file** (manual bootstrap).

**Non-goals (this RFC)**
- **N agents working simultaneously** (degree > 1). That is a separate, larger step
  — see [§10 Stage-2 horizon](#10-stage-2-horizon-n-simultaneous-agents).
- Routing policies (`--to any`, round-robin, work queues). Deferred; the handoff
  stays **named** (`--to <the other>`), exactly like the binary relay.
- Discovering the roster by scanning which anchor files exist (too implicit/fragile).

## 3. Design overview

The roster is **declared at `init`** and **stored in the LOCK block** (the single
source of truth, already read by every command). One new field; everything else is
a parametric generalization of names that are *already* per-agent
(`WORKING_<X>` / `AWAITING_<X>`).

## 4. Roster & storage

- CLI: `init --agents claude,codex,lechat` — ordered, de-duplicated, normalized to
  ASCII `[a-z][a-z0-9_-]*`, **at least 2 members**. The **first two** are the active
  relaying pair; any extra names are **stored in `agents:` but inactive** until
  stage 2 (*resolved* — see §9 Q1).
- Storage: one new LOCK line `agents:   claude,codex` (CSV), next to `lang`.
  Grep-able, versioned, parsed by `get_lock` with a plain `split(",")`.
- Read: `roster(lk)` → `lk["agents"].split(",")` if present, else `("claude","codex")`
  (fallback for any pre-RFC `M8SHIFT.md` — **no migration required**).
- `init` without `--force` on an existing `M8SHIFT.md` **preserves** the in-place
  roster (like the rest of the LOCK).

## 5. Anchor mapping (the real crux)

A known name→anchor table, hard-coded, with a documented fallback:

```python
ANCHORS = {
    "claude":  "CLAUDE.md",
    "codex":   "AGENTS.md",        # + AGENTS.override.md
    "gemini":  "GEMINI.md",        # Gemini CLI auto-loads GEMINI.md
    "lechat":  "AGENTS.md",        # Le Chat / Mistral: AGENTS.md (best-effort) — see below
    # nested-path anchors (e.g. Copilot's .github/copilot-instructions.md) are out of
    # stage 1: ensure_canonical_anchor is not path-aware → manual-bootstrap fallback.
}
```

`init` iterates the roster, resolves each agent's file, and injects the stanza
(idempotent — `ensure_canonical_anchor` + `inject_anchor` unchanged, just called per
agent).

Two hard cases, handled explicitly (not silently):

1. **Anchor collision.** Several "codex-compatible" tools (`codex`, `lechat`,
   `mistral`) auto-load `AGENTS.md`. We inject **one** stanza there; with a roster
   that shares a file, the stanza must be **generic** ("you are one of the agents
   sharing this file; identify yourself by your host tool") and list the valid
   `--to` targets. Honest limit: a tool sharing `AGENTS.md` does not intrinsically
   *know* which roster name it is — agent identity remains a human/launch convention.
2. **No auto-load convention** (e.g. Le Chat today, or any cron/CI launched outside
   the project, or a tool with no project-doc mechanism). M8Shift is **passive**: it
   can provide the stanza but cannot force a read. `init` writes a best-effort
   fallback anchor and **prints a warning**: *"agent `<X>`: no known auto-loaded
   anchor — bootstrap it manually by pointing it at `M8SHIFT.protocol.md`."* The
   agent stays a full roster member (its `claim`/`append` work); only auto-bootstrap
   is missing. **This is documented as an assumed limit, not a bug.**

## 6. LOCK schema & states

- Fields unchanged + `agents` (CSV). `holder ∈ roster ∪ {none}`.
- States stay **one per agent** — `WORKING_<X>` / `AWAITING_<X>` — computed from the
  roster instead of a frozen tuple:

  ```python
  valid_states(roster) = {"IDLE", "DONE"} \
      ∪ {f"WORKING_{a.upper()}" for a in roster} \
      ∪ {f"AWAITING_{a.upper()}" for a in roster}
  ```

  `state.removeprefix("WORKING_").lower()` recovers the agent. No `queue`, no `next`,
  no broadcast — the strict prolongation of the binary model. `holder` remains the
  **single** pen owner.

## 7. Handoff, CLI & invariant

- `append <self> --to <X>`: `X ∈ roster`, `X ≠ self`, accepted **only from
  `WORKING_<self>`** (unchanged). Sets `holder=X`, `state=AWAITING_<X>`, `turn+1`.
  With the default 2-agent roster, `--to` can only name the other → handoff **unchanged**.
- `need_agent` validates against the **current roster** (read from the LOCK), not the
  module constant; the error lists the effective roster.
- `other(agent)` is kept but its role shrinks to the stale-lock detection in
  `wait`/`claim`, generalized to "derive the agent from `state`" rather than assuming
  a single counterpart.
- New CLI surface: just `init --agents …`. `status` additionally prints `agents: …`.
  Return codes unchanged.
- **Invariant (restated):** *at any instant at most one roster agent is in
  `WORKING_<X>` (⇔ `holder==X`); only the holder modifies the repo; every entry into
  `WORKING_<X>` requires a successful `claim`, and `claim` is exclusive across the
  roster.* The proof is **roster-cardinality-independent**: `state` is a single
  scalar, and `claim` only succeeds from `IDLE`, `AWAITING_<self>`, own
  `WORKING_<self>` (refresh), or `--force` on a *stale* `WORKING_<other>`. Adding
  names only enlarges the set of `<other>`; it creates no second route into
  `WORKING`.

## 8. Backward compatibility & migration

- `init` without `--agents` → roster `claude,codex`; all relay transition paths are
  unchanged. The generated `M8SHIFT.md` does gain one optional `agents:` line (and the
  seed turn names the active pair), so the *file* is not byte-for-byte identical to the
  pre-roster output. A roster-unaware (pre-RFC) script stays safe **only for the
  default pair**: it ignores `agents:` and would treat a custom roster as
  `claude,codex`, which can corrupt it — a custom roster requires a roster-aware script.
- A pre-RFC `M8SHIFT.md` with no `agents:` line loads via the `("claude","codex")`
  fallback — no rewrite, no migration tool. `init --force` rewrites the LOCK and adds
  `agents:`.
- `other()` and `test_other` stay; `stanza_for` keeps the historical 2-agent wording
  when `len(roster)==2` (so `test_protocol_docs_in_sync` and `test_stanza_for` are
  untouched). The generic/plural stanza only activates for a non-default roster.
- **Code impact** (small, localized): `roster()` helper + `--agents` normalization;
  `valid_states(roster)` instead of the `VALID_STATES` constant; `load_or_die`
  validates against it; `need_agent` against the roster; `cmd_append` validates
  `--to ∈ roster`; `cmd_init` loops anchor injection over the roster via `ANCHORS`;
  `agents:` line in the `COWORK_*` LOCK templates. Untouched: `file_lock`, atomic
  `write`, `archive`, TTL machinery.

## 9. Open questions

1. **Roster size.** ✅ *Resolved.* `--agents` accepts **≥2 names**; the **first two**
   relay in this version and any extra names are stored (reserved for stage 2). This
   keeps the binary relay while letting a project declare its full roster up front.
2. **`set_lock` field preservation.** ✅ *Resolved.* `agents` is carried through every
   `lk.update(...)` (it comes from `get_lock`); locked down by
   `test_agents_field_survives_claim` (get/set round-trip across a `claim`).
3. **Anchor identity.** When several agents share `AGENTS.md`, how does each tool know
   *which* roster name it is? Likely unsolvable purely in-file → document the
   launch-time convention.
4. **Protocol doc sync.** ✅ *Resolved (stage 1) — implemented.* The protocol prose
   **and** the LOCK states table are now **pair-agnostic** (`WORKING_<X>`/`AWAITING_<X>`,
   "the two active agents", generic `holder`); `init` hints and the seed turn
   interpolate the active pair. The `PROTOCOL_EN`/`PROTOCOL_FR` templates were
   genericized and `docs/en/protocol.md` / `docs/fr/protocole.md` regenerated — so the
   snapshot **did change** (it is *not* unchanged) and `test_protocol_docs_in_sync` was
   re-baselined against `m8shift.PROTOCOL[lang]`. The `agents:` field itself stays a
   backward-compatible **optional** addition within protocol v1 (old readers ignore it).
5. **`lechat` anchor.** ✅ *Resolved (best-effort).* The convention is unconfirmed, so
   `lechat`/`mistral` map to `AGENTS.md` as a **best-effort** guess; an agent with no
   known anchor (or one whose anchor is already taken) triggers a printed
   manual-bootstrap warning rather than blocking `init`.

## 10. Stage-2 horizon — N *simultaneous* agents

A **later** version (the "after-next") targets **true multi-agent**: more than one
agent writing **at the same time**. That is a different beast — **degree > 1** — and
the clean mutex no longer suffices:

- It becomes a **counting semaphore** (k > 1 holders) *or* a set of **partitioned
  sub-locks** (each agent owns a disjoint area of the repo).
- New problems appear that this RFC deliberately avoids: conflict detection/merge of
  concurrent edits, repo partitioning, deadlock across multiple locks, fairness.
- The roster from this RFC is the natural substrate for it, but the **single-pen
  invariant would be replaced** by a per-partition or counted invariant.

Stage 2 is **out of scope here** and should get its own RFC. This RFC keeps the
strong, simple guarantee (one writer) while making *who* the two writers are
configurable.
