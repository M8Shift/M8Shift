"""Static argv help and refusal contract; no implicit shell evaluation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

RUNNER = Path(__file__).resolve().parents[1] / "examples" / "headless_runner.py"
spec = importlib.util.spec_from_file_location("headless_runner_contract", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerArgvTests(unittest.TestCase):
    def cli(self, *args, cwd):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("M8SHIFT_")}
        return subprocess.run([sys.executable, "-B", str(RUNNER), *args],
                              cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=10)

    def test_help_explains_tokens_and_explicit_shell(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.cli("--help", cwd=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = " ".join(result.stdout.split())
        for phrase in ("separate argument tokens", "not one quoted shell string",
                       "sh -c", "runner options before --cmd"):
            self.assertIn(phrase, text)

    def test_empty_and_non_array_argv_have_a_named_refusal(self):
        for value in ([], "echo hello", None, [""], [1]):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                runner.resolve_argv(value)

    def test_quoted_command_is_refused_without_executing_metacharacters(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.cli("alpha", "--dry-run", "--cmd",
                              "echo marker > SHOULD_NOT_EXIST", cwd=root)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("separate arguments", result.stderr)
            self.assertIn("sh -c", result.stderr)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_arguments_and_metacharacters_are_preserved_as_data(self):
        with tempfile.TemporaryDirectory() as root:
            args = [sys.executable, "-c", "print('not run')", "a b", "; touch SHOULD_NOT_EXIST"]
            result = self.cli("alpha", "--dry-run", "--cmd", *args, cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)["run_plan"]
            self.assertEqual(plan["argv"], args)
            self.assertFalse(plan["command"]["shell"])
            self.assertEqual(list(Path(root).iterdir()), [])

    @unittest.skipUnless(shutil.which("sh"), "explicit POSIX shell not available")
    def test_explicit_shell_is_an_explicit_argv_program_not_an_implicit_mode(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.cli("alpha", "--dry-run", "--cmd", "sh", "-c",
                              "printf marker > SHOULD_NOT_EXIST", cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)["run_plan"]
            self.assertEqual(plan["argv"], [shutil.which("sh"), "-c",
                                           "printf marker > SHOULD_NOT_EXIST"])
            self.assertFalse(plan["command"]["shell"])
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
