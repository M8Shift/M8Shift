# RFC — `subturn` (sub-agent fan-out provenance) — **REJECTED**

**Status:** REJECTED (roadmap item "🌿 `subturn`") · decided by an adversarial design panel
(Q0 + 3 angles → skeptical synthesis). The roadmap closes at **v3.4.0**; `subturn` does **not** ship.

## Q0 — does this belong, or is it already covered? → **REJECTED**

The idea: let an agent record its sub-agent fan-out (e.g. a workflow of reviewers) *under its turn*,
for provenance. The panel weighed it against what already ships and rejected it. Reasoning:

- **§5 advisory turn fields already cover the informational case.** `--field` is repeatable
  (`collect_advisory_fields` loops `args.field`), so an agent stamps N provenance values on one turn
  (`--field x_review_a=pass --field x_review_b=fail`), each `clean_field`-safe and surfaced verbatim
  by `peek`.
- **`remember` already covers the streaming/durable case.** The only thing §5 structurally cannot do
  is record a note *before* `append` (a turn abandoned/crashed before its append writes nothing). But
  `remember` is pen-free, durable (`write` + `os.replace`), timestamped, and file-ordered — an agent
  can already stream one durable line per sub-step *during* the turn with `remember`.
- **The only genuine differentiator — an `@turn` tag — is not dumb-ledger-shaped.** `LOCK.turn` is the
  *last completed* turn; tagging a subturn `@LOCK.turn+1` is **frequently a lie**: wrong when recorded
  with no pen (IDLE/DONE/AWAITING), wrong for two concurrent pen-free writers, wrong after the agent
  already appended. And reading `LOCK.turn` into a ledger line is the first step of *state decorating
  routing* — an explicit charter non-goal. Without the tag, `subturn` is just `remember`.

**Conclusion:** `subturn` adds no informational capability over §5, and its streaming/durable value is
already served by `remember`; the one distinctive feature (the turn tag) is either inaccurate or an
authority-creep. A fourth gitignored sibling ledger + a command + a `recap`/`log` tail is **redundant
surface that does not earn its keep**. Reject is the clean, complete endpoint.

## Guidance (what to do instead)

- **At-append provenance summary** → §5 advisory fields: `append … --field x_subagents="3 reviewers: 2 pass, 1 fail"`.
- **Mid-turn / crash-durable, per-step provenance** → `remember <you> "sub-step: …"` (pen-free, durable, timestamped).

## Rejected design (for the record)

The reduced sketch the panel evaluated: `subturn <agent> "<did>"` appending `- @<turn> <iso> <agent>: <did>`
to a gitignored `M8SHIFT.subturns.md`, pen-free, with `log`/`recap` grouping by turn. Cut entirely — see above.
