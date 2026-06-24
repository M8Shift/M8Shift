#!/usr/bin/env python3
"""Tests M8Shift — unitaires (fonctions pures) + non-régression (CLI, bord à bord).

Lancer :  python3 -m unittest discover -s tests        (depuis la racine du repo)
   ou  :  python3 tests/test_m8shift.py

Modèle : `claim` est obligatoire et exclusif avant de travailler ; `append` n'est
accepté que depuis `WORKING_<agent>`. Les tests CLI copient `m8shift.py` dans un
dossier temporaire isolé et l'exécutent en sous-processus — comme un agent.
Les tests gardent l'alias interne `cowork` uniquement pour réduire le bruit historique.
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
SCRIPT = os.path.join(REPO, "m8shift.py")   # canonical tool (M8Shift-only since v3.0.0)
sys.path.insert(0, REPO)
import m8shift as cowork  # noqa: E402  (import après ajustement du sys.path)

VERSION = "3.11.0"


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

    def test_display_time_keeps_utc_and_adds_local_label(self):
        out = cowork.display_time("2026-06-24T13:52:46Z")
        self.assertIn("2026-06-24T13:52:46Z", out)
        self.assertIn(" local ", out)
        self.assertEqual(cowork.display_time("-"), "-")
        self.assertEqual(cowork.display_time("not-a-date"), "not-a-date")

    def test_display_duration(self):
        self.assertEqual(cowork.display_duration(None), "-")
        self.assertEqual(cowork.display_duration(0), "00h 00m 00s")
        self.assertEqual(cowork.display_duration(3661), "01h 01m 01s")
        self.assertEqual(cowork.display_duration(90061), "1d 01h 01m 01s")
        self.assertEqual(cowork.display_duration(-1), "00h 00m 00s")

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
        out = cowork.clean_body("x M8SHIFT:TURN 999 claude BEGIN y")
        self.assertNotIn("M8SHIFT:TURN", out)

    def test_protocol_docs_in_sync(self):
        """Doc sync (EN-only core): docs/en == the core EN template; docs/<lang> == the
        i18n/<lang> pack body byte-for-byte (regenerate with scripts/gen_docs.py)."""
        cases = [("docs/en/protocol.md", cowork.PROTOCOL["en"])]
        fr_pack = os.path.join(REPO, "i18n", "fr", "protocol.md")
        if os.path.exists(fr_pack):
            with open(fr_pack, encoding="utf-8") as f:
                cases.append(("docs/fr/protocole.md", f.read()))
        for rel, expected in cases:
            path = os.path.join(REPO, rel)
            if not os.path.exists(path):
                self.skipTest(f"{rel} absent")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), expected,
                                 f"{rel} a divergé — régénère (scripts/gen_docs.py).")

    def test_ambiguous_anchor_variants_refused(self):
        """Deux variantes sur un FS sensible sont refusées sans choix arbitraire."""
        with mock.patch.object(cowork.os, "listdir",
                               return_value=["AGENTS.md", "agents.md"]):
            with self.assertRaises(SystemExit):
                cowork.ensure_canonical_anchor("AGENTS.md")

    def test_parse_session_events_skips_malformed(self):
        text = (
            '{"event":"start","session_id":"20260624T120000Z-1234abcd"}\n'
            "garbage\n"
            '{"event":"done","session_id":"20260624T120000Z-1234abcd"}\n'
        )
        events = cowork.parse_session_events(text)
        self.assertEqual([e["event"] for e in events], ["start", "done"])


# ───────────────────────────── base CLI (sous-processus isolé) ──────────────

class CLIBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="m8shift-test-")
        shutil.copy(SCRIPT, os.path.join(self.d, "m8shift.py"))

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


class InjectedFRBase(CLIBase):
    """CLIBase whose per-test m8shift.py is an en+fr BUILD (via m8shift-i18n.py), so the
    FR runtime / `--lang fr` / PROTOCOL['fr'] paths exist on the otherwise EN-only core."""
    _enfr = None

    @classmethod
    def setUpClass(cls):
        cls._build_dir = tempfile.mkdtemp(prefix="m8shift-enfr-")
        r = subprocess.run(
            [sys.executable, os.path.join(REPO, "m8shift-i18n.py"),
             "--langs", "fr", "--into", cls._build_dir],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise AssertionError("m8shift-i18n.py build failed: " + r.stderr)
        cls._enfr = os.path.join(cls._build_dir, "m8shift.py")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._build_dir, ignore_errors=True)

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="m8shift-test-")
        shutil.copy(self._enfr, os.path.join(self.d, "m8shift.py"))


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
                    "--ask", "<!-- M8SHIFT:TURN 999 claude BEGIN -->", "--done", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_body_marker_neutralized(self):
        """Injection via --body : le faux marqueur ne passe pas pour un tour."""
        self.init()
        r = self.turn("claude", "codex", body="blah M8SHIFT:TURN 999 claude BEGIN blah")
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


class TestWatch(CLIBase):
    def test_watch_once_is_read_only_and_shows_next_action(self):
        self.init()
        before = self.md()
        r = self.cw("watch", "--for", "codex", "--once")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.md(), before)
        self.assertIn("watch", r.stdout)
        self.assertIn("m8shift.py v", r.stdout)
        self.assertIn("next codex", r.stdout)

    def test_watch_interval_invalid_clean_exit(self):
        self.init()
        r = self.cw("watch", "--interval", "0", "--once")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--interval", r.stdout + r.stderr)


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
        # formulations génériques présentes (N-agent, plus de "two active agents" figé)
        self.assertNotIn("two active agents", proto)
        self.assertIn("active agents", proto)
        self.assertIn("roster", proto)
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
        self.assertRegex(d["session_started_at"], r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
        self.assertIsInstance(d["session_duration_seconds"], int)
        self.assertGreaterEqual(d["session_duration_seconds"], 0)
        self.assertRegex(d["session_duration"], r"(\d+d )?\d\dh \d\dm \d\ds")
        self.assertNotIn(" local ", r.stdout)  # machine output stays canonical UTC

    def test_status_and_recap_show_local_time_labels(self):
        self.init()
        status = self.cw("status").stdout
        recap = self.cw("recap").stdout
        self.assertRegex(status, r"since\s+\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ  local ")
        self.assertRegex(status, r"started\s+\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ  local ")
        self.assertRegex(status, r"duration\s+(\d+d )?\d\dh \d\dm \d\ds")
        self.assertRegex(recap, r"since\s+\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ  local ")
        self.assertIn("expires  -", status)

    def test_status_session_metadata_degrades_without_ledger(self):
        self.init()
        os.remove(os.path.join(self.d, "M8SHIFT.sessions.jsonl"))
        status = self.cw("status").stdout
        d = json.loads(self.cw("status", "--json").stdout)
        self.assertRegex(status, r"started\s+-")
        self.assertRegex(status, r"duration\s+-")
        self.assertEqual(d["session_started_at"], "-")
        self.assertIsNone(d["session_duration_seconds"])
        self.assertEqual(d["session_duration"], "-")

    def test_status_json_stale(self):
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()
        d = json.loads(self.cw("status", "--json").stdout)
        self.assertTrue(d["stale"])

    def test_doctor_healthy(self):
        self.init()
        r = self.cw("doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no findings", r.stdout)
        d = json.loads(self.cw("doctor", "--json").stdout)
        self.assertTrue(d["ok"])
        self.assertEqual(d["findings"], [])

    def test_doctor_lint_missing_relay(self):
        r = self.cw("doctor", "--lint", "--json")
        self.assertEqual(r.returncode, 1)
        d = json.loads(r.stdout)
        self.assertFalse(d["ok"])
        self.assertEqual(d["findings"][0]["check"], "relay.missing")
        self.assertEqual(d["findings"][0]["severity"], "error")

    def test_doctor_lint_missing_anchor(self):
        self.init()
        os.remove(os.path.join(self.d, "AGENTS.md"))
        r = self.cw("doctor", "--lint", "--json")
        self.assertEqual(r.returncode, 1)
        checks = {f["check"] for f in json.loads(r.stdout)["findings"]}
        self.assertIn("anchor.missing", checks)

    def test_doctor_severity_min_filters_output(self):
        self.init()
        os.remove(os.path.join(self.d, "AGENTS.md"))  # warning only
        r = self.cw("doctor", "--severity-min", "error", "--json")
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertTrue(d["ok"])
        self.assertEqual(d["findings"], [])
        text = self.cw("doctor", "--severity-min", "error")
        self.assertEqual(text.returncode, 0)
        self.assertIn("no findings", text.stdout)
        self.assertNotIn("anchor.missing", text.stdout)

    def test_doctor_lint_stale_working_lock(self):
        self.init()
        self.cw("claim", "claude")
        self.set_expires_past()
        r = self.cw("doctor", "--lint", "--json")
        self.assertEqual(r.returncode, 1)
        findings = json.loads(r.stdout)["findings"]
        self.assertIn("lock.stale_working", {f["check"] for f in findings})

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
        # the Stage-1 "only the first two relay" promise is gone (EN core; FR variant in TestI18nFR)
        self.assertNotIn("first two", self.init("--agents", "claude,codex,gemini").stdout)



# ───────────────── i18n FR : sur un build en+fr (injecteur) ─────────────────

class TestI18nFR(InjectedFRBase):
    def test_init_lang_fr_generates_french(self):
        self.init("--lang", "fr")
        self.assertEqual(self.lock().get("lang"), "fr")
        with open(os.path.join(self.d, "M8SHIFT.protocol.md"), encoding="utf-8") as f:
            self.assertIn("Protocole de relais", f.read())
        self.assertIn("verrou pris", self.cw("claim", "claude").stdout)

    def test_localized_seed_turn0_is_well_formed(self):
        # the single-line done: fix must hold in the localized seed too (all packs)
        self.init("--lang", "fr")
        t0 = cowork.parse_turns(self.md())[0]
        self.assertIn("files", t0["fields"])
        self.assertIn("handoff", t0["fields"])

    def test_env_overrides_runtime_lang(self):
        """$M8SHIFT_LANG forces the runtime language even if the LOCK says en."""
        self.init()  # lang: en
        env = dict(os.environ, M8SHIFT_LANG="fr")
        r = subprocess.run([sys.executable, "m8shift.py", "claim", "claude"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verrou pris", r.stdout)

    def test_bare_en_core_refuses_lang_fr(self):
        """The EN-only repo core (not this build) hard-errors `--lang fr` (argparse choices)."""
        d = tempfile.mkdtemp(prefix="m8shift-test-")
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copy(SCRIPT, os.path.join(d, "m8shift.py"))   # bare EN-only core
        r = subprocess.run([sys.executable, "m8shift.py", "init", "--lang", "fr"],
                           cwd=d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("invalid choice", r.stderr)


# ───────────── injecteur i18n : packs + build multi-langues ─────────────────

class TestInjector(unittest.TestCase):
    """m8shift-i18n.py — pack validation + multi-language build invariants."""
    INJ = os.path.join(REPO, "m8shift-i18n.py")
    I18N = os.path.join(REPO, "i18n")

    def _packs(self):
        if not os.path.isdir(self.I18N):
            return []
        return sorted(d for d in os.listdir(self.I18N)
                      if os.path.isdir(os.path.join(self.I18N, d)))

    def test_all_repo_packs_pass_check(self):
        langs = self._packs()
        self.assertTrue(langs, "aucun pack i18n/")
        for lang in langs:
            r = subprocess.run([sys.executable, self.INJ, "--check", lang],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{lang}: {r.stderr}")

    def test_pack_messages_are_format_safe(self):
        """Each translated message renders with the EN placeholders — an extra/renamed
        placeholder or a stray brace would raise at runtime (tr() does value.format(**kw))."""
        en = cowork.MESSAGES["en"]
        for lang in self._packs():
            mp = os.path.join(self.I18N, lang, "messages.json")
            if not os.path.isfile(mp):
                continue
            with open(mp, encoding="utf-8") as f:
                msgs = json.load(f)
            self.assertTrue(set(msgs) <= set(en), f"{lang}: clés inconnues")
            for k, v in msgs.items():
                en_ph = set(re.findall(r"\{(\w+)\}", en[k]))
                try:
                    v.format(**{p: "" for p in en_ph})
                except Exception as e:  # noqa: BLE001
                    self.fail(f"{lang}/{k} non format-safe: {e!r}")

    def test_multi_language_build_and_run(self):
        """Build en+fr+es and run a Spanish relay (regression: incremental dict splicing
        lost its EN-only anchor after the first language → only single-lang builds worked)."""
        if not all(os.path.isdir(os.path.join(self.I18N, l)) for l in ("fr", "es")):
            self.skipTest("packs fr/es absents")
        d = tempfile.mkdtemp(prefix="m8shift-multi-")
        self.addCleanup(shutil.rmtree, d, True)
        r = subprocess.run([sys.executable, self.INJ, "--langs", "fr,es", "--into", d],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(0, subprocess.run([sys.executable, "m8shift.py", "init", "--lang", "es"],
                                           cwd=d, capture_output=True, text=True).returncode)
        claim = subprocess.run([sys.executable, "m8shift.py", "claim", "claude"],
                               cwd=d, capture_output=True, text=True)
        self.assertIn("pluma tomada", claim.stdout)  # es claim_ok


# ───────────── §5 : champs de tour avisés (passthrough) ─────────────────────

class TestAdvisoryFields(CLIBase):
    """§5 advisory turn fields: sugar flags + the open `--field key=value` namespace,
    written verbatim after the fixed routing block, surfaced by peek, never interpreted."""

    def _claim_append(self, *extra):
        self.init()
        self.assertEqual(0, self.cw("claim", "claude").returncode)
        return self.cw("append", "claude", "--to", "codex", "--ask", "a", "--done", "b", *extra)

    def test_sugar_and_x_fields_written_and_peeked(self):
        r = self._claim_append("--branch", "feat/x", "--commit", "a1b2", "--tests", "9 pass",
                               "--next", "claim codex", "--blocked-on", "ci#1",
                               "--field", "x_jira=PROJ-7", "--field", "relation=review")
        self.assertEqual(r.returncode, 0, r.stderr)
        md = self.md()
        for line in ("- branch: feat/x", "- commit: a1b2", "- tests: 9 pass",
                     "- next: claim codex", "- blocked_on: ci#1", "- x_jira: PROJ-7",
                     "- relation: review"):
            self.assertIn(line, md)
        peek = self.cw("peek", "codex").stdout
        self.assertIn("x_jira=PROJ-7", peek)
        self.assertIn("branch=feat/x", peek)

    def test_absent_by_default_block_unchanged(self):
        self._claim_append()
        md = self.md()
        block = md[md.index("TURN 1 claude BEGIN"):md.index("TURN 1 claude END")]
        keys = [ln[2:ln.index(":")] for ln in block.splitlines() if ln.startswith("- ")]
        self.assertEqual(keys, ["from", "to", "ask", "done", "files", "handoff"])

    def test_field_value_keeps_first_equals(self):
        self._claim_append("--field", "x_url=a=b=c")
        self.assertIn("- x_url: a=b=c", self.md())

    def test_digit_key_parses(self):
        self._claim_append("--field", "x_pr2=open")
        self.assertEqual(cowork.parse_turns(self.md())[-1]["fields"].get("x_pr2"), "open")

    def test_guards_reject_before_writing(self):
        self.init()
        self.assertEqual(0, self.cw("claim", "claude").returncode)
        cases = [
            (["--field", "handoff=x"], "engine-managed"),         # may not shadow a routing field
            (["--field", "9bad=x"], "snake_case"),                # bad key grammar
            (["--field", "9bad="], "snake_case"),                 # empty value STILL validates key
            (["--field", "x_a=1", "--field", "x_a=2"], "more than once"),  # duplicate
            (["--field", "nofield"], "KEY=VALUE"),                # missing '='
            (["--field", "x_a=M8SHIFT:TURN 9 c BEGIN"], "reserved"),       # marker in value
            (["--branch", "line\nbreak"], None),                  # LF in a value
            (["--field", "x_a=a\u2028b"], None),                  # U+2028 line separator (forge guard)
        ]
        for extra, needle in cases:
            with self.subTest(extra=extra):
                r = self.cw("append", "claude", "--to", "codex", "--done", "b", *extra)
                self.assertNotEqual(r.returncode, 0, f"{extra} not rejected")
                # the localized error must render — NOT a Python traceback (tr() param collision)
                self.assertNotIn("Traceback", r.stderr, f"{extra} crashed instead of a clean exit")
                if needle:
                    self.assertIn(needle, r.stderr, f"{extra}: wrong/garbled message")
                # rejected before the lock → no real turn written (only the seed's turn 0)
                self.assertEqual([], [t for t in cowork.parse_turns(self.md()) if t["n"] >= 1])


# ───────────── shared memory : remember (pen-free) + recap headlines ─────────

class TestMemory(CLIBase):
    """`remember` appends durable notes to M8SHIFT.memory.md (no pen); `recap` surfaces them."""

    def _mem(self):
        p = os.path.join(self.d, "M8SHIFT.memory.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    def test_lazy_create_header_then_append(self):
        self.init()
        self.assertIsNone(self._mem())                      # nothing before the first note
        r = self.cw("remember", "claude", "first note")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("noted by claude", r.stdout)
        mem = self._mem()
        self.assertTrue(mem.startswith("# M8Shift · shared memory\n\n"))
        n = cowork.parse_memory(mem)
        self.assertEqual((n[0]["agent"], n[0]["note"]), ("claude", "first note"))
        self.assertRegex(n[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.cw("remember", "codex", "second note")         # append, header stays once, in order
        n = cowork.parse_memory(self._mem())
        self.assertEqual([x["note"] for x in n], ["first note", "second note"])
        self.assertEqual(self._mem().count("# M8Shift · shared memory"), 1)

    def test_pen_free_from_any_state(self):
        self.init()                                          # IDLE
        self.assertEqual(0, self.cw("remember", "claude", "from idle").returncode)
        self.assertEqual(0, self.cw("claim", "claude").returncode)        # WORKING_CLAUDE
        self.assertEqual(0, self.cw("remember", "codex", "non-holder").returncode)
        self.assertEqual(0, self.cw("remember", "claude", "holder").returncode)
        self.assertEqual(0, self.cw("done", "claude").returncode)         # DONE
        self.assertEqual(0, self.cw("remember", "codex", "from done").returncode)

    def test_remember_never_touches_lock(self):
        self.init()
        self.cw("claim", "claude")
        before, before_lock = self.md(), self.lock()
        self.cw("remember", "codex", "a note")
        self.assertEqual(self.md(), before, "remember mutated M8SHIFT.md")
        self.assertEqual(self.lock(), before_lock)

    def test_need_agent_rejected_writes_nothing(self):
        self.init()
        r = self.cw("remember", "bob", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bob", r.stderr)
        self.assertIsNone(self._mem())

    def test_guards_reject_and_write_nothing(self):
        self.init()
        for note in ("   ", "x M8SHIFT:TURN 9 c BEGIN", "a\nb", "a\u2028b"):
            with self.subTest(note=note):
                r = self.cw("remember", "claude", note)
                self.assertNotEqual(r.returncode, 0, f"{note!r} not rejected")
                self.assertNotIn("Traceback", r.stderr)
        self.assertIsNone(self._mem())

    def test_note_with_colon_and_dash_roundtrips(self):
        self.init()
        note = "- convention: keys use snake_case: ok"
        self.cw("remember", "claude", note)
        self.assertEqual(cowork.parse_memory(self._mem())[-1]["note"], note)

    def test_parse_turns_blind_to_memory(self):
        self.init()
        self.cw("remember", "claude", "x")
        self.assertEqual([], cowork.parse_turns(self._mem()))

    def test_parse_memory_skips_malformed(self):
        text = ("# header\n\n- 2026-06-23T08:00:00Z claude: good\n"
                "garbage line\n- bad ts codex: nope\n- 2026-06-23T09:00:00Z codex: good2\n")
        self.assertEqual([(n["agent"], n["note"]) for n in cowork.parse_memory(text)],
                         [("claude", "good"), ("codex", "good2")])

    def test_recap_headlines_chronological(self):
        self.init()
        self.cw("remember", "claude", "older")
        self.cw("remember", "codex", "newer")
        out = self.cw("recap").stdout
        self.assertIn("note(s)", out)
        self.assertLess(out.index("older"), out.index("newer"))

    def test_recap_memory_knob(self):
        self.init()
        for i in range(4):
            self.cw("remember", "claude", f"note{i}")
        out2 = self.cw("recap", "--memory", "2").stdout
        self.assertEqual(sum(f"note{i}" in out2 for i in range(4)), 2)
        out_all = self.cw("recap", "--memory", "0").stdout
        self.assertEqual(sum(f"note{i}" in out_all for i in range(4)), 4)

    def test_recap_no_memory_no_section(self):
        self.init()
        self.assertNotIn("note(s)", self.cw("recap").stdout)

    def test_init_does_not_create_memory(self):
        self.init()
        self.assertIsNone(self._mem())

    def test_unicode_note_roundtrips(self):
        self.init()
        note = "décision: éviter les accents cassés — café"
        self.cw("remember", "claude", note)
        self.assertEqual(cowork.parse_memory(self._mem())[-1]["note"], note)

    def test_parallel_remember_no_loss(self):
        import concurrent.futures
        self.init()

        def one(i):
            return subprocess.run([sys.executable, "m8shift.py", "remember", "claude", f"n{i}"],
                                  cwd=self.d, capture_output=True, text=True).returncode
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            rcs = list(ex.map(one, range(8)))
        self.assertEqual(rcs, [0] * 8)
        self.assertEqual(len(cowork.parse_memory(self._mem())), 8)        # none lost
        self.assertEqual(self._mem().count("# M8Shift · shared memory"), 1)  # one header (race)


# ───────────── claim --check : advisory file-overlap probe (read-only) ───────

class TestClaimCheck(CLIBase):
    """`claim --check`: read-only probe — readiness (rc 0/3, like wait --once EXCEPT DONE,
    which is not claimable) + file overlap, never takes the pen/mutates, overlap never changes rc."""

    def _history(self):
        # claude#1 touches src/api.py + src/db.py → codex ; codex#2 touches src/api.py + README → claude
        self.init()
        self.cw("claim", "claude")
        self.cw("append", "claude", "--to", "codex", "--done", "x", "--files", "src/api.py,src/db.py")
        self.cw("claim", "codex")
        self.cw("append", "codex", "--to", "claude", "--done", "y", "--files", "src/api.py,README.md")
        self.assertEqual(self.lock()["state"], "AWAITING_CLAUDE")

    def test_never_mutates_no_pen(self):
        self._history()
        before = self.md()
        r = self.cw("claim", "claude", "--check", "--files", "src/api.py")
        self.assertIn(r.returncode, (0, 3))
        self.assertEqual(self.md(), before, "claim --check mutated M8SHIFT.md")
        self.assertEqual(self.lock()["state"], "AWAITING_CLAUDE")  # pen NOT taken

    def test_force_is_noop(self):
        self._history()
        before = self.md()
        self.cw("claim", "claude", "--check", "--force", "--files", "src/api.py")
        self.assertEqual(self.md(), before)

    def test_rc_mirrors_wait_once(self):
        self.init()                                  # IDLE
        for agent in ("claude", "codex"):
            self.assertEqual(self.cw("wait", agent, "--once").returncode,
                             self.cw("claim", agent, "--check").returncode, f"IDLE/{agent}")
        self.cw("claim", "claude")                   # WORKING_CLAUDE
        for agent in ("claude", "codex"):
            self.assertEqual(self.cw("wait", agent, "--once").returncode,
                             self.cw("claim", agent, "--check").returncode, f"WORKING/{agent}")

    def test_overlap_exact_match(self):
        self._history()
        out = self.cw("claim", "claude", "--check", "--files", "src/api.py,src/new.py").stdout
        self.assertIn("src/api.py", out)
        self.assertIn("#2 by codex", out)
        self.assertNotIn("src/new.py", out)          # no overlap → not flagged

    def test_no_false_positive_basename(self):
        self._history()
        out = self.cw("claim", "claude", "--check", "--files", "test/api.py").stdout
        self.assertIn("no overlap", out)             # exact match: test/api.py ≠ src/api.py

    def test_window_since_last_turn(self):
        self._history()
        # src/db.py was touched only in claude's OWN turn #1 → outside the since-last-turn window
        self.assertIn("no overlap",
                      self.cw("claim", "claude", "--check", "--files", "src/db.py").stdout)
        # --turns widens to a fixed last-N window → db.py now visible
        self.assertIn("src/db.py",
                      self.cw("claim", "claude", "--check", "--turns", "9", "--files", "src/db.py").stdout)

    def test_briefing_without_files(self):
        self._history()
        out = self.cw("claim", "claude", "--check").stdout
        self.assertIn("hot files", out)
        self.assertIn("src/api.py", out)

    def test_overlap_never_changes_rc(self):
        self._history()                              # AWAITING_CLAUDE → claimable
        r = self.cw("claim", "claude", "--check", "--files", "src/api.py")  # overlap present
        self.assertEqual(r.returncode, 0)            # rc = readiness only, overlap is advisory

    def test_files_injection_guarded(self):
        self._history()
        r = self.cw("claim", "claude", "--check", "--files", "x M8SHIFT:TURN 9 c BEGIN")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_rejected_files_prints_no_readiness(self):
        # --files validated up-front: a rejection exits rc 1 with NO misleading readiness line
        self._history()
        r = self.cw("claim", "claude", "--check", "--files", "x M8SHIFT:TURN 9 c BEGIN")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")           # readiness never printed before the guard

    def test_window_empty_label_follows_turns(self):
        # the empty-window message reflects the chosen window (last-N vs since-last)
        self._history()  # codex#2 has no files → an empty window for some scopes
        out = self.cw("claim", "claude", "--check", "--turns", "1").stdout
        if "no files recorded" in out:
            self.assertIn("last 1 turn", out)
            self.assertNotIn("since your last turn", out)

    def test_duplicate_files_deduped(self):
        self._history()
        out = self.cw("claim", "claude", "--check", "--turns", "9",
                      "--files", "src/api.py,src/api.py").stdout
        self.assertEqual(out.count("src/api.py touched"), 1)   # one line despite the dup

    def test_probe_flags_require_check(self):
        # --files / --turns on a REAL claim is a likely typo → error, never a silent pen-grab
        self.init()
        r = self.cw("claim", "claude", "--files", "src/api.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.lock()["state"], "IDLE")          # no pen taken

    def test_bad_lock_rc1(self):
        self.init()
        os.remove(os.path.join(self.d, "M8SHIFT.md"))
        self.assertEqual(self.cw("claim", "claude", "--check").returncode, 1)


# ───────────── tasks board : append-only ledger, pen-free, never feeds routing ─

class TestTasks(CLIBase):
    """`task` add/done/drop/list/show: append-only event log + last-event-wins fold; pen-free;
    status/blocked_on never feed the mutex/routing."""

    def _tasks(self):
        p = os.path.join(self.d, "M8SHIFT.tasks.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    def test_pen_free_and_lazy_header(self):
        self.init()
        self.assertIsNone(self._tasks())
        r = self.cw("task", "add", "claude", "migrate auth")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("#1 added by claude", r.stdout)
        self.assertTrue(self._tasks().startswith("# M8Shift · tasks\n\n"))
        self.assertEqual(self.lock()["state"], "IDLE")          # no pen taken
        self.cw("claim", "claude")                               # other holds the pen
        self.assertEqual(0, self.cw("task", "add", "codex", "wire endpoints").returncode)

    def test_never_touches_lock(self):
        self.init()
        self.cw("claim", "claude")
        before, before_lock = self.md(), self.lock()
        self.cw("task", "add", "codex", "a task")
        self.cw("task", "done", "codex", "1")
        self.assertEqual(self.md(), before, "task mutated M8SHIFT.md")
        self.assertEqual(self.lock(), before_lock)

    def test_cmd_task_has_no_set_lock(self):
        import inspect
        src = inspect.getsource(cowork.cmd_task) + inspect.getsource(cowork._cmd_task_read)
        self.assertNotIn("set_lock(", src)   # no CALL to set_lock (docstrings name it, calls have a paren)

    def test_routing_never_reads_tasks(self):
        self.init()
        self.cw("task", "add", "claude", "big task", "--blocked-on", "external thing")
        self.assertIn("pen taken", self.cw("claim", "claude").stdout)   # claim ignores tasks
        self.assertEqual(0, self.cw("task", "done", "claude", "1").returncode)  # blocked closes

    def test_sequential_ids_and_fold(self):
        self.init()
        self.cw("task", "add", "claude", "first")
        self.cw("task", "add", "claude", "second")
        self.assertEqual([e["id"] for e in cowork.parse_tasks(self._tasks())], [1, 2])
        self.cw("task", "done", "claude", "1")
        fold = cowork.fold_tasks(cowork.parse_tasks(self._tasks()))
        self.assertEqual(fold[1]["verb"], "done")
        self.assertEqual(fold[1]["text"], "first")              # identity kept after done
        self.assertEqual(fold[2]["verb"], "add")

    def test_concurrent_add_unique_ids(self):
        import concurrent.futures
        self.init()

        def one(i):
            return subprocess.run([sys.executable, "m8shift.py", "task", "add", "claude", f"t{i}"],
                                  cwd=self.d, capture_output=True, text=True).returncode
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            rcs = list(ex.map(one, range(8)))
        self.assertEqual(rcs, [0] * 8)
        ids = [e["id"] for e in cowork.parse_tasks(self._tasks())]
        self.assertEqual(sorted(ids), list(range(1, 9)))        # 8 distinct sequential ids, none lost

    def test_list_open_default_and_show_history(self):
        self.init()
        self.cw("task", "add", "claude", "open one")
        self.cw("task", "add", "claude", "closed one")
        self.cw("task", "done", "claude", "2")
        out = self.cw("task", "list").stdout
        self.assertIn("#1", out)
        self.assertNotIn("#2", out)                             # done hidden by default
        self.assertIn("#2", self.cw("task", "list", "--all").stdout)
        self.assertEqual(self.cw("task", "show", "2").stdout.count("#2"), 2)  # add + done

    def test_guards_reject_and_write_nothing(self):
        self.init()
        for args in (["add", "claude", "   "],                       # empty desc
                     ["add", "claude", "x M8SHIFT:TASK y"],          # reserved marker
                     ["add", "claude", "d", "--blocked-on", "a\nb"],  # newline in blocked
                     ["add", "claude", "d", "--for", "ghost"],       # non-roster assignee
                     ["done", "claude", "999"]):                     # unknown id
            with self.subTest(args=args):
                r = self.cw("task", *args)
                self.assertNotEqual(r.returncode, 0, f"{args} not rejected")
                self.assertNotIn("Traceback", r.stderr)
        self.assertIsNone(self._tasks())                            # nothing was written

    def test_done_terminal_refused_no_event(self):
        self.init()
        self.cw("task", "add", "claude", "t")
        self.assertEqual(0, self.cw("task", "done", "claude", "1").returncode)
        before = self._tasks()
        self.assertNotEqual(self.cw("task", "done", "claude", "1").returncode, 0)  # already done
        self.assertEqual(self._tasks(), before)                     # no event appended

    def test_parse_tasks_tolerates_garbage(self):
        text = ("# header\n\n- #1 2026-06-23T08:00:00Z add claude: good\n"
                "garbage\n- #abc 2026-06-23T08:00:00Z add claude: bad-id\n"
                "- #2 2026-06-23T09:00:00Z add codex: good2\n")
        self.assertEqual([e["id"] for e in cowork.parse_tasks(text)], [1, 2])

    def test_recap_tasks_tail_and_absent(self):
        self.init()
        self.assertNotIn("open task", self.cw("recap").stdout)      # absent → no section
        self.cw("task", "add", "claude", "todo one")
        out = self.cw("recap").stdout
        self.assertIn("open task", out)
        self.assertIn("todo one", out)


# ───────────── session history : append-only ledger + read-only fold ─────────

class TestHistory(CLIBase):
    """`history` folds M8SHIFT.sessions.jsonl into one readable entry per session."""

    def _sessions(self):
        p = os.path.join(self.d, "M8SHIFT.sessions.jsonl")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return f.read()

    def _session_rows(self):
        return [json.loads(line) for line in self._sessions().splitlines() if line.strip()]

    def test_init_records_session_and_history(self):
        self.init("--name", "hist", "--agents", "claude,codex,gemini")
        sid = self.lock()["session"]
        self.assertRegex(sid, r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
        rows = self._session_rows()
        self.assertEqual(rows[0]["event"], "start")
        self.assertEqual(rows[0]["session_id"], sid)
        self.assertEqual(rows[0]["agents"], "claude,codex,gemini")
        out = self.cw("history").stdout
        self.assertIn(sid, out)
        self.assertIn("agents: claude,codex,gemini", out)
        self.assertIn("turns: 0", out)
        js = json.loads(self.cw("history", "--json").stdout)
        self.assertEqual(js["current_session"], sid)
        self.assertEqual(js["sessions"][0]["turns"], 0)

    def test_history_counts_turns_and_done(self):
        self.init()
        sid = self.lock()["session"]
        self.turn("claude", "codex", done="one")
        self.turn("codex", "claude", done="two")
        r = self.cw("done", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self._session_rows()
        self.assertEqual([r["event"] for r in rows], ["start", "done"])
        self.assertEqual(rows[-1]["closed_by"], "claude")
        self.assertEqual(rows[-1]["agents_used"], "claude,codex")
        js = json.loads(self.cw("history", "--json").stdout)
        s = js["sessions"][0]
        self.assertEqual(s["session_id"], sid)
        self.assertEqual(s["state"], "DONE")
        self.assertEqual(s["turns"], 2)
        self.assertEqual(s["closed_by"], "claude")
        self.assertEqual(s["agents_used"], "claude,codex")
        self.assertNotIn("events", s)
        self.assertNotIn("turn_start", s)
        self.assertNotIn("turn_end", s)
        self.assertNotIn("project", s)
        self.assertNotIn("lang", s)
        oneline = self.cw("history", "--oneline").stdout
        self.assertIn("DONE turns=2", oneline)
        self.assertIn(" local ", oneline)

    def test_force_init_marks_previous_session_reset(self):
        self.init()
        old_sid = self.lock()["session"]
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        r = self.init("--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        new_sid = self.lock()["session"]
        self.assertNotEqual(old_sid, new_sid)
        rows = self._session_rows()
        self.assertEqual([r["event"] for r in rows], ["start", "reset", "start"])
        self.assertEqual(rows[1]["session_id"], old_sid)
        self.assertEqual(rows[1]["state_before"], "WORKING_CLAUDE")
        out = self.cw("history", "--oneline").stdout
        self.assertIn(f"{old_sid}", out)
        self.assertIn("RESET", out)
        self.assertIn(f"{new_sid}", out)

    def test_doctor_warns_on_invalid_session_jsonl(self):
        self.init()
        with open(os.path.join(self.d, "M8SHIFT.sessions.jsonl"), "a", encoding="utf-8") as f:
            f.write("{bad json}\n")
        r = self.cw("doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sessions.jsonl_invalid", r.stdout)


# ───────────── régressions du round d'audit Codex (v3.x) ────────────────────

class TestAuditFixes(CLIBase):
    """Regressions for the Codex audit: claim --check DONE, seed turn-0 format, the headless
    runner rename, m8shift-i18n.py --check format-safety, and the baton-owner done/release."""

    def test_stanza_wait_wording_not_stale(self):
        # #1: the injected stanza (what agents read) must not promise "you may acquire" on
        # wait rc 0 — after claim --check DONE→rc3 we clarified rc 0 can mean DONE = stop.
        s = cowork.stanza_for("claude")
        self.assertNotIn("you may acquire", s)
        self.assertTrue("DONE" in s or "stop" in s)

    def test_version_surface(self):
        # dogfooding skew check: --version, status/recap, M8SHIFT.md banner, status --json carry VERSION
        v = cowork.VERSION
        self.assertRegex(v, r"^\d+\.\d+\.\d+")
        self.assertIn(v, self.cw("--version").stdout)
        self.init()
        self.assertIn(f"v{v}", self.cw("status").stdout.splitlines()[0])
        self.assertIn(f"v{v}", self.cw("recap").stdout.splitlines()[0])
        self.assertIn(v, self.md())                                   # stamped in the M8SHIFT.md banner
        self.assertEqual(json.loads(self.cw("status", "--json").stdout)["m8shift_version"], v)

    def test_distributed_scripts_version_surface(self):
        # Every tracked Python script carries the same explicit version surface as m8shift.py.
        v = cowork.VERSION
        scripts = [
            "m8shift-i18n.py",
            "m8shift-worktree.py",
            os.path.join("examples", "headless_runner.py"),
            os.path.join("scripts", "gen_docs.py"),
            os.path.join("tests", "test_m8shift.py"),
            os.path.join("tests", "test_worktree.py"),
        ]
        for rel in scripts:
            with self.subTest(script=rel):
                r = subprocess.run([sys.executable, os.path.join(REPO, rel), "--version"],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(v, r.stdout)

    def test_done_release_are_baton_owner_ops(self):
        # #4: in AWAITING_*, `holder` is the baton owner; done/release act for them WITHOUT an
        # active claim (append, the work write, still needs the pen). A non-holder is refused.
        self.init("--agents", "claude,codex,lechat")
        self.cw("claim", "claude")
        self.cw("append", "claude", "--to", "lechat", "--done", "x")   # → AWAITING_LECHAT
        self.assertEqual(self.lock()["holder"], "lechat")
        self.assertNotEqual(self.cw("done", "codex").returncode, 0)     # non-holder refused
        # the baton owner redirects via release WITHOUT claiming…
        self.assertEqual(self.cw("release", "lechat", "--to", "codex").returncode, 0)
        self.assertEqual(self.lock()["holder"], "codex")
        # …and the new baton owner closes via done WITHOUT claiming
        self.assertEqual(self.cw("done", "codex").returncode, 0)
        self.assertEqual(self.lock()["state"], "DONE")

    def test_claim_check_done_not_claimable(self):
        # #3: a real claim refuses DONE, so the pre-claim probe must NOT report ready (was rc 0)
        self.init()
        self.cw("claim", "claude")
        self.cw("done", "claude")
        r = self.cw("claim", "codex", "--check")
        self.assertEqual(r.returncode, 3, "claim --check still says DONE is claimable")
        self.assertIn("DONE", r.stdout)
        self.assertNotEqual(self.cw("claim", "codex").returncode, 0)   # real claim agrees

    def test_seed_turn0_is_well_formed(self):
        # #7: the bootstrap turn #0 must satisfy parse_turns (single-line done:)
        self.init()
        t0 = cowork.parse_turns(self.md())[0]
        self.assertEqual(t0["n"], 0)
        self.assertIn("files", t0["fields"])      # were leaking into the body before
        self.assertIn("handoff", t0["fields"])

    def test_headless_runner_reads_m8shift_lock(self):
        # #1: the example runner reads a CURRENT M8SHIFT.md (markers were still COWORK:*)
        import importlib.util
        rp = os.path.join(REPO, "examples", "headless_runner.py")
        spec = importlib.util.spec_from_file_location("headless_runner", rp)
        hr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hr)
        self.assertEqual(hr.LOCK_BEGIN, "<!-- M8SHIFT:LOCK:BEGIN -->")
        self.init()
        lk = hr.read_lock(os.path.join(self.d, "M8SHIFT.md"))
        self.assertIsNotNone(lk, "runner cannot read a current M8SHIFT.md")
        self.assertEqual(lk["state"], "IDLE")

    def test_injector_check_rejects_format_unsafe_pack(self):
        # #8: --check must reject a pack whose translated message renames/adds a placeholder
        bad = os.path.join(REPO, "i18n", "_zzbadtest")
        self.addCleanup(shutil.rmtree, bad, True)
        shutil.copytree(os.path.join(REPO, "i18n", "fr"), bad)
        mp = os.path.join(bad, "messages.json")
        with open(mp, encoding="utf-8") as f:
            msgs = json.load(f)
        msgs["remember_ok"] = "{agent} {bogus_placeholder}"   # EN has no {bogus_placeholder}
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, os.path.join(REPO, "m8shift-i18n.py"),
                            "--check", "_zzbadtest"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("format-safe", r.stderr)


class TestLoopGuardrails(CLIBase):
    """Regression tests for operator-loop guardrails: next/status hints/append --wait."""

    def test_next_claims_and_prints_handoff_when_ready(self):
        self.init()
        self.cw("claim", "claude")
        self.cw("append", "claude", "--to", "codex",
                "--ask", "review the README", "--done", "edited README", "--files", "README.md")
        r = self.cw("next", "codex", "--once")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lock()["state"], "WORKING_CODEX")
        self.assertIn("pen taken by codex", r.stdout)
        self.assertIn("ask=review the README", r.stdout)

    def test_next_once_not_ready_does_not_mutate(self):
        self.init()
        self.cw("claim", "claude")
        before = self.md()
        r = self.cw("next", "codex", "--once")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.md(), before)
        self.assertIn("wait codex", r.stdout)

    def test_next_force_refuses_fresh_lock_without_looping(self):
        # `next --force` on a FRESH WORKING_<other> must refuse immediately (like `claim --force`),
        # not fall through to the poll loop and hang. (regression for the infinite-loop bug)
        self.init()
        self.cw("claim", "codex")                       # WORKING_CODEX, fresh (not stale)
        before = self.md()
        try:
            r = subprocess.run([sys.executable, "m8shift.py", "next", "claude", "--force"],
                               cwd=self.d, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("next --force on a fresh lock hung — regressed the infinite poll")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("still valid", r.stdout + r.stderr)   # claim_active refusal, not a poll
        self.assertEqual(self.md(), before)                 # no mutation

    def test_status_for_prints_and_serializes_next_action(self):
        self.init()
        out = self.cw("status", "--for", "codex").stdout
        self.assertIn("next", out)
        self.assertIn("next codex", out)
        js = json.loads(self.cw("status", "--for", "codex", "--json").stdout)
        self.assertIn("next_action", js)
        self.assertIn("next codex", js["next_action"])

    def test_append_wait_blocks_until_agent_turn_returns(self):
        self.init()
        self.cw("claim", "claude")
        p = subprocess.Popen(
            [sys.executable, "m8shift.py", "append", "claude", "--to", "codex",
             "--ask", "review", "--done", "drafted", "--wait", "--wait-interval", "1"],
            cwd=self.d, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.lock().get("state") == "AWAITING_CODEX":
                break
            time.sleep(0.05)
        else:
            out, err = p.communicate(timeout=1)
            self.fail(f"append --wait did not hand off before waiting\nstdout={out}\nstderr={err}")

        self.cw("claim", "codex")
        self.cw("append", "codex", "--to", "claude", "--ask", "done", "--done", "reviewed")
        out, err = p.communicate(timeout=5)
        self.assertEqual(p.returncode, 0, out + err)
        self.assertIn("waiting for claude's next turn", out)
        self.assertIn("your turn (AWAITING_CLAUDE)", out)


# ───────────── §8 core foundation (degree-2 worktree companion) ──────────────

class TestStage8Core(CLIBase):
    """Core changes the §8 worktree companion needs: $M8SHIFT_ROOT path rebasing, the integration
    `integrating:` LOCK field (format/lifecycle validated + pen lockdown), and the file_lock
    token-ownership API."""

    SENT = "wt1@a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"   # <id>@<40-hex sha>, a valid sentinel

    def _inject(self, sentinel=SENT):
        """Splice an `integrating:` field into the LOCK (what the companion does under file_lock)."""
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace("note:", f"integrating: {sentinel}\nnote:", 1))

    def test_root_env_redirects_coordination(self):
        # $M8SHIFT_ROOT rebases coordination paths to a canonical root, not the script's dir
        root = tempfile.mkdtemp(prefix="m8root-")
        self.addCleanup(shutil.rmtree, root, True)
        env = dict(os.environ, M8SHIFT_ROOT=root)
        r = subprocess.run([sys.executable, "m8shift.py", "init"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(root, "M8SHIFT.md")))       # canonical root
        self.assertFalse(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))    # not the script dir
        # and without the env, init writes next to the script (degree-1 unchanged)
        self.init()
        self.assertTrue(os.path.exists(os.path.join(self.d, "M8SHIFT.md")))

    def test_root_env_nonexistent_dir_no_traceback(self):
        # $M8SHIFT_ROOT at a not-yet-existing dir must not crash file_lock with a raw traceback
        # (file_lock mirrors write()'s makedirs); init then auto-creates the root like a fresh dir.
        base = tempfile.mkdtemp(prefix="m8ne-")
        self.addCleanup(shutil.rmtree, base, True)
        root = os.path.join(base, "deep", "child")     # parents do not exist yet
        env = dict(os.environ, M8SHIFT_ROOT=root)
        r = subprocess.run([sys.executable, "m8shift.py", "claim", "claude"],
                           cwd=self.d, capture_output=True, text=True, env=env)
        self.assertNotIn("Traceback", r.stderr)        # clean refusal (not init'd), no crash
        ri = subprocess.run([sys.executable, "m8shift.py", "init"],
                            cwd=self.d, capture_output=True, text=True, env=env)
        self.assertEqual(ri.returncode, 0, ri.stderr)
        self.assertTrue(os.path.exists(os.path.join(root, "M8SHIFT.md")))    # auto-created

    def test_integrating_locks_the_pen(self):
        # an in-flight merge (`integrating:` set) locks the pen: every normal/forced public op is
        # refused and leaves the LOCK byte-for-byte intact; only the integrator's own TTL refresh passes.
        self.init()
        self.cw("claim", "claude")            # WORKING_CLAUDE, holder=claude (the integrator)
        self._inject()
        before = self.md()
        refused = [
            ("append", "claude", "--to", "codex"),   # holder, normal
            ("release", "claude", "--to", "codex"),  # holder, normal
            ("done", "claude"),                      # holder, normal
            ("claim", "claude", "--force"),          # holder, forced
            ("claim", "codex", "--force"),           # non-holder, forced
            ("release", "codex", "--force", "--to", "claude"),
            ("done", "codex", "--force"),
        ]
        for op in refused:
            self.assertNotEqual(self.cw(*op).returncode, 0, op)
        self.assertEqual(self.md(), before)   # not one refusal mutated the LOCK
        # the integrator keeps its own pen alive (TTL refresh) — sentinel rides along
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        self.assertIn(self.SENT, self.md())

    def test_integrating_malformed_is_clean_invalid(self):
        # a malformed sentinel ⇒ clean lock_invalid (no traceback), not a silent accept
        self.init()
        self.cw("claim", "claude")            # WORKING_CLAUDE
        self._inject("not-a-valid-ref")       # no @<hex-sha>
        r = self.cw("claim", "claude")        # any op routes through load_or_die
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("integrating", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_integrating_only_valid_while_working(self):
        # a well-formed sentinel in a non-WORKING state ⇒ invalid LOCK (lifecycle enforced)
        self.init()                            # state IDLE, holder none
        self._inject()                         # valid format, wrong state
        r = self.cw("claim", "claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("integrating", r.stderr)

    def test_integrating_rejects_state_holder_mismatch(self):
        # the sentinel is valid only while state == WORKING_<holder>; a mismatched pair (holder
        # claude, state WORKING_CODEX) must be rejected, not silently accepted
        self.init()
        self.cw("claim", "claude")             # WORKING_CLAUDE, holder=claude
        self._inject()                         # valid sentinel
        p = os.path.join(self.d, "M8SHIFT.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        with open(p, "w", encoding="utf-8") as f:   # state→CODEX, holder stays claude
            f.write(re.sub(r"(?m)^(state:\s*)WORKING_CLAUDE", r"\1WORKING_CODEX", t, count=1))
        r = self.cw("claim", "claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("integrating", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_file_lock_token_ownership(self):
        # file_lock() yields the guard; still_owned() flips False once the .m8shift.lock token changes
        d = tempfile.mkdtemp(prefix="m8lock-")
        self.addCleanup(shutil.rmtree, d, True)
        old = cowork.LOCKFILE
        cowork.LOCKFILE = os.path.join(d, ".m8shift.lock")
        self.addCleanup(setattr, cowork, "LOCKFILE", old)
        with cowork.file_lock() as guard:
            self.assertTrue(guard.still_owned())
            with open(cowork.LOCKFILE, "wb") as f:
                f.write(b"stolen")            # a stale takeover overwrote our token
            self.assertFalse(guard.still_owned())


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"test_m8shift.py {VERSION}")
        sys.exit(0)
    unittest.main(verbosity=2)
