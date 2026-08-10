#!/usr/bin/env python3
"""RFC 052 E1 — confidential denylist scrub-check over git TIP and HISTORY.

Scans the repository for operator-denylisted identifiers (foreign project names,
internal program names — the identities the path lint cannot know) BEFORE they
leave the machine. Read-only; stdlib-only; no network.

Denylist (never committed — it IS the confidential data):
  $M8SHIFT_DENYLIST if set, else ~/.config/m8shift/denylist.txt, else no-op.
  Format: one entry per line; `# comment` / blank ignored;
  `allow:<substring>` = exception; `word:<term>` = word-boundary; else literal.
  Every entry, exception included, must be at least 3 characters: an exception
  suppresses a whole line for every rule, so a shorter one silences more than any
  term it could justify (#266).
  Matching is case-insensitive.

Scans (raw `git` by argv — NEVER routed through a lossy optimizer such as rtk;
a "clean" through a lossy path is unverified by definition):
  TIP      git grep -I -i -n [-F|-E] -e <pattern> HEAD --
  HISTORY  git log <reachable scope> --diff-merges=separate --no-patch
           --pickaxe-regex -i -S<escaped> --
  Revisions always precede `--` (bad ordering silently scans nothing — the
  false-negative that let a real leak through; see RFC 052).

Range mode (`--range`, repeatable — the pre-push hook path): scan only what a
push is about to publish. `--range A..B` scans the B tree plus A..B history; a
bare `--range SHA` (new ref) scans that tree plus history not already reachable
its whole reachable history (#262: no exclusion is derived from remote-tracking
refs, which are a cache). The hook also supplies the target
`--remote` and corresponding `--ref`, so every history finding names its carrier
branch/tag. Annotated tag objects are scanned directly as well: tree/history
walks do not inspect their messages. Local side branches, worktree reflogs, and
unreachable objects are outside this publish scope and can never block a clean
pushed range.

Commit messages are scanned once across the same bounded history scope, so a
range finding names the pushed carrier. `--objects` is a separate release-audit
mode: it scans every local blob/tree plus full commit/tag objects, including
identity headers, side refs, and unreachable objects. It is never run
automatically by the pre-push hook.

The default direct scan is HEAD tip + HEAD history. `--all` is the explicit
repository-audit mode: it adds every ref, reflog, and bounded unreachable commit,
and labels each history hit with carrier refs, worktree reflogs, or an unreachable
object. Values passed as ranges remain hex-only rev specs.

Output is REDACTED by default: file:line / commit hash + a hashed term label,
never the term or the matched content. `--verbose` shows terms locally only.

Exit codes: 0 clean (or empty denylist = no-op), 1 at least one hit, 2 error
(not a repo, git missing/failed). The shipped pre-push hook treats 1 as advisory
unless M8SHIFT_SCRUB_ENFORCE is armed (1|true|yes|on, ASCII case-insensitive;
any unrecognised value refuses before scanning), always blocks on 2 (scan errors
fail closed), and blocks on this script's ABSENCE for any push that publishes
objects — "not installed" and "installed and clean" must not look alike (#264).
"""

import argparse
import concurrent.futures
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import unicodedata

DENYLIST_ENV = "M8SHIFT_DENYLIST"
DENYLIST_DEFAULT = os.path.join("~", ".config", "m8shift", "denylist.txt")
DENYLIST_MAX_BYTES = 64 * 1024
DENYLIST_MAX_TERMS = 256
DENYLIST_MIN_LEN = 3
GIT_TIMEOUT_S = 60
HISTORY_MAX_COMMITS = 5000
SCRUB_MAX_WORKERS = 8
OBJECT_MAX_BYTES = 256 * 1024 * 1024
OBJECT_GIT_TIMEOUT_S = 300
# A pushed merge publishes one tree against every parent it joins.  Separate
# parent diffs are therefore the strict publication-boundary semantics: a merge
# resolution that introduces or removes denied content must not disappear merely
# because ordinary `git log -S` suppresses merge diffs.  Keep this shared by the
# byte-exact pickaxe and normalized-content supplement so their merge universes
# cannot drift.
HISTORY_DIFF_MERGES = "--diff-merges=separate"
# Hex-only rev specs: `A..B` or a bare SHA. Rejecting anything else keeps a
# hostile/typoed value from ever reaching the git argv as an option.
RANGE_RX = re.compile(r"^[0-9a-fA-F]{4,64}(\.\.[0-9a-fA-F]{4,64})?$")
OBJECT_RX = re.compile(r"^[0-9a-fA-F]{40,64}$")
REMOTE_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
MATCH_SPACE_RX = re.compile(
    r"[\u0020\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
MATCH_IGNORABLE_RX = re.compile(
    r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    r"\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f"
    r"\ufeff\uffa0\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    r"\U000e0000-\U000e0fff]")


def label_of(term):
    """Confidential display label — a short hash, never the term itself."""
    return "denylist:" + hashlib.sha256(term.strip().lower().encode("utf-8")).hexdigest()[:10]


def normalize_for_match(text):
    """Canonicalize only the human-equivalent forms covered by #265.

    NFC closes decomposed-accent misses without NFKC's compatibility widening.
    Unicode space separators collapse to an ordinary space. Default-ignorable
    formatting controls are deleted first, so inserting one inside a single-token
    identifier cannot evade comparison. This intentionally does NOT fold ligatures,
    full-width forms, circled characters, superscripts, or other compatibility forms.
    """
    visible = MATCH_IGNORABLE_RX.sub("", text)
    return MATCH_SPACE_RX.sub(" ", unicodedata.normalize("NFC", visible))


def validate_word_term(term):
    normalized = normalize_for_match(term)
    if not normalized or not re.match(r"\w", normalized[0], re.UNICODE) or \
            not re.match(r"\w", normalized[-1], re.UNICODE):
        raise ValueError(
            "word denylist rule must start and end with a word character")


def parse_denylist_text(text):
    """-> (rules, allows, skipped). rules = [(label, term, mode)] with mode in
    {"literal", "word"}. MUST stay semantically identical to m8shift.py's
    _parse_denylist_text (a drift test compares both on a shared fixture)."""
    rules, allows, skipped = [], [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(rules) >= DENYLIST_MAX_TERMS:
            break
        mode, sep, rest = line.partition(":")
        if sep and mode == "allow" and rest.strip():
            # #266: an exception is held to the same floor as a term, because it is
            # STRONGER than one. Every textual consumer suppresses a whole line when
            # any allow substring occurs in it, so a one-character exception silences
            # every candidate line that can possibly contain a denied term: a line
            # cannot match `SensitiveToken` without also containing `e`. Measured on
            # the pre-fix parser: rc 1 and a TIP hit with the term alone, rc 0 and no
            # hit once `allow:e` is added. The floor was applied to literal and
            # `word:` rules only — the branch returned before reaching it.
            exception = rest.strip()
            if len(exception) < DENYLIST_MIN_LEN:
                skipped += 1
                continue
            allows.append(normalize_for_match(exception).lower())
            continue
        if sep and mode == "word" and rest.strip():
            term = rest.strip()
            if len(term) < DENYLIST_MIN_LEN:
                skipped += 1
                continue
            validate_word_term(term)
            rules.append((label_of(term), term, "word"))
            continue
        if len(line) < DENYLIST_MIN_LEN:
            skipped += 1
            continue
        rules.append((label_of(line), line, "literal"))
    return rules, allows, skipped


def load_denylist(path_override=None, env=None):
    """-> (rules, allows, note). Missing default path = no-op with a note."""
    env = os.environ if env is None else env
    explicit = path_override or (env.get(DENYLIST_ENV) or "").strip()
    path = os.path.expanduser(explicit or DENYLIST_DEFAULT)
    if not os.path.isfile(path):
        if explicit:
            raise RuntimeError(
                "explicit denylist path is missing or not a regular file")
        return [], [], "no denylist configured — no-op"
    try:
        with open(path, "rb") as fh:
            raw = fh.read(DENYLIST_MAX_BYTES + 1)
    except OSError as exc:
        if explicit:
            raise RuntimeError(
                "explicit denylist is unreadable (%s)" %
                exc.__class__.__name__)
        return [], [], "denylist unreadable (%s) — nothing scanned" % exc.__class__.__name__
    if len(raw) > DENYLIST_MAX_BYTES:
        raise RuntimeError(
            "denylist exceeds %d-byte scan bound" % DENYLIST_MAX_BYTES)
    text = raw.decode("utf-8", "replace")
    rules, allows, skipped = parse_denylist_text(text)
    eligible = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("allow:"):
            continue
        if line.startswith("word:"):
            line = line.partition(":")[2].strip()
        if len(line) >= DENYLIST_MIN_LEN:
            eligible += 1
    if eligible > DENYLIST_MAX_TERMS:
        raise RuntimeError(
            "denylist exceeds %d-term scan bound" % DENYLIST_MAX_TERMS)
    note = ""
    if skipped:
        note = ("%d denylist entr%s shorter than %d chars ignored"
                % (skipped, "y" if skipped == 1 else "ies", DENYLIST_MIN_LEN))
    return rules, allows, note


def tip_cmd(rule, rev="HEAD"):
    """git grep argv for one rule — the revision BEFORE `--` (HEAD by default;
    a pushed tip SHA in range mode).

    Always a case-insensitive LITERAL (-F): `\\b` in `git grep -E` is a GNU
    extension the BSD/macOS regex lacks, so a word-boundary pattern would scan
    CLEAN there — a silent false negative (caught empirically on macOS). Word
    semantics are applied portably in-process on the matched lines instead."""
    label, term, mode = rule
    return ["git", "grep", "-I", "-i", "-n", "-F", "-e", term, rev, "--"]


def history_revs(range_args=None, all_refs=False, refs_pull=False,
                 extra_revs=None):
    """The revision universe for ANY history walk. -> [rev args], no subcommand.

    #295: this three-way choice existed verbatim in history_cmd() and
    commit_message_cmd(), and the first attempt at a range-less path scan wrote a
    THIRD copy. Copies drift, and a path walk that drifts from the content walk is
    exactly the false clean this ticket is about: the audit would answer a different
    question for names than it answers for contents, while reporting one verdict.

    Pushed revs replace the audit walk in range mode; `--all` adds refs, reflogs and
    the bounded unreachable roots the caller discovered (plus refs/pull only when
    asked); otherwise HEAD.
    """
    if range_args:
        return list(range_args)
    if all_refs:
        revs = ["--all", "--reflog"] + list(extra_revs or [])
        if refs_pull:
            revs.append("--glob=refs/pull")
        return revs
    return ["HEAD"]


def history_cmd(rule, max_commits, refs_pull, range_args=None, all_refs=False,
                extra_revs=None):
    """git log pickaxe argv for one rule — revision specs BEFORE `--`.
    `--pickaxe-regex -i` + re.escape gives a portable case-insensitive literal
    (no \\b: word-boundary is a GNU extension the system regex may lack; the
    slight over-match on history is the honest, portable choice).
    range_args (range mode) replaces the audit walk with pushed revs only (e.g.
    ["A..B"] or ["SHA"]).  Direct mode walks HEAD;
    explicit all_refs adds refs, reflogs, and bounded unreachable roots."""
    label, term, mode = rule
    cmd = ["git", "log"] + history_revs(range_args, all_refs, refs_pull, extra_revs)
    # --diff-merges also turns patch output on.  --no-patch is a correctness
    # boundary here, not presentation: run_history parses every whitespace token
    # as a candidate object id, so diff text must never enter stdout.
    cmd += [HISTORY_DIFF_MERGES, "--no-patch",
            "--pickaxe-regex", "-i", "-S", re.escape(term),
            "--format=%H", "-n", str(max_commits), "--"]
    return cmd


class PathEnumerationError(RuntimeError):
    """A path walk did not complete. Carries no Git output — see scope_path_records."""


def parse_path_records(stdout, attribute):
    """Parse one path-walk stream. -> (records, walked_shas)

    Pure, and separate from the subprocess so a test can hand it the output of a
    REAL truncated `git log -n K ...` and inspect what Git actually produced.

    #297 review: my first attempt to prove the bounded case called the enumerator
    with no bound, walked the complete history, and then kept only the `D` statuses
    in test code — while the docstring claimed Git had produced a deletion-only set.
    The bound created none of the tested input. Extracting this seam is what makes
    that claim checkable instead of asserted.

    Framing is a NUL run: Git forbids NUL inside a path and never emits an empty
    name, so two consecutive empty records cannot come from a filename, and the
    record after them is the commit. `walked` collects DISTINCT SHAs, never frames:
    with `-m` a merge re-emits the format block once per parent (measured: five
    frames for four commits).
    """
    records, walked = [], set()
    fields = (stdout or "").split("\0")
    index, current = 0, None
    while index < len(fields):
        if attribute and fields[index] == "" and index + 2 < len(fields) \
                and fields[index + 1] == "":
            current = fields[index + 2].strip()
            if current:
                walked.add(current)
            index += 3
            continue
        token = fields[index]
        if not token:
            index += 1
            continue
        if attribute:
            # Alternating status/path pairs. Only a status may be stripped: a path
            # is taken verbatim because a newline is legal inside one.
            status = token.strip("\n").strip()
            if index + 1 >= len(fields) or not fields[index + 1]:
                index += 1
                continue
            records.append((current, status, fields[index + 1]))
            index += 2
            continue
        records.append((None, "", token))
        index += 1
    return records, walked


def is_publish_scope(range_args):
    """True only for a real `A..B` update range, i.e. a scope with TWO known
    endpoints. -> bool

    #295 review: the call site used `bool(range_args)`, but parse_ranges() renders
    a new-ref `--range SHA` as `[SHA]`, so a bare-SHA publish was also treated as
    having a base it does not have. Observationally dormant while the path walk is
    unbounded, yet it defeated the stated reason for keeping the guard at all: once
    the walk gains a bound, a bare-SHA publish could classify an old deletion as a
    cleanup. The predicate lives here so the endpoint-diff decision and the
    classification decision cannot disagree about what a publish scope is.
    """
    return bool(range_args) and len(range_args) == 1 and ".." in range_args[0]


def scope_path_records(tip_rev, range_args, repo, run, history=True,
                       history_revs_args=None, max_commits=None):
    """Enumerate the paths a pushed scope publishes or carries.

    -> [(sha_or_None, status, path)]; status is a Git name-status letter, or "" for
    a current-name record (which is a tree/endpoint state, not a change).

    #291: both scanners this hook runs match file CONTENT. `git grep` searches blob
    bodies, the pickaxe counts occurrences inside blobs, and the message scan reads
    %B — no scan input has ever contained a tree entry name. A denied identifier
    carried by a filename or a directory therefore published with rc 0 under
    enforcement, verified end to end with a real push.

    Enumerated ONCE per scope, not once per denylist term: the cost of this addition
    must not scale with the term count, and `--objects` stays the standalone audit.

    Two walks, mirroring the existing TIP/HISTORY split:

    * current names — the tree actually being published (`ls-tree` on a bare/new ref)
      or the endpoint diff for `A..B`, so an existing-ref push does not re-report
      every name already at the destination;
    * carried names — what each commit in the pushed history did to each path, with
      `--root` so a first-commit introduction is seen, `-m` so a merge's own diffs
      are, and `--no-renames` so a rename leaves BOTH names observable.

    FAILURE IS CLOSED. This function used to `return` on any non-zero Git rc, which
    the caller could not observe: with only the path commands forced to rc 128 and
    every other scanner command intact, `main()` printed "clean" and returned 0 —
    a fail-open at the exact boundary this ticket adds (review BLOCKER 1). Any
    incomplete walk now raises, and the caller fails the scan closed.

    FRAMING IS STRUCTURAL, not a sentinel. The first implementation marked commits
    with a literal `commit ` prefix, having replaced a bare-%H marker because a file
    may be named like a 40-hex sha. That merely moved the collision: `commit ` is a
    perfectly legal path prefix, and a path named `commit <denied-term>`, added and
    removed inside `A..B`, was consumed as metadata and never matched — measured rc 0
    where the same fixture without the prefix gave rc 1 (review BLOCKER 2). Any
    sentinel drawn from the same alphabet as the data has this defect. So the frame
    is `%x00%x00%H`: a NUL run. Git forbids NUL inside a path and never emits an
    empty name, so TWO consecutive empty records cannot be produced by any filename,
    and the record following them is the commit. Measured, not assumed — a file named
    `ligne1\nligne2.md` also proves why records are split on NUL rather than lines
    (4 records where a line split sees 5).
    """
    records = []
    # Distinct commit SHAs, not frames. Measured: with `-m` a merge re-emits the
    # format block once per parent, so a 4-commit history yielded 5 frames. Counting
    # frames would over-count merges and could declare the window exhausted when it
    # is not — a false rc 2 that trains an operator to raise the bound for nothing.
    walked = set()

    def harvest(cmd, attribute):
        proc = run(cmd, repo)
        if proc.returncode != 0:
            # Deliberately no Git stderr: it quotes the offending PATH, which is the
            # very thing that may carry a denied identifier. Subcommand and rc are
            # bounded, actionable, and cannot leak.
            raise PathEnumerationError("git %s rc=%d" % (cmd[1], proc.returncode))
        found, seen = parse_path_records(proc.stdout, attribute)
        records.extend(found)
        walked.update(seen)

    if is_publish_scope(range_args):
        base, _, tip = range_args[0].partition("..")
        # `--diff-filter=d` drops deletions: a name the endpoint no longer carries is
        # not a current name. Without it, a push whose only change REMOVES a denied
        # directory was reported as publishing it and blocked, so the one action the
        # gate asks an operator to take could not be pushed (review BLOCKER 3).
        harvest(["git", "diff", "-z", "--name-only", "--no-renames",
                 "--diff-filter=d", base, tip], False)
    elif tip_rev:
        harvest(["git", "ls-tree", "-r", "-z", "--name-only", tip_rev], False)

    revs = history_revs_args if history_revs_args is not None else range_args
    if history and revs:
        # Revision specs first and a `--` terminator, exactly like history_cmd() and
        # commit_message_cmd(). Same shape, same selector, same position: a reader
        # comparing the three walks should not have to reconstruct the equivalence,
        # and the argv test asserts it rather than trusting it.
        #
        # #297: the audit window. `max_commits` is set ONLY for the range-less
        # direct/`--all` walks; an explicit publish scope stays COMPLETE, because a
        # push larger than the window must still be caught on its oldest transmitted
        # commit. N+1 is requested rather than N: the extra frame is how truncation
        # is DETECTED. Seeing it means the window is too small to answer, and the
        # caller must fail closed instead of reporting on a prefix.
        bound = [] if max_commits is None else ["-n", str(max_commits + 1)]
        harvest(["git", "log"] + list(revs) + bound +
                ["--format=%x00%x00%H", "-z", "--name-status",
                 "--no-renames", "--root", "-m", "--"], True)
        if max_commits is not None and len(walked) > max_commits:
            raise PathEnumerationError(
                "audit window exhausted (>%d commits); raise --max-commits"
                % max_commits)
    return records


def path_records_block(status_by_path, publish_scope=True):
    """Split enumerated paths into (blocking, removed_only). -> (set, set)

    A path blocks when the pushed scope PUBLISHES or CARRIES it: present in the
    current-name walk (status ""), or touched by any commit with a status other than
    `D`. A path whose every record is a deletion is one this push REMOVES: the
    published tree does not carry it, and if the commit that introduced it were
    inside the pushed range that commit's own `A` record would appear here and block.
    So the discrimination is complete without any endpoint evidence and stays closed
    by construction — which is why an add-then-remove inside one push still blocks.

    `publish_scope` is False for the range-less AUDIT walks (#295): an audit answers
    "does this repository carry the name anywhere", so a historical occurrence IS the
    finding, and only a real `A..B` scope with two known endpoints may conclude that
    a deletion means nothing is published. A bare-SHA new-ref push is NOT such a
    scope: it publishes an entire history with no base to compare against.

    Stated precisely, because a name must not claim more than it holds. A COMPLETE
    range-less walk cannot reach the all-deletions state at all: it sees the commit
    that deletes a path, whose parent carries the file and is therefore reachable, so
    the parent's own `A` record appears and the path blocks anyway. A BOUNDED walk
    can produce that shape — put the addition before the window and the deletion
    inside — but since #297 the range-less scan REFUSES (rc 2) as soon as the window
    is exhausted, so production never hands a truncated record set to this function.

    The guard is therefore defence in depth, not a reachable production downgrade
    path. It is kept because it is the fail-safe direction and because the policy is
    exercised directly on real bounded Git output, and it must not be deleted as dead
    code: it is what a future change to the refusal semantics would land against.
    """
    blocking, removed = set(), set()
    for path, statuses in status_by_path.items():
        if not publish_scope or any(status != "D" for status in statuses):
            blocking.add(path)
        else:
            removed.add(path)
    return blocking, removed


def path_match_indexes(path, matcher):
    """Rule indexes matching a path. NO allow: suppression, by #292's finding.

    A path is not line-scoped text, exactly as a tree object is not: there is no
    boundary an `allow:` exception could be scoped to inside `a/b/c`. Applying one
    would let a legitimate lookalike in one directory component silence a denied
    identifier in another, which is the defect #292 closed for tree objects.
    """
    return content_match_indexes(path, matcher, ())


def parse_ranges(values):
    """-> (specs, error). specs = [(tip_rev, range_args)] per --range value:
    `A..B` scans tree(B) + commits A..B; a bare SHA scans tree(SHA) and its whole
    reachable history, excluding NOTHING. Invalid shapes are a hard error (rc 2).

    #262: this used to exclude `--not --remotes=<name>` — local remote-tracking
    refs, which are a cache. Recreate or purge the remote and the cache survives it,
    so unpublished history was excluded and the gate printed clean at the moment the
    risk was highest. Measured on a real recreated remote: rc 0 and zero history
    hits with the stale ref present, rc 1 and the leak with it removed.

    Re-observing the remote instead was tried and rejected: `git ls-remote` resolves
    the FETCH url while pushes go to `pushurl`, its tips can name objects the local
    store lacks (`fatal: bad object` on the routine "a teammate pushed since my last
    fetch" state), and the scanner header and RFC 052 both declare this family
    network-free.

    The endpoint authority is the pre-push `remote_sha`, which git obtained from the
    real push endpoint and hands the hook on stdin — the hook already turns a locally
    resolvable one into `remote_sha..local_sha` and falls back to a bare sha
    otherwise. This function's job is simply not to defeat that fallback: with no
    negotiation there is no basis for excluding anything, and over-scan is the safe
    direction."""
    specs = []
    for value in values or []:
        value = value.strip()
        if not RANGE_RX.match(value):
            return None, "invalid --range %r (expected hex A..B or a bare sha)" % value
        if ".." in value:
            base, _, tip = value.partition("..")
            specs.append((tip, [value]))
        else:
            specs.append((value, [value]))
    return specs, None


def validate_remote(value, repo, run):
    """Accept the caller's remote name as opaque reporting metadata.

    #262: this used to gate the scan, and its rc 2 outlived the exclusion it once
    guarded. I claimed the flag was inert after removing the exclusion; review
    executed it and showed otherwise — REMOTE_RX refused names git accepts, so a
    legitimately configured remote called `_fork` fail-closed a real push through the
    hook's "scan errors block" rule, for a value nothing reads.

    The walk no longer depends on this name in any way, so the scanner no longer
    vetoes it. Whether a name is a configured remote is the hook's question, and the
    hook already answers it with `git remote get-url` before passing one. What
    remains here is the shape check that keeps a wild value out of the report text.
    """
    if not value:
        return None, None
    if not isinstance(value, str) or "\n" in value or "\r" in value or \
            len(value) > 256:
        return None, "invalid --remote %r" % value
    return value, None

def redact(text, rules):
    """Redact every denied-term occurrence in a display string (review BLOCKER:
    a denied term inside a file PATH re-leaked through the default locator)."""
    for _label, term, mode in rules:
        text = re.sub(re.escape(term), "[redacted]", text, flags=re.IGNORECASE)
    normalized = normalize_for_match(text)
    for _label, term, mode in rules:
        needle = normalize_for_match(term)
        pattern = (r"\b" + re.escape(needle) + r"\b") \
            if mode == "word" else re.escape(needle)
        if re.search(pattern, normalized, re.IGNORECASE):
            return "[redacted]"
    return text


# Git subcommands this scanner is allowed to run. The family is declared
# network-free by the module header and by RFC 052 acceptance ("stdlib-only, no
# network, no daemon"), and #262 showed that boundary is easy to cross by accident:
# a first attempt at that ticket added `git ls-remote`, and the source-text guard
# written to prevent a repeat was itself bypassed by appending one token to an
# existing call — `run(["git", "remote"], …)` becomes `run(["git", "remote",
# "update"], …)`, which fetches, while a substring assertion still passes.
#
# So the boundary is enforced where the process is actually spawned, not asserted
# about the text. An allowlist of local-only subcommands, plus a refusal of the
# argument forms that make an otherwise-local subcommand reach the network.
LOCAL_ONLY_GIT_SUBCOMMANDS = frozenset({
    "grep", "log", "cat-file", "rev-parse", "rev-list", "show", "for-each-ref",
    "check-ref-format", "remote", "diff", "diff-tree", "ls-tree", "verify-pack",
    "count-objects", "name-rev", "branch", "tag", "config", "fsck", "reflog",
    "merge-base",
})
NETWORK_GIT_SUBCOMMANDS = frozenset({
    "ls-remote", "fetch", "pull", "push", "clone", "submodule", "archive",
    "send-pack", "fetch-pack", "upload-pack", "request-pull", "bundle",
})
NETWORK_GIT_ARGS = frozenset({"update", "prune", "set-head", "--fetch"})


class NetworkAttemptRefused(RuntimeError):
    """A git argv that could reach the network was refused before spawning."""


def refuse_network_argv(cmd):
    """Raise unless `cmd` is a local-only git invocation. Fail closed on anything
    unrecognised: an unknown subcommand is refused rather than allowed, because the
    cost of a false refusal is a visible error and the cost of a false allow is a
    silent network dependency in a pre-push hook."""
    if not cmd or cmd[0] != "git":
        raise NetworkAttemptRefused("scrub-check only runs git: %r" % (cmd[:1],))
    args = [a for a in cmd[1:] if not a.startswith("-") or a in NETWORK_GIT_ARGS]
    sub = next((a for a in cmd[1:] if not a.startswith("-")), None)
    if sub in NETWORK_GIT_SUBCOMMANDS:
        raise NetworkAttemptRefused("network git subcommand refused: %s" % sub)
    if sub not in LOCAL_ONLY_GIT_SUBCOMMANDS:
        raise NetworkAttemptRefused("git subcommand not on the local-only allowlist: "
                                    "%s" % sub)
    # `git remote` is local; `git remote update` is a fetch. Same for prune/set-head.
    tail = [a for a in args[1:] if a in NETWORK_GIT_ARGS]
    if sub == "remote" and tail:
        raise NetworkAttemptRefused("network git argument refused: remote %s" % tail[0])
    return cmd


def usable_endpoint_bases(values, repo, run):
    """Keep only bases the local object store can resolve. -> (bases, dropped).

    A base git cannot resolve here cannot be used to prove anything, and feeding it
    to a revision walk is what made the first #262 attempt die on `fatal: bad
    object`. Dropping it is safe: fewer proofs means fewer findings are downgraded
    from blocking, never more.
    """
    bases, dropped = [], []
    for value in values or []:
        if not OBJECT_RX.match(value or "") or set(value) == {"0"}:
            dropped.append(value)
            continue
        try:
            proc = run(["git", "cat-file", "-e", value + "^{commit}"], repo)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
            dropped.append(value)
            continue
        (bases if proc.returncode == 0 else dropped).append(value)
    return bases, dropped


def not_transmitted_by_this_push(sha, bases, repo, run):
    """True iff this push does not transmit `sha`, per git's own negotiation.

    Read the name carefully, because an earlier version of this function claimed
    more than it can know. `merge-base --is-ancestor` answers a question about the
    LOCAL object graph: is `sha` an ancestor of `base` here. It does not establish
    that the destination holds `sha`. Against a destination whose object store is
    not ancestor-complete — a shallow bare repo, a partial restore, the truncated
    endpoint family this ticket is about — review demonstrated the gate announcing
    "confirmed pre-existing at the destination" for commits `git cat-file -e` proved
    ABSENT there.

    What the code CAN substantiate is weaker and sufficient: git computed the pack
    by excluding everything reachable from the destination's advertised refs, and
    `bases` are a subset of those refs. So a finding answering True here is one this
    push does not send, and downgrading it can never suppress a block on content that
    is actually published. That is structural rather than lucky, and review verified
    it — including a case where git's own receive-side connectivity check stayed
    silent and the push fully succeeded, with no denylisted byte reaching the
    destination.

    The bases themselves still come only from git's push negotiation, never from a
    local ref and never from a remote-tracking cache: a stale local carrier can hold
    a commit a recreated destination has never seen, which is #262 itself.
    """
    for base in bases:
        try:
            proc = run(["git", "merge-base", "--is-ancestor", sha, base], repo)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
            continue
        if proc.returncode == 0:
            return True
    return False


def run_git(cmd, repo, binary=False, stream=False, **stream_kwargs):
    """Raw argv execution (shell=False), bounded, LOCAL ONLY. -> CompletedProcess.
    Explicit utf-8 + errors=replace: with bare text=True, invalid UTF-8 in a
    tracked file made the decode raise UnicodeDecodeError -> traceback -> rc 1,
    which the hooks then misread as a scrub HIT (review MEDIUM 2).

    ``binary`` keeps exact bytes at the normalized-content boundary. ``stream``
    opens the one bounded cat-file pipeline.  Both primitives deliberately live
    behind this same policy/injection boundary.
    """
    refuse_network_argv(cmd)
    if stream:
        return subprocess.Popen(cmd, cwd=repo, **stream_kwargs)
    kwargs = {"cwd": repo, "capture_output": True, "timeout": GIT_TIMEOUT_S}
    if not binary:
        kwargs.update(encoding="utf-8", errors="replace")
    return subprocess.run(cmd, **kwargs)


def run_git_bytes(cmd, repo, run=run_git):
    """Run through the injected Git seam and return byte stdout/stderr.

    Production uses ``run_git(binary=True)`` so invalid UTF-8 remains exact.
    A test/policy runner keeps authority over the command and may return either
    text or bytes; text is encoded only after that runner has answered.
    """
    if run is run_git:
        return run(cmd, repo, binary=True)
    result = run(cmd, repo)
    stdout = result.stdout if isinstance(result.stdout, bytes) else \
        (result.stdout or "").encode("utf-8")
    stderr = result.stderr if isinstance(result.stderr, bytes) else \
        (result.stderr or "").encode("utf-8")
    return subprocess.CompletedProcess(
        cmd, result.returncode, stdout=stdout, stderr=stderr)


def iter_blob_batch(shas, repo, run=run_git):
    """Yield unique ``(sha, body)`` pairs from one local cat-file process.

    Production streams ``--batch`` and rejects an oversized blob from its header
    before reading the body.  An injected runner uses a different one-object
    read strategy, so its size check is post-hoc rather than parser coverage.
    """
    ordered = list(dict.fromkeys(sha for sha in shas if sha and set(sha) != {"0"}))
    if not ordered:
        return
    if run is not run_git:
        # An injected runner is the authority for every Git invocation.  Fetch
        # one object at a time through that seam so only one body is retained,
        # without letting a real Popen escape a test/policy runner.  Because a
        # CompletedProcess already owns stdout, the byte-size bound below is
        # necessarily post-hoc.
        for expected in ordered:
            result = run_git_bytes(
                ["git", "cat-file", "blob", expected], repo, run)
            if result.returncode != 0:
                raise RuntimeError("git cat-file blob rc=%d: %s" % (
                    result.returncode,
                    result.stderr[:200].decode("utf-8", "replace")))
            if len(result.stdout) > OBJECT_MAX_BYTES:
                raise RuntimeError("blob %s exceeds %d-byte scan bound" % (
                    expected[:12], OBJECT_MAX_BYTES))
            yield expected, result.stdout
        return
    cmd = ["git", "cat-file", "--batch"]
    with tempfile.TemporaryFile() as requests, tempfile.TemporaryFile() as errors:
        requests.write(("\n".join(ordered) + "\n").encode("ascii"))
        requests.seek(0)
        proc = run(cmd, repo, binary=True, stream=True, stdin=requests,
                   stdout=subprocess.PIPE, stderr=errors)
        timed_out = threading.Event()

        def abort():
            timed_out.set()
            proc.kill()

        timer = threading.Timer(OBJECT_GIT_TIMEOUT_S, abort)
        timer.daemon = True
        timer.start()
        try:
            for expected in ordered:
                header = proc.stdout.readline().rstrip(b"\n").split()
                if timed_out.is_set():
                    raise RuntimeError("git cat-file --batch exceeded %ds timeout" %
                                       OBJECT_GIT_TIMEOUT_S)
                if len(header) != 3 or \
                        header[0].decode("ascii", "replace") != expected or \
                        header[1] != b"blob":
                    raise RuntimeError("invalid git cat-file batch blob header")
                try:
                    size = int(header[2])
                except ValueError:
                    raise RuntimeError("invalid git cat-file batch blob size")
                if size < 0 or size > OBJECT_MAX_BYTES:
                    raise RuntimeError("blob %s exceeds %d-byte scan bound" % (
                        expected[:12], OBJECT_MAX_BYTES))
                body = proc.stdout.read(size)
                trailer = proc.stdout.read(1)
                if len(body) != size or trailer != b"\n":
                    raise RuntimeError("truncated git cat-file batch blob body")
                yield expected, body
                body = None
            if proc.stdout.read(1):
                raise RuntimeError("unexpected trailing git cat-file batch output")
            returncode = proc.wait()
            if timed_out.is_set():
                raise RuntimeError("git cat-file --batch exceeded %ds timeout" %
                                   OBJECT_GIT_TIMEOUT_S)
            if returncode != 0:
                errors.seek(0)
                raise RuntimeError("git cat-file --batch rc=%d: %s" % (
                    returncode, errors.read(200).decode("utf-8", "replace")))
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def decode_comparison_text(raw):
    """Current text-side decoder; #265 A will add byte encodings at this seam."""
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", "replace")


def normalized_rule_indexes(rules):
    """Rules needing the raw-object supplement because Git cannot normalize.

    Every rule qualifies: an otherwise plain single-token term can acquire an
    invisible formatting control in the candidate text, which Git cannot fold.
    """
    return set(range(len(rules)))


def scan_normalized_tip(rules, allows, revs, repo, run=run_git):
    """Supplement git-grep with one raw UTF-8 tree pass for normalized forms."""
    wanted = normalized_rule_indexes(rules)
    if not wanted:
        return {}
    matcher = compile_content_matcher(rules)
    findings = {}
    for rev in revs:
        result = run_git_bytes(
            ["git", "ls-tree", "-rz", "--full-tree", rev], repo, run)
        if result.returncode != 0:
            raise RuntimeError("git ls-tree rc=%d: %s" % (
                result.returncode, result.stderr[:200].decode("utf-8", "replace")))
        records = []
        for raw_record in result.stdout.split(b"\x00"):
            if not raw_record:
                continue
            meta, sep, path_raw = raw_record.partition(b"\t")
            fields = meta.split()
            if not sep or len(fields) != 3 or fields[1] != b"blob":
                continue
            records.append((fields[2].decode("ascii"),
                            path_raw.decode("utf-8", "replace")))
        matches_by_sha = {}
        for sha, raw in iter_blob_batch(
                (sha for sha, _path in records), repo, run):
            text = decode_comparison_text(raw)
            if text is None:
                del raw
                continue
            matches = []
            for line_no, line in enumerate(text.splitlines(), 1):
                for index in content_match_indexes(line, matcher, allows) & wanted:
                    matches.append((index, line_no))
            matches_by_sha[sha] = matches
            del text, raw
        for sha, path in records:
            for index, line_no in matches_by_sha.get(sha, ()):
                findings.setdefault(index, []).append(
                    "%s:%s:%d" % (rev, path, line_no))
    return findings


def _normalized_occurrences(text, term, mode):
    normalized_text = normalize_for_match(text)
    normalized_term = normalize_for_match(term)
    return _occurrences_in_normalized_text(
        normalized_text, normalized_term, mode)


def _occurrences_in_normalized_text(normalized_text, normalized_term, mode):
    if mode == "word":
        return len(re.findall(r"\b" + re.escape(normalized_term) + r"\b",
                              normalized_text, re.IGNORECASE))
    return normalized_text.lower().count(normalized_term.lower())


def scan_normalized_history(rules, history_runs, args, extra_revs=None,
                            run=run_git):
    """Supplement pickaxe by comparing normalized counts in changed UTF-8 blobs.

    The unit remains one file pair, matching Git -S semantics (including a term
    moving between files in one commit).  This is the stable bytes->text boundary:
    the later encoding slice extends decode_comparison_text(), not comparison.
    """
    wanted = normalized_rule_indexes(rules)
    findings = {}
    if not wanted:
        return findings
    normalized_rules = {
        index: (normalize_for_match(rules[index][1]), rules[index][2])
        for index in wanted
    }
    for range_args, carrier in history_runs:
        cmd = ["git", "log"] + history_revs(
            range_args, args.all, args.refs_pull, extra_revs)
        cmd += [HISTORY_DIFF_MERGES,
                "--raw", "-z", "--no-abbrev", "--no-renames", "--root",
                "--format=%x1e%H%x00"]
        if not range_args:
            cmd += ["-n", str(args.max_commits + 1)]
        cmd.append("--")
        result = run_git_bytes(cmd, args.repo, run)
        if result.returncode != 0:
            raise RuntimeError("git log normalized history rc=%d: %s" % (
                result.returncode, result.stderr[:200].decode("utf-8", "replace")))
        # --diff-merges=separate emits one frame per parent.  Aggregate those
        # frames by commit before applying the per-term commit bound; otherwise a
        # two-parent merge could consume two slots and hide a later carrier.
        commit_records = {}
        blob_ids = []
        for chunk in result.stdout.split(b"\x1e"):
            if not chunk:
                continue
            sha_raw, sep, raw_records = chunk.partition(b"\x00")
            sha = sha_raw.strip().decode("ascii", "replace")
            if not sep or not OBJECT_RX.match(sha):
                raise RuntimeError("git log returned malformed normalized history")
            pairs = []
            fields = raw_records.split(b"\x00")
            index = 0
            while index < len(fields):
                meta = fields[index].strip()
                index += 1
                if not meta:
                    continue
                if not meta.startswith(b":") or index >= len(fields):
                    raise RuntimeError("git log returned malformed raw diff")
                parts = meta[1:].split()
                index += 1                         # path (names are irrelevant here)
                if len(parts) < 5:
                    raise RuntimeError("git log returned malformed raw metadata")
                old_sha = parts[2].decode("ascii") if parts[0] != b"160000" else "0"
                new_sha = parts[3].decode("ascii") if parts[1] != b"160000" else "0"
                pairs.append((old_sha, new_sha))
                blob_ids.extend((old_sha, new_sha))
            commit_records.setdefault(sha, []).extend(pairs)
        blob_counts = {}
        for object_sha, raw in iter_blob_batch(blob_ids, args.repo, run):
            text = decode_comparison_text(raw)
            if text is None:
                blob_counts[object_sha] = None
                del raw
                continue
            normalized_text = normalize_for_match(text)
            object_counts = {}
            for index in wanted:
                count = _occurrences_in_normalized_text(
                    normalized_text, normalized_rules[index][0],
                    normalized_rules[index][1])
                if count:
                    object_counts[index] = count
            blob_counts[object_sha] = object_counts
            del normalized_text, text, raw
        counts = {index: 0 for index in wanted}
        for sha, pairs in commit_records.items():
            hit_indexes = set()
            for old_sha, new_sha in pairs:
                old_counts = {} if set(old_sha) == {"0"} else blob_counts[old_sha]
                new_counts = {} if set(new_sha) == {"0"} else blob_counts[new_sha]
                if old_counts is None or new_counts is None:
                    continue
                for index in wanted:
                    if old_counts.get(index, 0) != new_counts.get(index, 0):
                        hit_indexes.add(index)
            for index in sorted(hit_indexes):
                if counts[index] >= args.max_commits:
                    continue
                findings.setdefault(index, []).append((sha, carrier))
                counts[index] += 1
    return findings


def ref_carrier(refname):
    """Turn a canonical Git ref into an actionable, stable carrier label."""
    if refname.startswith("refs/heads/"):
        return "branch " + refname[len("refs/heads/"):]
    if refname.startswith("refs/remotes/"):
        return "remote branch " + refname[len("refs/remotes/"):]
    if refname.startswith("refs/tags/"):
        return "tag " + refname[len("refs/tags/"):]
    return "ref " + refname


def range_carrier(refname, range_args):
    """Name a pushed ref, or retain a bounded range label for direct callers."""
    if refname:
        return ref_carrier(refname)
    spec = range_args[0] if range_args else "unknown"
    if ".." in spec:
        left, _, right = spec.partition("..")
        spec = "%s..%s" % (left[:12], right[:12])
    else:
        spec = spec[:12]
    return "pushed ref " + spec


def parse_tag_object(raw):
    """Return an annotated tag's target object and message/signature body."""
    headers, separator, body = raw.partition("\n\n")
    if not separator:
        raise RuntimeError("annotated tag object has no message separator")
    first = headers.splitlines()[0] if headers else ""
    prefix = "object "
    target = first[len(prefix):].strip() if first.startswith(prefix) else ""
    if not OBJECT_RX.match(target):
        raise RuntimeError("annotated tag object has invalid target header")
    return target, body


def tag_chain_candidates(rev, carrier, repo, run):
    """Return every annotated tag object from ``rev`` through recursive peel.

    Git permits an annotated tag to target another annotated tag.  Each tag
    object in that chain is published with the outer ref, so every intermediate
    message must be scanned.  Any read, parse, or type failure is a scanner
    error: a partially peeled chain must never be reported clean.
    """
    candidates = []
    seen = set()
    current = rev
    while True:
        result = run(["git", "cat-file", "-t", current], repo)
        if result.returncode != 0:
            raise RuntimeError("git cat-file -t rc=%d: %s" % (
                result.returncode, (result.stderr or "").strip()[:200]))
        obj_type = result.stdout.strip()
        if obj_type in ("blob", "commit", "tree"):
            break
        if obj_type != "tag":
            raise RuntimeError("git cat-file -t returned invalid object type")
        if current in seen:
            raise RuntimeError("annotated tag chain contains a cycle")
        seen.add(current)
        candidates.append((current, carrier))
        tag_result = run(["git", "cat-file", "tag", current], repo)
        if tag_result.returncode != 0:
            raise RuntimeError("git cat-file tag rc=%d: %s" % (
                tag_result.returncode,
                (tag_result.stderr or "").strip()[:200]))
        current, _body = parse_tag_object(tag_result.stdout)
    return candidates


def tag_candidates_for_tips(tip_revs, carriers, repo, run):
    """Return all tag objects recursively published by pushed/direct tips."""
    candidates = []
    for index, rev in enumerate(tip_revs):
        carrier = carriers[index] if index < len(carriers) else \
            "pushed ref " + rev[:12]
        candidates.extend(tag_chain_candidates(rev, carrier, repo, run))
    return list(dict.fromkeys(candidates))


def tag_candidates_for_all(repo, run):
    """Return every tag object recursively published by every live tag ref."""
    result = run(["git", "for-each-ref",
                  "--format=%(objectname)%09%(objecttype)%09%(refname)"], repo)
    if result.returncode != 0:
        raise RuntimeError("git for-each-ref rc=%d: %s" % (
            result.returncode, (result.stderr or "").strip()[:200]))
    roots = []
    for line in result.stdout.splitlines():
        sha, sep, rest = line.partition("\t")
        obj_type, sep2, refname = rest.partition("\t")
        if sep and sep2 and OBJECT_RX.match(sha) and obj_type == "tag" and refname:
            roots.append((sha, ref_carrier(refname)))
    candidates = []
    for sha, carrier in roots:
        candidates.extend(tag_chain_candidates(sha, carrier, repo, run))
    return list(dict.fromkeys(candidates))


def tag_message_matches(body, term, mode, allows):
    """Match one rule against tag-message lines with the normal allow policy."""
    normalized_term = normalize_for_match(term)
    word_rx = (re.compile(r"\b" + re.escape(normalized_term) + r"\b", re.IGNORECASE)
               if mode == "word" else None)
    for line in body.splitlines():
        normalized_line = normalize_for_match(line)
        matched = word_rx.search(normalized_line) if word_rx is not None else \
            normalized_term.lower() in normalized_line.lower()
        if matched and not any(a in normalized_line.lower() for a in allows):
            return True
    return False


def compile_content_matcher(rules):
    """Compile denylist rules for a single pass over decoded object text."""
    literal_trie = {}
    word_rxs = []
    for index, (_label, term, mode) in enumerate(rules):
        normalized_term = normalize_for_match(term)
        if mode == "word":
            word_rxs.append((index, re.compile(
                r"\b" + re.escape(normalized_term) + r"\b", re.IGNORECASE)))
            continue
        node = literal_trie
        for char in normalized_term.lower():
            node = node.setdefault(char, {})
        node.setdefault(None, []).append(index)
    return literal_trie, word_rxs


def content_match_indexes(text, matcher, allows):
    """Return rule indexes matching text, applying line-scoped allows."""
    literal_trie, word_rxs = matcher
    matched = set()
    for line in text.splitlines():
        normalized_line = normalize_for_match(line)
        lowered = normalized_line.lower()
        if any(allowed in lowered for allowed in allows):
            continue
        for start in range(len(lowered)):
            node = literal_trie
            offset = start
            while offset < len(lowered) and lowered[offset] in node:
                node = node[lowered[offset]]
                matched.update(node.get(None, ()))
                offset += 1
        for index, word_rx in word_rxs:
            if word_rx.search(normalized_line):
                matched.add(index)
    return matched


def scan_all_object_content(rules, allows, repo):
    """Scan every object in the local Git object database.

    This explicit release-audit mode covers full commit and annotated-tag
    objects (including identity and mergetag headers), trees and blobs, including
    unreachable objects. Findings are sorted after Git's intentionally unordered
    traversal so output remains deterministic. Oversized or malformed objects
    fail closed.
    """
    cmd = ["git", "cat-file", "--batch-all-objects", "--unordered", "--batch"]
    findings = []
    object_count = 0
    matcher = compile_content_matcher(rules)
    with tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(
            cmd, cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=stderr_file)
        timed_out = threading.Event()

        def stop_at_deadline():
            timed_out.set()
            try:
                proc.kill()
            except OSError:
                pass

        timer = threading.Timer(OBJECT_GIT_TIMEOUT_S, stop_at_deadline)
        timer.daemon = True
        timer.start()
        try:
            while True:
                header = proc.stdout.readline()
                if not header:
                    if timed_out.is_set():
                        raise RuntimeError(
                            "git cat-file exceeded %ds timeout" %
                            OBJECT_GIT_TIMEOUT_S)
                    break
                parts = header.rstrip(b"\n").split()
                if len(parts) != 3:
                    raise RuntimeError("malformed git cat-file object header")
                sha_raw, type_raw, size_raw = parts
                try:
                    sha = sha_raw.decode("ascii")
                    obj_type = type_raw.decode("ascii")
                    size = int(size_raw)
                except (UnicodeError, ValueError):
                    raise RuntimeError("invalid git cat-file object header")
                if (not OBJECT_RX.match(sha) or
                        obj_type not in ("blob", "commit", "tag", "tree") or
                        size < 0):
                    raise RuntimeError("invalid git cat-file object metadata")
                if size > OBJECT_MAX_BYTES:
                    raise RuntimeError(
                        "object %s exceeds %d-byte scan bound" %
                        (sha[:12], OBJECT_MAX_BYTES))
                body = bytearray()
                remaining = size
                while remaining:
                    chunk = proc.stdout.read(min(1024 * 1024, remaining))
                    if not chunk:
                        if timed_out.is_set():
                            raise RuntimeError(
                                "git cat-file exceeded %ds timeout" %
                                OBJECT_GIT_TIMEOUT_S)
                        raise RuntimeError("truncated git cat-file object body")
                    body.extend(chunk)
                    remaining -= len(chunk)
                if proc.stdout.read(1) != b"\n":
                    if timed_out.is_set():
                        raise RuntimeError(
                            "git cat-file exceeded %ds timeout" %
                            OBJECT_GIT_TIMEOUT_S)
                    raise RuntimeError("malformed git cat-file object terminator")
                object_count += 1
                text = bytes(body).decode("utf-8", "replace")
                # #292: `allow:` exceptions are LINE-SCOPED, and a tree has no
                # lines. Its body is a binary sequence of `<mode> <name>\0<20-byte
                # sha>` entries, so whether two entries land on the same decoded
                # "line" depends on whether those random sha bytes happen to contain
                # something `str.splitlines()` treats as a break — and that is a
                # wider set than \n: 0x0a 0x0b 0x0c 0x0d 0x1c 0x1d 0x1e. An allow
                # substring in one entry's name therefore suppressed the DENIED name
                # of a neighbouring entry, and which directories got audited flipped
                # whenever an unrelated sibling file changed.
                #
                # That made this mode a false-negative substitute for the manual
                # ritual it automates — the worst possible relationship between a
                # tool and the procedure it replaces. There is no defensible line
                # boundary to scope an exception to inside a tree, so trees get no
                # suppression at all. Textual objects keep the line-scoped behaviour
                # unchanged; the noise this costs on tree names is the price of an
                # audit that can be trusted.
                object_allows = () if obj_type == "tree" else allows
                for index in content_match_indexes(text, matcher, object_allows):
                    label, term, _mode = rules[index]
                    findings.append((sha, obj_type, label, term))
            returncode = proc.wait()
            stderr_file.seek(0)
            stderr_text = stderr_file.read(200).decode("utf-8", "replace")
            if timed_out.is_set():
                raise RuntimeError(
                    "git cat-file exceeded %ds timeout" %
                    OBJECT_GIT_TIMEOUT_S)
            if returncode != 0:
                raise RuntimeError(
                    "git cat-file rc=%d: %s" %
                    (returncode, stderr_text.strip()))
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise
        finally:
            timer.cancel()
            if proc.stdout is not None:
                proc.stdout.close()
    findings.sort(key=lambda row: (row[0], row[1], row[2]))
    return findings, object_count


def discover_unreachable(repo, run, limit):
    """Return bounded unreachable commit roots for explicit --all audits."""
    result = run(["git", "fsck", "--unreachable", "--no-reflogs",
                  "--no-progress"], repo)
    if result.returncode != 0:
        raise RuntimeError("git fsck rc=%d: %s" %
                           (result.returncode, (result.stderr or "").strip()[:200]))
    commits = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in ("unreachable", "dangling") and \
                parts[1] == "commit" and OBJECT_RX.match(parts[2]):
            if parts[2] not in commits:
                commits.append(parts[2])
            if len(commits) >= limit:
                break
    return commits


def read_reflog_entries(repo, run):
    """Read exact reflog commit/selectors once for carrier attribution."""
    result = run(["git", "reflog", "show", "--all",
                  "--format=%H%x09%gD"], repo)
    if result.returncode != 0:
        raise RuntimeError("git reflog rc=%d: %s" %
                           (result.returncode, (result.stderr or "").strip()[:200]))
    entries = []
    for line in result.stdout.splitlines():
        sha, sep, selector = line.partition("\t")
        if sep and OBJECT_RX.match(sha) and selector:
            entries.append((sha, selector))
    return entries


def history_carriers(sha, repo, run, reflog_entries, unreachable):
    """Name live refs, exact worktree reflogs, or unreachable-object state."""
    result = run(["git", "for-each-ref", "--format=%(refname)",
                  "--contains=%s" % sha], repo)
    if result.returncode != 0:
        raise RuntimeError("git for-each-ref rc=%d: %s" %
                           (result.returncode, (result.stderr or "").strip()[:200]))
    carriers = [ref_carrier(refname) for refname in result.stdout.splitlines()
                if refname]
    for entry_sha, selector in reflog_entries:
        if entry_sha != sha:
            continue
        match = re.match(r"worktrees/([^/]+)/HEAD@\{\d+\}$", selector)
        if match:
            carriers.append("worktree %s reflog" % match.group(1))
        elif not selector.startswith("refs/"):
            carriers.append("reflog " + selector.rsplit("@{", 1)[0])
    if sha in unreachable or not carriers:
        carriers.append("unreachable object")
    # Stable deduplication keeps findings bounded without hiding carrier kinds.
    return list(dict.fromkeys(carriers))[:12]


def commit_message_cmd(max_commits, refs_pull, range_args=None,
                       all_refs=False, extra_revs=None):
    """Build one bounded commit-message walk for a publish/audit scope."""
    cmd = ["git", "log"] + history_revs(range_args, all_refs, refs_pull, extra_revs)
    cmd.append("--format=%H%x00%B%x00")
    if not range_args:
        cmd += ["-n", str(max_commits + 1)]
    cmd.append("--")
    return cmd


def scan_commit_messages(rules, allows, history_runs, args, run,
                         extra_revs=None):
    """Scan commit messages once per bounded history scope."""
    matcher = compile_content_matcher(rules)
    findings = []
    for range_args, carrier in history_runs:
        result = run(commit_message_cmd(
            args.max_commits, args.refs_pull, range_args=range_args,
            all_refs=args.all, extra_revs=extra_revs), args.repo)
        if result.returncode != 0:
            raise RuntimeError("git log messages rc=%d: %s" % (
                result.returncode, (result.stderr or "").strip()[:200]))
        fields = result.stdout.split("\0")
        if fields and not fields[-1].strip():
            fields.pop()
        if len(fields) % 2:
            raise RuntimeError("git log returned malformed message records")
        if not range_args and len(fields) // 2 > args.max_commits:
            raise RuntimeError(
                "commit-message walk exceeds %d-commit scan bound" %
                args.max_commits)
        for offset in range(0, len(fields), 2):
            sha = fields[offset].strip()
            body = fields[offset + 1]
            if not OBJECT_RX.match(sha):
                raise RuntimeError("git log returned invalid commit id")
            for index in content_match_indexes(body, matcher, allows):
                findings.append((index, sha, carrier))
    return findings


def run_history(rule, history_runs, args, run, extra_revs=None):
    """Run one rule's unchanged pickaxe walks; return results in range order."""
    results = []
    for range_args, carrier in history_runs:
        result = run(history_cmd(
            rule, args.max_commits, args.refs_pull, range_args=range_args,
            all_refs=args.all, extra_revs=extra_revs), args.repo)
        results.append((result, carrier))
    return results


def main(argv=None, out=sys.stdout, err=sys.stderr, run=run_git):
    ap = argparse.ArgumentParser(
        prog="scrub-check.py",
        usage="%(prog)s [options]",
        description="Scan Git tip and history for confidential denylist terms (read-only, redacted by default).",
        epilog="""examples:
  scrub-check.py --repo .
  scrub-check.py --repo . --denylist ~/.config/m8shift/denylist.txt
  scrub-check.py --repo . --range abc123..def456""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository to scan (default: .)")
    ap.add_argument("--denylist", default=None,
                    help="explicit denylist path (beats M8SHIFT_DENYLIST)")
    ap.add_argument("--no-history", action="store_true",
                    help="scan only the tip (skip the pickaxe history pass)")
    ap.add_argument("--all", action="store_true",
                    help="explicit full-repository audit: all refs, reflogs, "
                         "and bounded unreachable commits")
    ap.add_argument("--objects", action="store_true",
                    help="explicit release audit of every local blob/tree and "
                         "commit/tag message body")
    ap.add_argument("--refs-pull", action="store_true",
                    help="also walk refs/pull/* history (slow; immutable on some "
                         "forges — a hit there needs delete/recreate, see RFC 052)")
    ap.add_argument("--range", action="append", dest="ranges", metavar="A..B|SHA",
                    help="scan only this pushed range (repeatable; hex A..B, or a "
                         "bare sha for a new branch). The "
                         "pre-push hook fast path; incompatible with --refs-pull")
    ap.add_argument("--remote", default=None, metavar="REMOTE",
                    help="target Git remote, carried as reporting metadata only. "
                         "It excludes nothing: #262 removed the tracking-ref "
                         "exclusion, because those refs are a local cache and "
                         "survive a destination being recreated")
    ap.add_argument("--ref", action="append", dest="range_refs", metavar="REF",
                    help="carrier ref corresponding to the preceding --range "
                         "(repeatable; used by the pre-push hook)")
    ap.add_argument("--endpoint-base", dest="endpoint_bases", action="append",
                    default=[], metavar="SHA",
                    help="a non-zero remote_sha from THIS pre-push batch, i.e. a "
                         "commit git's negotiation treats the destination as "
                         "holding. Repeatable. A finding reachable from one is NOT "
                         "TRANSMITTED by this push and is reported without "
                         "blocking; everything else blocks. This does not establish "
                         "that the destination possesses it — a shallow or "
                         "partially restored endpoint may not (#262)")
    ap.add_argument("--max-commits", type=int, default=HISTORY_MAX_COMMITS,
                    help="range-less AUDIT completeness window (default "
                         "%(default)s). Direct and --all refuse to answer rather "
                         "than report on a prefix when more commits are reachable; "
                         "explicit --range scopes are deliberately unbounded, since "
                         "a push must be judged whole")
    ap.add_argument("--verbose", action="store_true",
                    help="forensic local mode: show the matched terms (default "
                         "output is redacted so it can be pasted safely)")
    args = ap.parse_args(argv)

    try:
        remote, remote_err = validate_remote(args.remote, args.repo, run)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        print("scrub-check: ERROR validating --remote (%s)" %
              exc.__class__.__name__, file=err)
        return 2
    if remote_err:
        print("scrub-check: ERROR %s" % remote_err, file=err)
        return 2
    endpoint_bases, dropped_bases = usable_endpoint_bases(
        args.endpoint_bases, args.repo, run)
    for value in dropped_bases:
        print("scrub-check: NOTE endpoint base %r is not resolvable here; it proves "
              "nothing and is ignored (#262)" % (value or "")[:64], file=err)
    specs, range_err = parse_ranges(args.ranges)
    if range_err:
        print("scrub-check: ERROR %s" % range_err, file=err)
        return 2
    if specs and args.all:
        print("scrub-check: ERROR --range and --all are mutually exclusive",
              file=err)
        return 2
    if args.objects and (
            specs or args.all or args.refs_pull or args.no_history or
            args.remote or args.range_refs):
        print("scrub-check: ERROR --objects is a standalone scan mode",
              file=err)
        return 2
    if specs and args.refs_pull:
        print("scrub-check: ERROR --range and --refs-pull are mutually exclusive",
              file=err)
        return 2
    if args.refs_pull and not args.all:
        print("scrub-check: ERROR --refs-pull requires explicit --all", file=err)
        return 2
    range_refs = args.range_refs or []
    if range_refs and len(range_refs) != len(specs):
        print("scrub-check: ERROR each --ref requires one corresponding --range",
              file=err)
        return 2
    validated_range_refs = []
    if range_refs:
        for refname in range_refs:
            try:
                checked = run(["git", "check-ref-format", refname], args.repo)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
                checked = None
            if checked is None or checked.returncode != 0:
                # --ref is attribution metadata, never scan authority.  A
                # malformed label must not turn a real range scan into a
                # blocking scanner error when the range itself remains valid.
                print("scrub-check: WARNING invalid --ref label ignored; "
                      "scanning continues with the derived range carrier",
                      file=err)
                validated_range_refs.append(None)
            else:
                validated_range_refs.append(refname)
    # Range mode: tip-scan each distinct pushed tip, history-scan each range.
    # Default direct mode is HEAD-only; --all is the explicit repository audit.
    tip_revs = []
    tip_carriers = []
    for index, (rev, range_args) in enumerate(specs):
        if rev not in tip_revs:
            refname = validated_range_refs[index] if validated_range_refs else None
            tip_revs.append(rev)
            tip_carriers.append(range_carrier(refname, range_args))
    if not tip_revs:
        tip_revs = ["HEAD"]
        tip_carriers = ["ref HEAD"]
    history_runs = []
    for index, (_rev, range_args) in enumerate(specs):
        refname = validated_range_refs[index] if validated_range_refs else None
        history_runs.append((range_args, range_carrier(refname, range_args)))
    if not history_runs:
        history_runs = [(None, None if args.all else "ref HEAD")]

    try:
        rules, allows, note = load_denylist(args.denylist)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print("scrub-check: ERROR loading denylist (%s)" % exc, file=err)
        return 2
    if note:
        print("scrub-check: %s" % note, file=out)
    if not rules:
        return 0

    if args.objects:
        try:
            object_hits, object_count = scan_all_object_content(
                rules, allows, args.repo)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
                RuntimeError) as exc:
            print("scrub-check: ERROR scanning Git objects (%s)" % exc,
                  file=err)
            return 2
        for sha, obj_type, label, term in object_hits:
            shown = "%s term=%r" % (label, term) if args.verbose else label
            print("OBJECT hit: %s %s [%s]" %
                  (obj_type, sha[:12], shown), file=out)
        if object_hits:
            print("scrub-check: %d object-content hit(s); remove/rewrite every "
                  "matching object before publication." % len(object_hits),
                  file=out)
            return 1
        print("scrub-check: clean (%d term(s), %d Git object(s) checked)." %
              (len(rules), object_count), file=out)
        return 0

    # Tag peeling defines the publish object graph.  Prepare it before any
    # supplemental content walk so a malformed/nested tag reports the tagged
    # boundary failure instead of being masked by a later tree-scan error.
    try:
        tag_candidates = tag_candidates_for_all(args.repo, run) if args.all else \
            tag_candidates_for_tips(tip_revs, tip_carriers, args.repo, run)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
            RuntimeError) as exc:
        print("scrub-check: ERROR preparing annotated tags (%s)" % exc,
              file=err)
        return 2

    tag_bodies = {}
    try:
        for tag_sha, _carrier in tag_candidates:
            if tag_sha in tag_bodies:
                continue
            result = run(["git", "cat-file", "tag", tag_sha], args.repo)
            if result.returncode != 0:
                raise RuntimeError("git cat-file tag rc=%d: %s" % (
                    result.returncode, (result.stderr or "").strip()[:200]))
            _target, tag_bodies[tag_sha] = parse_tag_object(result.stdout)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
            RuntimeError) as exc:
        print("scrub-check: ERROR reading annotated tag (%s)" % exc, file=err)
        return 2

    unreachable = []
    reflog_entries = []
    if args.all and not args.no_history:
        try:
            unreachable = discover_unreachable(args.repo, run, args.max_commits)
            reflog_entries = read_reflog_entries(args.repo, run)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
                RuntimeError) as exc:
            print("scrub-check: ERROR preparing --all carriers (%s)" % exc,
                  file=err)
            return 2

    # Commit-message completeness is an explicit audit bound and therefore
    # precedes the other history surfaces.  Preserve that diagnostic priority:
    # a bounded audit must say which authority window was exhausted.
    message_hits = {}
    if not args.no_history:
        try:
            for rule_index, sha, carrier in scan_commit_messages(
                    rules, allows, history_runs, args, run, unreachable):
                message_hits.setdefault(rule_index, []).append((sha, carrier))
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
                RuntimeError) as exc:
            print("scrub-check: ERROR scanning commit messages (%s)" % exc,
                  file=err)
            return 2

    # Enumerate the publication path surface before supplemental content reads.
    # This is a preflight only; findings retain their established output position
    # below.  An incomplete tree/diff/log walk is the authority failure for that
    # publish scope and must not be masked by a later normalized-content command.
    path_scope_records = []
    path_scopes = [(tip, spec_args) for tip, spec_args in specs] or [("HEAD", None)]
    for scope_tip, scope_args in path_scopes:
        scope_revs = history_revs(scope_args, args.all, args.refs_pull, unreachable)
        audit_bound = None if scope_args else args.max_commits
        try:
            records = scope_path_records(
                scope_tip, scope_args, args.repo, run,
                history=not args.no_history,
                history_revs_args=scope_revs,
                max_commits=audit_bound)
        except (PathEnumerationError, OSError, subprocess.SubprocessError,
                UnicodeError, ValueError) as exc:
            print("scrub-check: ERROR path enumeration incomplete (%s)"
                  % (exc if isinstance(exc, PathEnumerationError)
                     else exc.__class__.__name__), file=err)
            return 2
        path_scope_records.append((scope_tip, scope_args, records))

    try:
        normalized_tip_hits = scan_normalized_tip(
            rules, allows, tip_revs, args.repo, run)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
            RuntimeError) as exc:
        print("scrub-check: ERROR scanning normalized tip content (%s)" % exc,
              file=err)
        return 2

    normalized_history_hits = {}
    if not args.no_history:
        try:
            normalized_history_hits = scan_normalized_history(
                rules, history_runs, args, unreachable, run)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
                RuntimeError) as exc:
            print("scrub-check: ERROR scanning normalized history (%s)" % exc,
                  file=err)
            return 2

    # Start the independent pickaxe walks early, but consume futures strictly in
    # denylist order below.  This changes scheduling only: argv, interpretation,
    # and byte ordering remain identical to the sequential implementation.
    history_futures = {}
    history_pool = None
    if not args.no_history:
        workers = min(len(rules), max(1, min(SCRUB_MAX_WORKERS,
                                             os.cpu_count() or 1)))
        history_pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        for index, rule in enumerate(rules):
            history_futures[index] = history_pool.submit(
                run_history, rule, history_runs, args, run, unreachable)

    hits = 0
    tip_hits = 0
    history_kinds = []
    pre_existing_hits = 0
    blocking_hits = 0
    carrier_cache = {}
    for rule_index, rule in enumerate(rules):
        label, term, mode = rule
        shown = "%s term=%r" % (label, term) if args.verbose else label
        # ANNOTATED TAG — neither git grep (commit tree) nor pickaxe history
        # reads the tag object's message. Scan the body directly and name the
        # pushed/live carrier without ever echoing matched content by default.
        for tag_sha, carrier in tag_candidates:
            if not tag_message_matches(tag_bodies[tag_sha], term, mode, allows):
                continue
            hits += 1
            carrier_text = carrier if args.verbose else redact(carrier, rules)
            print("TAG hit: %s object %s [%s]" %
                  (carrier_text, tag_sha[:12], shown), file=out)
        for sha, scoped_carrier in message_hits.get(rule_index, ()):
            hits += 1
            try:
                if scoped_carrier is not None:
                    carriers = [scoped_carrier]
                else:
                    if sha not in carrier_cache:
                        carrier_cache[sha] = history_carriers(
                            sha, args.repo, run, reflog_entries, unreachable)
                    carriers = carrier_cache[sha]
            except (OSError, subprocess.SubprocessError, UnicodeError,
                    ValueError, RuntimeError) as exc:
                if history_pool is not None:
                    history_pool.shutdown(wait=False)
                print("scrub-check: ERROR resolving message carrier (%s)" % exc,
                      file=err)
                return 2
            history_kinds.extend(carriers)
            carrier_text = ", ".join(carriers)
            if not args.verbose:
                carrier_text = redact(carrier_text, rules)
            print("MESSAGE hit: commit %s via %s [%s]" %
                  (sha[:12], carrier_text, shown), file=out)

        # TIP — raw-object normalization supplement first, then the unchanged
        # git-grep fast path.  Locator dedupe keeps the external format stable.
        seen_tip_locs = set()
        for loc in normalized_tip_hits.get(rule_index, ()):
            if loc in seen_tip_locs:
                continue
            seen_tip_locs.add(loc)
            hits += 1
            tip_hits += 1
            print("TIP hit: %s [%s]" %
                  (loc if args.verbose else redact(loc, rules), shown), file=out)

        # revision(s) before `--`; rc 0 = match, 1 = clean, >1 = error.
        for tip_rev in tip_revs:
            try:
                r = run(tip_cmd(rule, tip_rev), args.repo)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
                print("scrub-check: ERROR running git grep (%s)" % exc.__class__.__name__,
                      file=err)
                return 2
            if r.returncode not in (0, 1):
                print("scrub-check: ERROR git grep rc=%d: %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]), file=err)
                return 2
            if r.returncode == 0:
                normalized_term = normalize_for_match(term)
                word_rx = (re.compile(r"\b" + re.escape(normalized_term) + r"\b",
                                      re.IGNORECASE)
                           if mode == "word" else None)
                for line in r.stdout.splitlines():
                    # git grep -n output: rev:path:lineno:content — drop the content
                    # (it embeds the confidential term) and keep the locator only.
                    parts = line.split(":", 3)
                    loc = ":".join(parts[:3]) if len(parts) >= 3 else line[:120]
                    content = parts[3] if len(parts) >= 4 else line
                    normalized_content = normalize_for_match(content)
                    matched = word_rx.search(normalized_content) if word_rx is not None \
                        else normalized_term.lower() in normalized_content.lower()
                    if not matched:
                        continue          # literal over-match without a word boundary
                    # allow: is matched on the CONTENT only — matching the full grep
                    # line let an allow substring in the PATH suppress a real content
                    # hit (review MEDIUM 3).
                    if any(a in normalized_content.lower() for a in allows):
                        continue
                    if loc in seen_tip_locs:
                        continue
                    seen_tip_locs.add(loc)
                    hits += 1
                    tip_hits += 1
                    # The locator itself can carry a denied term (a term-named dir or
                    # file) — redact it in default mode; --verbose keeps it raw.
                    print("TIP hit: %s [%s]"
                          % (loc if args.verbose else redact(loc, rules), shown),
                          file=out)
        # HISTORY — pickaxe across all refs (or each pushed range); any commit
        # listed = the term was added or removed there (an allow-substring cannot
        # be evaluated without echoing blob content, so history hits are always
        # reported).
        if args.no_history:
            continue
        try:
            history_results = history_futures[rule_index].result()
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError,
                RuntimeError) as exc:
            if history_pool is not None:
                history_pool.shutdown(wait=False)
            print("scrub-check: ERROR running git log (%s)" % exc.__class__.__name__,
                  file=err)
            return 2
        history_candidates = list(normalized_history_hits.get(rule_index, ()))
        for r, scoped_carrier in history_results:
            if r.returncode != 0:
                if history_pool is not None:
                    history_pool.shutdown(wait=False)
                print("scrub-check: ERROR git log rc=%d: %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]), file=err)
                return 2
            history_candidates.extend((sha, scoped_carrier)
                                      for sha in r.stdout.split())
        seen_history = set()
        for sha, scoped_carrier in history_candidates:
            history_key = (sha, scoped_carrier)
            if history_key in seen_history:
                continue
            seen_history.add(history_key)
            hits += 1
            try:
                if scoped_carrier is not None:
                    carriers = [scoped_carrier]
                else:
                    if sha not in carrier_cache:
                        carrier_cache[sha] = history_carriers(
                            sha, args.repo, run, reflog_entries,
                            set(unreachable))
                    carriers = carrier_cache[sha]
            except (OSError, subprocess.SubprocessError, UnicodeError,
                    ValueError, RuntimeError) as exc:
                if history_pool is not None:
                    history_pool.shutdown(wait=False)
                print("scrub-check: ERROR resolving history carrier (%s)" % exc,
                      file=err)
                return 2
            history_kinds.extend(carriers)
            carrier_text = ", ".join(carriers)
            if not args.verbose:
                carrier_text = redact(carrier_text, rules)
            # #262: only this push's own negotiation can prove the destination
            # already has the commit. `carriers` names LOCAL refs and is
            # diagnostic attribution, never a downgrade.
            proven = not_transmitted_by_this_push(sha, endpoint_bases, args.repo, run)
            if proven:
                pre_existing_hits += 1
            else:
                blocking_hits += 1
            print("HISTORY hit: commit %s via %s [%s]%s"
                  % (sha[:12], carrier_text, shown,
                     "  (not transmitted by this push)" if proven
                     else ""), file=out)

    if history_pool is not None:
        history_pool.shutdown()

    # #291 — PATH scan, once per pushed scope and NOT once per denylist term.
    # Every other scanner here reads blob content or a commit message, so a denied
    # identifier carried only by a filename or a directory published with rc 0 under
    # enforcement. The cost contract is deliberate: two git walks per scope, both
    # independent of how many terms the operator denies. #297: the tree/endpoint walk
    # and explicit publication history stay COMPLETE; only range-less audit history
    # carries the `--max-commits` window, and it refuses rather than classifying an
    # incomplete read. `--objects` stays the
    # standalone audit rather than something the hook starts paying for.
    # No word_rx post-filter here, unlike the TIP scan. There, `git grep` does the
    # matching and the boundary has to be re-checked in-process; here the matcher IS
    # compile_content_matcher(), which compiles a word: rule as `\b...\b` and never
    # puts it in the literal trie, so a boundary-less match cannot be produced in the
    # first place. I had written that filter anyway: it could not change any outcome,
    # survived being mutated to `if False`, and read exactly like the guarantee it
    # was not providing.
    # #295: the range-less callers are covered too. They scanned NO path at all, so
    # `scrub-check.py --all` — the audit invocation named in hooks/pre-push and
    # SECURITY.md — printed clean on a denied directory name, and so did direct mode.
    # Measured on one clean-body fixture: rc 1 under `--range`, rc 0 under both of
    # the others. Coverage that depends on which caller invoked the scanner is not
    # coverage. The revision universe comes from history_revs(), the SAME selector
    # the content pickaxe and the message walk use, so the audit cannot answer one
    # question for names and another for contents.
    path_matcher = compile_content_matcher(rules)
    seen_paths = set()
    for scope_tip, scope_args, records in path_scope_records:
        # A publish scope has two KNOWN endpoints. A bare-SHA new-ref push does not:
        # it publishes a whole history with no base, so it may not conclude that an
        # all-deletions path is a cleanup — see path_records_block().
        publish_scope = is_publish_scope(scope_args)
        statuses = {}
        for _commit, status, path in records:
            statuses.setdefault(path, []).append(status)
        blocking_paths, removed_paths = path_records_block(
            statuses, publish_scope=publish_scope)
        for commit, _status, path in records:
            for index in path_match_indexes(path, path_matcher):
                key = (commit, path, index)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                label, term, _mode = rules[index]
                shown = label if not args.verbose else "%s:%s" % (label, term)
                # The path IS the finding, so the default rendering must not echo it.
                where = redact(path, rules) if not args.verbose else path
                carrier = ("commit %s" % commit[:12]) if commit else "pushed tree"
                hits += 1
                # A path this push only REMOVES is not one it publishes. Reported so
                # the operator still sees it, classified so the cleanup can be pushed.
                removed_only = path in removed_paths and path not in blocking_paths
                proven = removed_only or (
                    commit is not None and endpoint_bases and
                    not_transmitted_by_this_push(commit, endpoint_bases,
                                                 args.repo, run))
                if proven:
                    pre_existing_hits += 1
                else:
                    blocking_hits += 1
                note = ("  (removed by this push)" if removed_only else
                        "  (not transmitted by this push)" if proven else "")
                print("PATH hit: %s via %s [%s]%s"
                      % (where, carrier, shown, note), file=out)

    # #262 tri-state. Local reachability is NOT proof of publication — that was the
    # defect, and proposing it again was rejected in review. The only endpoint-
    # authoritative evidence a client-side hook has is the non-zero remote_sha git
    # supplies for refs in THIS batch: git obtained it from the real destination.
    #   introduced          -> in a resolvable A..B update range: blocks
    #   not transmitted    -> reachable from an endpoint base: reported, no block
    #                         (this does NOT assert the destination holds it)
    #   unknown             -> a new ref has no authoritative baseline: blocks
    # The boundary this exposes is real and is not papered over: a client-side hook
    # never receives an inventory of the destination's other refs, so it cannot both
    # avoid the post-recreation false clean and avoid blocking every clean new branch.
    # Where both are required the decision belongs server-side.
    # The downgrade requires EVERY finding to be proven, not merely some of them.
    # An earlier revision incremented these counters only in the history loop, so tag
    # and commit-message findings — which carry no endpoint proof at all — were
    # invisible to this condition. One proven history hit then silenced an unbounded
    # number of unproven ones, reached by the ordinary release command
    # `git push --follow-tags origin main`: the branch ref earns a base, the tag ref
    # rides on it. Measured: the same tag pushed alone was blocked, batched it was
    # published, and the summary under-reported the count as well.
    # `pre_existing_hits == hits` is the fail-closed form — anything not classified
    # here counts against the downgrade, by construction.
    if hits and pre_existing_hits == hits and not blocking_hits and tip_hits == 0:
        print("scrub-check: %d hit(s), none of them transmitted by this push "
              "according to git's own negotiation — reported, not blocking. This "
              "does NOT assert the destination already holds them."
              % hits, file=out)
        return 0

    if hits:
        if (tip_hits == 0 and history_kinds and
                all(carrier == "unreachable object" for carrier in history_kinds)):
            print("scrub-check: %d unreachable-only history hit(s); no live ref "
                  "carries them and a range-scoped pre-push will not block on "
                  "them. Local reap sequence: git worktree prune; git reflog "
                  "expire --expire=now --all; git gc --prune=now."
                  % hits, file=out)
            return 1
        print("scrub-check: %d hit(s) — the identifier(s) above are present on "
              "tip and/or the named carrier history; abstract/remove on tip "
              "and rewrite only the carrier refs named above. Published refs "
              "may still require the RFC 052 filter-repo procedure."
              % hits, file=out)
        return 1
    scope = ("%d pushed range(s)" % len(specs)) if specs else \
            ("tip%s" % ("" if args.no_history else
                         " + full repository audit" if args.all else
                         " + HEAD history"))
    print("scrub-check: clean (%d term(s) checked, %s)."
          % (len(rules), scope), file=out)
    return 0


def entrypoint(argv=None, out=sys.stdout, err=sys.stderr, run=run_git):
    """Map every otherwise-uncaught scanner exception to fail-closed rc 2."""
    try:
        return main(argv, out=out, err=err, run=run)
    except Exception as exc:
        print("scrub-check: ERROR unhandled scanner failure (%s)" %
              exc.__class__.__name__, file=err)
        return 2


if __name__ == "__main__":
    sys.exit(entrypoint())
