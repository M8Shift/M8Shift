#!/usr/bin/env python3
"""Tests cowork — unitaires (fonctions pures) + non-régression (CLI, bord à bord).

Lancer :  python3 -m unittest discover -s tests        (depuis la racine du repo)
   ou  :  python3 tests/test_cowork.py

Modèle : `claim` est obligatoire et exclusif avant de travailler ; `append` n'est
accepté que depuis `WORKING_<agent>`. Les tests CLI copient `cowork.py` dans un
dossier temporaire isolé et l'exécutent en sous-processus — comme un agent.
Chaque non-régression cible un bug corrigé (NR-n) ou une garantie du CDC.
Stdlib uniquement.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "cowork.py")
sys.path.insert(0, REPO)
import cowork  # noqa: E402  (import après ajustement du sys.path)


# ───────────────────────────── unitaires : fonctions pures ──────────────────

class TestPureFunctions(unittest.TestCase):
    def test_other(self):
        self.assertEqual(cowork.other("claude"), "codex")
        self.assertEqual(cowork.other("codex"), "claude")

    def test_iso_roundtrip(self):
        t = cowork.now()
        self.assertEqual(cowork.parse_iso(cowork.iso(t)), t)

    def test_parse_iso_empty(self):
        self.assertIsNone(cowork.parse_iso("-"))
        self.assertIsNone(cowork.parse_iso(""))
        self.assertIsNone(cowork.parse_iso("pas une date"))

    def test_lock_roundtrip(self):
        text = ("avant\n" + cowork.LOCK_BEGIN + "\nholder:   none\nstate:    IDLE\n"
                "turn:     0\n" + cowork.LOCK_END + "\naprès\n")
        lk = cowork.get_lock(text)
        self.assertEqual(lk["state"], "IDLE")
        self.assertEqual(lk["turn"], "0")
        out = cowork.set_lock(text, {"holder": "claude", "state": "WORKING_CLAUDE", "turn": "2"})
        lk2 = cowork.get_lock(out)
        self.assertEqual(lk2["holder"], "claude")
        self.assertEqual(lk2["state"], "WORKING_CLAUDE")
        self.assertEqual(lk2["turn"], "2")
        self.assertIn("avant", out)
        self.assertIn("après", out)

    def test_stanza_for(self):
        s = cowork.stanza_for("claude")
        self.assertIn(cowork.STANZA_BEGIN, s)
        self.assertIn(cowork.STANZA_END, s)
        self.assertIn("claude", s)
        self.assertIn("AWAITING_CLAUDE", s)
        self.assertIn("codex", s)  # mentionne l'autre agent

    def test_clean_body_neutralizes_markers(self):
        out = cowork.clean_body("x COWORK:TURN 999 claude BEGIN y")
        self.assertNotIn("COWORK:TURN", out)

    def test_protocol_doc_in_sync(self):
        """Non-régression doc : docs/COWORK.protocol.md == source PROTOCOL_TEMPLATE."""
        path = os.path.join(REPO, "docs", "COWORK.protocol.md")
        if not os.path.exists(path):
            self.skipTest("docs/COWORK.protocol.md absent")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), cowork.PROTOCOL_TEMPLATE,
                             "docs/COWORK.protocol.md a divergé de cowork.py "
                             "→ régénère : python3 -c \"import cowork;"
                             "open('docs/COWORK.protocol.md','w').write(cowork.PROTOCOL_TEMPLATE)\"")


# ───────────────────────────── base CLI (sous-processus isolé) ──────────────

class CLIBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cowork-test-")
        shutil.copy(SCRIPT, os.path.join(self.d, "cowork.py"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def cw(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, "cowork.py", *args],
            cwd=self.d, capture_output=True, text=True, input=stdin,
        )

    def md(self):
        with open(os.path.join(self.d, "COWORK.md"), encoding="utf-8") as f:
            return f.read()

    def lock(self):
        t = self.md()
        i = t.index(cowork.LOCK_BEGIN)
        j = t.index(cowork.LOCK_END)
        out = {}
        for line in t[i:j].splitlines():
            m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip()
        return out

    def init(self, *extra):
        r = self.cw("init", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def turn(self, agent, to, ask="a", done="b", files=None, body=None):
        """Joue un tour complet : claim <agent> puis append --to <autre>."""
        rc = self.cw("claim", agent)
        self.assertEqual(rc.returncode, 0, f"claim {agent}: {rc.stdout}{rc.stderr}")
        args = ["append", agent, "--to", to, "--ask", ask, "--done", done]
        if files:
            args += ["--files", files]
        if body is not None:
            args += ["--body", "-"]
        return self.cw(*args, stdin=body)

    def set_expires_past(self):
        p = os.path.join(self.d, "COWORK.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        t = re.sub(r"expires:\s*.*", "expires:  2020-01-01T00:00:00Z", t, count=1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(t)


# ───────────────────────────── non-régression : init / portabilité ─────────

class TestInit(CLIBase):
    def test_init_creates_kit(self):
        self.init()
        for f in ("COWORK.md", "COWORK.protocol.md", "CLAUDE.md", "AGENTS.md"):
            self.assertTrue(os.path.exists(os.path.join(self.d, f)), f)
        lk = self.lock()
        self.assertEqual(lk["state"], "IDLE")
        self.assertEqual(lk["holder"], "none")
        self.assertEqual(lk["turn"], "0")

    def test_init_project_name(self):
        self.init("--name", "Mon Super Projet")
        self.assertIn("# COWORK · Mon Super Projet", self.md())

    def test_reinit_idempotent_preserves_content(self):
        """NR-idempotence : ré-init ne duplique pas la stanza, préserve contenu + état."""
        claude = os.path.join(self.d, "CLAUDE.md")
        with open(claude, "w", encoding="utf-8") as f:
            f.write("# CLAUDE.md\n\nCONSIGNE-PROJET-UNIQUE\n")
        self.init()
        self.turn("claude", "codex")
        self.assertEqual(self.lock()["turn"], "1")
        self.init()  # 2e init, sans --force
        with open(claude, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CONSIGNE-PROJET-UNIQUE", content)
        self.assertEqual(content.count(cowork.STANZA_BEGIN), 1)
        self.assertEqual(self.lock()["turn"], "1")  # COWORK.md préservé

    def test_anchor_case_insensitive_no_duplicate(self):
        """NR-7 : un claude.md minuscule préexistant est réutilisé (pas de doublon)."""
        with open(os.path.join(self.d, "claude.md"), "w", encoding="utf-8") as f:
            f.write("# claude.md\n\nGARDE-MOI\n")
        r = self.init()
        anchors = [f for f in os.listdir(self.d) if f.lower() == "claude.md"]
        self.assertEqual(len(anchors), 1, anchors)
        with open(os.path.join(self.d, anchors[0]), encoding="utf-8") as f:
            self.assertIn("GARDE-MOI", f.read())
        self.assertIn(anchors[0], r.stdout)  # le nom rapporté est le nom réel on-disk

    def test_init_force_resets_lock(self):
        self.init()
        self.turn("claude", "codex")
        self.assertEqual(self.lock()["turn"], "1")
        self.init("--force")
        self.assertEqual(self.lock()["turn"], "0")
        self.assertEqual(self.lock()["state"], "IDLE")

    def test_write_preserves_file_mode(self):
        """NR-C : réécrire un ancrage ne doit pas casser ses permissions (mkstemp=0600)."""
        self.init()
        claude = os.path.join(self.d, "CLAUDE.md")
        os.chmod(claude, 0o644)
        self.init("--force")  # réinjecte la stanza → réécrit CLAUDE.md
        self.assertEqual(os.stat(claude).st_mode & 0o777, 0o644)


# ───────────────────────────── modèle claim → travail → append ─────────────

class TestClaimModel(CLIBase):
    def test_append_requires_claim_from_idle(self):
        """NR-bloquant : append depuis IDLE (sans claim) est refusé."""
        self.init()
        r = self.cw("append", "claude", "--to", "codex", "--ask", "x", "--done", "y")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("stylo", (r.stdout + r.stderr).lower())
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.lock()["turn"], "0")  # aucun tour écrit

    def test_append_requires_claim_from_awaiting(self):
        """Même après un handoff, l'agent destinataire doit claim avant d'append."""
        self.init()
        self.turn("claude", "codex")  # → AWAITING_CODEX
        r = self.cw("append", "codex", "--to", "claude", "--ask", "x", "--done", "y")
        self.assertNotEqual(r.returncode, 0)  # codex n'a pas encore claim

    def test_claim_exclusive_sequential(self):
        self.init()
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertNotEqual(self.cw("claim", "codex").returncode, 0)  # claude tient le stylo

    def test_handoff_increments_and_alternates(self):
        self.init()
        self.turn("claude", "codex")
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CODEX")
        self.assertEqual(lk["turn"], "1")
        self.turn("codex", "claude")
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CLAUDE")
        self.assertEqual(lk["turn"], "2")

    def test_append_out_of_turn_refused(self):
        self.init()
        self.turn("claude", "codex")  # claude a déjà passé la main
        r = self.cw("append", "claude", "--to", "codex", "--ask", "x", "--done", "y")
        self.assertNotEqual(r.returncode, 0)  # claude ne tient plus le stylo

    def test_body_stdin_inserted(self):
        self.init()
        r = self.turn("claude", "codex", body="CORPS-LIBRE-XYZ")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CORPS-LIBRE-XYZ", self.md())


# ───────────────────────────── mutex / garde-fous ──────────────────────────

class TestMutexGuards(CLIBase):
    def test_force_refused_on_fresh_lock(self):
        """NR-1 : claim --force ne vole pas un verrou non périmé."""
        self.init()
        self.cw("claim", "claude")
        r = self.cw("claim", "codex", "--force")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.lock()["holder"], "claude")

    def test_force_accepted_on_stale_lock(self):
        """NR-1 (suite) : claim --force reprend un verrou périmé."""
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()
        r = self.cw("claim", "codex", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lock()["holder"], "codex")
        self.assertIn("périmé", self.lock()["note"])

    def test_reclaim_own_lock_refreshes(self):
        """NR-4 : le détenteur peut reprendre son propre verrou (refresh TTL)."""
        self.init()
        self.cw("claim", "claude")
        r = self.cw("claim", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lock()["state"], "WORKING_CLAUDE")
        self.assertNotEqual(self.lock()["expires"], "-")

    def test_self_handoff_refused(self):
        """NR-3 : --to ne peut pas viser soi-même."""
        self.init()
        r = self.cw("append", "claude", "--to", "claude", "--ask", "x", "--done", "y")
        self.assertNotEqual(r.returncode, 0)
        r = self.cw("release", "claude", "--to", "claude")
        self.assertNotEqual(r.returncode, 0)

    def test_release_done_require_holder(self):
        """NR-2 : release/done refusés si tu ne tiens pas le stylo."""
        self.init()
        self.cw("claim", "claude")
        self.assertNotEqual(self.cw("release", "codex", "--to", "claude").returncode, 0)
        self.assertNotEqual(self.cw("done", "codex").returncode, 0)
        self.assertEqual(self.cw("release", "claude", "--to", "codex").returncode, 0)

    def test_release_done_force_overrides(self):
        self.init()
        self.cw("claim", "claude")
        r = self.cw("done", "codex", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lock()["state"], "DONE")


# ───────────────────────────── robustesse / entrées ────────────────────────

class TestRobustness(CLIBase):
    def test_body_missing_no_traceback(self):
        """NR-5 : --body fichier inexistant → sortie propre, pas de traceback."""
        self.init()
        before = self.md().count("COWORK:TURN")
        r = self.cw("append", "claude", "--to", "codex", "--ask", "x", "--done", "y",
                    "--body", "/no/such/file.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--body", r.stdout + r.stderr)
        self.assertEqual(self.md().count("COWORK:TURN"), before)

    def test_invalid_agent_clean_exit(self):
        self.init()
        r = self.cw("claim", "bob")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_status_requires_init(self):
        r = self.cw("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", (r.stdout + r.stderr).lower())

    def test_malformed_lock_markers_clean_exit(self):
        self.init()
        p = os.path.join(self.d, "COWORK.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace(cowork.LOCK_END, ""))
        r = self.cw("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("corrompu", r.stdout + r.stderr)

    def test_malformed_lock_schema_clean_exit(self):
        """NR-A : valeur LOCK invalide (turn non entier) → sortie propre, pas de traceback."""
        self.init()
        p = os.path.join(self.d, "COWORK.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("turn:     0", "turn:     nope"))
        r = self.cw("claim", "claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("LOCK invalide", r.stdout + r.stderr)

    def test_field_rejects_newline(self):
        self.init()
        r = self.cw("append", "claude", "--to", "codex", "--ask", "a\nb", "--done", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_field_rejects_reserved_marker(self):
        self.init()
        r = self.cw("append", "claude", "--to", "codex",
                    "--ask", "<!-- COWORK:TURN 999 claude BEGIN -->", "--done", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_body_marker_neutralized(self):
        """Injection via --body : le faux marqueur ne passe pas pour un tour."""
        self.init()
        r = self.turn("claude", "codex", body="blah COWORK:TURN 999 claude BEGIN blah")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.cw("status")
        self.assertIn("#1", s.stdout)
        self.assertNotIn("#999", s.stdout)

    def test_wait_interval_invalid_clean_exit(self):
        self.init()
        self.turn("claude", "codex")
        r = self.cw("wait", "claude", "--interval", "-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


# ───────────────────────────── archive ─────────────────────────────────────

class TestArchive(CLIBase):
    def test_archive_preserves_system_turn0(self):
        """NR-6 : archive ne déplace jamais le tour système #0."""
        self.init()
        agents = ["claude", "codex"]
        for n in range(6):
            a, b = agents[n % 2], agents[(n + 1) % 2]
            self.turn(a, b)
        r = self.cw("archive", "--keep", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        live = self.md()
        self.assertIn("COWORK:TURN 0 system", live)
        self.assertIn("COWORK:TURN 6", live)
        self.assertNotIn("COWORK:TURN 1 ", live)
        self.assertEqual(self.lock()["turn"], "6")
        arch = os.path.join(self.d, "COWORK.archive.md")
        self.assertTrue(os.path.exists(arch))
        with open(arch, encoding="utf-8") as f:
            self.assertIn("COWORK:TURN 1 ", f.read())


# ───────────────────────────── wait ────────────────────────────────────────

class TestWait(CLIBase):
    def test_wait_once_return_codes(self):
        self.init()
        self.assertEqual(self.cw("wait", "codex", "--once").returncode, 0)  # IDLE → claimable
        self.turn("claude", "codex")                                        # → AWAITING_CODEX
        self.assertEqual(self.cw("wait", "codex", "--once").returncode, 0)  # son tour
        self.assertEqual(self.cw("wait", "claude", "--once").returncode, 3)  # pas son tour

    def test_wait_once_stale_lock_unblocks(self):
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()
        self.assertEqual(self.cw("wait", "codex", "--once").returncode, 0)


# ───────────────────────────── concurrence ─────────────────────────────────

class TestConcurrency(CLIBase):
    def test_concurrent_claim_claude_vs_codex_single_winner(self):
        """NR-bloquant : N claim claude + N claim codex simultanés depuis IDLE
        → un seul AGENT acquiert (exclusivité), l'autre est totalement exclu ;
        aucun crash, pas de lock résiduel. (Le détenteur peut re-claim = refresh,
        donc plusieurs process du MÊME agent peuvent réussir : c'est attendu.)"""
        self.init()
        cmds = ([["claim", "claude"]] * 8) + ([["claim", "codex"]] * 8)
        procs = [
            subprocess.Popen([sys.executable, "cowork.py", *c], cwd=self.d,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for c in cmds
        ]
        outs = [p.communicate() for p in procs]
        claude_wins = sum(1 for c, p in zip(cmds, procs) if c[1] == "claude" and p.returncode == 0)
        codex_wins = sum(1 for c, p in zip(cmds, procs) if c[1] == "codex" and p.returncode == 0)
        # exactement un agent gagne ; l'autre n'acquiert jamais (mutuelle exclusion)
        self.assertEqual(min(claude_wins, codex_wins), 0,
                         f"les deux agents ont acquis : claude={claude_wins} codex={codex_wins}")
        self.assertGreater(max(claude_wins, codex_wins), 0)
        for out, err in outs:
            self.assertNotIn("Traceback", out + err)
            self.assertNotIn("FileNotFoundError", out + err)
        winner = "claude" if claude_wins else "codex"
        self.assertEqual(self.lock()["state"], f"WORKING_{winner.upper()}")
        self.assertFalse(os.path.exists(os.path.join(self.d, ".cowork.lock")))

    def test_stale_internal_lock_reclaimed(self):
        """Un .cowork.lock abandonné (mtime ancien) est repris, pas de blocage."""
        self.init()
        lockp = os.path.join(self.d, ".cowork.lock")
        with open(lockp, "w", encoding="utf-8") as f:
            f.write("999999:0")  # process fantôme
        old = time.time() - (cowork.LOCK_STALE_S + 30)
        os.utime(lockp, (old, old))
        r = self.cw("claim", "claude")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
