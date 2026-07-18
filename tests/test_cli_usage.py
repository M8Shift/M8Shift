import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


PYTHON_ENTRY_POINTS = (
    "m8shift.py",
    "m8shift-top.py",
    "m8shift-runtime.py",
    "m8shift-context.py",
    "m8shift-worktree.py",
    "m8shift-headroom.py",
    "m8shift-i18n.py",
    "m8shift-e2e.py",
    "m8shift-aliases.py",
    "examples/headless_runner.py",
    "examples/usage-adapters/claude-oauth-usage.py",
    "examples/usage-adapters/codex-ratelimits.py",
    "examples/usage-adapters/tokscale-spend.py",
    "scripts/m8shift-self-update.py",
    "scripts/scrub-check.py",
    "scripts/benchmark-startup.py",
    "scripts/benchmark-status-scale.py",
    "scripts/benchmark-scrub-check.py",
    "scripts/gen_docs.py",
)


def run(*argv):
    return subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class CliUsageTests(unittest.TestCase):
    def test_agent_facing_entry_points_bare_pipe_print_full_help_and_exit_zero(self):
        cases = {
            "m8shift-runtime.py": "local sidecars",
            "m8shift-context.py": "context records",
            "m8shift-top.py": "bare pipe/agent invocation",
            "examples/headless_runner.py": "bounded m8shift agent turn",
        }
        for relative, description in cases.items():
            with self.subTest(script=relative):
                result = run(sys.executable, str(ROOT / relative))
                self.assertEqual(result.returncode, 0, (relative, result.stderr))
                output = (result.stdout + result.stderr).lower()
                self.assertIn("usage:", output)
                self.assertIn("example", output)
                self.assertIn(description, output)

    def test_every_python_entry_point_has_help_with_usage_and_example(self):
        for relative in PYTHON_ENTRY_POINTS:
            with self.subTest(script=relative):
                result = run(sys.executable, str(ROOT / relative), "--help")
                self.assertEqual(result.returncode, 0, (relative, result.stderr))
                output = result.stdout.lower()
                self.assertIn("usage:", output)
                self.assertIn("example", output)

    def test_missing_append_recipient_is_actionable_and_keeps_argparse_exit_code(self):
        result = run(sys.executable, str(ROOT / "m8shift.py"), "append", "agent-a")
        self.assertEqual(result.returncode, 2)
        self.assertIn("the following arguments are required: --to", result.stderr)
        self.assertIn("m8shift.py append agent-a --to agent-b", result.stderr)
        normalized = " ".join(result.stderr.split())
        self.assertIn('--ask "review the change" --done "implemented it"', normalized)

    def test_other_required_argument_errors_print_command_specific_invocations(self):
        cases = (
            (("m8shift-worktree.py", "claim", "lane-a", "agent-a"), "--base BASE"),
            (("m8shift-e2e.py",), "m8shift-e2e.py CASE"),
            (("examples/headless_runner.py", "agent-a"), "--cmd COMMAND"),
            (("scripts/m8shift-self-update.py",), "--source DIR --target DIR"),
        )
        for (relative, *args), expected in cases:
            with self.subTest(script=relative):
                result = run(sys.executable, str(ROOT / relative), *args)
                self.assertEqual(result.returncode, 2, (relative, result.stderr))
                self.assertIn("required invocation example", result.stderr)
                self.assertIn(expected, result.stderr)

    def test_installer_help_and_missing_value_hint(self):
        help_result = run("bash", str(ROOT / "install.sh"), "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("Usage:", help_result.stdout)
        self.assertIn("Examples:", help_result.stdout)

        missing = run("bash", str(ROOT / "install.sh"), "--dir")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("--dir requires a value", missing.stderr)
        self.assertIn("try: bash install.sh --dir VALUE --dry-run", missing.stderr)

        watch_help = run("bash", str(ROOT / "scripts/watch-status.sh"), "--help")
        self.assertEqual(watch_help.returncode, 0)
        self.assertIn("Usage:", watch_help.stdout)
        self.assertIn("Examples:", watch_help.stdout)

    def test_powershell_installer_help_when_available(self):
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not installed")
        result = run(powershell, "-NoProfile", "-File", str(ROOT / "install.ps1"), "-Help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()
