"""Command divergence gates parity; prose and shell spacing do not."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("onboarding_parity", ROOT / "scripts/check-onboarding-parity.py")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)


class OnboardingParityTests(unittest.TestCase):
    def test_command_mutations_are_detected_without_prose_noise(self):
        source = "Canonical prose\n```sequence\npython3 tool.py --verify\n```\n"
        site = "Different prose\n```sh\npython3   tool.py --verify\n```\n"
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory, "source.md"), Path(directory, "site.md")
            left.write_text(source)
            right.write_text(site)
            self.assertEqual(parity.compare(left, right)["status"], "matched")
            left.write_text(source.replace("--verify", "--dry-run"))
            self.assertEqual(parity.compare(left, right)["differing_blocks"], [1])
            right.write_text(site.replace("--verify", "--dry-run"))
            self.assertEqual(parity.compare(left, right)["status"], "matched")

    def test_quotes_escapes_and_spaces_inside_arguments_are_not_discarded(self):
        pairs = [
            ('python3 tool.py --dir "$ROOT"', 'python3 tool.py --dir $ROOT'),
            ('tool "two  spaces"', 'tool "two spaces"'),
            ('tool "prefix"suffix', 'tool "prefix" suffix'),
            ('tool path\\ with\\ spaces', 'tool path with spaces'),
        ]
        for left, right in pairs:
            with self.subTest(left=left):
                self.assertNotEqual(parity.normalize_command(left),
                                    parity.normalize_command(right))

    def test_absent_or_oversized_command_evidence_is_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "empty.md")
            path.write_text("No executable sequence")
            with self.assertRaises(ValueError):
                parity.commands(path)
            path.write_text("x" * (parity.LIMIT + 1))
            with self.assertRaises(ValueError):
                parity.commands(path)
