# Shift demos — try M8Shift in minutes (#102)

Four tiny, self-contained exercises to watch a real two-agent relay exchange
(claim → work → append → review) with a **deterministic outcome**: identical
agent prose is never guaranteed, but the pass/fail oracle (a pinned value or a
pinned test) is the same for every agent pair. The reference pair is
`claude ↔ codex`; any two skills-capable agents work.

## Quickstart (same for every demo)

```bash
cd examples/shift-demos/<demo>                            # pick one below
python3 ../../../m8shift.py init --agents agent-a,agent-b # relay in THIS dir
# agent A (first turn):   python3 ../../../m8shift.py claim agent-a
# agent B (waits):        python3 ../../../m8shift.py wait agent-b
```

The `--agents` flag matters: a bare `init` creates the default
`claude,codex` roster, which would reject the neutral `agent-a`/`agent-b`
identities shown here. Substitute your real agent names freely
(e.g. `--agents claude,codex` and `claim claude`) — the oracles do not care.

Run each agent from its own terminal/session in this directory, roles as per
the demo README. Relay artifacts (`M8SHIFT.*`) are runtime state — the demo
`.gitignore` keeps them out of version control. Expect a handful of turns:
the turn counter in `status` is the screenshot money-shot.

| Demo | Oracle | Typical turns |
|------|--------|---------------|
| [compute-and-verify](compute-and-verify/) | pinned SHA-256 of a fixed file | 4-6 |
| [fix-and-review](fix-and-review/) | pinned failing test turns green | 4-6 |
| [spec-implement-verify](spec-implement-verify/) | pinned test file passes | 4-6 |
| [adversarial-verify](adversarial-verify/) | claim refuted against a fixed file | 4 |

Compartmentalization (RFC 052) applies: demos use placeholder names and
relative paths only — never paste your real project names or home paths into
demo turns.
