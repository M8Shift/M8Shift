<!-- ╔════════════════════════════════════════════════════════════╗
     ║  COWORK · single-file multi-agent relay · protocol v1      ║
     ║  Read COWORK.protocol.md BEFORE writing here.              ║
     ╚════════════════════════════════════════════════════════════╝ -->

# COWORK · cowork

> Shared work file. **Only one agent writes at a time.** The lock is the
> `LOCK` block below. Only write if `state == AWAITING_<you>`. Details →
> [COWORK.protocol.md](COWORK.protocol.md). Tool → `./cowork.py status`.

<!-- COWORK:LOCK:BEGIN -->
holder:   none
state:    IDLE
agents:   claude,codex
lang:     en
turn:     0
since:    2026-06-21T20:39:51Z
expires:  -
note:     session initialized, no turn opened
<!-- COWORK:LOCK:END -->

---

## Turn log

<!-- Turns stack below, from oldest to most recent.                          -->
<!-- Turn format: see COWORK.protocol.md §3. Never edit a turn that is        -->
<!-- already closed (END set): add a new turn instead.                        -->

<!-- COWORK:TURN 0 system BEGIN -->
- from:    system
- to:      none
- ask:     —
- done:    Relay initialization. The first agent that starts runs
           `./cowork.py claim claude` (or `codex`), works, then
           `./cowork.py append claude --to codex --ask "..." --done "..."`.
- files:   COWORK.md, COWORK.protocol.md, cowork.py
- handoff: none
<!-- COWORK:TURN 0 system END -->
