# compute-and-verify

Agent A computes the SHA-256 of `input.txt` (fixed, do not edit) and appends
the value; agent B independently recomputes it, compares against
`EXPECTED.sha256`, and approves or blocks. Fixed input → fixed digest: the
outcome is deterministic for any agent pair. Suggested flow (~4-6 turns):
A `claim` → compute → `append --to <B> --ask "verify"` → B recompute+compare →
`append` verdict → A closes with `done` when both sides match.
