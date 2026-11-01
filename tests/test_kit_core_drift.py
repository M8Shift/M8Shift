"""Regression tests for core-byte drift diagnostics in kit receipts."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

CORE = Path(__file__).resolve().parents[1] / "m8shift.py"
spec = importlib.util.spec_from_file_location("m8shift_kit_drift_test", CORE)
m8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m8)


class KitCoreDriftTests(unittest.TestCase):
    def test_manifest_records_core_hash_and_doctor_detects_same_version_edit(self):
        original_here = m8.HERE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                m8.HERE = str(root)
                core = root / "m8shift.py"
                core.write_text('VERSION = "4.5.0"\n', encoding="utf-8")
                m8._write_kit_manifest([])
                receipt = m8._read_kit_manifest(str(root))
                expected = hashlib.sha256(core.read_bytes()).hexdigest()
                self.assertEqual(receipt["core"]["sha256"], expected)
                self.assertFalse(any(row["check"] == "kit.drift"
                                     for row in m8._kit_doctor_findings()))
                core.write_text('VERSION = "4.5.0"\n# changed bytes\n', encoding="utf-8")
                drift = [row for row in m8._kit_doctor_findings()
                         if row["check"] == "kit.drift"]
                self.assertEqual([row.get("path") for row in drift], ["m8shift.py"])
        finally:
            m8.HERE = original_here

    def test_legacy_manifest_without_hash_is_unverifiable_not_drift(self):
        original_here = m8.HERE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                m8.HERE = str(root)
                (root / "m8shift.py").write_text('VERSION = "4.5.0"\n', encoding="utf-8")
                (root / ".m8shift").mkdir()
                m8._write_kit_manifest_document({
                    "schema": "m8shift.kit.v1",
                    "core": {"script": "m8shift.py", "version": "4.5.0"},
                    "companions": [],
                })
                findings = m8._kit_doctor_findings()
                self.assertTrue(any(row["check"] == "kit.unverifiable"
                                    for row in findings))
                self.assertFalse(any(row["check"] == "kit.drift"
                                     for row in findings))
        finally:
            m8.HERE = original_here

    def test_symlink_core_is_never_hash_verified(self):
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlink unavailable")
        original_here = m8.HERE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                m8.HERE = str(root)
                target = root / "target.py"
                target.write_text('VERSION = "4.5.0"\n', encoding="utf-8")
                core = root / "m8shift.py"
                try:
                    core.symlink_to(target)
                except OSError:
                    self.skipTest("symlink unavailable")
                (root / ".m8shift").mkdir()
                m8._write_kit_manifest_document({
                    "schema": "m8shift.kit.v1",
                    "core": {"script": "m8shift.py", "version": "4.5.0",
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()},
                    "companions": [],
                })
                findings = m8._kit_doctor_findings()
                self.assertTrue(any(row["check"] == "kit.companions"
                                    and row.get("path") == "m8shift.py"
                                    for row in findings))
        finally:
            m8.HERE = original_here


if __name__ == "__main__":
    unittest.main()
