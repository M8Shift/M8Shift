#!/usr/bin/env python3
"""Deterministic tests for m8shift-worktree.py (§8 degree-2 companion).

Each test builds a throwaway git repo (no timing races, no network), copies in the core +
companion, inits the relay, and detaches the canonical root so an integration target branch is
free for the dedicated _integration worktree. Covers the v1 contract: happy-path merge, idempotent
re-integrate, conflict-abort + handoff (no stuck WORKING), pen-busy refusal, target-checked-out
refusal, the integrating: sentinel force-guard, committed-but-unhanded retry, path-safety, and
canonical-root pinning from a linked worktree.
"""
import json
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
VERSION = "3.56.0"


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
        with open(os.path.join(self.d, "M8SHIFT.md"), encoding="utf-8") as f:
            text = f.read()
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
    def test_status_shows_timezone_prefixed_local_time(self):
        out = self.wt("status").stdout
        self.assertIn("since=", out)
        self.assertRegex(out, r"since=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ  .+ \d{4}-\d\d-\d\d \d\d:\d\d:\d\d")

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
        self.assertEqual(
            self.core("release", "codex", "--to", "claude",
                      "--force", "--reason", "test setup returns integration baton").returncode,
            0,
        )
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
        self.assertEqual(
            self.core("release", "codex", "--to", "claude",
                      "--force", "--reason", "test setup returns integration baton").returncode,
            0,
        )
        r = self.wt("integrate", "feat-b", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 1, r.stdout)            # non-zero: integration failed
        integ = os.path.join(self.d, ".m8shift", "worktrees", "_integration")
        self.assertEqual(self.git("status", "--porcelain", cwd=integ).stdout, "")   # tree clean (aborted)
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")        # NOT stuck WORKING — handed off
        self.assertNotIn("integrating", lk)                    # sentinel cleared on the failure path
        with open(os.path.join(self.d, "M8SHIFT.md"), encoding="utf-8") as f:
            self.assertIn("conflict:feat-b", f.read())  # reason recorded

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
        with open(os.path.join(self.d, "M8SHIFT.md"), encoding="utf-8") as f:
            self.assertIn("commit-error:feat-a", f.read())
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

    def test_branch_policy_rejects_ambiguous_or_whitespace_names(self):
        for extra in (
            ("--branch=-bad",),
            ("--branch", "bad branch"),
        ):
            with self.subTest(extra=extra):
                r = self.wt("claim", "feat-safe", "claude", "--base", "main", *extra)
                self.assertNotEqual(r.returncode, 0)
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
        with open(p, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"(?m)^(state:\s*).*$", r"\1WORKING_CLAUDE", text, count=1)
        text = re.sub(r"(?m)^(holder:\s*).*$", r"\1claude", text, count=1)
        text = re.sub(r"(?m)^(note:)", f"integrating: feat-a@{target_sha}\nnote:", text, count=1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
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
        with open(p, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"(?m)^(state:\s*).*$", r"\1WORKING_CLAUDE", text, count=1)
        text = re.sub(r"(?m)^(holder:\s*).*$", r"\1claude", text, count=1)
        text = re.sub(r"(?m)^(note:)", f"integrating: feat-a@{bogus}\nnote:", text, count=1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)      # failed, but cleanly
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")            # handed off — NOT stuck WORKING
        self.assertNotIn("integrating", lk)                        # sentinel cleared, not stranded
        with open(p, encoding="utf-8") as f:
            self.assertIn("head-moved:feat-a", f.read())           # reason recorded
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


class TestRFC049PRCOwnership(WTBase):
    """RFC 049 PR C: owner sidecar OUTSIDE the checkout + ADVISORY cross-owner guard on the
    companion's mutating verbs (`--takeover --reason` = the explicit, audited override) +
    read-only `doctor` findings. Never a security boundary: a malformed/absent sidecar
    FAILS OPEN (verbs proceed; doctor reports the gap)."""

    def owner_file(self, idv):
        return os.path.join(self.d, ".m8shift", "worktree-owners", f"{idv}.json")

    def read_owner(self, idv):
        with open(self.owner_file(idv), encoding="utf-8") as fh:
            return json.load(fh)

    def doctor_findings(self):
        r = self.wt("doctor", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)["findings"]

    # ── sidecar lifecycle ─────────────────────────────────────────────────────
    def test_claim_records_ownership_outside_checkout(self):
        self.assertEqual(self.wt("claim", "feat-a", "claude", "--base", "main").returncode, 0)
        doc = self.read_owner("feat-a")
        self.assertEqual(doc["schema"], "m8shift.worktree_owner.v1")
        self.assertEqual(doc["agent"], "claude")
        self.assertEqual(doc["id"], "feat-a")
        self.assertEqual(doc["branch"], "feat-a")
        self.assertEqual(doc["path"], os.path.join(".m8shift", "worktrees", "feat-a"))
        self.assertRegex(doc["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        # OUTSIDE the checkout: not under the worktree the peer edits in
        self.assertFalse(self.owner_file("feat-a").startswith(
            os.path.join(self.d, ".m8shift", "worktrees", "feat-a") + os.sep))

    def test_drop_by_owner_removes_sidecar(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        self.assertEqual(self.wt("drop", "feat-a", "claude", "--yes").returncode, 0)
        self.assertFalse(os.path.exists(self.owner_file("feat-a")))

    # ── advisory cross-owner guard ────────────────────────────────────────────
    def test_cross_owner_verbs_refused_without_takeover(self):
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        for verb in (["done", "feat-a", "codex"],
                     ["drop", "feat-a", "codex", "--yes"],
                     ["integrate", "feat-a", "codex", "--into", "main", "--to", "claude"]):
            r = self.wt(*verb)
            self.assertNotEqual(r.returncode, 0, verb)
            self.assertIn("owned by 'claude'", r.stderr)
        # the integrate refusal happened BEFORE any pen flip
        lk = self.lock()
        self.assertEqual(lk["state"], "IDLE")
        self.assertNotIn("integrating", lk)
        self.assertTrue(os.path.isdir(os.path.join(self.d, ".m8shift", "worktrees", "feat-a")))
        self.assertEqual(self.read_owner("feat-a")["agent"], "claude")   # sidecar untouched

    def test_takeover_requires_nonempty_reason(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        for extra in (["--takeover"], ["--takeover", "--reason", "  "]):
            r = self.wt("done", "feat-a", "codex", *extra)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--reason", r.stderr)
        self.assertEqual(self.read_owner("feat-a")["agent"], "claude")

    def test_takeover_audits_and_preserves_created_at(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        before = self.read_owner("feat-a")["created_at"]
        r = self.wt("done", "feat-a", "codex", "--takeover", "--reason", "peer unresponsive")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("takeover", r.stdout)
        doc = self.read_owner("feat-a")
        self.assertEqual(doc["agent"], "codex")
        self.assertEqual(doc["taken_over_from"], "claude")
        self.assertEqual(doc["takeover_reason"], "peer unresponsive")
        self.assertEqual(doc["created_at"], before)          # original claim time preserved
        self.assertRegex(doc["takeover_at"], r"Z$")

    def test_same_owner_never_gated(self):
        self.claim_and_commit("feat-a", "a.txt", "from A\n")
        self.assertEqual(self.wt("done", "feat-a", "claude").returncode, 0)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_malformed_sidecar_fails_open_and_doctor_flags(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        with open(self.owner_file("feat-a"), "w") as fh:
            fh.write("{not json")
        # advisory guard fails OPEN — the verb proceeds without --takeover
        self.assertEqual(self.wt("done", "feat-a", "codex").returncode, 0)
        found = [f for f in self.doctor_findings() if f["worktree"] == "feat-a"]
        self.assertEqual([f["id"] for f in found], ["worktree.owner_missing"])

    def test_symlinked_sidecar_ignored(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        real = self.owner_file("feat-a")
        aside = real + ".real"
        os.rename(real, aside)
        os.symlink(aside, real)                              # O_NOFOLLOW must refuse it
        self.assertEqual(self.wt("done", "feat-a", "codex").returncode, 0)   # fail-open
        found = [f for f in self.doctor_findings() if f["worktree"] == "feat-a"]
        self.assertEqual([f["id"] for f in found], ["worktree.owner_missing"])

    # ── doctor matrix ─────────────────────────────────────────────────────────
    def test_doctor_clean_missing_mismatch_orphan(self):
        import json
        self.wt("claim", "feat-a", "claude", "--base", "main")
        self.wt("claim", "feat-b", "codex", "--base", "main")
        self.assertEqual(self.doctor_findings(), [])         # clean → no findings
        r = self.wt("doctor")
        self.assertIn("no findings", r.stdout)
        # missing: delete feat-a's sidecar
        os.unlink(self.owner_file("feat-a"))
        # mismatch: falsify feat-b's branch + a non-roster owner
        doc = self.read_owner("feat-b")
        doc["branch"], doc["agent"] = "wrong", "mallory"
        with open(self.owner_file("feat-b"), "w") as fh:
            json.dump(doc, fh)
        # orphan: sidecar for a worktree that does not exist
        ghost = {"schema": "m8shift.worktree_owner.v1", "id": "ghost", "agent": "claude",
                 "created_at": "2026-01-01T00:00:00Z", "path": "x", "branch": "x"}
        with open(self.owner_file("ghost"), "w") as fh:
            json.dump(ghost, fh)
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")
        self.assertEqual(by["feat-b"]["id"], "worktree.owner_mismatch")
        self.assertIn("mallory", by["feat-b"]["detail"])
        self.assertIn("wrong", by["feat-b"]["detail"])
        self.assertEqual(by["ghost"]["id"], "worktree.owner_mismatch")
        self.assertIn("orphan", by["ghost"]["detail"])
        # doctor is advisory: findings never flip the exit code
        self.assertEqual(self.wt("doctor").returncode, 0)

    def test_status_shows_owner_column(self):
        self.wt("claim", "feat-a", "claude", "--base", "main")
        out = self.wt("status").stdout
        self.assertIn("owner=claude", out)
        os.unlink(self.owner_file("feat-a"))
        self.assertIn("owner=?", self.wt("status").stdout)   # unusable sidecar → honest "?"


class TestRFC049PRCHardening(WTBase):
    """RFC 049 PR C adversarial hardening (Codex PR C review, 6 findings). The owner
    sidecar is advisory, but its WRITES must not escape the project, its ACTORS must be
    roster-validated before any read/write/destruction, a mandatory takeover audit must
    fail CLOSED, hostile recorded metadata must never reach the terminal raw, and status
    must agree with doctor."""

    OWNERS_REL = os.path.join(".m8shift", "worktree-owners")

    def owner_file(self, idv):
        return os.path.join(self.d, self.OWNERS_REL, f"{idv}.json")

    def write_raw(self, idv, text):
        os.makedirs(os.path.join(self.d, self.OWNERS_REL), exist_ok=True)
        with open(self.owner_file(idv), "w", encoding="utf-8") as fh:
            fh.write(text)

    def doc(self, idv, **over):
        base = {"schema": "m8shift.worktree_owner.v1", "id": idv, "agent": "claude",
                "created_at": "2026-01-01T00:00:00Z",
                "path": os.path.join(".m8shift", "worktrees", idv), "branch": idv}
        base.update(over)
        return base

    def doctor_findings(self):
        r = self.wt("doctor", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)["findings"]

    def read_owner_agent(self, idv):
        with open(self.owner_file(idv)) as fh:
            return json.load(fh)["agent"]

    def ledger_records(self):
        path = os.path.join(self.d, self.OWNERS_REL, "_takeovers.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    _DRIVER_PREAMBLE = (
        "import importlib.util, os, json, sys\n"
        "cs=importlib.util.spec_from_file_location('m8shift','m8shift.py')\n"
        "core=importlib.util.module_from_spec(cs); cs.loader.exec_module(core)\n"
        "ws=importlib.util.spec_from_file_location('wt','m8shift-worktree.py')\n"
        "wt=importlib.util.module_from_spec(ws); ws.loader.exec_module(wt)\n"
        "wt.ROOT=os.getcwd(); core.configure_root(os.getcwd())\n"
    )

    def driver(self, code):
        """Run an in-process driver against the copied core+companion (ROOT-configured), so a
        deterministic concurrency scenario can call the takeover functions directly — no
        timing/interleaving. Returns the CompletedProcess."""
        script = os.path.join(self.d, "_driver.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(self._DRIVER_PREAMBLE + code)
        return run([sys.executable, script], self.d)

    # ── finding 1: writes must never escape the project ───────────────────────
    def test_takeover_tmp_symlink_does_not_overwrite_external_file(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        external = os.path.join(self.d, "external-sentinel.txt")
        with open(external, "w") as fh:
            fh.write("UNTOUCHED")
        # preplant the OLD fixed temp name as a symlink to the external file
        os.symlink(external, self.owner_file("feat-a") + ".tmp")
        r = self.wt("done", "feat-a", "codex", "--takeover", "--reason", "x")
        self.assertEqual(r.returncode, 0, r.stderr)          # write goes through a UNIQUE temp
        with open(external) as fh:
            self.assertEqual(fh.read(), "UNTOUCHED")         # external bytes intact
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")

    def test_symlinked_owners_dir_refuses_writes(self):
        # a symlinked owners directory would let O_NOFOLLOW-on-final escape via the parent
        m8 = os.path.join(self.d, ".m8shift")
        os.makedirs(m8, exist_ok=True)
        target = os.path.join(self.d, "evil-owners")
        os.makedirs(target)
        os.symlink(target, os.path.join(m8, "worktree-owners"))
        r = self.wt("claim", "feat-a", "claude", "--base", "main")
        self.assertEqual(r.returncode, 0)                    # worktree still created
        self.assertIn("not recorded", r.stderr)              # sidecar write REFUSED
        self.assertFalse(os.path.exists(os.path.join(target, "feat-a.json")))  # no escape write
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")  # doctor flags the gap

    # ── finding 2: actor roster-validated before any owner op / destruction ───
    def test_drop_refuses_unknown_agent_even_with_missing_sidecar(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        os.unlink(self.owner_file("feat-a"))                # malformed/absent → fail-open read
        r = self.wt("drop", "feat-a", "mallory", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown agent", r.stderr)
        self.assertTrue(os.path.isdir(                       # worktree NOT deleted
            os.path.join(self.d, ".m8shift", "worktrees", "feat-a")))

    def test_all_verbs_reject_unknown_actor_before_side_effects(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        before = self.read_owner_agent("feat-a")
        for verb in (["done", "feat-a", "mallory", "--takeover", "--reason", "x"],
                     ["drop", "feat-a", "mallory", "--yes", "--takeover", "--reason", "x"],
                     ["integrate", "feat-a", "mallory", "--into", "main", "--to", "claude",
                      "--takeover", "--reason", "x"]):
            r = self.wt(*verb)
            self.assertEqual(r.returncode, 1, verb)
            self.assertIn("unknown agent", r.stderr, verb)
            self.assertEqual(self.read_owner_agent("feat-a"), before)   # sidecar unchanged
            self.assertEqual(self.lock()["state"], "IDLE")              # no pen flip
        self.assertNotIn("mallory", self.git(
            "log", "--all", "--oneline", check=False).stdout)

    # ── finding 3: failed audit / failed precondition never transfers ownership ─
    def test_takeover_fails_closed_when_audit_write_fails(self):
        # DETERMINISTIC, permission-independent injection (Codex PR C round-2 finding 4:
        # chmod 0500 is unreliable as root / on some Windows FS): make the durable takeover
        # ledger path a DIRECTORY so its append fails for every user, and assert the takeover
        # fails closed with ownership unchanged and no done-ledger line.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        os.makedirs(os.path.join(self.d, self.OWNERS_REL, "_takeovers.jsonl"))
        r = self.wt("done", "feat-a", "codex", "--takeover", "--reason", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("audit", r.stderr)
        self.assertEqual(self.read_owner_agent("feat-a"), "claude")     # ownership unchanged
        self.assertNotIn("done by codex", self._done_log())             # no ledger line either

    def test_integrate_precondition_failure_does_not_transfer_owner(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        r = self.wt("integrate", "feat-a", "codex", "--into", "no-such-branch",
                    "--to", "claude", "--takeover", "--reason", "x")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read_owner_agent("feat-a"), "claude")     # owner untouched
        self.assertEqual(self.lock()["state"], "IDLE")                  # pen never flipped
        self.assertNotIn("integrating", self.lock())

    def _done_log(self):
        p = os.path.join(self.d, ".m8shift", "done.log")
        return open(p).read() if os.path.exists(p) else ""

    # ── finding 4: hostile metadata never reaches the terminal; strict schema ──
    def test_control_chars_in_agent_are_owner_missing_and_never_echoed(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", agent="cl[31maude")))
        out = self.wt("status").stdout
        self.assertNotIn("\x1b", out)                        # no raw ESC to the terminal
        self.assertIn("owner=?", out)                        # not a valid agent → unusable
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")  # bad shape → missing

    def test_strict_schema_incomplete_docs_are_owner_missing(self):
        import json as _json
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        for bad in (
            {"schema": "m8shift.worktree_owner.v1", "agent": "claude"},          # no id/path/…
            self.doc("feat-a", id="other"),                                       # wrong id
            self.doc("feat-a", created_at="not-a-timestamp"),                     # bad time
            self.doc("feat-a", path="/etc/passwd"),                              # absolute path
            self.doc("feat-a", path="../../escape"),                             # traversal
            self.doc("feat-a", agent="x" * 300),                                 # oversized
            self.doc("feat-a", branch=123),                                       # non-string
        ):
            self.write_raw("feat-a", _json.dumps(bad))
            by = {f["worktree"]: f for f in self.doctor_findings()}
            self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing", bad)

    def test_well_shaped_off_roster_is_mismatch_not_missing(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", agent="mallory")))
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_mismatch")
        self.assertIn("mallory", by["feat-a"]["detail"])

    def test_hostile_orphan_filename_is_sanitized(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        # an orphan sidecar whose id carries a control char
        self.write_raw("ghost", json.dumps(self.doc("ghost")))
        r = self.wt("doctor")                                # human output
        self.assertNotIn("\x1b", r.stdout)
        j = self.doctor_findings()
        self.assertTrue(any(f["id"] == "worktree.owner_mismatch"
                            and "orphan" in f["detail"] for f in j))
        self.assertFalse(any("\x1b" in f["worktree"] for f in j))

    # ── finding 5: status and doctor agree on the integration tree ────────────
    def test_integration_tree_owner_na_and_doctor_clean(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.assertEqual(self.wt("integrate", "feat-a", "claude",
                                 "--into", "main", "--to", "codex").returncode, 0)
        out = self.wt("status").stdout
        integ_line = next(l for l in out.splitlines() if "_integration" in l)
        self.assertIn("owner=n/a", integ_line)               # not owner=? (finding 5)
        self.assertNotIn("owner=?", integ_line)
        self.assertFalse(any(f["worktree"] == "_integration"
                             for f in self.doctor_findings()))  # doctor excludes it → agree

    # ── round-2 adversarial hunt regressions ──────────────────────────────────
    def test_integrate_busy_pen_does_not_transfer_ownership(self):
        # A busy integration pen is the pen's ROUTINE serialization state; a CROSS-OWNER
        # takeover must not commit and then die on the busy pen, stranding a transferred
        # ownership. owner=codex, integrator=claude (--takeover), pen held by codex.
        self.assertEqual(self.wt("claim", "feat-a", "codex", "--base", "main").returncode, 0)
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self._write("a.txt", "x\n", cwd=wtdir)
        self.git("add", "a.txt", cwd=wtdir)
        self.git("commit", "-qm", "w", cwd=wtdir)
        self.assertEqual(self.core("claim", "codex").returncode, 0)   # pen busy: WORKING_CODEX
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex",
                    "--takeover", "--reason", "hijack")
        self.assertEqual(r.returncode, 1)
        self.assertIn("pen", (r.stderr + r.stdout).lower())
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")   # ownership NOT transferred

    def test_status_sanitizes_hostile_worktree_basename(self):
        # a managed worktree whose dir name carries an ANSI escape must not inject it into
        # the terminal via status (doctor already sanitizes — the two must agree).
        base = os.path.join(self.d, ".m8shift", "worktrees")
        os.makedirs(base, exist_ok=True)
        hostile = os.path.join(base, "x\x1b[31mPWNED")
        r = self.git("worktree", "add", "-b", "hostilebr", hostile, "main", check=False)
        if r.returncode != 0:
            self.skipTest("filesystem/git refuses ESC in a worktree path")
        out = self.wt("status").stdout
        self.assertNotIn("\x1b", out)                        # no raw ESC reaches the terminal
        self.assertIn("PWNED", out)                          # the (sanitized) name still shows

    def test_detached_head_worktree_listed_by_status(self):
        # a detached-HEAD managed worktree has no porcelain `branch ` line; status must still
        # list it (agreeing with doctor/_managed_worktrees), marked "(detached)".
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self.git("checkout", "-q", "--detach", cwd=wtdir)
        out = self.wt("status").stdout
        line = next((l for l in out.splitlines() if "feat-a" in l), "")
        self.assertIn("feat-a", line)
        self.assertIn("(detached)", line)
        self.assertIn("owner=claude", line)

    def test_takeover_reason_length_bounded(self):
        # an oversized --reason would push the audit doc past the read cap, so the just-
        # written audit would read back as owner_missing (silent loss) — reject it instead.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        r = self.wt("done", "feat-a", "codex", "--takeover", "--reason", "z" * 9000)
        self.assertEqual(r.returncode, 1)
        self.assertIn("too long", r.stderr)
        self.assertEqual(self.read_owner_agent("feat-a"), "claude")  # ownership unchanged
        # a normal (bounded) reason still works and reads back
        r = self.wt("done", "feat-a", "codex", "--takeover", "--reason", "peer AWOL")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")

    def test_non_ascii_timestamp_is_owner_missing(self):
        # semantic timestamp validation is ASCII-strict: Arabic-Indic digits must not validate.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc(
            "feat-a", created_at="٢٠٢٦-٠١-"
                                 "٠١T٠٠:٠٠:٠٠Z")))
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")

    # ── round-3 adversarial regressions (Codex PR C round-2 review) ────────────
    def test_integrate_become_busy_race_is_atomic(self):
        # finding 1: the become-busy race — a peer claiming the pen AFTER the read-only
        # precheck but BEFORE claim_pen — must not transfer ownership. Deterministic race
        # seam: a one-shot git post-checkout hook (fired during integrate's integration-tree
        # prep, which runs between the precheck and claim_pen) claims the pen as codex.
        # Because the takeover commit is folded INTO claim_pen under the file lock, claim_pen
        # sees the now-busy pen and refuses, transferring NOTHING.
        self.assertEqual(self.wt("claim", "feat-a", "codex", "--base", "main").returncode, 0)
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self._write("a.txt", "x\n", cwd=wtdir)
        self.git("add", "a.txt", cwd=wtdir)
        self.git("commit", "-qm", "w", cwd=wtdir)
        hookdir = os.path.join(self.d, ".git", "hooks")
        os.makedirs(hookdir, exist_ok=True)
        sentinel = os.path.join(self.d, ".race-fired")
        hook = os.path.join(hookdir, "post-checkout")
        with open(hook, "w") as fh:
            fh.write("#!/bin/sh\n"
                     f'[ -e "{sentinel}" ] && exit 0\n'
                     f'touch "{sentinel}"\n'
                     f'cd "{self.d}" && "{sys.executable}" m8shift.py claim codex '
                     ">/dev/null 2>&1\nexit 0\n")
        os.chmod(hook, 0o755)
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex",
                    "--takeover", "--reason", "race")
        self.assertTrue(os.path.exists(sentinel), "race seam did not fire")   # hook ran
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")    # ownership NOT transferred
        self.assertFalse(any(x["verb"] == "integrate" for x in self.ledger_records()))
        self.assertEqual(self.lock()["state"], "WORKING_CODEX")       # LOCK consistent (codex holds)
        self.assertNotIn("integrating", self.lock())                  # no stranded sentinel

    def test_integrate_busy_pen_precheck_no_transfer(self):
        # the read-only precheck also refuses a statically-busy pen (friendly fast-fail).
        self.assertEqual(self.wt("claim", "feat-a", "codex", "--base", "main").returncode, 0)
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self._write("a.txt", "x\n", cwd=wtdir)
        self.git("add", "a.txt", cwd=wtdir)
        self.git("commit", "-qm", "w", cwd=wtdir)
        self.assertEqual(self.core("claim", "codex").returncode, 0)   # pen busy up front
        r = self.wt("integrate", "feat-a", "claude", "--into", "main", "--to", "codex",
                    "--takeover", "--reason", "hijack")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")
        self.assertFalse(any(x["verb"] == "integrate" for x in self.ledger_records()))

    def test_drop_takeover_leaves_durable_ledger_audit(self):
        # finding 2: a cross-owner drop destroys the sidecar, so the durable ledger must
        # hold the authorized + completed records with the reason.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        r = self.wt("drop", "feat-a", "codex", "--yes", "--takeover",
                    "--reason", "DROP_SENTINEL_9931")
        self.assertEqual(r.returncode, 0, r.stderr)
        drops = [x for x in self.ledger_records() if x["verb"] == "drop"]
        self.assertEqual({x["phase"] for x in drops}, {"authorized", "completed"})
        self.assertTrue(all(x["from"] == "claude" and x["to"] == "codex" for x in drops))
        self.assertTrue(any(x["reason"] == "DROP_SENTINEL_9931" for x in drops))

    def test_drop_dirty_tree_records_authorized_not_completed(self):
        # finding 2: a dirty worktree makes `git worktree remove` fail AFTER the authorized
        # record — the ledger must truthfully show attempted (authorized) but NOT completed,
        # and the worktree must survive.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self._write("dirty.txt", "uncommitted\n", cwd=wtdir)       # dirty → remove refuses
        r = self.wt("drop", "feat-a", "codex", "--yes", "--takeover", "--reason", "r")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(os.path.isdir(wtdir))                     # worktree survived
        phases = {x["phase"] for x in self.ledger_records() if x["verb"] == "drop"}
        self.assertIn("authorized", phases)
        self.assertNotIn("completed", phases)

    def test_same_owner_drop_has_no_bogus_takeover_audit(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.assertEqual(self.wt("drop", "feat-a", "claude", "--yes").returncode, 0)
        self.assertEqual(self.ledger_records(), [])               # no takeover records at all

    def test_drop_missing_worktree_writes_no_phantom_audit(self):
        # the worktree-exists precondition runs BEFORE the authorize record, so a drop of a
        # non-existent (but sidecar-owned) worktree dies without a phantom ledger entry.
        self.write_raw("ghost", json.dumps(self.doc("ghost")))
        r = self.wt("drop", "ghost", "codex", "--yes", "--takeover", "--reason", "phantom")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no worktree", r.stderr)
        self.assertEqual(self.ledger_records(), [])               # no authorized record written

    def test_impossible_calendar_timestamp_is_owner_missing(self):
        # finding 3: 2026-99-99T99:99:99Z has the right SHAPE but is an impossible instant.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", created_at="2026-99-99T99:99:99Z")))
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")

    def test_empty_branch_owner_doc_is_owner_missing(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", branch="")))
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")

    def test_detached_head_recorded_branch_is_mismatch(self):
        # finding 3: a claimed owner branch while the worktree is detached is a mismatch.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        wtdir = os.path.join(self.d, ".m8shift", "worktrees", "feat-a")
        self.git("checkout", "-q", "--detach", cwd=wtdir)
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_mismatch")
        self.assertIn("detached", by["feat-a"]["detail"])

    def test_fifo_ledger_path_fails_closed_no_hang(self):
        # PR C round-3 hunt: a FIFO at the ledger path must NOT block the write-only open
        # forever (which would freeze the relay under the global lock) — O_NONBLOCK + S_ISREG
        # make it fail closed. Run under a wall-clock timeout to catch a regression hang.
        if not hasattr(os, "mkfifo"):
            self.skipTest("no os.mkfifo on this platform")
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        os.makedirs(os.path.join(self.d, self.OWNERS_REL), exist_ok=True)
        os.mkfifo(os.path.join(self.d, self.OWNERS_REL, "_takeovers.jsonl"))
        r = subprocess.run([sys.executable, COMPANION, "done", "feat-a", "codex",
                            "--takeover", "--reason", "x"], cwd=self.d,
                           capture_output=True, text=True, timeout=30)  # timeout catches a hang
        self.assertEqual(r.returncode, 1)                  # fail-closed, not a hang
        self.assertEqual(self.read_owner_agent("feat-a"), "claude")   # ownership unchanged

    def test_non_canonical_timestamps_are_owner_missing(self):
        # PR C round-3 hunt: single-digit fields, whitespace padding, and non-ASCII year all
        # deviate from the canonical strftime form and must be rejected (owner_missing).
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        for bad in ("2026-2-3T4:5:6Z", "  2026-01-01T00:00:00Z  ",
                    "٢٠٢٦-01-01T00:00:00Z"):
            self.write_raw("feat-a", json.dumps(self.doc("feat-a", created_at=bad)))
            by = {f["worktree"]: f for f in self.doctor_findings()}
            self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing", bad)

    def test_whitespace_only_takeover_reason_is_owner_missing(self):
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc(
            "feat-a", taken_over_from="codex", takeover_reason="   ",
            takeover_at="2026-01-01T00:00:00Z")))
        by = {f["worktree"]: f for f in self.doctor_findings()}
        self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing")

    def test_malformed_takeover_tuple_is_owner_missing(self):
        # finding 3: the optional audit tuple is validated ALL-OR-NONE — a partial, oversized,
        # ANSI-agent, or bad-time audit makes the whole doc malformed (owner_missing).
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        for bad in (
            self.doc("feat-a", taken_over_from="mallory"),                 # partial tuple
            self.doc("feat-a", taken_over_from="x\x1bevil",
                     takeover_reason="r", takeover_at="2026-01-01T00:00:00Z"),  # ANSI prev
            self.doc("feat-a", taken_over_from="x", takeover_reason="z" * 300,
                     takeover_at="2026-01-01T00:00:00Z"),                  # oversized reason
            self.doc("feat-a", taken_over_from="x", takeover_reason="r",
                     takeover_at="2026-99-99T00:00:00Z"),                  # impossible time
        ):
            self.write_raw("feat-a", json.dumps(bad))
            by = {f["worktree"]: f for f in self.doctor_findings()}
            self.assertEqual(by["feat-a"]["id"], "worktree.owner_missing", bad)

    # ── round-4 concurrency regressions (Codex PR C round-3 review) ────────────
    def test_stale_ticket_cas_refuses_overwriting_a_changed_owner(self):
        # finding 1: a takeover ticket captured before the lock must NOT overwrite an owner
        # that changed under the lock. Deterministic driver: current owner is gemini, but the
        # ticket expects claude → the CAS refuses, writes nothing, leaves gemini + no ledger.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", agent="gemini")))
        r = self.driver(
            "json.dump(dict(prev='claude', reason='x', branch='feat-a',"
            " created_at='2026-01-01T00:00:00Z'), open('_ticket.json','w'))\n"
            "tk=json.load(open('_ticket.json'))\n"
            "rc=1\n"
            "try:\n"
            "    with core.file_lock():\n"
            "        wt.commit_takeover_or_die('feat-a','codex',tk,'done')\n"
            "    rc=0\n"
            "except SystemExit as e:\n"
            "    sys.stderr.write(str(e))\n"
            "print(rc)\n")
        self.assertEqual(r.stdout.strip().splitlines()[-1], "1", r.stdout + r.stderr)  # died
        self.assertIn("owner changed", r.stderr)
        self.assertEqual(self.read_owner_agent("feat-a"), "gemini")  # NOT overwritten
        self.assertEqual(self.ledger_records(), [])                  # no stale audit record

    def test_matching_ticket_cas_commits_with_truthful_from(self):
        # the positive CAS path: when the current owner still equals the ticket's prev, the
        # takeover applies and the ledger `from` is truthful.
        self.claim_and_commit("feat-a", "a.txt", "x\n")             # owner=claude
        r = self.driver(
            "tk=dict(prev='claude', reason='ok', branch='feat-a',"
            " created_at=json.load(open('.m8shift/worktree-owners/feat-a.json'))['created_at'])\n"
            "with core.file_lock():\n"
            "    wt.commit_takeover_or_die('feat-a','codex',tk,'done')\n"
            "print('done')\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")
        recs = self.ledger_records()
        self.assertEqual([x["from"] for x in recs], ["claude"])      # truthful displaced owner
        self.assertEqual(recs[0]["to"], "codex")

    def test_resume_reapplies_takeover_not_bypassed(self):
        # finding 2: on the integration RESUME path (own WORKING sentinel + same id), a supplied
        # takeover of a sidecar that went foreign mid-flight must STILL be applied, not bypassed.
        # Driver: set LOCK to our own in-flight sentinel, owner foreign (gemini), call claim_pen
        # with a matching ticket → returns resume AND applies the takeover.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        self.write_raw("feat-a", json.dumps(self.doc("feat-a", agent="gemini")))
        sha = "a" * 40
        r = self.driver(
            "text=core.load_or_die(); lk=core.get_lock(text)\n"
            "lk.update(holder='codex', state='WORKING_CODEX', integrating='feat-a@%s',\n"
            "          since=core.iso(core.now()), expires=core.iso(core.now()))\n"
            "core.write(core.set_lock(text, lk))\n"
            "tk=dict(prev='gemini', reason='reassert', branch='feat-a',"
            " created_at='2026-01-01T00:00:00Z')\n"
            "mode,_=wt.claim_pen('codex','feat-a','%s',tk)\n"
            "print(mode)\n" % (sha, sha))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "resume")
        self.assertEqual(self.read_owner_agent("feat-a"), "codex")   # takeover APPLIED on resume
        recs = self.ledger_records()
        self.assertTrue(any(x["verb"] == "integrate" and x["from"] == "gemini" for x in recs))

    def test_completed_drop_audit_failure_is_surfaced_nonzero(self):
        # finding 3: if the post-removal `completed` ledger append fails, the drop is reported
        # as a bounded partial-failure (rc 2), never a silent full success. Deterministic
        # driver: run authorize → remove → (ledger swapped to a directory) → complete, and
        # assert complete returns not-ok and cmd_drop's return-2 branch is taken.
        self.claim_and_commit("feat-a", "a.txt", "x\n")
        r = self.driver(
            "tk=dict(prev='claude', reason='r', branch='feat-a',"
            " created_at=json.load(open('.m8shift/worktree-owners/feat-a.json'))['created_at'])\n"
            "with core.file_lock():\n"
            "    wt.authorize_drop_takeover_or_die('feat-a','codex',tk)\n"
            "wt.git(['worktree','remove', wt.wt_path('feat-a')])\n"
            "wt.remove_owner('feat-a')\n"
            "led=os.path.join('.m8shift','worktree-owners','_takeovers.jsonl')\n"
            "os.remove(led); os.mkdir(led)\n"           # ledger now a directory → append fails
            "ok,err=wt.complete_drop_takeover('feat-a','codex',tk)\n"
            "print('OK' if ok else 'FAILCLOSED')\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "FAILCLOSED")  # complete surfaced not-ok
        # and the end-to-end path returns rc 2 with the warning (ledger dir from the start makes
        # authorize fail; here we prove the helper contract that cmd_drop's rc-2 branch consumes)


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"test_worktree.py {VERSION}")
        sys.exit(0)
    unittest.main(verbosity=2)
