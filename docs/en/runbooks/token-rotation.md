# Operator runbook — Forge token rotation

Use this runbook to rotate a forge access token without interrupting local Git
delivery, CI, or managed listeners/runners. It implements the operator-only steps
of [RFC 068](../rfc/068-rfc-forge-token-rotation.md). The repository changes no
credential automatically.

All `<...>` strings below are placeholders. Replace them locally. Never paste a
real token into this document, a command argument, shell history, Git config,
relay text, issue, commit, or log.

## 1. Preconditions and stop conditions

Start from the repository root in a private operator shell. You need forge account
access, authority to manage the existing token and CI secret, and an inventory of
every listener/runner that inherits the token.

Stop before mutation if any of these is unknown:

- the old token's owner, repositories, scopes, or expiry;
- which `.env`, CI secret, helper, listener, or runner consumes it;
- whether a push, CI job, or managed invocation is currently in flight;
- the exact token scopes required by the approved RFC 065 workflow.

Disable tracing and create no transcript:

```sh
set +x
unset GIT_TRACE GIT_TRACE_PACKET GIT_TRACE_CURL
umask 077
```

Confirm that `.env` is ignored and private. The permission command is portable
across common macOS and Linux hosts; inspect its output and require owner-only
read/write (`600`) before continuing.

```sh
git check-ignore --quiet .env
test -f .env
stat -f '%Lp %N' .env 2>/dev/null || stat -c '%a %n' .env
```

The file contains exactly one colon-delimited entry for the token:

```text
FORGEJO_TOKEN:<token>
```

Do not print the line to verify it. This bounded check reports only the count:

```sh
awk -F: '$1 == "FORGEJO_TOKEN" { count++ } END { print "FORGEJO_TOKEN entries=" count; exit count == 1 ? 0 : 1 }' .env
```

## 2. Inventory and baseline

Create a secret-free rotation record in the governing ticket. For each consumer,
record only its name, owner, adoption boundary, current generation label, and
status:

| Consumer | Adoption boundary | Baseline | Replacement | Post-revoke |
|---|---|---|---|---|
| Local helper / pre-push | next helper process | pending | pending | pending |
| CI secret | next job start | pending | pending | pending |
| Listener `<agent>` | explicit managed restart | pending | pending | pending |
| Runner `<agent>` | first child after parent restart | pending | pending | pending |

Record all active pushes, CI jobs, and listener invocations by bounded job ID and
commit SHA. Do not record environment dumps, request headers, or command output
that might contain credentials.

Load the current value from `.env` into the shell without displaying it. The
subprocess writes only into shell command substitution; tracing must remain off.

```sh
export FORGEJO_TOKEN="$(python3 - <<'PY'
import sys

with open('.env', 'r', encoding='utf-8') as source:
    values = [line.split(':', 1)[1].rstrip('\n') for line in source
              if line.split(':', 1)[0] == 'FORGEJO_TOKEN']
if len(values) != 1 or not values[0]:
    raise SystemExit('refusing: expected exactly one non-empty FORGEJO_TOKEN entry')
sys.stdout.write(values[0])
PY
)"
```

Run a baseline read-only API request and a representative push dry-run. The probe
prints status and account name, never a request header or token.

```sh
FORGE_API_URL='https://<forge-host>/api/v1/user' python3 - <<'PY'
import json
import os
import urllib.request

request = urllib.request.Request(
    os.environ['FORGE_API_URL'],
    headers={'Authorization': 'token ' + os.environ['FORGEJO_TOKEN']},
)
with urllib.request.urlopen(request, timeout=15) as response:
    payload = json.load(response)
    print('forge API read: status=%s account=%s' % (response.status, payload.get('login', '<unknown>')))
PY
GIT_TERMINAL_PROMPT=0 git push --dry-run <remote> HEAD:refs/heads/<authorized-test-branch>
unset FORGEJO_TOKEN
```

If either baseline check fails, repair it before rotating; otherwise the cutover
cannot distinguish a pre-existing outage from a rotation regression.

## 3. Create the replacement at the forge

In the forge UI for `https://<forge-host>`:

1. create a new token with a non-secret generation label and a short expiry;
2. restrict it to `<repository-or-project>`;
3. grant repository metadata read and content push only if required;
4. grant issue and pull/merge-request write only if the approved workflow uses it;
5. omit user/org admin, deletion, hooks, packages, and unrelated repositories;
6. copy the value directly into the private operator shell or secret store; and
7. leave the old token active.

If the forge cannot express those scopes, stop and record the exception for an
operator decision. Do not silently copy the old token's broader authority.

Read the new value without echoing it and export it only to the current shell:

```sh
printf '%s' 'Paste replacement token (input hidden): ' >&2
stty -echo
IFS= read -r ROTATION_NEW_TOKEN
stty echo
printf '\n' >&2
export ROTATION_NEW_TOKEN
test -n "${ROTATION_NEW_TOKEN}"
```

If the shell is interrupted while echo is disabled, run `stty echo` before doing
anything else.

## 4. Verify the replacement before cutover

The following read-only probe keeps the token out of argv and prints only a status
plus the authenticated account name. Set the API URL placeholder first.

```sh
FORGE_API_URL='https://<forge-host>/api/v1/user' ROTATION_PROBE_TOKEN="${ROTATION_NEW_TOKEN}" python3 - <<'PY'
import json
import os
import urllib.request

request = urllib.request.Request(
    os.environ["FORGE_API_URL"],
    headers={"Authorization": "token " + os.environ["ROTATION_PROBE_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=15) as response:
    payload = json.load(response)
    print("forge API read: status=%s account=%s" % (response.status, payload.get("login", "<unknown>")))
PY
```

Temporarily expose the replacement under the name consumed by the configured Git
credential helper. The helper definition must read `FORGEJO_TOKEN` from its
environment; it must not contain or interpolate the token into argv, a URL, or
Git config.

```sh
export FORGEJO_TOKEN="${ROTATION_NEW_TOKEN}"
GIT_TERMINAL_PROMPT=0 git push --dry-run <remote> HEAD:refs/heads/<authorized-test-branch>
```

Use a representative branch/ref covered by the intended token scope. `--dry-run`
must report success without changing the remote. If the API probe or dry-run
fails, unset the variables, correct the token/scope, and repeat this section. Do
not update consumers or revoke the old token.

## 5. Atomically update the local `.env`

This script replaces exactly one `FORGEJO_TOKEN:` entry, preserves every other
line, writes mode `600`, and atomically renames the result. The token is read from
the environment, not argv.

```sh
ROTATION_ENV_FILE='.env' python3 - <<'PY'
import os
import tempfile

path = os.environ["ROTATION_ENV_FILE"]
token = os.environ["ROTATION_NEW_TOKEN"]
with open(path, "r", encoding="utf-8") as source:
    lines = source.readlines()
indexes = [i for i, line in enumerate(lines) if line.split(":", 1)[0] == "FORGEJO_TOKEN"]
if len(indexes) != 1:
    raise SystemExit("refusing: expected exactly one FORGEJO_TOKEN entry")
lines[indexes[0]] = "FORGEJO_TOKEN:" + token + "\n"
directory = os.path.dirname(os.path.abspath(path))
fd, temporary = tempfile.mkstemp(prefix=".env.rotation-", dir=directory, text=True)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        target.writelines(lines)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
```

Repeat the count and permission checks from §1. Do not display or diff `.env`.
Retain the old value only in the operator's secret store until §8; do not create a
repository-adjacent backup.

## 6. Propagate while both generations are valid

1. Replace the CI secret named `<ci-secret-name>` through the forge's encrypted
   settings. Do not place it in a workflow file or CLI argument.
2. Stop dispatching new token-dependent work.
3. For each listener, wait for the current child invocation to reach its normal
   safe boundary, then stop/start or managed-restart the listener so it reloads
   the environment.
4. Verify each restarted process is healthy and its redacted plan reports only the
   variable name/presence. Never inspect or log the value.
5. Launch one bounded no-mutation preflight through each runner consumer.
6. Run a fresh CI job after the secret update and require its authenticated,
   non-mutating gate to pass.
7. Reload `.env` with the private loader from §2, then repeat the API probe and
   Git push dry-run from §4.

Mark a consumer `Replacement=pass` only from a process or job started after that
consumer's adoption boundary.

## 7. Drain in-flight work

Do not revoke while any pre-cutover work is unresolved.

- Let an active push finish or cancel it. If its result is uncertain, compare the
  exact local SHA with the authoritative remote ref before retrying.
- Let an old-generation CI job finish or cancel it. A replacement-generation job
  must then run from the same intended commit.
- Let a listener child reach its safe boundary; do not kill it mid-effect merely
  to shorten the overlap window.

Keep the old token valid until every row is settled. If the overlap exceeds the
operator's limit, keep new work stopped and investigate; do not revoke on a timer.

## 8. Revoke the old generation

Preflight the inventory: every consumer is replacement-green, every in-flight item
is settled, and both §4 checks still pass. Then revoke the old token in the forge
UI by its generation label. Do not delete the replacement.

Perform a controlled negative check of the old generation from the operator's
secret store: the read-only API endpoint must return the forge's unauthenticated
or forbidden response. Keep the old value out of argv and output, then delete it
from the secret store. Record only the status/result and UTC time.

```sh
printf '%s' 'Paste revoked old token for one negative check (input hidden): ' >&2
stty -echo
IFS= read -r ROTATION_OLD_TOKEN
stty echo
printf '\n' >&2
export ROTATION_OLD_TOKEN
FORGE_API_URL='https://<forge-host>/api/v1/user' python3 - <<'PY'
import os
import urllib.error
import urllib.request

request = urllib.request.Request(
    os.environ['FORGE_API_URL'],
    headers={'Authorization': 'token ' + os.environ['ROTATION_OLD_TOKEN']},
)
try:
    urllib.request.urlopen(request, timeout=15)
except urllib.error.HTTPError as error:
    if error.code not in (401, 403):
        raise SystemExit('unexpected old-generation status=%s' % error.code)
    print('old generation rejected: status=%s' % error.code)
else:
    raise SystemExit('refusing completion: old generation still authenticates')
PY
unset ROTATION_OLD_TOKEN
```

## 9. Post-revocation verification

With fresh replacement-generation processes/jobs:

1. repeat the read-only API probe;
2. repeat the representative Git push dry-run;
3. run a fresh CI authenticated no-mutation gate;
4. recheck listener health and one bounded runner preflight per consumer; and
5. confirm no old-generation job/process remains.

Run repository integrity and raw leak gates over the exact change/delivery range.
Do not route the leak scan through a lossy output filter and do not paste matching
raw lines into the ticket. Record only pass/fail plus bounded redacted locators.

Rotation is complete only when every inventory row is `Post-revoke=pass`, the old
generation is revoked, and the replacement remains valid.

## 10. Resume after interruption or failure

This runbook is re-entrant. On return, inspect the secret-free inventory and begin
at the first incomplete proof:

- replacement not created or not proven: repeat §§3–4;
- `.env` or CI not updated: repeat the relevant atomic update;
- consumer adoption unknown: restart/re-run only that consumer and verify it;
- in-flight work unknown: reconcile exact remote/job state before retrying;
- old token still active: remain in overlap until all rows are green;
- old token revoked: never restore it; diagnose the replacement or mint another
  generation through this same runbook.

Before revocation, rollback means restoring the old token from the operator's
secret store through the same atomic/secret-setting paths and re-verifying every
affected consumer. After revocation, failure is a new incident and requires a new
generation; it is not rollback.

Finally clear the ephemeral shell values:

```sh
unset ROTATION_NEW_TOKEN ROTATION_PROBE_TOKEN FORGEJO_TOKEN FORGE_API_URL
```
