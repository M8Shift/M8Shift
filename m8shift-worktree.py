#!/usr/bin/env python3
"""m8shift-worktree.py — §8 degree-2 companion for m8shift.py.

Parallel feature **worktrees** (degree-2: many agents work at once, isolated) + a serialized,
crash-safe **integration pen** (degree-1: only `integrate` takes the ONE canonical pen) layered on
top of the passive degree-1 core. NOT part of `m8shift.py`; opt-in.

It imports the core and uses ONLY its low-level helpers (`file_lock`/`get_lock`/`set_lock`/
`load_or_die`/`render_turn`/`now`/`iso`/`configure_root`/`active_agents`) — NEVER the `cmd_*` CLI
functions (they `sys.exit` and would make the wrong transitions). Stdlib only.

  claim     <id> <agent> --base <b> [--branch <b>]   add a feature worktree on a (new) branch
  done      <id> <agent>                             note the task done (dumb ledger line)
  integrate <id> <agent> --into <branch> --to <next> serialized non-committing merge + handoff
  drop      <id> <agent> --yes                        remove a feature worktree (never automatic)
  status    [<id>]                                    canonical LOCK + companion worktrees
  doctor    [--json]                                  read-only ownership findings (advisory)

Ownership (RFC 049 PR C): `claim` records the claiming agent in a sidecar OUTSIDE the checkout
(`.m8shift/worktree-owners/<id>.json`); `done`/`integrate`/`drop` refuse when a DIFFERENT agent
owns the worktree unless `--takeover --reason TEXT` is explicit (audited in the sidecar). This
is an ADVISORY companion guardrail, never a security boundary — direct git/editor/filesystem
writes do not pass through the companion and cannot be refused.

Safety (see docs/en/rfc/008-rfc-worktree-companion.md, the CONVERGED v1 contract): the `.m8shift.lock` is
held ONLY around the fast LOCK flips, never around `git merge`; the merge is `--no-ff --no-commit`
so an abort is a real rollback; an `integrating:<id>@<sha>` sentinel guards the pen against a TTL
reclaim mid-merge; the merge is committed only after re-verifying holder+state+sentinel+HEAD under
the lock; every non-crash post-claim path hands off via `--to` (no stuck WORKING).
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = None        # canonical repo root (set in main, before any core read/write)
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")   # mirrors the core sentinel id class
VERSION = "3.56.0"


def die(msg):
    sys.exit(f"m8shift-worktree: {msg}")


def load_core():
    path = os.path.join(HERE, "m8shift.py")
    if not os.path.isfile(path):
        die("m8shift.py must sit next to m8shift-worktree.py")
    spec = importlib.util.spec_from_file_location("m8shift", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()


# ───────────────────────────── git + path helpers ──────────────────────────────

def git(args, cwd=None, check=True):
    r = subprocess.run(["git", "-C", cwd or ROOT, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r


def git_out(args, cwd=None):
    return git(args, cwd, check=False).stdout.strip()


def resolves(ref, cwd=None):
    return bool(git_out(["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"], cwd))


def safe_branch_name(branch, label="branch"):
    if not branch:
        die(f"{label} is empty")
    if branch.startswith("-") or any(ord(c) < 32 or c.isspace() for c in branch):
        die(f"unsafe {label} {branch!r} — no leading '-' / whitespace / control characters")
    r = git(["check-ref-format", "--branch", branch], check=False)
    if r.returncode != 0:
        die(f"unsafe {label} {branch!r} — not a valid Git branch name")
    return branch


def local_branch_exists(branch):
    return git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0


def merge_in_progress(tree):
    return bool(git_out(["rev-parse", "--verify", "--quiet", "MERGE_HEAD"], tree))


def safe_id(i):
    if not ID_RE.match(i or "") or ".." in i or "/" in i:
        die(f"unsafe id {i!r} — use [A-Za-z0-9][A-Za-z0-9_-]* (no '/', '..', spaces)")
    return i


def wt_path(idv):
    return os.path.join(ROOT, ".m8shift", "worktrees", idv)


def integ_path():
    return os.path.join(ROOT, ".m8shift", "worktrees", "_integration")


def discover_root():
    """$M8SHIFT_ROOT, else the parent of `git rev-parse --git-common-dir` (so a LINKED worktree
    resolves to the canonical main checkout, never its own copy). Refuse bare/ambiguous layouts."""
    env = os.environ.get("M8SHIFT_ROOT")
    if env:
        return os.path.abspath(env)
    r = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if r.returncode != 0:
        die("not inside a git repository (and $M8SHIFT_ROOT is unset)")
    common = os.path.abspath(r.stdout.strip())
    if os.path.basename(common) != ".git":
        die("bare/ambiguous git layout — set $M8SHIFT_ROOT to the canonical repo root explicitly")
    return os.path.dirname(common)


def foreign_checkout_of(branch):
    """Path of a NON-integration worktree that has <branch> checked out, or None.
    Merging into a branch checked out elsewhere is unsafe, so `integrate` refuses it pre-flip."""
    integ = os.path.abspath(integ_path())
    path = None
    for line in git_out(["worktree", "list", "--porcelain"]).splitlines():
        if line.startswith("worktree "):
            path = os.path.abspath(line[len("worktree "):])
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()             # e.g. refs/heads/main
            if ref == f"refs/heads/{branch}" and path and os.path.abspath(path) != integ:
                return path
    return None


def roster_or_die(lk, *names):
    roster = core.active_agents(lk)
    for n in names:
        if n not in roster:
            die(f"unknown agent {n!r} — roster is {' | '.join(roster)}")
    return roster


# ──────────────── owner sidecar (RFC 049 PR C — advisory, never authority) ────────────────
#
# Ownership metadata lives in `.m8shift/worktree-owners/<id>.json`, a sibling of the peer's
# checkout rather than a file inside it, so NORMAL edits confined to the worktree do not
# touch it. This is an ADVISORY companion guardrail, NOT a security boundary: a process with
# filesystem access can address the sidecar path directly, and direct `git`, editor, or
# filesystem writes never pass through the companion and cannot be refused (RFC 049 "Security
# and prompt boundaries"). Consequently every READER fails open (a malformed/unreadable
# sidecar degrades to "no recorded owner" and `doctor` reports the gap), while every WRITE is
# hardened against path-escape (unpredictable temp via the core primitive + validated real
# parents), and a MANDATORY audit write (a takeover) fails CLOSED if it cannot be persisted.

OWNER_SCHEMA = "m8shift.worktree_owner.v1"
OWNER_MAX_BYTES = 8192           # an owner doc is ~200 bytes; anything larger is not ours
OWNER_FIELD_MAX = 256            # bound every recorded string field (defeats oversized echo)
_TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z", re.ASCII)  # strict ASCII UTC-Z
_AGENT_RE = re.compile(core.AGENT_RE + r"\Z", re.ASCII)   # anchored ASCII roster-agent shape
_UNSAFE = re.compile(r"[^\x20-\x7e]")                      # printable-ASCII whitelist for echo


def _safe(value, cap=OWNER_FIELD_MAX):
    """Reduce any recorded/derived string to a short printable-ASCII token before it reaches
    a terminal (RFC 052 §9.5 prompt-safety): control chars / ANSI escapes → `?`, length
    capped. NEVER echo an untrusted agent/id/path/reason/filename raw."""
    if not isinstance(value, str):
        value = str(value)
    return _UNSAFE.sub("?", value)[:cap]


def owners_dir():
    return os.path.join(ROOT, ".m8shift", "worktree-owners")


def owner_path(idv):
    return os.path.join(owners_dir(), f"{idv}.json")


def _owners_dir_safe():
    """Return the absolute owners directory ONLY when every parent component within ROOT is a
    real directory (never a symlink) and the resolved directory stays contained in ROOT —
    else None. O_NOFOLLOW protects only the FINAL path component, so a symlinked
    `.m8shift` or `worktree-owners` would otherwise let reads/writes/unlinks escape the
    project (Codex PR C review BLOCKER 1). A not-yet-created leaf is fine (claim makes it)."""
    root = os.path.realpath(ROOT)
    m8 = os.path.join(root, ".m8shift")
    owners = os.path.join(m8, "worktree-owners")
    for comp in (m8, owners):
        if os.path.islink(comp):
            return None                                   # symlinked parent → escape risk
        if os.path.exists(comp) and not os.path.isdir(comp):
            return None                                   # a file/FIFO/device where a dir must be
    try:
        if os.path.exists(m8) and os.path.commonpath([root, os.path.realpath(m8)]) != root:
            return None                                   # .m8shift resolves outside ROOT
    except ValueError:
        return None                                       # different drives (Windows) → refuse
    return owners


def validate_owner_doc(idv, doc):
    """STRICT tri-state validation of a parsed owner document against the EXPECTED id.
    Returns the doc when WELL-SHAPED (schema exact, `id == idv`, `agent` roster-shaped,
    `created_at` strict-Z, `path` a bounded normalized RELATIVE path, `branch` a bounded
    string, every field length-bounded), else None. A well-shaped doc may still CONFLICT
    with reality (roster/path/branch) — that is doctor's `owner_mismatch`; a doc that fails
    THIS shape check is `owner_missing` (Codex PR C review finding 4)."""
    if not isinstance(doc, dict) or doc.get("schema") != OWNER_SCHEMA:
        return None
    if doc.get("id") != idv:
        return None
    agent = doc.get("agent")
    if not isinstance(agent, str) or len(agent) > OWNER_FIELD_MAX or not _AGENT_RE.match(agent):
        return None
    created = doc.get("created_at")
    if not isinstance(created, str) or not _TS_RE.match(created):
        return None
    path = doc.get("path")
    if (not isinstance(path, str) or not path or len(path) > OWNER_FIELD_MAX
            or os.path.isabs(path) or "\\" in path or ".." in path.split("/")):
        return None
    branch = doc.get("branch")
    if not isinstance(branch, str) or len(branch) > OWNER_FIELD_MAX:
        return None
    return doc


def read_owner(idv):
    """Bounded, path-safe, STRICT read of the owner sidecar. The opened fd is the proof
    (O_NOFOLLOW final component + validated real parents + regular file + size cap), and the
    parsed document must pass `validate_owner_doc`. Anything else → None (no recorded owner).
    Advisory fail-open by design: a malformed sidecar never bricks a verb."""
    owners = _owners_dir_safe()
    if owners is None:
        return None
    try:
        fd = os.open(os.path.join(owners, f"{idv}.json"),
                     os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > OWNER_MAX_BYTES:
            return None
        raw = os.read(fd, OWNER_MAX_BYTES)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    return validate_owner_doc(idv, doc)


def write_owner(idv, agent, branch, *, created_at=None, takeover_from=None, reason=None):
    """Record ownership and return `(ok: bool, err: str|None)`. Path-hardened: refuses when
    the owners directory is missing/uncontained/symlinked, and writes through the core's
    UNIQUE-temp `+ os.replace` primitive (an unpredictable `.m8shift-*.tmp` name inside the
    validated real directory — the fixed `<id>.json.tmp` preplant is defused). The CALLER
    decides fail-open (claim/cleanup) vs fail-closed (a mandatory takeover audit)."""
    owners = _owners_dir_safe()
    if owners is None:
        return False, "owners directory missing, uncontained, or symlinked"
    t = core.iso(core.now())
    doc = {
        "schema": OWNER_SCHEMA, "id": idv, "agent": agent,
        "created_at": created_at or t,
        "path": os.path.relpath(wt_path(idv), ROOT),
        "branch": branch,
    }
    if takeover_from is not None:
        doc.update(taken_over_from=takeover_from, takeover_reason=reason, takeover_at=t)
    try:
        os.makedirs(owners, exist_ok=True)
        if _owners_dir_safe() is None:                    # re-validate post-makedirs (TOCTOU)
            return False, "owners directory became unsafe"
        core.write(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   os.path.join(owners, f"{idv}.json"))
        return True, None
    except OSError as e:
        return False, str(e)


def remove_owner(idv):
    """Best-effort cleanup (a leftover orphan is a doctor concern, never a failure). Refuses
    an unsafe owners directory rather than unlink through a symlinked parent."""
    owners = _owners_dir_safe()
    if owners is None:
        return
    try:
        os.unlink(os.path.join(owners, f"{idv}.json"))
    except OSError:
        pass


def require_takeover_or_die(idv, actor, args):
    """READ-ONLY phase of the advisory cross-owner guard: return a takeover TICKET (dict with
    the CAPTURED prior owner's agent/branch/created_at + the validated reason) to commit
    LATER, or None when no takeover is needed (no recorded owner, malformed → fail open, or
    the actor already owns it). Validates `--takeover --reason` WITHOUT writing, so the caller
    can run every remaining precondition before persisting anything (Codex PR C review finding
    3). The ticket CARRIES the branch/created_at observed here so the commit phase does NOT
    re-read the sidecar — a concurrent swap between the two phases can no longer make the audit
    record name the wrong displaced owner or reset `created_at` (PR C round-2 hunt)."""
    owner = read_owner(idv)
    if owner is None or owner.get("agent") == actor:
        return None
    prev = owner["agent"]                                # validated: present, roster-shaped
    if not getattr(args, "takeover", False):
        die(f"worktree {_safe(idv)!r} is owned by {_safe(prev)!r} (advisory sidecar) — pass "
            f"--takeover --reason TEXT to take it over explicitly")
    reason = (getattr(args, "reason", None) or "").strip()
    if not reason:
        die("--takeover requires a non-empty --reason")
    if len(reason) > OWNER_FIELD_MAX:                    # keep the written doc under the read cap
        die(f"--reason too long (max {OWNER_FIELD_MAX} chars) — the audit must stay readable")
    return {"prev": prev, "reason": reason,
            "branch": owner["branch"], "created_at": owner["created_at"]}


def commit_takeover_or_die(idv, actor, ticket):
    """COMMIT phase: persist the takeover audit from the require-phase TICKET, FAILING CLOSED
    (die, ownership unchanged) if the mandatory write cannot be persisted OR does not read
    back as this actor's ownership — a takeover must never print success on a lost audit
    (Codex PR C review finding 3 + round-2 oversized-field hunt). Uses the captured
    branch/created_at (no re-read)."""
    if ticket is None:
        return
    ok, err = write_owner(idv, actor, ticket["branch"], created_at=ticket["created_at"],
                          takeover_from=ticket["prev"], reason=ticket["reason"])
    if not ok:
        die(f"takeover audit write failed ({_safe(err)}) — refusing (ownership unchanged)")
    back = read_owner(idv)                               # the audit MUST be readable back
    if back is None or back["agent"] != actor:
        die("takeover audit did not persist as readable — refusing (ownership unverified)")
    print(f"⚠ takeover: worktree {_safe(idv)} ownership {_safe(ticket['prev'])} → "
          f"{_safe(actor)} (reason: {_safe(ticket['reason'])})")


# ───────────────────────────── pen flips (file_lock) ───────────────────────────

def _integration_pen_free_or_die(agent, idv):
    """READ-ONLY mirror of `claim_pen`'s availability gate (no lock, no write): refuse a busy
    or not-free integration pen BEFORE `cmd_integrate` commits a takeover, so the ROUTINE
    busy-pen case cannot strand a transferred ownership (PR C round-2 hunt). `claim_pen`
    remains the authoritative gate under the file lock."""
    lk = core.get_lock(core.load_or_die())
    working_self = f"WORKING_{agent.upper()}"
    st, held = lk.get("state", ""), lk.get("integrating")
    if held:
        if st == working_self and held.split("@", 1)[0] == idv:
            return                                       # resuming OUR own integration of this id
        die(f"integration pen busy: {lk.get('holder')} is integrating {held}")
    if st not in ("IDLE", f"AWAITING_{agent.upper()}", working_self):
        die(f"integration pen not free: state={st}, holder={lk.get('holder')}")


def claim_pen(agent, idv, target_sha):
    """Take (or resume) the integration pen and stamp the `integrating:<id>@<sha>` sentinel,
    atomically under the canonical file lock. Returns `(mode, sentinel)` where mode is 'resume' if
    WE already hold an in-flight integration of THIS id (a committed-but-unhanded retry — its
    recorded sentinel is reused verbatim, since after a committed merge the target tip has moved and
    the sha no longer matches a freshly recomputed one), else 'claimed'. Refuses if another agent
    — or our own pen carrying a DIFFERENT id — holds it."""
    working_self = f"WORKING_{agent.upper()}"
    with core.file_lock() as guard:
        text = core.load_or_die()
        lk = core.get_lock(text)
        roster_or_die(lk, agent)
        st, held = lk.get("state", ""), lk.get("integrating")
        if held:
            if st == working_self and held.split("@", 1)[0] == idv:
                return "resume", held                        # resume OUR integration of this id
            die(f"integration pen busy: {lk.get('holder')} is integrating {held}")
        if st not in ("IDLE", f"AWAITING_{agent.upper()}", working_self):
            die(f"integration pen not free: state={st}, holder={lk.get('holder')}")
        sentinel = f"{idv}@{target_sha}"
        t = core.now()
        lk.update(holder=agent, state=working_self, since=core.iso(t),
                  expires=core.iso(t + dt.timedelta(minutes=core.TTL_MIN)),
                  integrating=sentinel,
                  note=f"integrating {idv} into target by {agent}")
        guard.require_owned()
        core.write(core.set_lock(text, lk))
        if not guard.still_owned():
            die("lost the .m8shift.lock token during the pen claim — aborted (no merge started)")
    return "claimed", sentinel


def finalize(agent, to, idv, sentinel, *, done, advisory=(), commit_tree=None):
    """Close out an integration under the canonical file lock and hand the pen off. Returns
    `(turn, ok)`.

    Re-verify the pen is still OURS (holder + state + exact sentinel + token). When it is, this
    ALWAYS reaches the handoff — flip WORKING_<agent> → AWAITING_<to> and CLEAR the sentinel — so a
    post-claim path can never leave the pen stuck WORKING or the sentinel stranded:
      * success → verify the integration HEAD is still the sentinel's recorded sha, COMMIT the
        prepared merge, hand off (ok=True);
      * the HEAD moved out-of-band → abort the merge and hand off with `blocked_on=head-moved`
        (ok=False) instead of committing.
    The ONE non-handoff exit is an EXTERNALLY changed/stolen pen (not ours): we abort our own
    uncommitted merge and refuse, leaving that foreign LOCK untouched (no stolen merge) — recover by
    hand or `init --force`. Only the fast local commit of the already-prepared merge runs under the
    lock; `git merge` itself never does."""
    ok = True
    with core.file_lock() as guard:
        text = core.load_or_die()
        lk = core.get_lock(text)
        if not (lk.get("holder") == agent and lk.get("state") == f"WORKING_{agent.upper()}"
                and lk.get("integrating") == sentinel and guard.still_owned()):
            if commit_tree is not None and merge_in_progress(commit_tree):
                git(["merge", "--abort"], commit_tree, check=False)   # drop our uncommitted merge
            die(f"pen/sentinel changed externally (state={lk.get('state')}, "
                f"integrating={lk.get('integrating')}) — refusing to commit or touch a foreign LOCK "
                f"(no stolen merge); recover by hand or `m8shift.py init --force`")
        if commit_tree is not None:
            target_sha = sentinel.split("@", 1)[1]
            head = git_out(["rev-parse", "HEAD"], commit_tree)
            fail = None
            if head != target_sha:                            # OUR pen, but the tree moved out-of-band
                fail = ("head-moved", f"integration tree moved out-of-band ({head[:9]} != {target_sha[:9]})")
            elif git(["commit", "--no-edit"], commit_tree, check=False).returncode != 0:
                fail = ("commit-error", "git commit failed (pre-commit hook / identity / signing?)")
            if fail:                                          # abort + hand off — NEVER strand the pen
                if merge_in_progress(commit_tree):
                    git(["merge", "--abort"], commit_tree, check=False)
                ok = False
                done = f"integrate {idv} FAILED — {fail[1]}; handed to {to}"
                advisory = [("blocked_on", f"{fail[0]}:{idv}")]
        n = int(lk.get("turn", "0")) + 1
        block = core.render_turn(n, agent, to, done=done, files="—", advisory=advisory)
        text = text.rstrip("\n") + "\n\n" + block
        t = core.now()
        lk.update(holder=to, state=f"AWAITING_{to.upper()}", turn=str(n),
                  since=core.iso(t), expires="-", note=f"integrate {idv} → handed to {to}")
        lk.pop("integrating", None)                          # cleared on EVERY ours-path finalization
        guard.require_owned()
        core.write(core.set_lock(text, lk))
    return n, ok


# ──────────────────────────────── commands ─────────────────────────────────────

def cmd_claim(args):
    idv = safe_id(args.id)
    lk = core.get_lock(core.load_or_die())
    roster_or_die(lk, args.agent)
    branch = safe_branch_name(args.branch or idv)
    ftree = wt_path(idv)
    if os.path.exists(ftree):
        die(f"worktree {idv!r} already exists at {ftree}")
    if not resolves(args.base):
        die(f"--base {args.base!r} does not resolve to a commit")
    if local_branch_exists(branch):
        git(["worktree", "add", ftree, branch])              # check out an existing branch
    else:
        git(["worktree", "add", "-b", branch, ftree, args.base])  # new branch off --base
    # RFC 049 PR C: a fresh claim owns the worktree — record it beside the checkout.
    # Creation is best-effort (the worktree already exists; a failed sidecar is a doctor
    # owner_missing, not a claim failure). A stale sidecar for a since-removed worktree is
    # moot: the claimer owns the new tree.
    ok, err = write_owner(idv, args.agent, branch)
    if not ok:
        print(f"⚠ owner sidecar not recorded ({_safe(err)}) — advisory only, continuing",
              file=sys.stderr)
    print(f"✓ claimed worktree {idv} → {os.path.relpath(ftree, ROOT)} (branch {branch} from {args.base})")
    return 0


def cmd_done(args):
    """Append to a COMPANION-only completion ledger (`.m8shift/done.log`) under the canonical file
    lock — degree-2 worktree ids are a different id space from the core's integer task board, so this
    deliberately does NOT touch `M8SHIFT.tasks.md` (no format/lock collision with the dumb core
    ledger). It records that a worktree's branch is ready to integrate; the real handoff is
    `integrate`."""
    idv = safe_id(args.id)
    roster_or_die(core.get_lock(core.load_or_die()), args.agent)   # actor BEFORE any owner op
    ticket = require_takeover_or_die(idv, args.agent, args)         # validate (no write yet)
    with core.file_lock() as guard:
        roster_or_die(core.get_lock(core.load_or_die()), args.agent)  # re-check under the lock
        commit_takeover_or_die(idv, args.agent, ticket)            # persist AFTER the re-check
        log = os.path.join(ROOT, ".m8shift", "done.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        prev_log = core.read(log) if os.path.exists(log) else "# m8shift-worktree done ledger (degree-2)\n"
        guard.require_owned()
        core.write(prev_log + f"- {idv} done by {args.agent} @ {core.iso(core.now())}\n", log)
    print(f"✓ noted worktree {idv} done by {args.agent}")
    return 0


def cmd_drop(args):
    if not args.yes:
        die("drop needs --yes (a worktree is never removed automatically)")
    idv = safe_id(args.id)
    roster_or_die(core.get_lock(core.load_or_die()), args.agent)   # actor BEFORE any destruction
    # A cross-owner drop still requires an explicit --takeover --reason INTENT gate; the
    # reason need not persist (the sidecar is removed with the worktree), so drop does not
    # commit an audit — but the destructive `git worktree remove` never runs for an
    # unauthorized actor or an unacknowledged foreign owner (Codex PR C review finding 2).
    require_takeover_or_die(idv, args.agent, args)
    ftree = wt_path(idv)
    if not os.path.exists(ftree):
        die(f"no worktree {idv!r} at {ftree}")
    git(["worktree", "remove", ftree])                       # git refuses if dirty (no --force)
    remove_owner(idv)                                        # best-effort cleanup (RFC 049 PR C)
    print(f"✓ dropped worktree {idv}")
    return 0


def cmd_status(args):
    lk = core.get_lock(core.load_or_die())
    print(f"m8shift-worktree.py v{VERSION}   core=m8shift.py v{getattr(core, 'VERSION', '?')}   root={ROOT}")
    print(f"pen: {lk.get('state')}  holder={lk.get('holder')}  turn={lk.get('turn')}")
    print(f"     since={core.display_time(lk.get('since', '-'))}  expires={core.display_time(lk.get('expires', '-'))}")
    if lk.get("integrating"):
        print(f"  ⚠ integrating: {lk['integrating']}  (merge in flight — pen locked)")
    print("worktrees:")
    found = [False]

    def flush(path, branchref):
        # Record on the WORKTREE line (like `_managed_worktrees`/doctor), so a DETACHED-HEAD
        # worktree — which has no porcelain `branch ` line — is not silently omitted (PR C
        # round-2 hunt: status and doctor must agree). The basename is echoed via `_safe` so
        # a hostile worktree dirname can never inject ANSI into the terminal.
        if path is None or not _under_worktrees_base(path):
            return
        name = os.path.basename(os.path.abspath(path))
        if args.id and name != args.id:
            return
        if name == "_integration":
            who = "n/a"                                   # shared integration tree (doctor excludes)
        else:
            owner = read_owner(name)
            who = _safe(owner["agent"]) if owner else "?" # "?" = no usable sidecar → doctor flags it
        br = branchref if branchref else "(detached)"
        print(f"  {_safe(name):<20} {_safe(br):<30} owner={who}")
        found[0] = True

    path, branchref = None, None
    for line in git_out(["worktree", "list", "--porcelain"]).splitlines() + [""]:
        if line.startswith("worktree ") or line == "":
            flush(path, branchref)                        # flush the PREVIOUS worktree block
            path = line[len("worktree "):] if line else None
            branchref = None
        elif line.startswith("branch "):
            branchref = line[len("branch "):].strip()
    if not found[0]:
        print("  (none)")
    return 0


def _under_worktrees_base(path):
    """True when `path` is contained in `.m8shift/worktrees/` by REALPATH/COMMONPATH (not a
    raw `startswith`, which a sibling like `.m8shift/worktrees-evil` or a symlink could
    spoof)."""
    base = os.path.realpath(os.path.join(ROOT, ".m8shift", "worktrees"))
    try:
        rp = os.path.realpath(path)
        return rp != base and os.path.commonpath([base, rp]) == base
    except ValueError:
        return False


def _managed_worktrees():
    """{id: {"path": abs, "branch": ref-or-None}} for every NON-integration worktree under
    `.m8shift/worktrees/` (from `git worktree list --porcelain` — never a directory scan,
    so a stray folder that git does not know is not a managed worktree). Containment is by
    realpath/commonpath, not a raw prefix match (Codex PR C review finding 5)."""
    out, path = {}, None
    for line in git_out(["worktree", "list", "--porcelain"]).splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):]
            name = os.path.basename(os.path.abspath(path))
            if _under_worktrees_base(path) and name != "_integration":
                out[name] = {"path": os.path.abspath(path), "branch": None}
            else:
                path = None
        elif line.startswith("branch ") and path:
            out[os.path.basename(os.path.abspath(path))]["branch"] = line[len("branch "):].strip()
    return out


def cmd_doctor(args):
    """RFC 049 PR C: read-only advisory findings over the owner sidecars — never repairs,
    never gates (rc 0 always; the guard itself is advisory, so its diagnostics are too).

      worktree.owner_missing   warning  managed worktree lacks USABLE sidecar ownership
                                        metadata (absent OR malformed/unreadable — a
                                        malformed sidecar is treated as missing, because
                                        the fail-open guard treats it that way too)
      worktree.owner_mismatch  warning  sidecar metadata conflicts with the known
                                        path/branch/roster, or the sidecar is an orphan
                                        (no such managed worktree)
    """
    lk = core.get_lock(core.load_or_die())
    roster = set(core.active_agents(lk))
    trees = _managed_worktrees()
    findings = []
    for idv, info in sorted(trees.items()):
        owner = read_owner(idv)                          # STRICT: well-shaped doc or None
        if owner is None:
            findings.append({"id": "worktree.owner_missing", "severity": "warning",
                             "worktree": _safe(idv),
                             "detail": "no usable ownership sidecar (absent or malformed)"})
            continue
        problems = []
        if owner["agent"] not in roster:                 # well-shaped agent, but off-roster
            problems.append(f"owner {_safe(owner['agent'])!r} not on the roster")
        rel = os.path.relpath(info["path"], ROOT)
        if owner["path"] != rel:
            problems.append(f"recorded path {_safe(owner['path'])!r} != {_safe(rel)!r}")
        branch = info.get("branch") or ""
        short = branch[len("refs/heads/"):] if branch.startswith("refs/heads/") else branch
        if owner["branch"] and short and owner["branch"] != short:
            problems.append(f"recorded branch {_safe(owner['branch'])!r} != {_safe(short)!r}")
        if problems:
            findings.append({"id": "worktree.owner_mismatch", "severity": "warning",
                             "worktree": _safe(idv), "detail": "; ".join(problems)})
    owners = _owners_dir_safe()
    try:
        names = [f for f in os.listdir(owners)] if owners else []
    except OSError:
        names = []
    for f in sorted(names):
        if not f.endswith(".json"):
            continue
        idv = f[:-len(".json")]
        if idv not in trees:
            findings.append({"id": "worktree.owner_mismatch", "severity": "warning",
                             "worktree": _safe(idv),
                             "detail": "orphan sidecar — no such managed worktree"})
    if args.json:
        print(json.dumps({"ok": not findings, "findings": findings},
                         indent=1, sort_keys=True))
    elif findings:
        for f in findings:
            print(f"{f['severity']}: {f['id']} [{f['worktree']}] — {f['detail']}")
    else:
        print("✓ worktree ownership: no findings")
    return 0


def cmd_integrate(args):
    idv = safe_id(args.id)
    agent, to, into = args.agent, args.to, safe_branch_name(args.into, "--into")

    # ---- validate the ACTOR and RECIPIENT before ANY owner op (Codex PR C review
    #      finding 2) and capture (but do NOT yet commit) a required takeover -------
    lk = core.get_lock(core.load_or_die())
    roster_or_die(lk, agent, to)
    if to == agent:
        die("--to must hand off to a DIFFERENT agent")
    ticket = require_takeover_or_die(idv, agent, args)        # validates --takeover; no write

    # ---- every remaining precondition BEFORE the takeover commit and the pen flip,
    #      so a failed precondition never transfers ownership (finding 3) ----------
    _integration_pen_free_or_die(agent, idv)     # read-only pen precheck (PR C round-2 hunt):
    #      a busy pen is the pen's ROUTINE serialization state; without this precheck the
    #      takeover would commit and then claim_pen would die on the busy pen, stranding a
    #      transferred ownership. claim_pen still re-checks under the lock (authoritative), so
    #      the pen is never taken before the fail-closed audit — only a rare become-busy race
    #      between this precheck and claim_pen remains (advisory sidecar, documented).
    if not local_branch_exists(into):
        die(f"--into {into!r} is not a local branch — integration must advance a BRANCH; pass a "
            f"branch name (a commit/tag/detached ref would merge into a detached HEAD and silently "
            f"NOT update any branch)")

    ftree = wt_path(idv)
    feature_ref = (git_out(["symbolic-ref", "--short", "HEAD"], ftree) or idv) \
        if os.path.isdir(ftree) else idv
    if not resolves(feature_ref):
        die(f"feature ref {feature_ref!r} does not resolve (claim the worktree first?)")

    foreign = foreign_checkout_of(into)
    if foreign:
        die(f"target branch {into!r} is checked out in {_safe(foreign)} — git forbids a second "
            f"checkout, so the dedicated integration tree cannot own it. Free {into!r} there "
            f"(detach it, or keep the canonical root on a coordination branch) so only the "
            f"_integration tree holds it.")

    integ = integ_path()
    if not os.path.isdir(integ):
        os.makedirs(os.path.dirname(integ), exist_ok=True)
        git(["worktree", "add", integ, into])
    else:
        if git_out(["rev-parse", "--verify", "--quiet", "MERGE_HEAD"], integ):
            git(["merge", "--abort"], integ, check=False)    # clear a prior interrupted merge
        if git_out(["symbolic-ref", "--short", "HEAD"], integ) != into:
            if git_out(["status", "--porcelain"], integ):
                die(f"integration tree dirty and not on {into!r} — clean it manually")
            git(["checkout", into], integ)
    if git_out(["status", "--porcelain"], integ):
        die(f"integration tree {integ} is not clean — refusing (pre-flip precondition)")
    target_sha = git_out(["rev-parse", "HEAD"], integ)

    # ---- all preconditions passed: NOW commit the takeover (fail-closed), THEN the
    #      pen flip. A takeover audit that cannot persist aborts here, before any flip.
    commit_takeover_or_die(idv, agent, ticket)

    # ---- take the pen + stamp the sentinel -------------------------------------
    mode, sentinel = claim_pen(agent, idv, target_sha)

    # ---- merge (OUTSIDE the lock) or detect already-integrated -----------------
    already = git(["merge-base", "--is-ancestor", feature_ref, "HEAD"], integ, check=False).returncode == 0
    if already:
        n, _ = finalize(agent, to, idv, sentinel,
                        done=f"{idv} already integrated in {into} (no-op merge); handed to {to}",
                        advisory=[("integrated", f"{idv}:already")])
        print(f"✓ {idv} already in {into} — pen handed to {to} (turn {n}) [{mode}]")
        return 0

    r = git(["merge", "--no-ff", "--no-commit", feature_ref], integ, check=False)
    if r.returncode != 0:
        conflict = merge_in_progress(integ)
        if conflict:
            git(["merge", "--abort"], integ, check=False)
        reason = f"conflict:{idv}" if conflict else f"merge-error:{idv}"
        n, _ = finalize(agent, to, idv, sentinel,
                        done=f"integrate {idv} into {into} FAILED ({reason}); handed to {to}",
                        advisory=[("blocked_on", reason)])
        print(f"✗ merge failed ({reason}) — aborted, pen handed to {to} (turn {n})", file=sys.stderr)
        return 1

    # ---- reverify + commit + handoff (finalize ALWAYS hands off when the pen is ours) ----
    n, ok = finalize(agent, to, idv, sentinel, commit_tree=integ,
                     done=f"integrated {idv} into {into}; handed to {to}",
                     advisory=[("integrated", f"{idv}:{into}")])
    if not ok:
        print(f"✗ merge could not be committed (see blocked_on) — aborted, pen handed to {to} (turn {n})",
              file=sys.stderr)
        return 1
    print(f"✓ integrated {idv} into {into} — pen handed to {to} (turn {n}) [{mode}]")
    return 0


# ──────────────────────────────── entry point ──────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(prog="m8shift-worktree.py", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"m8shift-worktree.py {VERSION}",
                   help="show the companion version and exit")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("claim", help="add a feature worktree on a (new) branch")
    c.add_argument("id", help="worktree id ([A-Za-z0-9][A-Za-z0-9_-]*, no '/' or '..'), also the default branch name")
    c.add_argument("agent", help="agent claiming the worktree (must be on the LOCK roster)")
    c.add_argument("--base", required=True, help="commit/branch to branch from")
    c.add_argument("--branch", help="branch name (default: <id>)")
    c.set_defaults(fn=cmd_claim)

    d = sub.add_parser("done", help="note the task done (dumb ledger line)")
    d.add_argument("id", help="worktree id to record as done in the companion ledger")
    d.add_argument("agent", help="agent recording the completion (must be on the LOCK roster)")
    _add_takeover(d)
    d.set_defaults(fn=cmd_done)

    i = sub.add_parser("integrate", help="serialized non-committing merge + handoff")
    i.add_argument("id", help="worktree id whose feature branch is merged")
    i.add_argument("agent", help="agent taking the integration pen (must be on the LOCK roster)")
    i.add_argument("--into", required=True, help="target branch to merge into")
    i.add_argument("--to", required=True, help="next agent to hand the pen to")
    _add_takeover(i)
    i.set_defaults(fn=cmd_integrate)

    r = sub.add_parser("drop", help="remove a feature worktree (never automatic)")
    r.add_argument("id", help="worktree id to remove (git refuses if the tree is dirty)")
    r.add_argument("agent", help="agent performing the drop")
    r.add_argument("--yes", action="store_true", help="confirm removal")
    _add_takeover(r)
    r.set_defaults(fn=cmd_drop)

    s = sub.add_parser("status", help="canonical LOCK + companion worktrees")
    s.add_argument("id", nargs="?", help="restrict the worktree listing to this id (default: list all)")
    s.set_defaults(fn=cmd_status)

    doc = sub.add_parser("doctor", help="read-only ownership findings (RFC 049 PR C, advisory)")
    doc.add_argument("--json", action="store_true", help="machine-readable findings")
    doc.set_defaults(fn=cmd_doctor)
    return p


def _add_takeover(sp):
    """RFC 049 PR C: explicit advisory takeover of another agent's recorded worktree
    ownership — both flags together, audited in the sidecar."""
    sp.add_argument("--takeover", action="store_true",
                    help="override another agent's recorded ownership (requires --reason)")
    sp.add_argument("--reason", help="why the takeover is legitimate (audited in the sidecar)")


# RFC 038 §9.2 (Codex code-review BLOCKER 3): companion mutators bypass the core
# argparse dispatcher, so the session-binding preflight runs HERE. claim/done/
# integrate/drop mutate relay/ledger state (actor-bearing via their agent arg);
# status is read-only.
_MUTATING_VERBS = {"claim", "done", "integrate", "drop"}


def main(argv=None):
    args = build_parser().parse_args(argv)
    global ROOT
    ROOT = discover_root()
    core.configure_root(ROOT)        # rebase the core onto the canonical root BEFORE any read/write
    if getattr(args, "cmd", "") in _MUTATING_VERBS:
        # The preflight may resolve the actor's binding to the OTHER candidate;
        # the companion's own ROOT must follow the returned root or the core
        # lock and the companion writes split across relays (Codex re-review
        # BLOCKER 3).
        resolved = core.session_binding_preflight(getattr(args, "agent", None))
        if resolved and os.path.realpath(resolved) != os.path.realpath(ROOT):
            ROOT = resolved
            core.configure_root(ROOT)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
