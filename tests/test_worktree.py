#!/usr/bin/env python3
"""Deterministic tests for m8shift-worktree.py (§8 degree-2 companion).

Each test builds a throwaway git repo (no timing races, no network), copies in the core +
companion, inits the relay, and detaches the canonical root so an integration target branch is
free for the dedicated _integration worktree. Covers the v1 contract: happy-path merge, idempotent
re-integrate, conflict-abort + handoff (no stuck WORKING), pen-busy refusal, target-checked-out
refusal, the integrating: sentinel force-guard, committed-but-unhanded retry, path-safety, and
canonical-root pinning from a linked worktree.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT_SRC, "m8shift.py")
COMPANION = os.path.join(ROOT_SRC, "m8shift-worktree.py")
VERSION = "3.9.0"


def run(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


class WTBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="m8wt-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t.t")
        self.git("config", "user.name", "t")
        shutil.copy(CORE, self.d)
        shutil.copy(COMPANION, self.d)
        self._write("f.txt", "base\n")
        self.git("add", "f.txt")
        self.git("commit", "-qm", "base")
        self._write(".gitignore", ".m8shift/\nM8SHIFT*.md\nAGENTS.md\nCLAUDE.md\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore")
        self.assertEqual(run([sys.executable, "m8shift.py", "init"], self.d).returncode, 0)
        self.git("checkout", "-q", "--detach")     # free `main` for the _integration tree

    # -- helpers ---------------------------------------------------------------
    def git(self, *args, cwd=None, check=True):
        r = run(["git", *args], cwd or self.d)
        if check:
            self.assertEqual(r.returncode, 0, f"git {args}: {r.stderr}")
        return r

    def wt(self, *args, cwd=None):
        # invoke the companion by absolute path (it discovers + rebases the canonical root from cwd),
        # so it works from a linked worktree where the gitignored companion file isn't present
        return run([sys.executable, COMPANION, *args], cwd or self.d)

    def core(self, *args, cwd=None):
        return run([sys.executable, "m8shift.py", *args], cwd or self.d)

    def _write(self, rel, text, cwd=None):
        with open(os.path.join(cwd or self.d, rel), "w") as f:
            f.write(text)

    def lock(self):
        """Parse the canonical LOCK fields from M8SHIFT.md."""
        text = open(os.path.join(self.d, "M8SHIFT.md")).read()
        body = text[text.index("LOCK:BEGIN"):text.index("LOCK:END")]
        out = {}
        for line in body.splitlines():
            m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip()
        return out

    def claim_and_commit(self, idv, fname, content):
        """Claim a feature worktree off main and commit one file in it."""
        self.assertEqual(self.wt("claim", idv, "claude", "--base", "main").returncode, 0)
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", idv)
        self._write(fname, content, cwd=wtdir)
        self.git("add", fname, cwd=wtdir)
        self.git("commit", "-qm", f"{idv} work", cwd=wtdir)

    def merge_commits_on(self, branch):
        return self.git("log", branch, "--oneline", "--merges").stdout.strip().splitlines()


class TestWorktreeHappyPath(WTBase):
    def test_status_shows_local_time_labels(self):
        out = self.wt("status").stdout
        self.assertIn("since=", out)
        self.assertIn(" local ", out)

    def test_claim_creates_worktree_on_branch(self):
        r = self.wt("claim", "feat-a", "claude", "--base", "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.d, ".m8shift", "worktrees", "feat-a")))
        self.assertIn("feat-a", self.git("branch", "--list", "feat-a").stdout)

    def test_integrate_merges_hands_off_and_clears_sentinel(self):
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git("cat-file", "-e", "main:a.txt", check=False).returncode, 0)  # merged
        self.assertEqual(len(self.merge_commits_on("main")), 1)                                # one --no-ff merge
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")        # handed off, not stuck WORKING
        self.assertEqual(lk["holder"], "codex")
        self.assertNotIn("integrating", lk)                    # sentinel cleared

    def test_integrate_idempotent_no_double_merge(self):
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        self.assertEqual(self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex").returncode, 0)
        self.assertEqual(len(self.merge_commits_on("main")), 1)
        self.core("release", "codex", "--to", "claude")        # pen back to claude
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")   # 2nd time
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already", (r.stdout + r.stderr).lower())
        self.assertEqual(len(self.merge_commits_on("main")), 1)   # STILL exactly one merge effect


class TestWorktreeConflict(WTBase):
    def test_conflict_aborts_clean_and_hands_off(self):
        # main diverges on f.txt, feat-b edits f.txt too → merge conflict
        self.claim_and_commit("feat-b", "f.txt", "feat-b side\n")
        # advance main (not checked out) so f.txt differs from feat-b's base
        self.claim_and_commit("seed", "f.txt", "main side\n")
        self.assertEqual(self.wt("integrate", "seed", "claude", "--into", "main", "--to", "codex").returncode, 0)
        self.core("release", "codex", "--to", "claude")
        r = self.wt("integrate", "feat-b", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 1, r.stdout)            # non-zero: integration failed
        integ = os.path.join(self.d, ".m8shift", "worktrees", "_integration")
        self.assertEqual(self.git("status", "--porcelain", cwd=integ).stdout, "")   # tree clean (aborted)
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")        # NOT stuck WORKING — handed off
        self.assertNotIn("integrating", lk)                    # sentinel cleared on the failure path
        self.assertIn("conflict:feat-b", open(os.path.join(self.d, "M8SHIFT.md")).read())  # reason recorded

    def test_commit_failure_hands_off_not_stranded(self):
        # a git commit failure (failing pre-commit hook / signing / identity) is NOT a hard crash:
        # finalize must abort the merge and hand off (clear sentinel), never strand WORKING.
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        hooks = os.path.join(self.d, ".git", "hooks")     # shared by all linked worktrees
        os.makedirs(hooks, exist_ok=True)
        hook = os.path.join(hooks, "pre-commit")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")           # handed off — NOT stuck WORKING
        self.assertNotIn("integrating", lk)                       # sentinel cleared
        self.assertIn("commit-error:feat-a", open(os.path.join(self.d, "M8SHIFT.md")).read())
        integ = os.path.join(self.d, ".m8shift", "worktrees", "_integration")
        merge_head = self.git("rev-parse", "--verify", "--quiet", "MERGE_HEAD", cwd=integ, check=False)
        self.assertNotEqual(merge_head.returncode, 0)             # MERGE_HEAD gone (merge aborted)
        self.assertEqual(len(self.merge_commits_on("main")), 0)   # nothing committed to the target


class TestWorktreeSafety(WTBase):
    def test_pen_busy_refuses(self):
        # someone else holds the pen → integrate cannot claim it
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.core("claim", "codex")                            # codex takes the pen (WORKING_CODEX)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pen", (r.stdout + r.stderr).lower())
        self.assertEqual(self.lock()["state"], "WORKING_CODEX")   # untouched

    def test_target_checked_out_in_root_refused(self):
        # re-attach the root to main → main is checked out there → integrate must refuse pre-flip
        self.git("checkout", "-q", "main")
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        # claim_and_commit re-detached? no — it doesn't touch the root. main now in root.
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checked out", (r.stdout + r.stderr).lower())
        self.assertEqual(self.lock()["state"], "IDLE")          # never flipped (fail before claim)

    def test_into_must_be_a_local_branch(self):
        # --into a commit/tag (not a branch) would merge into a detached HEAD and silently NOT
        # advance any branch → must refuse BEFORE claiming, leaving the LOCK untouched
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        sha = self.git("rev-parse", "main").stdout.strip()
        r = self.wt("integrate", "feat-a", "claude", "--into", sha, "--to", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("branch", (r.stdout + r.stderr).lower())
        self.assertEqual(self.lock()["state"], "IDLE")             # never flipped (fail before claim)
        self.assertNotEqual(self.git("cat-file", "-e", "main:a.txt", check=False).returncode, 0)  # unmerged

    def test_path_safety_rejects_bad_id(self):
        for bad in ("../evil", "a/b", "a b", ".hidden"):
            r = self.wt("integrate", bad, "claude", "--into", "main", "--to", "codex")
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("unsafe", (r.stdout + r.stderr).lower())

    def test_drop_needs_yes(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        self.assertNotEqual(self.wt("drop", "feat-a", "claude").returncode, 0)        # no --yes
        self.assertEqual(self.wt("drop", "feat-a", "claude", "--yes").returncode, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.d, ".m8shift", "worktrees", "feat-a")))


class TestWorktreeRecovery(WTBase):
    def test_committed_but_unhanded_retry_resumes(self):
        # simulate a crash AFTER the merge commit but BEFORE the handoff: pen WORKING_claude +
        # sentinel set, merge already in main. Retrying must finalize (no double-apply) and hand off.
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        self.assertEqual(self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex").returncode, 0)
        self.assertEqual(len(self.merge_commits_on("main")), 1)
        # rewind the LOCK to the crash window: WORKING_claude + integrating sentinel for feat-a
        sha = self.git("rev-parse", "main~1" if False else "main").stdout.strip()  # any 40-hex sha
        target_sha = self.git("rev-parse", "main^1").stdout.strip()                # the pre-merge tip
        p = os.path.join(self.d, "M8SHIFT.md")
        text = open(p).read()
        text = re.sub(r"(?m)^(state:\s*).*$", r"\1WORKING_CLAUDE", text, count=1)
        text = re.sub(r"(?m)^(holder:\s*).*$", r"\1claude", text, count=1)
        text = re.sub(r"(?m)^(note:)", f"integrating: feat-a@{target_sha}\nnote:", text, count=1)
        open(p, "w").write(text)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.merge_commits_on("main")), 1)   # NO double-apply
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")
        self.assertNotIn("integrating", lk)                        # sentinel cleared on recovery

    def test_head_moved_hands_off_not_stranded(self):
        # if finalize finds the integration tree HEAD ≠ the sentinel's recorded sha (out-of-band
        # move) while the pen is still OURS, it must abort the merge and HAND OFF (clear the
        # sentinel, never stuck WORKING) — not die() leaving the pen stranded.
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        bogus = "0" * 40                                   # a valid-format sha that ≠ the integ HEAD
        p = os.path.join(self.d, "M8SHIFT.md")
        text = open(p).read()
        text = re.sub(r"(?m)^(state:\s*).*$", r"\1WORKING_CLAUDE", text, count=1)
        text = re.sub(r"(?m)^(holder:\s*).*$", r"\1claude", text, count=1)
        text = re.sub(r"(?m)^(note:)", f"integrating: feat-a@{bogus}\nnote:", text, count=1)
        open(p, "w").write(text)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)      # failed, but cleanly
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")            # handed off — NOT stuck WORKING
        self.assertNotIn("integrating", lk)                        # sentinel cleared, not stranded
        self.assertIn("head-moved:feat-a", open(p).read())         # reason recorded
        integ = os.path.join(self.d, ".m8shift", "worktrees", "_integration")
        self.assertEqual(self.git("status", "--porcelain", cwd=integ).stdout, "")  # merge aborted


class TestCanonicalRootPinning(WTBase):
    def test_linked_worktree_coordinates_against_canonical(self):
        # run the companion FROM a linked feature worktree; it must coordinate against the canonical
        # M8SHIFT.md in the root, not a worktree-local copy.
        self.wt("claim", "feat-a", "claude", "--base", "main")
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self._write("a.txt", "x\n", cwd=wtdir)
        self.git("add", "a.txt", cwd=wtdir)
        self.git("commit", "-qm", "w", cwd=wtdir)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex", cwd=wtdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        # the canonical LOCK (in the root) advanced — proof the linked worktree used it
        self.assertEqual(self.lock()["state"], "AWAITING_CODEX")
        self.assertFalse(os.path.exists(os.path.join(wtdir, "M8SHIFT.md")))   # no worktree-local copy


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"test_worktree.py {VERSION}")
        sys.exit(0)
    unittest.main(verbosity=2)
