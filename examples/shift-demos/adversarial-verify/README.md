# adversarial-verify

`CLAIM.md` contains a plausible-but-wrong claim about `facts.txt` (fixed, do
not edit). Agent A relays the claim as if true; agent B refutes it with raw
evidence (`wc -l facts.txt`, `sed -n '42p' facts.txt`) — both parts of the
claim are wrong in a checkable way. Showcases the second-opinion value of a
relay: the refutation is deterministic. ~4 turns.
