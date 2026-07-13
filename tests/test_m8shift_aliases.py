import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "m8shift-aliases.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m8shift_aliases", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AliasInstallerTests(unittest.TestCase):
    def test_default_is_preview_with_absolute_paths(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], text=True, capture_output=True, check=True
        )
        self.assertIn("alias m8shift=", result.stdout)
        self.assertIn(str((ROOT / "m8shift.py").resolve()), result.stdout)
        self.assertIn(str((ROOT / "m8shift-top.py").resolve()), result.stdout)

    def test_write_is_idempotent_and_preserves_other_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = Path(tmp) / ".zshrc"
            rc.write_text("export KEEP=yes\n", encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "--write", "--shell", "zsh", "--rc", str(rc)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            first = rc.read_text(encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True, text=True)
            second = rc.read_text(encoding="utf-8")
            self.assertEqual(first, second)
            self.assertIn("export KEEP=yes", second)
            self.assertEqual(second.count("# >>> m8shift aliases >>>"), 1)

    def test_existing_marked_block_is_replaced(self):
        aliases = load_module()
        old = "before\n# >>> m8shift aliases >>>\nold\n# <<< m8shift aliases <<<\nafter\n"
        updated = aliases.replace_block(old, aliases.alias_block(ROOT))
        self.assertNotIn("\nold\n", updated)
        self.assertTrue(updated.startswith("before\n"))
        self.assertTrue(updated.endswith("after\n"))


if __name__ == "__main__":
    unittest.main()
