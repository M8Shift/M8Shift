#!/usr/bin/env python3
"""Tests for m8shift-context.py Phase 1 native context companion."""
import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(REPO, "m8shift.py")
CONTEXT = os.path.join(REPO, "m8shift-context.py")


def run(args, cwd, stdin=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, input=stdin)


def load_context_module():
    spec = importlib.util.spec_from_file_location("m8shift_context", CONTEXT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContextBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="m8ctx-")
        self.addCleanup(shutil.rmtree, self.d, True)
        shutil.copy(CORE, os.path.join(self.d, "m8shift.py"))
        shutil.copy(CONTEXT, os.path.join(self.d, "m8shift-context.py"))
        self.assertEqual(self.core("init").returncode, 0)

    def core(self, *args):
        return run([sys.executable, "m8shift.py", *args], self.d)

    def ctx(self, *args, stdin=None):
        return run([sys.executable, "m8shift-context.py", *args], self.d, stdin=stdin)

    def write_json(self, rel, data):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path) or self.d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path


class TestContextInitDoctor(ContextBase):
    def test_init_writes_profiles_and_doctor_is_read_only_clean(self):
        r = self.ctx("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        profile = os.path.join(self.d, ".m8shift", "context", "profiles", "reviewer.json")
        self.assertTrue(os.path.exists(profile))
        with open(profile, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["schema"], "m8shift.context.profile.v1")
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "rtk-shell-output.json")
        self.assertTrue(os.path.exists(adapter))
        with open(adapter, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["schema"], "m8shift.adapter.v1")
        self.assertEqual(manifest["type"], "shell_output_filter")
        self.assertIn("git-diff", manifest["policy"]["forbidden_modes"])

        dr = self.ctx("doctor", "--json")
        self.assertEqual(dr.returncode, 0, dr.stderr)
        self.assertEqual(json.loads(dr.stdout)["findings"], [])


class TestContextPack(ContextBase):
    def test_pack_preserves_handoff_fields_verbatim_and_writes_receipt_metrics(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        self.assertEqual(self.core("claim", "claude").returncode, 0)
        ask = "PLEASE_KEEP_THIS_ASK_VERBATIM"
        done = "PLEASE_KEEP_THIS_DONE_VERBATIM"
        r = self.core(
            "append", "claude", "--to", "codex",
            "--ask", ask,
            "--done", done,
            "--files", "m8shift-context.py",
            "--decision", "accept",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        pr = self.ctx("pack", "--profile", "reviewer", "--turns", "1", "--write", "--json")
        self.assertEqual(pr.returncode, 0, pr.stderr)
        payload = json.loads(pr.stdout)
        pack_path = os.path.join(self.d, payload["pack"])
        with open(pack_path, encoding="utf-8") as fh:
            body = fh.read()

        self.assertIn("ask (verbatim)", body)
        self.assertIn(ask, body)
        self.assertIn("done (verbatim)", body)
        self.assertIn(done, body)
        self.assertIn("decision: accept", body)
        self.assertIn("Source references", body)
        self.assertTrue(payload["receipt"]["references"])

        mr = self.ctx("metrics", "--last", "--json")
        self.assertEqual(mr.returncode, 0, mr.stderr)
        metrics = json.loads(mr.stdout)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["schema"], "m8shift.context.metrics.v1")
        self.assertTrue(metrics[0]["required_fields_preserved"])


class TestContextBenchmark(ContextBase):
    def test_benchmark_requires_real_token_counts_for_ship_gate(self):
        proxy_only = self.ctx("benchmark", "--json")
        self.assertEqual(proxy_only.returncode, 0, proxy_only.stderr)
        payload = json.loads(proxy_only.stdout)
        self.assertFalse(payload["ship_gate_passed"])
        self.assertIn("missing real token counts", payload["warnings"][0])

        counts = {
            "small": {"without": 500, "with": 200},
            "medium": {"without": 5000, "with": 1000},
            "large": {"without": 20000, "with": 2500},
        }
        path = self.write_json("real-tokens.json", counts)
        real = self.ctx("benchmark", "--real-tokens", path, "--require-real-tokens", "--json")
        self.assertEqual(real.returncode, 0, real.stderr + real.stdout)
        payload = json.loads(real.stdout)
        self.assertTrue(payload["ship_gate_passed"])
        self.assertTrue(all(row["real_token_reduction"] > 0 for row in payload["fixtures"]))


class TestContextAdapters(ContextBase):
    def test_rtk_manifest_policy_and_forbidden_git_diff_mode(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        shown = self.ctx("adapters", "show", "rtk-shell-output")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        manifest = json.loads(shown.stdout)
        self.assertEqual(manifest["command"], ["rtk", "$M8SHIFT_ADAPTER_MODE_ARGS"])
        self.assertEqual(manifest["modes"]["err"], ["err"])
        self.assertEqual(manifest["modes"]["git-diff"], ["git", "diff"])
        self.assertIn("git-diff", manifest["policy"]["forbidden_modes"])

        checked = self.ctx("adapters", "check", "rtk-shell-output", "--json")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["ok"])

        refused = self.ctx(
            "adapters", "run", "rtk-shell-output", "--mode", "git-diff", "--stdin",
            stdin="diff --git a/x b/x\n@@\n-old\n+new\n",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("forbidden", refused.stderr)

    def test_adapter_runner_is_argv_only_bounded_and_wraps_output(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        self.write_json(".m8shift/context/adapters/fake-filter.json", {
            "schema": "m8shift.adapter.v1",
            "name": "fake-filter",
            "type": "shell_output_filter",
            "version": "0.1.0",
            "authority": "advisory",
            "command": [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write(sys.stdin.read().replace('INFO noisy\\n', ''))",
            ],
            "capabilities": ["filter_errors"],
            "input_schema": "m8shift.shell_output_filter.request.v1",
            "output_schema": "m8shift.shell_output_filter.response.v1",
            "mutates_core": False,
            "mutates_repo": False,
            "requires_env": [],
            "timeout_seconds": 10,
            "max_stdout_bytes": 4096,
            "failure_policy": "fail_closed",
            "modes": {"err": []},
        })
        run_result = self.ctx(
            "adapters", "run", "fake-filter", "--mode", "err", "--stdin", "--json",
            stdin="INFO noisy\nERROR keep me\n",
        )
        self.assertEqual(run_result.returncode, 0, run_result.stderr)
        payload = json.loads(run_result.stdout)
        self.assertEqual(payload["schema"], "m8shift.adapter.result.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("INFO noisy", payload["filtered_text"])
        self.assertIn("ERROR keep me", payload["filtered_text"])
        self.assertEqual(payload["filtered_metrics"]["lines"], 1)

    def test_adapter_check_rejects_shell_string_command(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        self.write_json(".m8shift/context/adapters/bad.json", {
            "schema": "m8shift.adapter.v1",
            "name": "bad",
            "type": "shell_output_filter",
            "version": "0.1.0",
            "authority": "advisory",
            "command": "rtk err",
            "capabilities": [],
            "input_schema": "m8shift.shell_output_filter.request.v1",
            "output_schema": "m8shift.shell_output_filter.response.v1",
            "mutates_core": False,
            "mutates_repo": False,
            "requires_env": [],
            "timeout_seconds": 10,
            "max_stdout_bytes": 4096,
            "failure_policy": "fail_closed",
        })
        checked = self.ctx("adapters", "check", "bad", "--json")
        self.assertEqual(checked.returncode, 1)
        findings = json.loads(checked.stdout)["findings"]
        self.assertIn("adapter.command_string", {row["check"] for row in findings})


class TestContextGitCollector(unittest.TestCase):
    def test_git_collector_timeout_returns_empty_string(self):
        module = load_context_module()
        with mock.patch.object(
            module.subprocess,
            "run",
            side_effect=module.subprocess.TimeoutExpired(["git"], module.GIT_TIMEOUT_SECONDS),
        ) as run_mock:
            self.assertEqual(module.git("/tmp/project", ["status", "--short"]), "")
        self.assertEqual(run_mock.call_args.kwargs["timeout"], module.GIT_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
