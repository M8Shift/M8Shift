"""Contract tests for the exact-tip test-discovery witness."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-test-loading.py"


def load():
    spec = importlib.util.spec_from_file_location("test_loading_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLoadingCheckTests(unittest.TestCase):
    def test_exact_tip_discovery_and_dirty_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "tests").mkdir()
            test = root / "tests" / "test_demo.py"
            test.write_text("import unittest\nclass Example(unittest.TestCase):\n def test_ok(self): pass\n")
            subprocess.run(["git", "-C", str(root), "add", "tests/test_demo.py"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            mod = load()
            self.assertEqual(mod.inspect(root)["discovered_cases"], 1)
            test.write_text(test.read_text() + "# dirty\n")
            with self.assertRaisesRegex(ValueError, "uncommitted"):
                mod.inspect(root)

    def test_rejects_non_head_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "tests").mkdir()
            (root / "tests" / "test_demo.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_a(self): pass\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "first"], check=True)
            previous = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            (root / "README.md").write_text("next")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "second"], check=True)
            with self.assertRaisesRegex(ValueError, "not the checked-out HEAD"):
                load().inspect(root, previous)


if __name__ == "__main__":
    unittest.main()
