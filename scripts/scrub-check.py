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
  HISTORY  git log --all [--glob=refs/pull] --pickaxe-regex -i -S<escaped> --
  Revisions always precede `--` (bad ordering silently scans nothing — the
  false-negative that let a real leak through; see RFC 052).

Output is REDACTED by default: file:line / commit hash + a hashed term label,
never the term or the matched content. `--verbose` shows terms locally only.

Exit codes: 0 clean (or empty denylist = no-op), 1 at least one hit, 2 error
(not a repo, git missing/failed). The shipped hooks treat 1 as advisory unless
M8SHIFT_SCRUB_ENFORCE=1, and treat 2 as fail-open (printed, never blocking).
"""

import argparse
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


def tip_cmd(rule):
    """git grep argv for one rule — HEAD (the revision) BEFORE `--`.

    Always a case-insensitive LITERAL (-F): `\\b` in `git grep -E` is a GNU
    extension the BSD/macOS regex lacks, so a word-boundary pattern would scan
    CLEAN there — a silent false negative (caught empirically on macOS). Word
    semantics are applied portably in-process on the matched lines instead."""
    label, term, mode = rule
    return ["git", "grep", "-I", "-i", "-n", "-F", "-e", term, "HEAD", "--"]


def history_cmd(rule, max_commits, refs_pull):
    """git log pickaxe argv for one rule — revision specs BEFORE `--`.
    `--pickaxe-regex -i` + re.escape gives a portable case-insensitive literal
    (no \\b: word-boundary is a GNU extension the system regex may lack; the
    slight over-match on history is the honest, portable choice)."""
    label, term, mode = rule
    cmd = ["git", "log", "--all"]
    if refs_pull:
        cmd.append("--glob=refs/pull")
    cmd += ["--pickaxe-regex", "-i", "-S", re.escape(term),
            "--format=%H", "-n", str(max_commits), "--"]
    return cmd


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


def main(argv=None, out=sys.stdout, err=sys.stderr, run=run_git):
    ap = argparse.ArgumentParser(
        prog="scrub-check.py",
        description="RFC 052 E1: denylist scrub over git tip + history "
                    "(read-only, redacted by default).")
    ap.add_argument("--repo", default=".", help="repository to scan (default: .)")
    ap.add_argument("--denylist", default=None,
                    help="explicit denylist path (beats M8SHIFT_DENYLIST)")
    ap.add_argument("--no-history", action="store_true",
                    help="scan only the tip (skip the pickaxe history pass)")
    ap.add_argument("--refs-pull", action="store_true",
                    help="also walk refs/pull/* history (slow; immutable on some "
                         "forges — a hit there needs delete/recreate, see RFC 052)")
    ap.add_argument("--max-commits", type=int, default=HISTORY_MAX_COMMITS,
                    help="history bound per term (default %(default)s)")
    ap.add_argument("--verbose", action="store_true",
                    help="forensic local mode: show the matched terms (default "
                         "output is redacted so it can be pasted safely)")
    args = ap.parse_args(argv)

    rules, allows, note = load_denylist(args.denylist)
    if note:
        print("scrub-check: %s" % note, file=out)
    if not rules:
        return 0

    hits = 0
    for rule in rules:
        label, term, mode = rule
        shown = "%s term=%r" % (label, term) if args.verbose else label
        # TIP — revision (HEAD) before `--`; rc 0 = match, 1 = clean, >1 = error.
        try:
            r = run(tip_cmd(rule), args.repo)
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
                # git grep -n output: HEAD:path:lineno:content — drop the content
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
                # The locator itself can carry a denied term (a term-named dir or
                # file) — redact it in default mode; --verbose keeps it raw.
                print("TIP hit: %s [%s]"
                      % (loc if args.verbose else redact(loc, rules), shown),
                      file=out)
        # HISTORY — pickaxe across all refs; any commit listed = the term was
        # added or removed there (an allow-substring cannot be evaluated without
        # echoing blob content, so history hits are always reported).
        if args.no_history:
            continue
        try:
            r = run(history_cmd(rule, args.max_commits, args.refs_pull), args.repo)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
            print("scrub-check: ERROR running git log (%s)" % exc.__class__.__name__,
                  file=err)
            return 2
        if r.returncode != 0:
            print("scrub-check: ERROR git log rc=%d: %s"
                  % (r.returncode, (r.stderr or "").strip()[:200]), file=err)
            return 2
        for sha in r.stdout.split():
            hits += 1
            print("HISTORY hit: commit %s [%s]" % (sha[:12], shown), file=out)

    if hits:
        print("scrub-check: %d hit(s) — the identifier(s) above are present on "
              "tip and/or in history; abstract/remove on tip, and see RFC 052 "
              "for history remediation (filter-repo + recreate for refs/pull)."
              % hits, file=out)
        return 1
    print("scrub-check: clean (%d term(s) checked, tip%s)."
          % (len(rules), "" if args.no_history else " + history"), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
