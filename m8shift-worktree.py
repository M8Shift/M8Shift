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
import contextlib
import datetime as dt
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time


class HelpfulArgumentParser(argparse.ArgumentParser):
    """Print command help plus a valid required-argument shape on errors."""

    def error(self, message):
        parts = [self.prog]
        for action in self._actions:
            if action.dest == "help" or not action.required:
                continue
            if action.option_strings:
                parts.append(action.option_strings[-1])
            if action.nargs != 0:
                value = action.metavar or action.dest.upper()
                parts.append(str(value[0] if isinstance(value, tuple) else value))
        old = self.epilog
        self.epilog = ((old + "\n\n") if old else "") + \
            "required invocation example:\n  " + " ".join(parts)
        self.print_help(sys.stderr)
        self.epilog = old
        self.exit(2, "\n%s: error: %s\n" % (self.prog, message))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = None        # canonical repo root (set in main, before any core read/write)
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")   # mirrors the core sentinel id class
VERSION = "3.62.0"


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
# and prompt boundaries"). Design invariants (Codex PR C review rounds 1-2):
#   - every READER fails open + STRICT: a malformed/unreadable/wrong-shaped sidecar degrades
#     to "no recorded owner" (doctor reports the gap); shape validation is SEMANTIC (a real
#     UTC-Z calendar instant, a non-empty branch, an all-or-none takeover audit tuple);
#   - every ACTOR is roster-validated BEFORE any owner read/write or destruction;
#   - every WRITE is path-hardened against a PRE-EXISTING symlinked parent or a preplanted
#     fixed temp (unpredictable temp via the core primitive + validated real parents); a
#     live privileged CONCURRENT parent-symlink swap is a TOCTOU out of the threat model;
#   - every MANDATORY takeover audit is durable-ledger-first and fails CLOSED (a durable
#     append-only ledger records the takeover, surviving the sidecar's deletion on `drop`);
#   - `integrate` folds the pen-availability check + audit + pen flip into ONE serialized
#     file-lock phase, so a busy pen transfers nothing and a failed audit flips nothing.

OWNER_SCHEMA = "m8shift.worktree_owner.v1"
OWNER_MAX_BYTES = 8192           # an owner doc is ~200 bytes; anything larger is not ours
OWNER_FIELD_MAX = 256            # bound every recorded string field (defeats oversized echo)
TAKEOVER_LEDGER = "_takeovers.jsonl"  # durable append-only takeover audit (survives sidecar delete)
OWNER_LOCK_STALE_S = 30          # s: a per-id ownership lock older than this is a crashed holder
_AGENT_RE = re.compile(core.AGENT_RE + r"\Z", re.ASCII)   # anchored ASCII roster-agent shape
_UNSAFE = re.compile(r"[^\x20-\x7e]")                      # printable-ASCII whitelist for echo
_GEN_RE = re.compile(r"[0-9a-f]{16,64}\Z", re.ASCII)      # per-claim generation nonce shape
_TAKEOVER_KEYS = ("taken_over_from", "takeover_reason", "takeover_at")


def _new_gen():
    """A per-claim GENERATION nonce (Codex PR C review round-4 finding 1): a fresh 128-bit
    random hex stamped by every `claim`, PRESERVED across takeovers of the same lane, and
    RENEWED on every re-claim. The CAS checks it so a stale ticket cannot overwrite a lane
    that was dropped and re-claimed by the SAME agent (agent-name ABA) — a drop+reclaim
    yields a new gen the old ticket can no longer match, even byte-identical same-second."""
    return os.urandom(16).hex()


def _valid_ts(value):
    """A CANONICAL UTC-Z timestamp of a real calendar instant. `core.parse_iso`
    (`strptime("%Y-%m-%dT%H:%M:%SZ")`) rejects impossible dates (`2026-99-99…`), but strptime
    alone still accepts single-digit fields (`2026-2-3T4:5:6Z`), surrounding whitespace (it
    strips), and non-ASCII digits in the year (`\\d` is Unicode). So we additionally require the
    string to EQUAL the re-rendered canonical form — that pins ASCII, zero-padding, and no
    padding, exactly as the round-3 contract claims (PR C round-3 hunt, LOW deviations)."""
    if not isinstance(value, str):
        return False
    parsed = core.parse_iso(value)
    return parsed is not None and value == parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _bounded_str(value, *, allow_empty=False):
    return isinstance(value, str) and len(value) <= OWNER_FIELD_MAX and (allow_empty or bool(value))


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
    Returns the doc when WELL-SHAPED, else None. Well-shaped = schema exact, `id == idv`,
    `agent` roster-shaped, `created_at` a REAL canonical UTC-Z instant, `path` a bounded
    normalized RELATIVE path, `branch` a bounded NON-EMPTY string, every field length-bounded;
    and the OPTIONAL takeover audit tuple is validated ALL-OR-NONE (a partial/oversized/
    ANSI/impossible-time audit makes the whole doc malformed). A well-shaped doc may still
    CONFLICT with reality (roster/path/branch/detached) — that is doctor's `owner_mismatch`;
    a doc that fails THIS shape check is `owner_missing` (Codex PR C review findings 3-4)."""
    if not isinstance(doc, dict) or doc.get("schema") != OWNER_SCHEMA:
        return None
    if doc.get("id") != idv:
        return None
    agent = doc.get("agent")
    if not _bounded_str(agent) or not _AGENT_RE.match(agent):
        return None
    if not _valid_ts(doc.get("created_at")):                # real calendar instant, not just shape
        return None
    path = doc.get("path")
    if (not _bounded_str(path) or os.path.isabs(path) or "\\" in path
            or ".." in path.split("/")):
        return None
    if not _bounded_str(doc.get("branch")):                 # a claimed owner always has a branch
        return None
    gen = doc.get("gen")                                    # per-claim generation nonce (ABA guard)
    if not isinstance(gen, str) or not _GEN_RE.match(gen):
        return None
    present = [k for k in _TAKEOVER_KEYS if k in doc]        # optional audit tuple: all-or-none
    if present:
        if len(present) != len(_TAKEOVER_KEYS):
            return None
        tf = doc["taken_over_from"]
        if not _bounded_str(tf) or not _AGENT_RE.match(tf):
            return None
        if not _bounded_str(doc["takeover_reason"]) or not doc["takeover_reason"].strip():
            return None                                     # bounded AND non-whitespace
        if not _valid_ts(doc["takeover_at"]):
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


def write_owner(idv, agent, branch, *, created_at=None, gen=None,
                takeover_from=None, reason=None):
    """Record ownership and return `(ok: bool, err: str|None)`. Path-hardened: refuses when
    the owners directory is missing/uncontained/symlinked, and writes through the core's
    UNIQUE-temp `+ os.replace` primitive (an unpredictable `.m8shift-*.tmp` name inside the
    validated real directory — the fixed `<id>.json.tmp` preplant is defused). `gen` is the
    per-claim generation nonce: a fresh one on a claim (`gen=None` → minted), the ticket's
    captured gen PRESERVED on a takeover. The CALLER decides fail-open (claim/cleanup) vs
    fail-closed (a mandatory takeover audit)."""
    owners = _owners_dir_safe()
    if owners is None:
        return False, "owners directory missing, uncontained, or symlinked"
    t = core.iso(core.now())
    doc = {
        "schema": OWNER_SCHEMA, "id": idv, "agent": agent,
        "created_at": created_at or t,
        "path": os.path.relpath(wt_path(idv), ROOT),
        "branch": branch,
        "gen": gen or _new_gen(),
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


def append_takeover_ledger(record):
    """Append one bounded JSON record to the DURABLE append-only takeover ledger
    (`.m8shift/worktree-owners/_takeovers.jsonl`). Returns `(ok, err)`. Path-safe (validated
    owners dir; `O_APPEND|O_CREAT|O_NOFOLLOW` — a symlink or directory at the ledger path
    fails deterministically, for every user including root). This is the audit that SURVIVES
    a sidecar delete, so a cross-owner `drop` still leaves a durable record (Codex PR C
    review round-2 finding 2)."""
    owners = _owners_dir_safe()
    if owners is None:
        return False, "owners directory missing, uncontained, or symlinked"
    try:
        os.makedirs(owners, exist_ok=True)
        if _owners_dir_safe() is None:
            return False, "owners directory became unsafe"
        line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        # O_NONBLOCK + S_ISREG parity with read_owner (PR C round-3 hunt): O_NOFOLLOW blocks
        # only a symlinked FINAL component — a FIFO at the ledger path would otherwise make
        # a write-only open BLOCK FOREVER while holding the global .m8shift.lock, freezing the
        # relay. O_NONBLOCK turns that into ENXIO (fail-closed); the fstat rejects any
        # non-regular file that still opened (e.g. a FIFO with a reader attached).
        fd = os.open(os.path.join(owners, TAKEOVER_LEDGER),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return False, "ledger path is not a regular file"
            os.write(fd, line)
        finally:
            os.close(fd)
        return True, None
    except OSError as e:
        return False, str(e)


def _pid_alive(pid):
    """Best-effort cross-platform liveness of an owner-lock holder PID (mirrors the runtime
    companion's probe): POSIX signal-0 (PermissionError → alive but not ours), Windows
    `tasklist`. FAIL-SAFE contract: whenever liveness CANNOT be POSITIVELY proven dead —
    unknown error, probe timeout, OR a tasklist run that itself failed (nonzero returncode) —
    the holder counts as ALIVE, so we NEVER steal a lock we cannot confidently attribute to a
    dead process (Codex PR C review rounds 5-6). Only a SUCCESSFUL probe with no matching PID
    reads as dead."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":                                  # pragma: no cover - Windows only
        try:
            probe = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                   capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return True                                  # cannot prove dead → alive
        if probe.returncode != 0:
            return True                                  # the PROBE failed → unknown → alive
        return f'"{pid}"' in (probe.stdout or "")        # successful probe: exact-PID match
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                                      # alive, just not ours
    except OSError:
        return True                                      # cannot prove dead → don't steal
    return True


def _reclaim_owner_lock(path):
    """Reclaim the per-id lock ONLY when it is a stale REGULAR-file lock whose recorded holder
    PID is POSITIVELY proven dead AND whose inode/token is unchanged across the check — never
    stealing a live long-running holder (a legitimate `git worktree add/remove` may exceed the
    stale threshold) and never unlinking a fresh successor. A MALFORMED token (unparseable PID)
    means the holder's identity is UNKNOWN → fail safe, never reclaim (manual recovery: delete
    the lock by hand after confirming no ownership operation is in flight). Returns True iff
    exactly that abandoned lock was unlinked. A directory / FIFO / symlink / non-unlinkable
    lock returns False, so the caller falls to the BOUNDED busy timeout and never spins (Codex
    PR C review rounds 5-6)."""
    try:
        st1 = os.lstat(path)
        if not stat.S_ISREG(st1.st_mode):                # a dir/FIFO/symlink lock is never reclaimed
            return False
        if time.time() - st1.st_mtime <= OWNER_LOCK_STALE_S:
            return False                                 # not old enough
        raw, st2 = core._read_regular_file_token(path)   # raises unless a regular file
        if not core._same_file(st1, st2):
            return False                                 # inode changed under us
        try:
            pid = int(raw.split(b":", 1)[0])
        except (ValueError, IndexError):
            return False                                 # unknown holder identity → fail safe
        if _pid_alive(pid):
            return False                                 # LIVE (or unprovable) holder → never steal
        st3 = os.lstat(path)                             # re-validate immediately before unlink
        if not core._same_file(st2, st3) or time.time() - st3.st_mtime <= OWNER_LOCK_STALE_S:
            return False
        os.unlink(path)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def owner_lock(idv, timeout=10):
    """A PER-ID ownership lock (`.m8shift/worktree-owners/<id>.lock`, `O_CREAT|O_EXCL` + a
    `<pid>:<ns>` token) serializing EVERY ownership mutation for one worktree id — `claim`
    create, `done`/`integrate`/`drop` takeover, and `drop`'s authorize→remove→cleanup span —
    WITHOUT holding the global core lock across slow git (Codex PR C review round-4 finding 2).
    Finer-grained than the core lock (blocks only same-id ownership ops). A stale lock is broken
    ONLY when its holder PID is provably dead and its inode/token is unchanged (`_reclaim_owner_
    lock`), so a live long-running holder is never stolen. Serialization is GUARANTEED only
    when the owners namespace is SAFE: an UNSAFE (symlinked/uncontained) directory degrades to
    a no-op, consistent with the documented advisory fail-open limitation — ownership takeover
    mutations cannot happen there (the reader yields no ticket), though fail-open verbs like a
    same-owner `drop` still perform their normal work. When the directory is SAFE and the lock
    cannot be acquired it FAILS CLOSED (die), never running an ownership mutation unserialized
    (Codex PR C review round-5 finding 4). Acquire order everywhere: owner_lock OUTER,
    core.file_lock INNER — a single order, so no deadlock."""
    owners = _owners_dir_safe()
    if owners is None:
        yield False                                      # advisory: unsafe dir → cannot lock
        return
    os.makedirs(owners, exist_ok=True)
    path = os.path.join(owners, f"{idv}.lock")
    token = f"{os.getpid()}:{time.time_ns()}".encode()
    start = time.monotonic()
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.write(fd, token)
            finally:
                os.close(fd)
            break
        except FileExistsError:
            if _reclaim_owner_lock(path):                # only a proven-dead, unchanged, regular lock
                continue                                 # reclaimed → retry the create at once
            if time.monotonic() - start > timeout:       # a live/held or non-reclaimable lock → busy
                die(f"ownership lock for {_safe(idv)!r} is busy — another ownership operation "
                    f"is in flight; retry")
            time.sleep(0.02)
        except OSError as e:                             # SAFE dir but acquisition failed → fail closed
            die(f"ownership lock for {_safe(idv)!r} could not be acquired ({_safe(str(e))}) — "
                f"refusing to run an ownership mutation unserialized")
    try:
        yield True
    finally:                                             # unlink ONLY our own unchanged token,
        with contextlib.suppress(OSError):               # NEVER a successor's (finding 3): a read
            got, _ = core._read_regular_file_token(path)  # failure suppresses → no unlink at all
            if got == token:
                os.unlink(path)


def _takeover_record(idv, actor, ticket, verb, phase):
    return {"ts": core.iso(core.now()), "verb": verb, "phase": phase, "id": idv,
            "from": ticket["prev"], "to": actor, "reason": ticket["reason"]}


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
    return {"prev": prev, "reason": reason, "branch": owner["branch"],
            "created_at": owner["created_at"], "gen": owner["gen"]}


def _cas_owner_or_die(idv, ticket):
    """Optimistic-concurrency check (Codex PR C review round-3 finding 1 + round-4 ABA): the
    ticket was captured BEFORE the ownership lock, so under the lock the CURRENT usable owner
    must STILL be the exact lane the ticket expects — SAME agent AND SAME per-claim generation
    nonce. The nonce defeats agent-name ABA (drop + reclaim by the SAME agent yields a new gen
    the stale ticket can never match). On a mismatch we refuse and write NOTHING. Callers hold
    the per-id ownership lock, under which every ownership write is serialized, so this
    compare-and-swap is authoritative."""
    current = read_owner(idv)
    if current is None or current.get("agent") != ticket["prev"] \
            or current.get("gen") != ticket["gen"]:
        cur = _safe(current["agent"]) if current else "none"
        die(f"owner changed under the lock (now {cur!r}, expected {_safe(ticket['prev'])!r} "
            f"same generation) — retry the takeover")


def commit_takeover_or_die(idv, actor, ticket, verb):
    """COMMIT phase for `done`/`integrate` (the sidecar SURVIVES, so it holds the re-stamped
    audit). MUST run under the PER-ID ownership lock (`owner_lock(idv)`), the serialization
    under which every ownership write happens and the CAS is authoritative: re-read + require
    the current owner still equals the ticket's expected prior owner AND generation nonce
    (optimistic CAS, defeats agent-name ABA), then durable-audit-first append the ledger record,
    re-stamp the sidecar from the CAPTURED ticket (no data re-read, PRESERVING the gen), and
    verify it reads back as this actor's ownership — each step fails CLOSED. Over-records (a
    ledger line for a takeover whose sidecar apply then failed) rather than under-records."""
    if ticket is None:
        return
    _cas_owner_or_die(idv, ticket)                       # CAS: same agent AND same generation
    ok, err = append_takeover_ledger(_takeover_record(idv, actor, ticket, verb, "applied"))
    if not ok:
        die(f"takeover audit ledger write failed ({_safe(err)}) — refusing (ownership unchanged)")
    ok, err = write_owner(idv, actor, ticket["branch"], created_at=ticket["created_at"],
                          gen=ticket["gen"],           # PRESERVE the lane generation across takeover
                          takeover_from=ticket["prev"], reason=ticket["reason"])
    if not ok:
        die(f"takeover sidecar write failed ({_safe(err)}) — refusing (ownership unverified)")
    back = read_owner(idv)                               # the audit MUST be readable back
    if back is None or back["agent"] != actor:
        die("takeover audit did not persist as readable — refusing (ownership unverified)")
    print(f"⚠ takeover: worktree {_safe(idv)} ownership {_safe(ticket['prev'])} → "
          f"{_safe(actor)} (reason: {_safe(ticket['reason'])})")


def authorize_drop_takeover_or_die(idv, actor, ticket):
    """`drop` COMMIT phase 1: the worktree AND its sidecar are about to be removed, so the
    durable ledger is the ONLY surviving audit. MUST run under the PER-ID ownership lock, which
    `cmd_drop` holds across the WHOLE authorize→remove→cleanup span: CAS the current owner
    (agent AND generation) against the ticket, then record `phase=authorized` BEFORE the
    destructive `git worktree remove`, failing CLOSED if either the owner changed or the record
    cannot be persisted — a cross-owner drop must never destroy against a stale owner, without a
    durable record, or let a concurrent takeover slip between authorization and removal (Codex
    PR C review round-2 finding 2 + round-3/4 finding 1-2)."""
    if ticket is None:
        return
    _cas_owner_or_die(idv, ticket)                       # CAS under the same serialization lock
    ok, err = append_takeover_ledger(_takeover_record(idv, actor, ticket, "drop", "authorized"))
    if not ok:
        die(f"takeover audit ledger write failed ({_safe(err)}) — refusing (worktree untouched)")
    print(f"⚠ takeover: worktree {_safe(idv)} ownership {_safe(ticket['prev'])} → "
          f"{_safe(actor)} for drop (reason: {_safe(ticket['reason'])})")


def complete_drop_takeover(idv, actor, ticket):
    """`drop` COMMIT phase 2: `phase=completed` tombstone AFTER a successful removal, so the
    ledger truthfully distinguishes an authorized-but-failed drop (dirty tree) from a completed
    one. Returns `(ok, err)` — the removal cannot be rolled back, but a failed completion audit
    is surfaced by the caller (nonzero rc), never reported as a full success (Codex PR C review
    round-3 finding 3)."""
    if ticket is None:
        return True, None
    return append_takeover_ledger(_takeover_record(idv, actor, ticket, "drop", "completed"))


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


def claim_pen(agent, idv, target_sha, ticket=None):
    """Take (or resume) the integration pen and stamp the `integrating:<id>@<sha>` sentinel,
    atomically under the canonical file lock. Returns `(mode, sentinel)` where mode is 'resume' if
    WE already hold an in-flight integration of THIS id (a committed-but-unhanded retry — its
    recorded sentinel is reused verbatim, since after a committed merge the target tip has moved and
    the sha no longer matches a freshly recomputed one), else 'claimed'. Refuses if another agent
    — or our own pen carrying a DIFFERENT id — holds it.

    When a takeover `ticket` is supplied, the pen-availability check, the takeover commit, and the
    pen flip run as ONE serialized phase UNDER THIS LOCK (Codex PR C review round-2 finding 1): if
    the pen is busy we die having written NOTHING (no ownership transfer); if the mandatory audit
    fails we die having flipped NOTHING. This closes the become-busy race the earlier read-only
    precheck only narrowed — a peer that claims the pen between the precheck and here is caught
    here, before the takeover is persisted."""
    working_self = f"WORKING_{agent.upper()}"
    with core.file_lock() as guard:
        text = core.load_or_die()
        lk = core.get_lock(text)
        roster_or_die(lk, agent)
        st, held = lk.get("state", ""), lk.get("integrating")
        if held:
            if st == working_self and held.split("@", 1)[0] == idv:
                # RESUME our own in-flight integration. Any supplied takeover must STILL be
                # applied here (Codex PR C review round-3 finding 2): if the sidecar became
                # foreign while the integration was in flight, resuming must not bypass the
                # re-stamp + ledger + CAS. commit_takeover_or_die no-ops on ticket=None.
                commit_takeover_or_die(idv, agent, ticket, "integrate")
                return "resume", held
            die(f"integration pen busy: {lk.get('holder')} is integrating {held}")
        if st not in ("IDLE", f"AWAITING_{agent.upper()}", working_self):
            die(f"integration pen not free: state={st}, holder={lk.get('holder')}")
        # pen is FREE and WE hold the file lock → commit the takeover NOW, before the flip,
        # so a busy pen could never have transferred ownership and a failed audit flips nothing.
        commit_takeover_or_die(idv, agent, ticket, "integrate")
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
    if not resolves(args.base):
        die(f"--base {args.base!r} does not resolve to a commit")
    # Hold the PER-ID ownership lock across the exists-check + worktree create + sidecar write,
    # so a claim serializes with a concurrent takeover/drop of the same id and stamps a FRESH
    # generation nonce (Codex PR C review round-4: a drop+reclaim must not let a stale ticket
    # match the new lane).
    with owner_lock(idv):
        if os.path.exists(ftree):
            die(f"worktree {idv!r} already exists at {ftree}")
        if local_branch_exists(branch):
            git(["worktree", "add", ftree, branch])          # check out an existing branch
        else:
            git(["worktree", "add", "-b", branch, ftree, args.base])  # new branch off --base
        # A fresh claim owns the worktree — record it beside the checkout with a NEW gen.
        # Creation is best-effort (the worktree already exists; a failed sidecar is a doctor
        # owner_missing, not a claim failure).
        ok, err = write_owner(idv, args.agent, branch)       # gen=None → minted fresh
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
    with owner_lock(idv):                                # per-id serialization (CAS authority)
        with core.file_lock() as guard:                 # inner: the done.log ledger
            roster_or_die(core.get_lock(core.load_or_die()), args.agent)  # re-check under the lock
            commit_takeover_or_die(idv, args.agent, ticket, "done")   # CAS + persist
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
    ticket = require_takeover_or_die(idv, args.agent, args)         # INTENT gate (no write yet)
    ftree = wt_path(idv)
    # A cross-owner drop destroys both the worktree AND its sidecar, so the DURABLE ledger is
    # the only surviving audit. The ENTIRE span — exists-check, CAS + `authorized` record, the
    # destructive `git worktree remove`, and the sidecar cleanup — runs under the PER-ID
    # ownership lock, so no concurrent `done`/`integrate` takeover can slip into the gap between
    # authorization and removal and have its new lane deleted (Codex PR C review round-4 finding
    # 2). The per-id lock (not the global core lock) means git runs serialized only against
    # same-id ownership ops, never freezing the relay.
    with owner_lock(idv):
        if not os.path.exists(ftree):                        # precondition BEFORE the audit, so a
            die(f"no worktree {idv!r} at {ftree}")           # missing tree writes no phantom record
        authorize_drop_takeover_or_die(idv, args.agent, ticket)   # CAS (agent+gen) + authorized
        git(["worktree", "remove", ftree])                   # git refuses if dirty (no --force)
        remove_owner(idv)                                    # best-effort cleanup (RFC 049 PR C)
        ok, err = complete_drop_takeover(idv, args.agent, ticket)  # phase=completed tombstone
    print(f"✓ dropped worktree {idv}")
    if not ok:
        # the removal cannot be rolled back, but a failed completion audit must NOT be reported
        # as a full success (Codex PR C review round-3 finding 3): surface it and exit nonzero.
        print(f"⚠ drop completed but the completion audit could not be recorded ({_safe(err)}); "
              f"the `authorized` ledger record stands as the durable audit", file=sys.stderr)
        return 2
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
        if short and owner["branch"] != short:
            problems.append(f"recorded branch {_safe(owner['branch'])!r} != {_safe(short)!r}")
        elif not short:                                  # detached HEAD: owner claims a branch
            problems.append(f"recorded branch {_safe(owner['branch'])!r} but worktree is detached")
        if problems:
            findings.append({"id": "worktree.owner_mismatch", "severity": "warning",
                             "worktree": _safe(idv), "detail": "; ".join(problems)})
    owners = _owners_dir_safe()
    try:
        names = [f for f in os.listdir(owners)] if owners else []
    except OSError:
        names = []
    for f in sorted(names):
        if not f.endswith(".json") or f == TAKEOVER_LEDGER:   # ledger is not an owner sidecar
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

    # ---- every remaining precondition BEFORE the pen flip. The takeover is NOT committed
    #      here: it is folded into claim_pen so the pen-availability check, the mandatory
    #      audit, and the pen flip are ONE serialized phase under the file lock (finding 1).
    #      This early read-only precheck is only a friendly fast-fail before the (reusable)
    #      integration-tree prep; claim_pen re-checks authoritatively under the lock.
    _integration_pen_free_or_die(agent, idv)
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

    # ---- take the pen + commit the takeover + stamp the sentinel. claim_pen holds the CORE
    #      file lock (pen atomicity); we wrap it in the PER-ID ownership lock (OUTER — the single
    #      acquire order) so the takeover CAS serializes with a concurrent done/drop of this id
    #      too. A busy pen transfers nothing, a failed audit flips nothing. ----
    with owner_lock(idv):
        mode, sentinel = claim_pen(agent, idv, target_sha, ticket)

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
    p = HelpfulArgumentParser(
        prog="m8shift-worktree.py",
        usage="%(prog)s [--version] <command> [args]",
        description="Create isolated feature worktrees and serialize their integration.",
        epilog="""examples:
  m8shift-worktree.py status
  m8shift-worktree.py claim feature-a agent-a --base main
  m8shift-worktree.py integrate feature-a agent-a --into main --to agent-b""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
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

    doc = sub.add_parser("doctor", help="read-only worktree ownership diagnostics")
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
