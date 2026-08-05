# RFC 079 — The out-of-roster observer

- **Status:** draft / design-only
- **Date:** 2026-07-29
- **Issue:** #285
- **Scope:** invoking a third agent that produces observations without ever
  writing, and the guards that make its output usable as evidence
- **Siblings:** [RFC 032](032-rfc-tiered-delegation.md),
  [RFC 010](010-rfc-runtime-patterns.md) §B,
  [RFC 078](078-rfc-freshness-first-class.md)

## 1. The problem this closes

A two-agent relay alternating producer and reviewer catches a great deal, and
shares its blind spots. Both agents watched the same decisions being made and
read the artifact with a context its real recipient will not have. An agent that
has never seen the project reads **what is written**, not what was meant.

RFC 078 §2.1 and the evidence behind the multi-agent rationale say the same thing
from the model side: self-preference scales with self-recognition, and agreement
between agents that share a context is not independent evidence. The remedy is a
reader who shares no context — and the question is how to invoke one without
corrupting the coordination it is meant to inform.

## 2. The principle: a source of observations is not a decision mechanism

The reflex is to add the third agent to the roster. That is the error, and the
reason for it is the whole pattern:

> An agent that **writes nothing** needs no write token. Adding it to the roster
> would mix a *source of observations* into the *mechanism that decides*, and
> would mutate a live session for a participant with no writes to coordinate.

So the observer stays **outside the protocol**:

- it never takes the pen;
- it modifies no repository;
- its output is **material to sift, never a verdict**;
- the roster agents remain the sole authors of verdicts and corrections.

The mutex needs to know nothing about it. That is what makes the pattern
compatible with a passive core: **no protocol change is required.**

## 3. What already exists, and what is missing

The engine ships `consult --from --to --brief-file --save-response`, an advisory
`consults.jsonl` ledger, and a fail-closed attestation — `compile_consult_argv`
raises unless the adapter declares `sandbox=read_only`. RFC 032 provides the
delegation frame.

What it does not yet provide is everything below: the workspace construction, the
provenance header, the pinned model, and the two-pass method. Field use produced a
companion that supplies them; this RFC proposes folding them in rather than
leaving every adopter to rediscover them.

## 4. The guards, each from a real defect

| Guard | Defect it prevents |
|---|---|
| Refuse an output directory inside a versioned repository | raw output committed before filtering is a leak |
| **Named** allow-list for the workspace, cardinality derived from the list | a hard-coded count loosens for convenience the day a piece is added; a named list forces an explicit, reviewed edit |
| Scratch area **separate** from the workspace | output redirection created the response file *inside* the workspace, so the agent saw it — the allow-list lied at the exact moment it was supposed to guarantee |
| Isolation proven before the call: no extensions, no tool servers, no global context | read-only means read-only, **not read-only-the-pieces-provided**; an extension or a global context widens the input with no written rule broken |
| Atomic publication after a zero exit code **and** a verified structure | a failure leaves a valid-looking provenance attached to an empty output |
| Uniqueness marker observed free, never assumed | two runs in the same second overwrite each other |
| Mandatory provenance header: tool, version, model, input digest, timestamp | without it, the sift concerns an indeterminate state of the input |

**The rule that gives the last line teeth:** an output whose header lacks those
values is **not sifted, it is re-run**. Re-running is cheap; sifting an
unidentified source forces redoing everything without knowing what changed.

### 4.1 Why the workspace must be built, not merely declared

A first formulation said "do not submit unfiltered sources". That is not enough.
A command-line agent launched from a repository root has **read** access to the
whole tree. Read-only mode prevents writing, not reading: the output could return
confined content with no rule broken.

The effective guard is therefore that the tool **builds the workspace itself**,
outside any repository, and places in it only the artifact under review and the
brief.

## 5. Pinning the model is about comparability, not quality

A tool in automatic model selection is incompatible with a method that **compares
two passes**. If selection routes to one model on the first pass and another on
the second, the observed difference is no longer the effect of what was changed —
it is a change of model. One would sift an infrastructure artifact believing it to
be a substantive effect.

The model is therefore **pinned in the companion, not overridable on the command
line**, and reported in the provenance.

A corollary worth recording: model hierarchy by name no longer necessarily holds.
A "fast" model of one generation can beat the "pro" model of the previous one on
some public aggregates. The choice must be justified by the **nature of the
task** — judgement over long context versus agent loop — and carry a written
contra-indication for when that changes.

## 6. The two-pass method

**Cold pass** — without the internal frame of reference, to measure what the
artifact conveys on its own. Minimal framing only, and above all: **do not reveal
what you are looking for**, because a reader told what to look for finds it.

**Informed pass** — with the frame of reference, asking the reader to confirm,
withdraw or reclassify each initial observation.

**The material is the difference between the two passes**, not the second alone:
it separates a real defect from an objection that faults the artifact for not
being a different artifact.

For several artifacts of one family: independent cold passes in isolated contexts,
then one transverse pass receiving everything. Never serial reading — the last one
would no longer be read cold. The transverse pass confirms, withdraws or
reclassifies; it does not rewrite. A transverse pass needs more pieces than a cold
one, so it gets **its own profile with its own allow-list**, never a loosening of
the cold profile's.

## 7. What the relay consumes

Three artifacts, and the discipline that goes with them:

1. a **raw output**, archived, never rewritten;
2. a **provenance** that makes the output contestable;
3. a **sifting procedure** in which disagreement between agents is a result, not
   a problem.

## 8. Open questions

1. **Where does the companion live?** The guards are executable, not advisory, so
   they belong in code rather than in a document. Whether that is a new companion
   or an extension of the existing `consult` path is an implementation choice this
   RFC does not make.
2. **Does the provenance header belong in `consults.jsonl`?** The ledger records
   the call; the header describes the artifact. They may want to stay separate so
   the raw output remains self-describing away from the instance.
3. **How is the allow-list expressed** without becoming a second configuration
   language? A named list in a profile is the minimum; anything richer risks
   re-implementing the packer this project deliberately does not ship.

## 9. Provenance of this design

The pattern was not designed here. It was built and hardened in field use on
another shift, where every guard in §4 came from an observed defect — most found
in contradictory review, one by the validation itself — and was then written up
deliberately abstracted, with no project, repository, ticket or subject-matter
identity, so that it could be carried over as-is. That decision to carry it over
belongs to this project, and this RFC is it.
