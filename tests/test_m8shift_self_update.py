import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "m8shift-self-update.py")
SPEC = importlib.util.spec_from_file_location("m8shift_self_update", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class SelfUpdateTests(unittest.TestCase):
    def test_snapshot_restore_is_reversible(self):
        with tempfile.TemporaryDirectory() as target, tempfile.TemporaryDirectory() as backup:
            os.makedirs(os.path.join(target, ".m8shift"))
            for rel, body in (("m8shift.py", "old core"), ("m8shift-top.py", "old top"),
                              (os.path.join(".m8shift", "kit.json"), "{}")):
                with open(os.path.join(target, rel), "w", encoding="utf-8") as fh:
                    fh.write(body)
            rels, absent = mod.snapshot(target, backup)
            for rel in rels:
                with open(os.path.join(target, rel), "w", encoding="utf-8") as fh:
                    fh.write("new")
            audit = os.path.join(target, ".m8shift", "update-audit.jsonl")
            open(audit, "w").close()
            mod.restore(target, backup, rels, absent)
            self.assertEqual(open(os.path.join(target, "m8shift.py"), encoding="utf-8").read(), "old core")
            self.assertEqual(json.load(open(os.path.join(backup, "manifest.json"), encoding="utf-8"))["files"], rels)
            self.assertFalse(os.path.exists(audit))

    @mock.patch.object(mod, "git")
    def test_source_authority_requires_clean_exact_ref(self, git):
        with tempfile.TemporaryDirectory() as source:
            open(os.path.join(source, "m8shift.py"), "w").close()
            git.side_effect = [mock.Mock(returncode=0, stdout="aaa\n"),
                               mock.Mock(returncode=0, stdout="bbb\n"),
                               mock.Mock(returncode=0, stdout="")]
            ok, reason = mod.source_authority(source, "origin/main")
            self.assertFalse(ok)
            self.assertIn("does not equal", reason)


if __name__ == "__main__":
    unittest.main()
