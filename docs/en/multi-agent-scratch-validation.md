# Multi-agent scratch validation

This report validates the shipped multi-agent primitives in M8Shift v3.60.0.
All commands ran in a fresh throwaway Git repository named `scratch-relay` with
the roster `claude,codex,codex-2`. No existing relay was used or modified.

## Result

| Area | Result | Evidence |
|------|--------|----------|
| N-agent initialization | Pass | `init --agents claude,codex,codex-2` created an `IDLE` relay with all three names in the lock roster. |
| Identity discrimination | Pass | A turn sent to `codex-2` made `claim codex` fail and `claim codex-2` succeed; the next turn recorded `codex-2` as its author. |
| Provider model pin | Pass after explicit configuration | Managed Codex rows rendered distinct `--model` arguments. Scaffolded nonstandard agents are not launchable until configured. |
| Listener lifecycle | Partial | The detached `codex-2` listener became `ALIVE` and carried its pinned model into the runner plan, but the nested Codex process could not initialize on the validation host. |
| Two concurrent Codex sessions | Blocked by host | Both processes were launched concurrently, but both failed before provider contact with the same local app-server permission error. Collision, quota, and model-access behavior remain unproven. |
| Degree-2 worktrees | Pass with a setup precondition | Two worktrees were claimed and committed concurrently; their integrations were serialized into `main`. The canonical root had to release `main` first. |
| Add an agent to a live roster | Gap | There is no non-destructive, same-session roster-mutation command. `init --force --agents ...` resets the living journal and starts a new session. |

## 1. N-agent routing and identity discrimination

The scratch relay was initialized with:

```console
./m8shift.py init --name scratch-relay \
  --agents claude,codex,codex-2 --full --gitignore
```

The resulting lock exposed all three active agents. Routing was then exercised
as follows:

```console
./m8shift.py claim claude
./m8shift.py append claude --to codex-2 \
  --ask "verify identity isolation" --done "routed to codex-2"
./m8shift.py claim codex        # refused: awaiting codex-2
./m8shift.py claim codex-2      # accepted
./m8shift.py append codex-2 --to codex \
  --ask "confirm separate lane" --done "codex-2 claimed its own turn"
```

`status --for codex` instructed `codex` to wait while `status --for codex-2`
instructed `codex-2` to claim. The lock state used `AWAITING_CODEX-2` and
`WORKING_CODEX-2`, and the immutable turn author was `codex-2`. The core relay
therefore discriminates the two Codex identities by exact roster name.

One bootstrap limitation is visible: `codex-2` has no built-in dedicated anchor
mapping. Initialization prints a manual-bootstrap warning. Sharing `AGENTS.md`
is workable for this scratch test, but an operator must explicitly tell the new
session that its relay identity is `codex-2`.

## 2. Provider pin and listener launch

`providers init --agents claude,codex,codex-2` did not infer that `codex-2` is
another OpenAI Codex lane. Its initial row used provider `codex-2`, an empty
`argv`, and model `UNSET`. This is fail-closed and safe, but it is not directly
launchable.

The scratch row was explicitly changed to the managed adapter contract:

```json
{
  "name": "codex-2",
  "provider": "openai-codex",
  "model": "operator-selected-model-id",
  "mode": "headless",
  "argv": ["codex", "exec", "$M8SHIFT_PROMPT"],
  "anchor": "AGENTS.md",
  "permissions": "workspace-write",
  "capabilities": ["read_repo", "write_repo", "run_tests"],
  "requires_env": []
}
```

After syntactically valid operator-selected model IDs were set,
`providers check` accepted both managed Codex rows and `providers render`
inserted each row's own `--model` value. The remaining `UNSET` warning belonged
to a non-launchable interactive Claude row. Model accessibility could not be
proven because process startup failed before provider contact.

The listener dry run and detached start were then exercised:

```console
./m8shift-runtime.py listener start --agent codex-2 --provider \
  --backend local --runner examples/headless_runner.py --dry-run
./m8shift-runtime.py listener start --agent codex-2 --provider \
  --backend local --runner examples/headless_runner.py
./m8shift-runtime.py listener status --agent codex-2
```

The launch plan contained `agent=codex-2`, the row's pinned `agent_model`, the
compiled `codex exec --model ...` argv, and `--agent-model ...` for the runner.
The detached listener became process-resident and reported `ALIVE`.

The first real child invocation then failed before it could claim the scratch
turn:

```text
Error: failed to initialize in-process app-server client: Operation not permitted
```

A direct one-shot `codex exec` failed identically. The listener correctly
classified each attempt as `non_completion`, backed off, and halted after its
configured three failures. It was then stopped. This validates listener
lifecycle and failure containment, but not a successful model response.

## 3. Concurrent Codex sessions

Two `codex exec` processes, using the two configured model IDs, were started at
the same time. Both reached the same local app-server permission failure before
network/provider contact. There was no evidence of a relay identity collision,
but there was also no opportunity to observe quota sharing, model availability,
or two successful concurrent sessions.

This acceptance item must be rerun on a host that permits nested Codex CLI
startup. A passing rerun requires all of the following:

1. Both commands reach their selected provider model.
2. Both return their distinct marker response.
3. Neither reports a session collision, credential lock, or quota error.
4. The `codex-2` listener claims and appends only the `codex-2` turn.
5. `listener status --agent codex-2` records a non-empty successful run.

An `ALIVE` listener process alone is not sufficient evidence that an agent is
online and able to complete turns.

## 4. Degree-2 worktrees and degree-1 integration

The worktree companion created both lanes concurrently:

```console
python3 m8shift-worktree.py claim feature-codex codex \
  --base main --branch task/codex
python3 m8shift-worktree.py claim feature-codex-2 codex-2 \
  --base main --branch task/codex-2
```

Both feature worktrees existed at once and accepted independent commits. Their
`done` ledger records also serialized without loss.

The first integration attempt failed safely because `main` was still checked
out at the canonical root. Git cannot also assign that branch to the dedicated
`_integration` worktree. The safe setup is:

```console
git switch --detach main
```

The canonical root must be clean before this step. A coordination branch is
also valid; the invariant is that only `_integration` owns the target branch.

After that precondition, the two integrations succeeded in sequence:

```console
python3 m8shift-worktree.py integrate feature-codex-2 codex-2 \
  --into main --to codex
python3 m8shift-worktree.py integrate feature-codex codex \
  --into main --to claude
```

`main` contained two merge commits, one for each feature branch. The shared
relay advanced through two ordinary handoffs, so isolated degree-2 production
and serialized degree-1 integration behaved as designed.

## 5. Live roster expansion is not supported safely in place

Running `init` against the populated scratch journal with one added roster name
and without `--force` failed closed:

```console
./m8shift.py init --agents claude,codex,codex-2,reviewer
# refused: requested roster differs from the declared roster
```

The SHA-256 of `M8SHIFT.md` was unchanged after the refusal.

Repeating the command with `--force` changed the hash, replaced the living
journal, created a new session, and returned the relay to turn 0 in `IDLE` with
the four-name roster. The session ledger records a reset event, but that event
does not preserve the removed turn bodies. Therefore:

- `init --agents` without `--force` is non-destructive but cannot add an agent;
- `init --force --agents` changes the roster by resetting the relay;
- no shipped `roster add` or equivalent command preserves the current session;
- manually editing the lock is unsupported and bypasses relay invariants.

### Safe procedure today

There is no safe same-session procedure to add an agent to a live roster. Do
not run `init --force` on an active production journal.

The supported zero-loss alternative is a planned session boundary:

1. Finish or hand off all work; confirm no `WORKING_*` holder remains.
2. Have the awaited holder close the session with `./m8shift.py done <agent>`.
3. Move every closed turn out of the living file with
   `./m8shift.py archive --keep 0`.
4. Copy `M8SHIFT.md`, `M8SHIFT.archive.md`, `M8SHIFT.sessions.jsonl`, and the
   memory/task/request ledgers to a read-only backup location. Record and verify
   checksums before continuing.
5. Prefer initializing a new adjacent relay directory with the expanded roster;
   leave the completed relay untouched as the historical record.
6. If an in-place new session is operationally required, only then run
   `./m8shift.py init --force --agents <full-roster> ...`. Treat it as session
   rotation, not live roster mutation, and verify the archive and backup again.
7. Run `providers init --agents <full-roster>`, explicitly configure every new
   managed provider row and model pin, then run `providers check` and a listener
   dry run.
8. Install or document the new agent's anchor, start a fresh agent session so it
   reloads the roster, and verify exact-name routing before assigning real work.

Step 5 is the safest option because it does not mutate the completed relay at
all. Step 6 preserves history only because steps 3 and 4 externalize and verify
it first; the living journal and session identity still reset.

## Follow-up gaps

1. Add an audited roster-mutation command that preserves the current lock,
   session, journal, and existing anchors while adding a validated inactive or
   active agent.
2. Add a provider-template selector so names such as `codex-2` can explicitly
   reuse the `openai-codex` adapter without hand-editing JSON.
3. Add a first-class per-agent anchor/identity bootstrap for multiple instances
   of the same CLI family.
4. Rerun successful listener and two-session concurrency acceptance on a host
   that permits nested Codex CLI processes.
