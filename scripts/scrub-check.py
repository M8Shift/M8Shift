#!/usr/bin/env python3
"""RFC 052 E1 — confidential denylist scrub-check over git TIP and HISTORY.

Scans the repository for operator-denylisted identifiers (foreign project names,
internal program names — the identities the path lint cannot know) BEFORE they
leave the machine. Read-only; stdlib-only; no network.

Denylist (never committed — it IS the confidential data):
  $M8SHIFT_DENYLIST if set, else ~/.config/m8shift/denylist.txt, else no-op.
  Format: one entry per line; `# comment` / blank ignored;
  `allow:<substring>` = exception; `word:<term>` = word-boundary; else literal.
  Matching is case-insensitive.

Scans (raw `git` by argv — NEVER routed through a lossy optimizer such as rtk;
a "clean" through a lossy path is unverified by definition):
  TIP      git grep -I -i -n [-F|-E] -e <pattern> HEAD --
  HISTORY  git log <reachable scope> --pickaxe-regex -i -S<escaped> --
  Revisions always precede `--` (bad ordering silently scans nothing — the
  false-negative that let a real leak through; see RFC 052).

Range mode (`--range`, repeatable — the pre-push hook path): scan only what a
push is about to publish. `--range A..B` scans the B tree plus A..B history; a
bare `--range SHA` (new ref) scans that tree plus `SHA --not --remotes`. The hook
also supplies the corresponding `--ref`, so every history finding names its
carrier branch/tag. Local side branches, worktree reflogs, and unreachable
objects are outside this publish scope and can never block a clean pushed range.

The default direct scan is HEAD tip + HEAD history. `--all` is the explicit
repository-audit mode: it adds every ref, reflog, and bounded unreachable commit,
and labels each history hit with carrier refs, worktree reflogs, or an unreachable
object. Values passed as ranges remain hex-only rev specs.

Output is REDACTED by default: file:line / commit hash + a hashed term label,
never the term or the matched content. `--verbose` shows terms locally only.

Exit codes: 0 clean (or empty denylist = no-op), 1 at least one hit, 2 error
(not a repo, git missing/failed). The shipped hooks treat 1 as advisory unless
M8SHIFT_SCRUB_ENFORCE=1, and treat 2 as fail-open (printed, never blocking).
"""

import argparse
import concurrent.futures
import hashlib
import os
import re
import subprocess
import sys

DENYLIST_ENV = "M8SHIFT_DENYLIST"
DENYLIST_DEFAULT = os.path.join("~", ".config", "m8shift", "denylist.txt")
DENYLIST_MAX_BYTES = 64 * 1024
DENYLIST_MAX_TERMS = 256
DENYLIST_MIN_LEN = 3
GIT_TIMEOUT_S = 60
HISTORY_MAX_COMMITS = 5000
SCRUB_MAX_WORKERS = 8
# Hex-only rev specs: `A..B` or a bare SHA. Rejecting anything else keeps a
# hostile/typoed value from ever reaching the git argv as an option.
RANGE_RX = re.compile(r"^[0-9a-fA-F]{4,64}(\.\.[0-9a-fA-F]{4,64})?$")
OBJECT_RX = re.compile(r"^[0-9a-fA-F]{40,64}$")


def label_of(term):
    """Confidential display label — a short hash, never the term itself."""
    return "denylist:" + hashlib.sha256(term.strip().lower().encode("utf-8")).hexdigest()[:10]


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
            allows.append(rest.strip().lower())
            continue
        if sep and mode == "word" and rest.strip():
            term = rest.strip()
            if len(term) < DENYLIST_MIN_LEN:
                skipped += 1
                continue
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
            return [], [], "denylist missing at the explicit path — nothing scanned"
        return [], [], "no denylist configured — no-op"
    try:
        with open(path, "rb") as fh:
            raw = fh.read(DENYLIST_MAX_BYTES)
    except OSError as exc:
        return [], [], "denylist unreadable (%s) — nothing scanned" % exc.__class__.__name__
    rules, allows, skipped = parse_denylist_text(raw.decode("utf-8", "replace"))
    note = ""
    if skipped:
        note = "%d term(s) shorter than %d chars ignored" % (skipped, DENYLIST_MIN_LEN)
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


def history_cmd(rule, max_commits, refs_pull, range_args=None, all_refs=False,
                extra_revs=None):
    """git log pickaxe argv for one rule — revision specs BEFORE `--`.
    `--pickaxe-regex -i` + re.escape gives a portable case-insensitive literal
    (no \\b: word-boundary is a GNU extension the system regex may lack; the
    slight over-match on history is the honest, portable choice).
    range_args (range mode) replaces the audit walk with pushed revs only (e.g.
    ["A..B"] or ["SHA", "--not", "--remotes"]).  Direct mode walks HEAD;
    explicit all_refs adds refs, reflogs, and bounded unreachable roots."""
    label, term, mode = rule
    if range_args:
        cmd = ["git", "log"] + list(range_args)
    elif all_refs:
        cmd = ["git", "log", "--all", "--reflog"]
        cmd.extend(extra_revs or [])
        if refs_pull:
            cmd.append("--glob=refs/pull")
    else:
        cmd = ["git", "log", "HEAD"]
    cmd += ["--pickaxe-regex", "-i", "-S", re.escape(term),
            "--format=%H", "-n", str(max_commits), "--"]
    return cmd


def parse_ranges(values):
    """-> (specs, error). specs = [(tip_rev, range_args)] per --range value:
    `A..B` scans tree(B) + commits A..B; a bare SHA (new branch — no remote
    base) scans tree(SHA) + `SHA --not --remotes` (commits not already on any
    remote-tracking ref; with no remotes at all this over-scans, never
    under-scans). Invalid shapes are a hard error (rc 2 — hooks fail open)."""
    specs = []
    for value in values or []:
        value = value.strip()
        if not RANGE_RX.match(value):
            return None, "invalid --range %r (expected hex A..B or a bare sha)" % value
        if ".." in value:
            base, _, tip = value.partition("..")
            specs.append((tip, [value]))
        else:
            specs.append((value, [value, "--not", "--remotes"]))
    return specs, None


def redact(text, rules):
    """Redact every denied-term occurrence in a display string (review BLOCKER:
    a denied term inside a file PATH re-leaked through the default locator)."""
    for _label, term, mode in rules:
        text = re.sub(re.escape(term), "[redacted]", text, flags=re.IGNORECASE)
    return text


def run_git(cmd, repo):
    """Raw argv execution (shell=False), bounded. -> CompletedProcess.
    Explicit utf-8 + errors=replace: with bare text=True, invalid UTF-8 in a
    tracked file made the decode raise UnicodeDecodeError -> traceback -> rc 1,
    which the hooks then misread as a scrub HIT (review MEDIUM 2)."""
    return subprocess.run(cmd, cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace",
                          timeout=GIT_TIMEOUT_S)


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
    ap.add_argument("--refs-pull", action="store_true",
                    help="also walk refs/pull/* history (slow; immutable on some "
                         "forges — a hit there needs delete/recreate, see RFC 052)")
    ap.add_argument("--range", action="append", dest="ranges", metavar="A..B|SHA",
                    help="scan only this pushed range (repeatable; hex A..B, or a "
                         "bare sha for a new branch = sha --not --remotes). The "
                         "pre-push hook fast path; incompatible with --refs-pull")
    ap.add_argument("--ref", action="append", dest="range_refs", metavar="REF",
                    help="carrier ref corresponding to the preceding --range "
                         "(repeatable; used by the pre-push hook)")
    ap.add_argument("--max-commits", type=int, default=HISTORY_MAX_COMMITS,
                    help="history bound per term (default %(default)s)")
    ap.add_argument("--verbose", action="store_true",
                    help="forensic local mode: show the matched terms (default "
                         "output is redacted so it can be pasted safely)")
    args = ap.parse_args(argv)

    specs, range_err = parse_ranges(args.ranges)
    if range_err:
        print("scrub-check: ERROR %s" % range_err, file=err)
        return 2
    if specs and args.all:
        print("scrub-check: ERROR --range and --all are mutually exclusive",
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
    if range_refs:
        for refname in range_refs:
            try:
                checked = run(["git", "check-ref-format", refname], args.repo)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
                checked = None
            if checked is None or checked.returncode != 0:
                print("scrub-check: ERROR invalid --ref %r" % refname, file=err)
                return 2
    # Range mode: tip-scan each distinct pushed tip, history-scan each range.
    # Default direct mode is HEAD-only; --all is the explicit repository audit.
    tip_revs = []
    for rev, _ra in specs:
        if rev not in tip_revs:
            tip_revs.append(rev)
    if not tip_revs:
        tip_revs = ["HEAD"]
    history_runs = []
    for index, (_rev, range_args) in enumerate(specs):
        refname = range_refs[index] if range_refs else None
        history_runs.append((range_args, range_carrier(refname, range_args)))
    if not history_runs:
        history_runs = [(None, None if args.all else "ref HEAD")]

    rules, allows, note = load_denylist(args.denylist)
    if note:
        print("scrub-check: %s" % note, file=out)
    if not rules:
        return 0

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
    carrier_cache = {}
    for rule_index, rule in enumerate(rules):
        label, term, mode = rule
        shown = "%s term=%r" % (label, term) if args.verbose else label
        # TIP — revision(s) before `--`; rc 0 = match, 1 = clean, >1 = error.
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
                word_rx = (re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
                           if mode == "word" else None)
                for line in r.stdout.splitlines():
                    # git grep -n output: rev:path:lineno:content — drop the content
                    # (it embeds the confidential term) and keep the locator only.
                    parts = line.split(":", 3)
                    loc = ":".join(parts[:3]) if len(parts) >= 3 else line[:120]
                    content = parts[3] if len(parts) >= 4 else line
                    if word_rx is not None and not word_rx.search(content):
                        continue          # literal over-match without a word boundary
                    # allow: is matched on the CONTENT only — matching the full grep
                    # line let an allow substring in the PATH suppress a real content
                    # hit (review MEDIUM 3).
                    if any(a in content.lower() for a in allows):
                        continue
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
        for r, scoped_carrier in history_results:
            if r.returncode != 0:
                if history_pool is not None:
                    history_pool.shutdown(wait=False)
                print("scrub-check: ERROR git log rc=%d: %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]), file=err)
                return 2
            for sha in r.stdout.split():
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
                print("HISTORY hit: commit %s via %s [%s]"
                      % (sha[:12], carrier_text, shown), file=out)

    if history_pool is not None:
        history_pool.shutdown()

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


if __name__ == "__main__":
    sys.exit(main())
