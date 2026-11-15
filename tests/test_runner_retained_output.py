"""Bounded opt-in provider diagnostics; retained bytes never enter portable events."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner_retention_test", ROOT / "examples/headless_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RetainedOutputTests(unittest.TestCase):
    def capture(self, *, retain):
        child = subprocess.Popen(
            [sys.executable, "-c", "import os; os.write(1,b'A'*90000+b'\\xff'); os.write(2,b'B'*70000)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tee = runner.BoundedTTYTee(child, retain_output=retain)
        self.assertEqual(child.wait(timeout=15), 0)
        return tee.finish()

    def test_default_retains_no_stream_payload_for_persistence(self):
        result = self.capture(retain=False)
        self.assertIsNone(result["_retained_streams"])
        self.assertEqual(result["streams"]["stdout"]["bytes"], 90001)

    def test_large_dual_stream_output_is_bounded_and_digest_exact(self):
        result = self.capture(retain=True)
        with tempfile.TemporaryDirectory(prefix="m8-output-") as directory:
            receipt, error = runner.write_retained_output(directory, "capture-test", result)
            self.assertEqual(error, "")
            path = Path(directory, receipt["path"])
            document = json.loads(path.read_text())
            for name, expected, count in (("stdout", b"A", 90001), ("stderr", b"B", 70000)):
                row = document["streams"][name]
                decoded = base64.b64decode(row["data"])
                self.assertEqual(decoded, expected * runner.TEE_CAPTURE_LIMIT)
                self.assertEqual(row["sha256"], hashlib.sha256(decoded).hexdigest())
                self.assertEqual(row["observed_bytes"], count)
                self.assertTrue(row["truncated"])
                self.assertNotIn("data", receipt["streams"][name])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertLess(path.stat().st_size, 180000)
            second, error = runner.write_retained_output(directory, "capture-test", result)
            self.assertIsNone(second)
            self.assertEqual(error, "output_capture_write_failed")

    def test_symlinked_storage_does_not_write_to_the_target(self):
        with tempfile.TemporaryDirectory(prefix="m8-output-") as directory:
            target = Path(directory, "target")
            target.mkdir()
            Path(directory, "runtime").symlink_to(target, target_is_directory=True)
            summary = {"_retained_streams": {"stdout": b"x", "stderr": b""},
                       "streams": {"stdout": {"bytes": 1}, "stderr": {"bytes": 0}}}
            receipt, error = runner.write_retained_output(str(Path(directory, "runtime")), "safe-id", summary)
            self.assertIsNone(receipt)
            self.assertEqual(error, "output_capture_unsafe_path")
            self.assertEqual(list(target.iterdir()), [])


class RetentionCLIContract(base.CLIBase):
    def test_failed_turn_retains_private_output_but_not_in_the_ledger(self):
        self.init()
        marker = "fixture-private-provider-output"
        result = subprocess.run(
            [sys.executable, str(ROOT / "examples/headless_runner.py"), "claude",
             "--m8shift", str(Path(self.d, "M8SHIFT.md")),
             "--m8shift-py", str(Path(self.d, "m8shift.py")),
             "--runtime-dir", str(Path(self.d, ".m8shift/runtime")), "--cwd", self.d,
             "--run-id", "retention-cli", "--once", "--start-on-idle", "--max-retries", "1",
             "--retain-output", "--cmd", sys.executable, "-c", "print(%r)" % marker],
            cwd=self.d, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        ledger = Path(self.d, ".m8shift/runtime/runs.jsonl").read_text()
        self.assertNotIn(marker, ledger + result.stdout + result.stderr)
        rows = [json.loads(line) for line in ledger.splitlines()]
        receipt = next(row["output_receipt"] for row in rows if row["event"] == "run.output_retained")
        self.assertTrue(all(row["session_id"] for row in rows))
        private = json.loads(Path(self.d, ".m8shift/runtime", receipt["path"]).read_text())
        self.assertEqual(base64.b64decode(private["streams"]["stdout"]["data"]), (marker + "\n").encode())
        self.assertNotEqual(rows[-1].get("status"), "advanced")


if __name__ == "__main__":
    unittest.main()
