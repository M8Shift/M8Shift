"""Roster bootstrap and declared blocks are visible without changing pen authority."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base


class RosterAndBlockVisibility(base.CLIBase):
    def test_roster_add_creates_distinct_anchor_and_preserves_work_window(self):
        self.init()
        self.assertEqual(self.cw("claim", "claude").returncode, 0)
        before = json.loads(self.cw("status", "--json").stdout)
        result = self.cw("roster", "add", "reviewer", "--by", "claude")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        anchor = Path(self.d, "REVIEWER.md")
        self.assertIn("You are **reviewer**", anchor.read_text())
        self.assertIn("M8SHIFT_AGENT", anchor.read_text())
        after = json.loads(self.cw("status", "--json").stdout)
        for key in ("session", "state", "holder", "turn", "since", "expires"):
            self.assertEqual(after[key], before[key])
        original = anchor.read_bytes()
        self.assertEqual(self.cw("roster", "add", "reviewer", "--by", "claude").returncode, 0)
        self.assertEqual(anchor.read_bytes(), original)

    def test_existing_and_shared_anchors_are_preserved(self):
        self.init()
        self.cw("claim", "claude")
        custom = Path(self.d, "REVIEWER.md")
        custom.write_text("Existing project instructions\n")
        agents = Path(self.d, "AGENTS.md").read_bytes()
        self.assertEqual(self.cw("roster", "add", "reviewer", "--by", "claude").returncode, 0)
        self.assertEqual(custom.read_text(), "Existing project instructions\n")
        self.assertEqual(self.cw("roster", "add", "vibe", "--by", "claude").returncode, 0)
        self.assertEqual(Path(self.d, "AGENTS.md").read_bytes(), agents)

    def test_roster_refusal_creates_no_anchor(self):
        self.init()
        before = self.md()
        result = self.cw("roster", "add", "reviewer", "--by", "claude")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(Path(self.d, "REVIEWER.md").exists())
        self.assertEqual(self.md(), before)

    def test_declared_block_is_visible_to_peer_and_does_not_mutate_the_lock(self):
        self.init()
        self.cw("claim", "claude")
        result = self.cw("task", "add", "claude", "Need an operator decision",
                         "--blocked-on", "manual confirmation")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = self.md()
        human = self.cw("status", "--for", "codex")
        self.assertIn("manual confirmation", human.stdout)
        self.assertIn("advisory; session unbound", human.stdout)
        payload = json.loads(self.cw("status", "--json").stdout)
        blocks = payload["snapshot"]["declared_blocks"]
        self.assertEqual(blocks[0]["agent"], "claude")
        self.assertEqual(blocks[0]["authority"], "advisory")
        self.assertEqual(payload["state"], "WORKING_CLAUDE")
        self.assertEqual(self.md(), before)
        self.assertNotEqual(self.cw("claim", "codex", "--force").returncode, 0)
        self.cw("task", "done", "claude", "1")
        payload = json.loads(self.cw("status", "--json").stdout)
        self.assertEqual(payload["snapshot"]["declared_blocks"], [])

    def test_off_roster_task_signature_is_reported_read_only(self):
        self.init()
        task = Path(self.d, "M8SHIFT.tasks.md")
        task.write_text("- #1 2026-11-15T00:00:00Z add claude: Work\n"
                        "- #1 2026-11-15T00:00:01Z done outside-reader: \n")
        before = {name: Path(self.d, name).read_bytes() for name in ("M8SHIFT.md", task.name)}
        result = self.cw("doctor", "--json")
        findings = json.loads(result.stdout)["findings"]
        row = next(row for row in findings if row["check"] == "register.off_roster_signatures")
        self.assertIn("outside-reader", row["message"])
        self.assertIn("Historical membership", row["message"])
        self.assertEqual(before, {name: Path(self.d, name).read_bytes() for name in before})
