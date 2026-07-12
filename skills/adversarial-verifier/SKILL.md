---
name: adversarial-verifier
description: Test whether a claimed invariant is genuinely enforced by deliberately breaking its implementation and requiring the named test to fail. Use for adversarial verification of gates, comparisons, boundaries, and prohibited-input controls.
license: Apache-2.0
metadata:
  m8shift-lane: advisory-read-only
  m8shift-report: required
---

# Adversarial verifier

Prove that a test protects the claimed behavior by making that behavior wrong.

## Mutation procedure

1. Name the invariant and the specific test claimed to enforce it.
2. Locate the enforcing comparison, gate, or validation path.
3. Apply one minimal mutation: neutralize a condition with `and False`, swap a
   boundary such as `>` and `>=`, or inject an input the control must ban.
4. Run the named test. It **must turn red for the expected reason**.
5. Revert only the mutation and rerun the test to green.
6. Record the mutation plus raw before/after test output as evidence.

Never leave a mutation in the tree. Respect the repository's write guard and do
not mutate when the current lane is read-only.

## False-evidence patterns

Reject tests that only grep source text, pin a constant, or count markers. Such
tests can stay green while the protected comparison or gate is disabled. They
may check packaging or structure, but they do not prove runtime enforcement.
