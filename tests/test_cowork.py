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
from unittest import mock

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

    def test_protocol_docs_in_sync(self):
        """Non-régression doc : docs/en/protocol.md et docs/fr/protocole.md ==
        cowork.PROTOCOL[lang] (chaque protocole rendu reste fidèle au template)."""
        for lang, rel in (("en", "docs/en/protocol.md"), ("fr", "docs/fr/protocole.md")):
            path = os.path.join(REPO, rel)
            if not os.path.exists(path):
                self.skipTest(f"{rel} absent")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), cowork.PROTOCOL[lang],
                                 f"{rel} a divergé de cowork.PROTOCOL['{lang}'] — régénère.")

    def test_ambiguous_anchor_variants_refused(self):
        """Deux variantes sur un FS sensible sont refusées sans choix arbitraire."""
        with mock.patch.object(cowork.os, "listdir",
                               return_value=["AGENTS.md", "agents.md"]):
            with self.assertRaises(SystemExit):
                cowork.ensure_canonical_anchor("AGENTS.md")


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
        r = self.init()
        for f in ("COWORK.md", "COWORK.protocol.md", "CLAUDE.md", "AGENTS.md"):
            self.assertTrue(os.path.exists(os.path.join(self.d, f)), f)
        lk = self.lock()
        self.assertEqual(lk["state"], "IDLE")
        self.assertEqual(lk["holder"], "none")
        self.assertEqual(lk["turn"], "0")
        self.assertIn("session", r.stdout)

    def test_init_project_name(self):
        self.init("--name", "Mon Super Projet")
        self.assertIn("# COWORK · Mon Super Projet", self.md())

    def test_missing_agents_bridges_existing_claude_instructions(self):
        """Un projet Claude-only devient utilisable par Codex sans action manuelle."""
        with open(os.path.join(self.d, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# Instructions partagées\n\nREGLE-METIER\n")

        r = self.init()

        with open(os.path.join(self.d, "AGENTS.md"), encoding="utf-8") as f:
            agents = f.read()
        self.assertTrue(agents.startswith(cowork.STANZA_BEGIN))
        self.assertIn(cowork.BRIDGE["en"].strip(), agents)
        self.assertIn("automatic bridge", r.stdout)

    def test_existing_agents_does_not_receive_claude_bridge(self):
        """Des instructions Codex existantes restent autonomes et inchangées."""
        with open(os.path.join(self.d, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# Instructions Claude\n")
        with open(os.path.join(self.d, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write("# Instructions Codex\n\nREGLE-CODEX\n")

        self.init()

        with open(os.path.join(self.d, "AGENTS.md"), encoding="utf-8") as f:
            agents = f.read()
        self.assertIn("REGLE-CODEX", agents)
        self.assertNotIn(cowork.BRIDGE["en"].strip(), agents)

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
        """NR-7 : une variante unique est réutilisée/normalisée sans doublon."""
        with open(os.path.join(self.d, "claude.md"), "w", encoding="utf-8") as f:
            f.write("# claude.md\n\nGARDE-MOI\n")
        r = self.init()
        anchors = [f for f in os.listdir(self.d) if f.lower() == "claude.md"]
        self.assertEqual(len(anchors), 1, anchors)
        with open(os.path.join(self.d, anchors[0]), encoding="utf-8") as f:
            self.assertIn("GARDE-MOI", f.read())
        self.assertIn(anchors[0], r.stdout)  # le nom rapporté est le nom réel on-disk

    def test_codex_anchor_is_canonical_on_case_sensitive_fs(self):
        """NR-D : `agents.md` doit rester auto-chargeable par le chemin `AGENTS.md`."""
        lower = os.path.join(self.d, "agents.md")
        canonical = os.path.join(self.d, "AGENTS.md")
        with open(lower, "w", encoding="utf-8") as f:
            f.write("# consignes existantes\n\nGARDE-CODEX\n")
        self.init()

        self.assertTrue(os.path.exists(canonical))
        variants = [f for f in os.listdir(self.d) if f.casefold() == "agents.md"]
        self.assertEqual(variants, ["AGENTS.md"])
        with open(canonical, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GARDE-CODEX", content)
        self.assertIn(cowork.STANZA_BEGIN, content)

    @unittest.skipUnless(shutil.which("git"), "git absent")
    def test_tracked_anchor_case_rename_updates_git_index(self):
        """NR-G : un agents.md suivi devient AGENTS.md dans l'index, même sur macOS."""
        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=self.d, capture_output=True, text=True,
            )

        self.assertEqual(git("init", "-q").returncode, 0)
        self.assertEqual(git("config", "user.email", "test@example.invalid").returncode, 0)
        self.assertEqual(git("config", "user.name", "cowork test").returncode, 0)
        with open(os.path.join(self.d, "agents.md"), "w", encoding="utf-8") as f:
            f.write("# consignes suivies\n")
        self.assertEqual(git("add", "agents.md").returncode, 0)
        self.assertEqual(git("commit", "-qm", "fixture").returncode, 0)

        self.init()

        tracked = git("ls-files").stdout.splitlines()
        self.assertIn("AGENTS.md", tracked)
        self.assertNotIn("agents.md", tracked)

    def test_stanza_is_moved_to_anchor_start(self):
        """NR-E : la stanza reste avant le contenu utilisateur, y compris après ré-init."""
        claude = os.path.join(self.d, "CLAUDE.md")
        with open(claude, "w", encoding="utf-8") as f:
            f.write("# Contenu projet\n\nGARDE-MOI\n")
        self.init()
        self.init()
        with open(claude, encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(content.startswith(cowork.STANZA_BEGIN))
        self.assertEqual(content.count(cowork.STANZA_BEGIN), 1)
        self.assertIn("GARDE-MOI", content)

    def test_codex_override_also_receives_stanza(self):
        """NR-F : AGENTS.override.md masque AGENTS.md, donc les deux sont synchronisés."""
        override = os.path.join(self.d, "AGENTS.override.md")
        with open(override, "w", encoding="utf-8") as f:
            f.write("# Override temporaire\n\nGARDE-OVERRIDE\n")

        r = self.init()

        for name in ("AGENTS.md", "AGENTS.override.md"):
            with open(os.path.join(self.d, name), encoding="utf-8") as f:
                content = f.read()
            self.assertTrue(content.startswith(cowork.STANZA_BEGIN), name)
            self.assertEqual(content.count(cowork.STANZA_BEGIN), 1)
        with open(override, encoding="utf-8") as f:
            self.assertIn("GARDE-OVERRIDE", f.read())
        self.assertIn("Codex override active", r.stdout)

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
        self.assertIn("pen", (r.stdout + r.stderr).lower())
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
        self.assertIn("stale", self.lock()["note"])

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
        self.assertIn("corrupted", r.stdout + r.stderr)

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
        self.assertIn("invalid LOCK", r.stdout + r.stderr)

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


# ───────────────────────────── i18n (en / fr) ──────────────────────────────

class TestI18n(CLIBase):
    def test_init_default_is_english(self):
        self.init()
        self.assertEqual(self.lock().get("lang"), "en")
        with open(os.path.join(self.d, "COWORK.protocol.md"), encoding="utf-8") as f:
            self.assertIn("Single-file relay protocol", f.read())
        r = self.cw("claim", "claude")
        self.assertIn("pen taken", r.stdout)

    def test_init_lang_fr_generates_french(self):
        self.init("--lang", "fr")
        self.assertEqual(self.lock().get("lang"), "fr")
        with open(os.path.join(self.d, "COWORK.protocol.md"), encoding="utf-8") as f:
            self.assertIn("Protocole de relais", f.read())
        r = self.cw("claim", "claude")
        self.assertIn("verrou pris", r.stdout)

    def test_env_overrides_runtime_lang(self):
        """COWORK_LANG force la langue des messages runtime, même si le LOCK dit en."""
        self.init()  # lang: en
        env = dict(os.environ, COWORK_LANG="fr")
        r = subprocess.run([sys.executable, "cowork.py", "claim", "claude"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verrou pris", r.stdout)

    def test_lang_field_in_schema(self):
        """Un champ lang invalide est rejeté proprement (pas de traceback)."""
        self.init()
        p = os.path.join(self.d, "COWORK.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("lang:     en", "lang:     xx"))
        r = self.cw("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
