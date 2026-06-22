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
import json
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
SCRIPT = os.path.join(REPO, "m8shift.py")   # canonical tool
SHIM = os.path.join(REPO, "cowork.py")      # deprecated exec-shim (parity test)
sys.path.insert(0, REPO)
import m8shift as cowork  # noqa: E402  (import après ajustement du sys.path)


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

    def test_stanza_does_not_overpromise_autonomy(self):
        """La stanza (lue par l'agent) ne promet plus l'autonomie totale et porte la
        réserve UI : `wait` ne réveille pas l'UI de chat."""
        s = cowork.stanza_for("claude")
        self.assertNotIn("no human help required", s)
        self.assertIn("does not wake your UI", s)

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
        self.d = tempfile.mkdtemp(prefix="m8shift-test-")
        shutil.copy(SCRIPT, os.path.join(self.d, "m8shift.py"))
        shutil.copy(SHIM, os.path.join(self.d, "cowork.py"))  # legacy shim, for parity

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def cw(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, "m8shift.py", *args],
            cwd=self.d, capture_output=True, text=True, input=stdin,
        )

    def md(self):
        with open(os.path.join(self.d, "M8SHIFT.md"), encoding="utf-8") as f:
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
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        t = re.sub(r"expires:\s*.*", "expires:  2020-01-01T00:00:00Z", t, count=1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(t)


# ───────────────────────────── non-régression : init / portabilité ─────────

class TestInit(CLIBase):
    def test_init_creates_kit(self):
        r = self.init()
        for f in ("M8SHIFT.md", "M8SHIFT.protocol.md", "CLAUDE.md", "AGENTS.md"):
            self.assertTrue(os.path.exists(os.path.join(self.d, f)), f)
        lk = self.lock()
        self.assertEqual(lk["state"], "IDLE")
        self.assertEqual(lk["holder"], "none")
        self.assertEqual(lk["turn"], "0")
        self.assertIn("session", r.stdout)

    def test_init_project_name(self):
        self.init("--name", "Mon Super Projet")
        self.assertIn("# M8Shift · Mon Super Projet", self.md())

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
        self.assertEqual(self.lock()["turn"], "1")  # M8SHIFT.md préservé

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

    def test_init_backs_up_modified_anchor(self):
        """init sauvegarde le contenu pré-init d'un ancrage existant avant de le modifier."""
        claude = os.path.join(self.d, "CLAUDE.md")
        original = "# Mes instructions\n\nGARDE-MOI\n"
        with open(claude, "w", encoding="utf-8") as f:
            f.write(original)
        self.init()
        bak = claude + ".m8shift.bak"
        self.assertTrue(os.path.exists(bak), "backup .m8shift.bak attendu")
        with open(bak, encoding="utf-8") as f:
            self.assertEqual(f.read(), original)  # contenu d'origine intact
        with open(claude, encoding="utf-8") as f:
            cur = f.read()
        self.assertIn(cowork.STANZA_BEGIN, cur)   # vivant = stanza + contenu préservé
        self.assertIn("GARDE-MOI", cur)

    def test_fresh_anchor_has_no_backup(self):
        """Un ancrage CRÉÉ par init (inexistant avant) ne génère pas de .m8shift.bak."""
        self.init()
        self.assertFalse(os.path.exists(os.path.join(self.d, "CLAUDE.md.m8shift.bak")))

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
        before = self.md().count("M8SHIFT:TURN")
        r = self.cw("append", "claude", "--to", "codex", "--ask", "x", "--done", "y",
                    "--body", "/no/such/file.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--body", r.stdout + r.stderr)
        self.assertEqual(self.md().count("M8SHIFT:TURN"), before)

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
        p = os.path.join(self.d, "M8SHIFT.md")
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
        p = os.path.join(self.d, "M8SHIFT.md")
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
        self.assertIn("M8SHIFT:TURN 0 system", live)
        self.assertIn("M8SHIFT:TURN 6", live)
        self.assertNotIn("M8SHIFT:TURN 1 ", live)
        self.assertEqual(self.lock()["turn"], "6")
        arch = os.path.join(self.d, "M8SHIFT.archive.md")
        self.assertTrue(os.path.exists(arch))
        with open(arch, encoding="utf-8") as f:
            self.assertIn("M8SHIFT:TURN 1 ", f.read())


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
            subprocess.Popen([sys.executable, "m8shift.py", *c], cwd=self.d,
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
        with open(os.path.join(self.d, "M8SHIFT.protocol.md"), encoding="utf-8") as f:
            self.assertIn("Single-file relay protocol", f.read())
        r = self.cw("claim", "claude")
        self.assertIn("pen taken", r.stdout)

    def test_init_lang_fr_generates_french(self):
        self.init("--lang", "fr")
        self.assertEqual(self.lock().get("lang"), "fr")
        with open(os.path.join(self.d, "M8SHIFT.protocol.md"), encoding="utf-8") as f:
            self.assertIn("Protocole de relais", f.read())
        r = self.cw("claim", "claude")
        self.assertIn("verrou pris", r.stdout)

    def test_env_overrides_runtime_lang(self):
        """COWORK_LANG force la langue des messages runtime, même si le LOCK dit en."""
        self.init()  # lang: en
        env = dict(os.environ, COWORK_LANG="fr")
        r = subprocess.run([sys.executable, "m8shift.py", "claim", "claude"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verrou pris", r.stdout)

    def test_lang_field_in_schema(self):
        """Un champ lang invalide est rejeté proprement (pas de traceback)."""
        self.init()
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("lang:     en", "lang:     xx"))
        r = self.cw("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


# ───────────────────────────── roster (RFC stage 1) ────────────────────────

class TestRoster(CLIBase):
    def test_default_writes_agents_field(self):
        """Sans --agents, le couple par défaut claude,codex est consigné."""
        self.init()
        self.assertEqual(self.lock().get("agents"), "claude,codex")

    def test_custom_pair_field_and_anchors(self):
        """--agents claude,gemini : champ consigné + ancrage GEMINI.md, pas d'AGENTS.md."""
        r = self.init("--agents", "claude,gemini")
        self.assertEqual(self.lock().get("agents"), "claude,gemini")
        self.assertTrue(os.path.exists(os.path.join(self.d, "CLAUDE.md")))
        gemini = os.path.join(self.d, "GEMINI.md")
        self.assertTrue(os.path.exists(gemini), r.stdout)
        with open(gemini, encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(content.startswith(cowork.STANZA_BEGIN))
        self.assertIn("gemini", content)
        # codex hors couple → son ancrage n'est pas créé
        self.assertFalse(os.path.exists(os.path.join(self.d, "AGENTS.md")))

    def test_custom_pair_full_relay(self):
        """Un couple non-défaut relaie réellement (claim/append/alternance)."""
        self.init("--agents", "claude,gemini")
        self.assertEqual(self.cw("claim", "gemini").returncode, 0)
        r = self.cw("append", "gemini", "--to", "claude", "--ask", "x", "--done", "y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lk = self.lock()
        self.assertEqual(lk["state"], "AWAITING_CLAUDE")
        self.assertEqual(lk["turn"], "1")
        # codex n'est pas dans le roster → rejeté proprement
        rc = self.cw("claim", "codex")
        self.assertNotEqual(rc.returncode, 0)
        self.assertNotIn("Traceback", rc.stderr)

    def test_extra_agents_are_active(self):
        """Stage 2: a 3rd declared agent is ACTIVE — the relay routes the baton to it
        (claude → lechat → codex). Replaces the Stage-1 'only first two relay' contract."""
        r = self.init("--agents", "claude,codex,lechat")
        self.assertEqual(self.lock().get("agents"), "claude,codex,lechat")
        self.assertNotIn("first two", r.stdout)              # old degree-2 promise is gone
        self.assertIn("3 agents active", r.stdout)
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertEqual(self.cw("append", "claude", "--to", "lechat",
                                 "--ask", "x", "--done", "y").returncode, 0)
        self.assertEqual(self.lock().get("state"), "AWAITING_LECHAT")
        self.assertEqual(self.cw("claim", "lechat").returncode, 0)   # 3rd agent is active
        self.assertEqual(self.cw("append", "lechat", "--to", "codex",
                                 "--ask", "x", "--done", "z").returncode, 0)

    def test_agents_field_survives_claim(self):
        """Le champ agents (roster complet) est préservé par un claim (set_lock)."""
        self.init("--agents", "claude,codex,lechat")
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertEqual(self.lock().get("agents"), "claude,codex,lechat")

    def test_bad_roster_single_name_refused(self):
        """--agents avec un seul nom est refusé proprement."""
        r = self.cw("init", "--agents", "claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("two", (r.stdout + r.stderr).lower())

    def test_unknown_agent_anchor_best_effort(self):
        """Un agent sans ancrage connu : init réussit + avertit (best effort, Q5)."""
        r = self.init("--agents", "claude,zzz")
        self.assertIn("anchor", r.stdout.lower())
        self.assertFalse(os.path.exists(os.path.join(self.d, "zzz.md")))
        # il peut tout de même relayer (amorçage manuel) :
        self.assertEqual(self.cw("claim", "zzz").returncode, 0)

    def test_status_shows_active_pair(self):
        self.init("--agents", "claude,codex,lechat")
        r = self.cw("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("agents", r.stdout)
        self.assertIn("claude,codex", r.stdout)

    def test_reinit_preserves_existing_roster(self):
        """Sans --force, ré-init préserve le roster du M8SHIFT.md vivant."""
        self.init("--agents", "claude,gemini")
        r = self.init()  # ré-init sans --agents ni --force
        self.assertEqual(self.lock().get("agents"), "claude,gemini")

    def test_reinit_same_roster_idempotent(self):
        """Ré-init avec le MÊME roster (sans --force) réussit, idempotent."""
        self.init("--agents", "claude,gemini")
        self.init("--agents", "claude,gemini")  # même couple → OK
        self.assertEqual(self.lock().get("agents"), "claude,gemini")

    def test_reinit_different_roster_refused_without_force(self):
        """Ré-init avec un roster DIFFÉRENT (sans --force) est refusé proprement."""
        self.init("--agents", "claude,codex")
        r = self.cw("init", "--agents", "claude,gemini")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--force", r.stdout + r.stderr)
        self.assertEqual(self.lock().get("agents"), "claude,codex")  # inchangé

    def test_reinit_force_replaces_roster(self):
        """--force réécrit M8SHIFT.md avec le nouveau roster."""
        self.init("--agents", "claude,gemini")
        self.init("--agents", "claude,codex", "--force")
        self.assertEqual(self.lock().get("agents"), "claude,codex")

    def test_collision_codex_then_lechat(self):
        """codex,lechat : codex possède AGENTS.md, lechat est averti (collision)."""
        r = self.init("--agents", "codex,lechat")
        with open(os.path.join(self.d, "AGENTS.md"), encoding="utf-8") as f:
            agents = f.read()
        self.assertEqual(agents.count(cowork.STANZA_BEGIN), 1)
        self.assertIn("You are **codex**", agents)
        self.assertIn("already used", r.stdout)

    def test_collision_lechat_then_codex(self):
        """NR-collision (ordre) : lechat possède AGENTS.md, codex (branche dédiée) averti."""
        r = self.init("--agents", "lechat,codex")
        self.assertNotIn("Traceback", r.stderr)
        with open(os.path.join(self.d, "AGENTS.md"), encoding="utf-8") as f:
            agents = f.read()
        self.assertEqual(agents.count(cowork.STANZA_BEGIN), 1)
        self.assertIn("You are **lechat**", agents)  # le 1er gagne, pas d'écrasement
        self.assertIn("already used", r.stdout)

    def test_copilot_unmapped_best_effort(self):
        """copilot (ancrage imbriqué) hors étape 1 : non mappé → avertissement, pas de fichier."""
        r = self.init("--agents", "claude,copilot")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("no known anchor", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".github")))
        # copilot reste un membre du roster : il peut relayer (amorçage manuel)
        self.assertEqual(self.cw("claim", "copilot").returncode, 0)

    def test_init_rejects_invalid_stored_roster_without_force(self):
        """init sans --force échoue sur un `agents:` stocké invalide (pas de préservation)."""
        self.init()
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("agents:   claude,codex", "agents:   claude,codex,@@"))
        r = self.cw("init")  # sans --force → refuse de préserver la corruption
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("invalid LOCK", r.stdout + r.stderr)
        r2 = self.cw("init", "--force")  # --force répare / re-sème
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(self.lock().get("agents"), "claude,codex")

    def test_generated_protocol_is_pair_agnostic(self):
        """Le protocole généré ne fige plus l'identité claude/codex : ouverture, holder,
        états, commentaire TURN et schéma d'amorçage tous génériques."""
        self.init("--agents", "gemini,lechat")
        with open(os.path.join(self.d, "M8SHIFT.protocol.md"), encoding="utf-8") as f:
            proto = f.read()
        # plus aucune affirmation exclusive claude/codex
        self.assertNotIn("either `claude` or `codex`", proto)         # §0 identité
        self.assertNotIn("`claude` \\| `codex` \\| `none`", proto)    # holder enum
        self.assertNotIn("# claude | codex", proto)                   # commentaire TURN
        self.assertNotIn("WORKING_CLAUDE", proto)                     # énum d'états figée
        self.assertNotIn("(Claude) + AGENTS.md (Codex)", proto)       # schéma d'amorçage
        self.assertNotIn("block into `CLAUDE.md` and", proto)         # §8 bullet d'injection
        # formulations génériques présentes
        self.assertIn("two active agents", proto)
        self.assertIn("an active agent", proto)
        self.assertIn("each active agent's anchor", proto)            # §8 bullet générique
        self.assertIn("WORKING_<X>", proto)
        # la bannière du M8SHIFT.md généré ne fige plus le couple non plus
        md = self.md()
        self.assertNotIn("Claude ⇄ Codex", md)
        self.assertIn("multi-agent relay", md)
        # le protocole généré ne promet plus l'autonomie totale + porte la réserve UI
        self.assertNotIn("operate without human help", proto)
        self.assertIn("does not wake your chat UI", proto)

    def test_invalid_token_in_agents_rejected(self):
        """NR-token : un token --agents mal formé est rejeté, pas filtré en silence."""
        r = self.cw("init", "--agents", "claude,@@,codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))

    def test_invalid_token_in_lock_rejected(self):
        """NR-token (LOCK) : un roster stocké partiellement invalide est rejeté."""
        self.init()
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("agents:   claude,codex", "agents:   claude,codex,@@"))
        r = self.cw("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("invalid LOCK", r.stdout + r.stderr)

    def test_hyphen_name_visible_and_archivable(self):
        """NR-hyphen : un agent `foo-bar` est reconnu par status ET archive (regex TURN)."""
        self.init("--agents", "foo-bar,baz")
        self.assertEqual(self.cw("claim", "foo-bar").returncode, 0)
        r = self.cw("append", "foo-bar", "--to", "baz", "--ask", "x", "--done", "y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.cw("status")
        self.assertIn("#1", s.stdout)
        self.assertIn("foo-bar", s.stdout)
        a = self.cw("archive", "--keep", "0")
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertNotIn("M8SHIFT:TURN 1 foo-bar", self.md())
        with open(os.path.join(self.d, "M8SHIFT.archive.md"), encoding="utf-8") as f:
            self.assertIn("M8SHIFT:TURN 1 foo-bar", f.read())

    def test_bootstrap_text_uses_active_pair(self):
        """NR-bootstrap : les textes générés nomment le couple actif, pas claude/codex."""
        r = self.init("--agents", "gemini,lechat")
        self.assertIn("claim gemini", r.stdout)
        self.assertNotIn("claim claude", r.stdout)
        md = self.md()
        self.assertIn("claim gemini", md)
        self.assertNotIn("claim claude", md)


# ───────────────────────── Phase 2 : rename + backward-compat ───────────────

class TestPhase2Compat(CLIBase):
    """Phase-2 rename (cowork.py→m8shift.py, COWORK.*→M8SHIFT.*): existing CoWork
    projects keep working (dual-read + brand-preserving writes); `migrate-brand`
    converts them; `cowork.py` stays a parity shim."""

    def _read(self, name):
        with open(os.path.join(self.d, name), encoding="utf-8") as f:
            return f.read()

    def _legacy_living(self, state="IDLE", holder="none", turn="0"):
        c = cowork
        body = (
            "# COWORK · Legacy\n\n> Outil → `./cowork.py status`.\n\n"
            f"{c.OLD_LOCK_BEGIN}\n"
            f"holder:   {holder}\nstate:    {state}\nagents:   claude,codex\n"
            f"lang:     en\nturn:     {turn}\nsince:    -\nexpires:  -\nnote:     -\n"
            f"{c.OLD_LOCK_END}\n\n"
            "<!-- COWORK:TURN 0 system BEGIN -->\n- from:    system\n- files:   COWORK.md\n"
            "<!-- COWORK:TURN 0 system END -->\n"
        )
        with open(os.path.join(self.d, "COWORK.md"), "w", encoding="utf-8") as f:
            f.write(body)

    def _legacy_project(self):
        self._legacy_living()
        with open(os.path.join(self.d, "COWORK.protocol.md"), "w", encoding="utf-8") as f:
            f.write("# COWORK protocol\n\nUse `./cowork.py`. Marker COWORK:LOCK.\n")

    def test_fresh_init_is_pure_m8shift(self):
        self.init()
        self.assertTrue(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "COWORK.md")))
        live = self._read("M8SHIFT.md")
        self.assertIn("M8SHIFT:LOCK:BEGIN", live)
        self.assertNotIn("COWORK", live)

    def test_legacy_dual_read_in_place(self):
        self._legacy_living()
        self.assertEqual(self.cw("status").returncode, 0)
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertEqual(self.cw("append", "claude", "--to", "codex",
                                 "--ask", "a", "--done", "b").returncode, 0)
        live = self._read("COWORK.md")
        self.assertIn("COWORK:TURN 1 claude", live)      # brand preserved
        self.assertNotIn("M8SHIFT:", live)               # never silently re-marked
        self.assertFalse(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))  # no orphan

    def test_append_brand_matches_file(self):
        self._legacy_living()
        self.cw("claim", "claude")
        self.cw("append", "claude", "--to", "codex", "--ask", "a", "--done", "b")
        self.assertIn("COWORK:TURN 1", self._read("COWORK.md"))
        d2 = tempfile.mkdtemp(prefix="m8shift-test-")
        self.addCleanup(shutil.rmtree, d2, True)
        shutil.copy(SCRIPT, os.path.join(d2, "m8shift.py"))
        for c in (["init"], ["claim", "claude"],
                  ["append", "claude", "--to", "codex", "--ask", "a", "--done", "b"]):
            subprocess.run([sys.executable, "m8shift.py", *c], cwd=d2, capture_output=True)
        with open(os.path.join(d2, "M8SHIFT.md"), encoding="utf-8") as f:
            self.assertIn("M8SHIFT:TURN 1", f.read())

    def test_set_lock_preserves_brand(self):
        c = cowork
        for begin, end in ((c.LOCK_BEGIN, c.LOCK_END), (c.OLD_LOCK_BEGIN, c.OLD_LOCK_END)):
            text = f"x\n{begin}\nholder:   none\nstate:    IDLE\nturn:     0\n{end}\ny\n"
            out = c.set_lock(text, {"holder": "claude", "state": "WORKING_CLAUDE", "turn": "1"})
            self.assertIn(begin, out)                    # same brand kept
            self.assertEqual(c.get_lock(out)["holder"], "claude")

    def test_clean_body_neutralizes_both_brands(self):
        c = cowork
        self.assertNotIn("COWORK:TURN", c.clean_body("x COWORK:TURN 9 a BEGIN"))
        self.assertNotIn("M8SHIFT:TURN", c.clean_body("x M8SHIFT:TURN 9 a BEGIN"))

    def test_both_brand_markers_reserved(self):
        for marker in ("COWORK:LOCK", "COWORK:TURN", "M8SHIFT:LOCK", "M8SHIFT:TURN"):
            self.assertIn(marker, cowork.RESERVED)

    def test_shim_parity(self):
        self.init()
        a = self.cw("status")
        b = subprocess.run([sys.executable, "cowork.py", "status"],
                           cwd=self.d, capture_output=True, text=True)
        self.assertEqual(a.returncode, b.returncode)
        self.assertEqual(a.stdout, b.stdout)             # stdout identical
        self.assertIn("deprecated", b.stderr)            # note on stderr only

    def test_migrate_brand_full(self):
        self._legacy_project()
        r = self.cw("migrate-brand")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "M8SHIFT.protocol.md")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "COWORK.md")))
        live = self._read("M8SHIFT.md")
        self.assertIn("M8SHIFT:LOCK", live)
        self.assertNotIn("COWORK:", live)
        self.assertTrue(os.path.exists(os.path.join(self.d, "COWORK.md.m8shift.bak")))
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertEqual(self.cw("append", "claude", "--to", "codex",
                                 "--ask", "a", "--done", "b").returncode, 0)
        self.assertIn("M8SHIFT:TURN 1", self._read("M8SHIFT.md"))

    def test_migrate_dry_run_then_idempotent(self):
        self._legacy_project()
        before = self._read("COWORK.md")
        self.assertEqual(self.cw("migrate-brand", "--dry-run").returncode, 0)
        self.assertEqual(self._read("COWORK.md"), before)            # nothing written
        self.assertFalse(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))
        self.cw("migrate-brand")
        self.assertIn("nothing to migrate", self.cw("migrate-brand").stdout)

    def test_migrate_refuses_ambiguous(self):
        self._legacy_project()
        open(os.path.join(self.d, "M8SHIFT.md"), "w").close()        # both names exist
        r = self.cw("migrate-brand")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("both", r.stdout + r.stderr)

    def test_migrate_refuses_mid_turn(self):
        self._legacy_living(state="WORKING_CLAUDE", holder="claude")
        r = self.cw("migrate-brand")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mid-turn", r.stdout + r.stderr)

    def test_migrate_uses_git_when_tracked(self):
        self._legacy_project()
        subprocess.run(["git", "init", "-q"], cwd=self.d, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.d, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], cwd=self.d, capture_output=True)
        self.assertEqual(self.cw("migrate-brand").returncode, 0)
        tracked = subprocess.run(["git", "ls-files"], cwd=self.d,
                                 capture_output=True, text=True).stdout
        self.assertIn("M8SHIFT.md", tracked)
        self.assertNotIn("COWORK.md\n", tracked)

    def test_m8shift_lang_env_primary(self):
        self.init()
        env = dict(os.environ, M8SHIFT_LANG="fr")
        r = subprocess.run([sys.executable, "m8shift.py", "claim", "claude"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertIn("verrou", r.stdout + r.stderr)     # FR runtime message



# ───────────────────────── Stage 2 increment 1 : read commands ──────────────

class TestReadCommands(CLIBase):
    def _seed(self):
        self.init()
        self.turn("claude", "codex", done="did A", files="a.py,b.py")
        self.turn("codex", "claude", done="did B", files="c.py")  # ends AWAITING_CLAUDE

    def test_status_json(self):
        self._seed()
        r = self.cw("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["state"], "AWAITING_CLAUDE")
        self.assertEqual(d["holder"], "claude")
        self.assertEqual(d["agents_active"], ["claude", "codex"])
        self.assertFalse(d["stale"])
        self.assertEqual(d["last_turn"], {"n": 2, "agent": "codex"})

    def test_status_json_stale(self):
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()
        d = json.loads(self.cw("status", "--json").stdout)
        self.assertTrue(d["stale"])

    def test_recap(self):
        self._seed()
        out = self.cw("recap", "--turns", "2").stdout
        self.assertIn("AWAITING_CLAUDE", out)
        self.assertIn("did A", out)
        self.assertIn("did B", out)

    def test_log_timeline(self):
        self._seed()
        out = self.cw("log").stdout
        self.assertIn("#1", out)
        self.assertIn("#2", out)
        self.assertIn("claude -> codex", out)
        limited = self.cw("log", "--limit", "1").stdout
        self.assertIn("#2", limited)
        self.assertNotIn("#1", limited)
        self.assertIn("did B", self.cw("log", "--oneline").stdout)

    def test_peek_my_turn(self):
        self._seed()  # AWAITING_CLAUDE ; last handoff to claude = turn 2 (from codex)
        r = self.cw("peek", "claude")
        self.assertEqual(r.returncode, 0)
        self.assertIn("from=codex", r.stdout)
        self.assertIn("done=did B", r.stdout)

    def test_peek_not_my_turn(self):
        self._seed()  # codex is not awaited → rc 3 ; last handoff to codex = turn 1
        r = self.cw("peek", "codex")
        self.assertEqual(r.returncode, 3)
        self.assertIn("from=claude", r.stdout)

    def test_parse_turns_preserves_unknown_keys(self):
        text = ("x\n<!-- M8SHIFT:TURN 5 claude BEGIN -->\n"
                "- from:    claude\n- to:      codex\n- role:    coordinator\n"
                "- x_custom: hello world\n\nbody text here\n"
                "<!-- M8SHIFT:TURN 5 claude END -->\ny\n")
        turns = cowork.parse_turns(text)
        self.assertEqual(len(turns), 1)
        t = turns[0]
        self.assertEqual((t["n"], t["agent"]), (5, "claude"))
        self.assertEqual(t["fields"]["role"], "coordinator")       # unknown advisory key kept
        self.assertEqual(t["fields"]["x_custom"], "hello world")   # open x_ namespace kept
        self.assertEqual(t["body"], "body text here")

    def test_read_commands_dual_read_legacy(self):
        # a legacy COWORK.md (old markers) must be readable by log/status --json
        c = cowork
        body = (
            "# COWORK · Legacy\n\n"
            f"{c.OLD_LOCK_BEGIN}\n"
            "holder:   claude\nstate:    AWAITING_CLAUDE\nagents:   claude,codex\n"
            "lang:     en\nturn:     1\nsince:    -\nexpires:  -\nnote:     -\n"
            f"{c.OLD_LOCK_END}\n\n"
            "<!-- COWORK:TURN 0 system BEGIN -->\n- from:    system\n- to:      none\n"
            "<!-- COWORK:TURN 0 system END -->\n\n"
            "<!-- COWORK:TURN 1 codex BEGIN -->\n- from:    codex\n- to:      claude\n"
            "- done:    legacy work\n<!-- COWORK:TURN 1 codex END -->\n"
        )
        with open(os.path.join(self.d, "COWORK.md"), "w", encoding="utf-8") as f:
            f.write(body)
        d = json.loads(self.cw("status", "--json").stdout)
        self.assertEqual(d["last_turn"], {"n": 1, "agent": "codex"})
        self.assertIn("legacy work", self.cw("log").stdout)
        self.assertEqual(self.cw("peek", "claude").returncode, 0)   # AWAITING_CLAUDE



# ───────────────────────── Stage 2 increment 2 : N-agent relay ──────────────

class TestNAgentRelay(CLIBase):
    # — stanza byte-compat (top risk: inject_anchor re-injects idempotently) —
    def test_stanza_pair_mode_byte_identical(self):
        self.addCleanup(setattr, cowork, "ROSTER", cowork.AGENTS)
        cowork.ROSTER = ("claude", "codex")
        s = cowork.stanza_for("claude")
        self.assertIn("codex", s)               # the single peer, as before
        self.assertIn("WORKING_CODEX", s)
        self.assertNotIn("<agent>", s)          # the N>2 placeholder must NOT appear
        self.assertNotIn("<AGENT>", s)

    def test_stanza_n_agents_uses_placeholder(self):
        self.addCleanup(setattr, cowork, "ROSTER", cowork.AGENTS)
        cowork.ROSTER = ("claude", "codex", "gemini")
        s = cowork.stanza_for("claude")
        self.assertIn("<agent>", s)             # generic peer placeholder for N>2
        self.assertIn("WORKING_<AGENT>", s)

    # — cmd_wait self-exclusion (a self-held stale lock must stay silent) —
    def test_wait_self_stale_is_silent(self):
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()                 # claude's OWN lock is now stale
        r = self.cw("wait", "claude", "--once")
        self.assertEqual(r.returncode, 3)       # not your turn, as before the edit
        self.assertNotIn("stale", (r.stdout + r.stderr).lower())

    def test_wait_third_agent_stale_detected(self):
        self.init("--agents", "claude,codex,gemini")
        self.cw("claim", "gemini")              # 3rd agent holds the pen
        self.set_expires_past()
        r = self.cw("wait", "claude", "--once")
        self.assertEqual(r.returncode, 0)       # a stale non-self lock unblocks me
        self.assertIn("gemini", r.stdout)       # names the REAL holder, not other()

    def test_wait_peer_stale_unchanged_pair(self):
        self.init()
        self.cw("claim", "codex")
        self.set_expires_past()
        r = self.cw("wait", "claude", "--once")
        self.assertEqual(r.returncode, 0)
        self.assertIn("codex", r.stdout)        # pair-mode message names codex, as before

    # — status / recap show the full roster (byte-identical for N=2 elsewhere) —
    def test_status_recap_show_full_roster(self):
        self.init("--agents", "claude,codex,gemini")
        d = json.loads(self.cw("status", "--json").stdout)
        self.assertEqual(d["agents_active"], ["claude", "codex", "gemini"])
        self.assertIn("gemini", self.cw("status").stdout)
        self.assertIn("gemini", self.cw("recap").stdout)

    # — 3rd agent with a unique anchor gets a stanza —
    def test_third_agent_gets_anchor(self):
        self.init("--agents", "claude,codex,gemini")
        p = os.path.join(self.d, "GEMINI.md")
        self.assertTrue(os.path.exists(p), "GEMINI.md should be created for the 3rd agent")
        with open(p, encoding="utf-8") as f:
            self.assertIn(cowork.STANZA_BEGIN, f.read())

    # — the CLAUDE→Codex bridge still fires inside a >2 active set —
    def test_bridge_survives_three_agents(self):
        with open(os.path.join(self.d, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# Shared\n\nRULE\n")
        self.init("--agents", "claude,codex,gemini")
        with open(os.path.join(self.d, "AGENTS.md"), encoding="utf-8") as f:
            self.assertIn(cowork.BRIDGE["en"].strip(), f.read())

    # — no locale still promises 'only the first two' after activation —
    def test_no_first_two_promise_after_activation(self):
        self.assertNotIn("first two", self.init("--agents", "claude,codex,gemini").stdout)
        r = self.init("--agents", "claude,codex,gemini", "--lang", "fr", "--force")
        self.assertNotIn("deux premiers", r.stdout)



if __name__ == "__main__":
    unittest.main(verbosity=2)
