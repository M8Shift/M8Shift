# `m8shift.py` command reference

`m8shift.py` uses positional commands, like Git:

```text
m8shift.py <command> [args]
```

Run `m8shift.py <command> -h` for the authoritative parameter list installed
with your version. Do not prefix a command with `-` or `--`: use
`m8shift.py init`, not `m8shift.py -init` or `m8shift.py --init`.

This page is also the site-ready source for the public command reference. All
project names, agents, paths, turns, sessions, and timestamps below are
fabricated placeholders, so the page can be mirrored without exposing a live
relay.

## `init`

Purpose: create or refresh the M8Shift kit in the current project. Existing
relay state is preserved unless `--force` is explicit.

Parameters:

- `--name PROJECT`: project label; defaults to the folder name.
- `--agents AGENT,...`: active roster of two or more agents.
- `--lang CODE`: generated-file language.
- `--force`: reset the relay file as well as regenerating the kit.
- `--force-generated`: rebuild a damaged generated agent pack after backup.
- `--profile {bare,headless,ops,full}`: stable initialization profile.
- `--capabilities ID,...`: additive capability set.
- `--list-profiles`: list profiles without writing.
- `--gitignore` / `--no-gitignore`: enable or disable the generated ignore block.
- `--companions NAME,...`: companions to install.
- `--with-runtime`, `--with-context`, `--with-worktree`, `--with-headroom-companion`,
  `--with-i18n`, `--with-e2e`: install individual companions.
- `--full`: install all operational companions.
- `--no-companions`: explicitly install no companions.
- `--companion-source DIR`: directory from which companions are copied.
- `--force-companions`: replace an older or edited local companion.

```bash
./m8shift.py init --name my-project --agents agent-a,agent-b
```

## `update`

Purpose: update a target project's generated kit from a newer source copy
without resetting its relay history.

Parameters:

- `--target DIR` (required): project to update; use `.` explicitly for the current directory.
- `--source DIR`: source release or checkout; defaults to the running script's directory.
- `--components NAME,...`: `core`, `protocol`, `pack`, `anchors`, `runner`, or `companions`.
- `--companions NAME,...`: companions to refresh or install.
- `--dry-run`: print the plan without writing.
- `--json`: emit machine-readable results.
- `--allow-downgrade`: permit an older source version.
- `--allow-generation-change`: permit a major-version migration after review.
- `--allow-working`: permit an update while the target relay is working.
- `--force-generated`: rebuild damaged generated blocks after backup.

```bash
python3 /opt/m8shift/m8shift.py update --target ./my-project --dry-run
```

## `status`

Purpose: print a read-only snapshot of the lock, roster, current session, and
latest turn.

Parameters:

- `--json`: machine-readable snapshot.
- `--activity-limit N`: number of activity rows, clamped to 0–200.
- `--brief`: compact human-readable subset.
- `--for AGENT`: include the next safe action for that agent.

```bash
./m8shift.py status --for agent-a
```

## `time`

Purpose: report read-only effective-work, non-work, and unknown time for a session.

Parameters:

- `SESSION`: optional session id; defaults to `current`.
- `--json`: machine-readable accounting breakdown.

```bash
./m8shift.py time current
```

## `may-i-write`

Purpose: provide a point-in-time write guard. It exits 0 only while the named
agent owns a valid working pen.

Parameters: `AGENT` is the roster agent whose ownership is checked.

```bash
./m8shift.py may-i-write agent-a
```

## `guard`

Purpose: alias `may-i-write` for hooks and wrappers.

Parameters: `AGENT` is the roster agent whose ownership is checked.

```bash
./m8shift.py guard agent-a
```

## `watch`

Purpose: repeatedly render the read-only status view.

Parameters:

- `--for AGENT`: include that agent's next safe action.
- `--interval SECONDS`: polling interval; default 5.
- `--clear`: clear the terminal before each snapshot.
- `--changes-only`: print only when relay state changes.
- `--once`: render one snapshot and exit.

```bash
./m8shift.py watch --for agent-a --interval 5
```

## `doctor`

Purpose: run read-only health, integrity, installation, contract, security, and
publication-hygiene checks. It never repairs or takes the pen.

Parameters:

- `--json`: machine-readable findings.
- `--lint`: exit 1 for findings at or above `--severity-min`.
- `--security`: include security-oriented checks.
- `--contracts`: include contract-validation findings.
- `--hygiene`: scan publishable tracked files for sensitive path patterns.
- `--hygiene-only`: run only the hygiene checks.
- `--hygiene-verbose`: reveal local denylist matches for forensic use.
- `--hygiene-anchors`: also scan generated agent anchors.
- `--install`: include post-install verification.
- `--severity-min {info,warning,error}`: display and lint threshold.
- `--source DIR`: compare the installed core and runners with a source copy.

```bash
./m8shift.py doctor --lint --json
```

## `contract`

Purpose: validate advisory turn contracts.

Parameters for `contract validate`:

- `--strict`: exit 1 for findings at or above the selected threshold.
- `--json`: machine-readable findings.
- `--all`: include archived turns.
- `--severity-min {info,warning,error}`: displayed-finding threshold.

```bash
./m8shift.py contract validate --strict
```

## `recap`

Purpose: print a read-only briefing with lock state, recent turns, memory, and tasks.

Parameters:

- `--turns N`: turn summaries; default 6, non-positive means all.
- `--memory N`: memory headlines; default 5, non-positive means all.
- `--tasks N`: open-task headlines; default 5, non-positive means all.
- `--brief`: compact human-readable subset.

```bash
./m8shift.py recap --turns 3 --brief
```

## `peek`

Purpose: print the latest handoff addressed to an agent; exits 3 when it is not
that agent's turn.

Parameters: `AGENT` is the handoff recipient to inspect.

```bash
./m8shift.py peek agent-a
```

## `log`

Purpose: print the read-only relay turn timeline.

Parameters:

- `--limit N`: show only the latest N turns.
- `--all`: include archived turns.
- `--oneline`: use one compact line per turn.

```bash
./m8shift.py log --limit 10 --oneline
```

## `turn`

Purpose: fetch one immutable turn with its complete recorded text.

Parameters:

- `NUMBER`: turn number.
- `--json`: machine-readable turn payload.

```bash
./m8shift.py turn 42 --json
```

## `history`

Purpose: print folded relay-session history.

Parameters:

- `--limit N`: show only the latest N sessions.
- `--oneline`: one compact line per session.
- `--json`: machine-readable history.

```bash
./m8shift.py history --limit 5 --oneline
```

## `decisions`

Purpose: inspect the decision-record target or scaffold a decision record from
session turns.

Parameters:

- `decisions target --set {forge,github,both,git,md}`: persist a traceability target override.
- `decisions target --json`: machine-readable target information.
- `decisions scaffold --session SESSION`: source session; default `current`.
- `decisions scaffold --target {forge,github,both,git,md}`: one-run target override.
- `decisions scaffold --single`: append to one `DECISIONS.md` file.
- `decisions scaffold --title TEXT`: decision title.
- `decisions scaffold --status {proposed,accepted,superseded}`: recorded status.
- `decisions scaffold --json`: machine-readable scaffold result.

```bash
./m8shift.py decisions scaffold --session current --title "Choose cache policy"
```

## `session`

Purpose: inspect folded sessions and optionally render a Markdown report.

Parameters:

- `session list [--limit N] [--json]`: list sessions.
- `session show SESSION [--full] [--json]`: show turns; `--full` includes bodies.
- `session decisions SESSION [--json]`: show structured review decisions.
- `session report SESSION [--write] [--output PATH] [--force] [--include-body]`:
  render or write a report.

```bash
./m8shift.py session show current --full
```

## `wait`

Purpose: wait until it is the named agent's turn, the session ends, or a stale
peer lock needs attention.

Parameters:

- `AGENT`: roster agent waiting.
- `--interval SECONDS`: poll interval; default 60.
- `--once`: check once and exit 3 when not ready.

```bash
./m8shift.py wait agent-a --once
```

## `next`

Purpose: perform one safe resumption step: wait if necessary, claim, then print
the incoming handoff.

Parameters:

- `AGENT`: roster agent to resume.
- `--interval SECONDS`: polling interval; default 60.
- `--once`: make the readiness check non-blocking.
- `--force`: recover only a stale working lock.
- `--resume`: resume a paused session before claiming.
- `--reason TEXT`: required with `--resume`.
- `--work-item REF`: primary work reference for the new window.

```bash
./m8shift.py next agent-a --work-item task:42
```

## `claim`

Purpose: exclusively acquire or refresh the relay pen.

Parameters:

- `AGENT`: roster agent taking the pen.
- `--force`: reclaim only a stale working lock.
- `--refresh`: extend only the caller's current working lock.
- `--reason TEXT`: audit reason for recovery.
- `--live-override`: with `--force` and `--reason`, override a protected expired lock.
- `--check`: read-only readiness and overlap probe.
- `--files FILE,...`: planned files for `--check`.
- `--turns N`: overlap window for `--check`.
- `--work-item REF`: primary work reference for a new window.

```bash
./m8shift.py claim agent-a --work-item task:42
```

## `append`

Purpose: close the current working turn, record its result, and hand the pen to
another roster agent.

Parameters:

- `AGENT`: sending agent; it must already hold the pen.
- `--to AGENT` (required): different roster agent receiving the handoff.
- `--ask TEXT`: actionable request for the recipient.
- `--done TEXT`: summary of completed work.
- `--files FILE,...`: files touched.
- `--body FILE|-`: body file, or `-` for standard input.
- `--allow-large-body`: permit a body above the normal size limit.
- `--wait`: wait for the sender's next turn after handoff.
- `--wait-interval SECONDS`: polling interval used by `--wait`.
- `--branch`, `--commit`, `--tests`, `--next`, `--blocked-on`: optional delivery metadata.
- `--role-from`, `--role-to`, `--relation`, `--requires`, `--expected-output`,
  `--evidence`, `--decision`, `--waiver-reason`, `--schema`, `--permissions`:
  optional contract metadata.
- `--stance TAG`: explicit advisory decision stance.
- `--field KEY=VALUE`: repeatable custom advisory field.

```bash
./m8shift.py append agent-a --to agent-b \
  --ask "review task 42" --done "implemented task 42" --files m8shift.py
```

## `request-turn`

Purpose: ask the current holder to yield the pen. This writes the request ledger,
not the relay lock.

Parameters: `AGENT` is the requestor; `--to AGENT` names the current holder;
`--reason TEXT` is required.

```bash
./m8shift.py request-turn agent-a --to agent-b --reason "urgent review"
```

## `yield-turn`

Purpose: accept an open cooperative request and yield the pen.

Parameters: `AGENT` is the current holder; `--request N` identifies the request;
`--to AGENT` names the requestor; `--reason TEXT` adds an optional audit note.

```bash
./m8shift.py yield-turn agent-b --request 3 --to agent-a
```

## `decline-turn`

Purpose: decline an open cooperative turn request while keeping the pen.

Parameters: `AGENT` is the current holder; `--request N` identifies the request;
`--reason TEXT` is required.

```bash
./m8shift.py decline-turn agent-b --request 3 --reason "finishing an atomic change"
```

## `steer-turn`

Purpose: redirect an idle awaiting holder after an open request, with an audited
operator override.

Parameters: `AGENT` receives the turn; `--from AGENT` names the idle holder;
`--request N` identifies the request; `--force` and `--reason TEXT` are required.

```bash
./m8shift.py steer-turn agent-a --from agent-b --request 3 --force --reason "operator reassignment"
```

## `remember`

Purpose: append one durable advisory note without taking the pen.

Parameters: `AGENT` records the note; `NOTE` is single-line text.

```bash
./m8shift.py remember agent-a "release checks run before handoff"
```

## `pause`

Purpose: park an open session when no active task exists.

Parameters: `AGENT` parks the session; `--reason TEXT` explains why no agent
should take the pen.

```bash
./m8shift.py pause agent-a --reason "waiting for new scope"
```

## `cooldown`

Purpose: park an idle or awaiting relay until an external usage window recovers.

Parameters:

- `--until TIMESTAMP` (required): UTC cooldown end.
- `--reason TEXT` (required): cooldown reason.
- `--for AGENT`: agent to resume for; inferred when possible.
- `--source LABEL`: source label; default `manual`.
- `--wait-interval SECONDS`: recommended quiet polling interval.
- `--replace`: update an existing paused state.

```bash
./m8shift.py cooldown --until 2030-01-02T03:04:05Z --reason "usage window reset"
```

## `resume`

Purpose: resume a paused session for one agent after new scope arrives.

Parameters: `AGENT` receives the resumed turn; `--reason TEXT` states the new scope.

```bash
./m8shift.py resume agent-a --reason "task 42 approved"
```

## `work-tag`

Purpose: assign or replace one opaque primary work reference on the current
working window.

Parameters: `AGENT` must hold the pen; `WORK_ITEM` is the reference.

```bash
./m8shift.py work-tag agent-a task:42
```

## `task`

Purpose: maintain the shared append-only advisory task ledger without taking the pen.

Parameters:

- `task add AGENT DESC [--for AGENT] [--blocked-on TEXT]`: add a task.
- `task done AGENT ID`: mark an open task done.
- `task drop AGENT ID`: drop an open task.
- `task list [--all]`: list open tasks, or all final states.
- `task show ID`: show one task's complete event history.

```bash
./m8shift.py task add agent-a "document the command surface" --for agent-b
```

## `release`

Purpose: hand off without appending a numbered turn.

Parameters: `AGENT` is the current holder; `--to AGENT` is required; `--force`
overrides ownership or unread-turn checks and requires `--reason TEXT`.

```bash
./m8shift.py release agent-a --to agent-b
```

## `done`

Purpose: close the relay session so no further turns can be appended.

Parameters: `AGENT` closes the session; `--force` closes while another agent
holds the pen and requires `--reason TEXT`.

```bash
./m8shift.py done agent-a
```

## `archive`

Purpose: move older closed turns from the live journal into the archive.

Parameters: `--keep N` selects how many closed turns remain live; default 6.

```bash
./m8shift.py archive --keep 10
```

## `bind`

Purpose: durably pin an agent session to this project's relay. No pen is required.

Parameters:

- `AGENT`: roster identity to bind.
- `--candidate {env,script}`: choose between two detected relay candidates.
- `--show`: print this agent's effective binding.
- `--clear`: remove this agent's binding when safe.
- `--list`: list all bindings in the effective relay.

```bash
./m8shift.py bind agent-a
```

## `heartbeat`

Purpose: let a managed listener or wrapper record a protective liveness beat for
an agent that currently holds the working pen.

Parameters: `AGENT` is the working holder; `--source {runtime-listener,wrapper}`
names the managed producer; `--cadence-seconds N` records its real loop cadence.

```bash
./m8shift.py heartbeat agent-a --source wrapper --cadence-seconds 60
```
