#!/usr/bin/env python3
"""Tests for m8shift-context.py Phase 1 native context companion."""
import hashlib
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


def run(args, cwd, stdin=None, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, input=stdin, env=env)


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

    def ctx(self, *args, stdin=None, env=None):
        return run([sys.executable, "m8shift-context.py", *args], self.d, stdin=stdin, env=env)

    def write_json(self, rel, data):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path) or self.d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def fake_rtk_env(self, body):
        bindir = os.path.join(self.d, "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "rtk")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n" + body)
        os.chmod(path, 0o755)
        self.fake_rtk_path = path
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        return env

    def trusted_rtk_identity(self, path=None):
        path = path or self.fake_rtk_path
        real = os.path.realpath(path)
        h = hashlib.sha256()
        with open(real, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return {"program": "rtk", "path": real, "sha256": h.hexdigest()}

    def symlinked_rtk_to_core_env(self):
        bindir = os.path.join(self.d, "bin")
        os.makedirs(bindir, exist_ok=True)
        core = os.path.join(self.d, "m8shift.py")
        os.chmod(core, 0o755)
        os.symlink(core, os.path.join(bindir, "rtk"))
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        return env

    def rtk_hijack_env(self, body, dirname="hijack-bin"):
        bindir = os.path.join(self.d, dirname)
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "rtk")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        return env


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
        self.assertIn("rtk", json.loads(dr.stdout))

    def test_init_disables_rtk_telemetry_and_doctor_surfaces_state(self):
        marker = os.path.join(self.d, "rtk-telemetry.txt")
        env = self.fake_rtk_env(
            "import sys\n"
            f"open({marker!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
        )
        r = self.ctx("init", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(marker, encoding="utf-8") as fh:
            calls = fh.read()
        self.assertIn("telemetry disable", calls)

        dr = self.ctx("doctor", "--json", env=env)
        self.assertEqual(dr.returncode, 0, dr.stderr)
        payload = json.loads(dr.stdout)
        self.assertTrue(payload["rtk"]["present"])
        self.assertTrue(payload["rtk"]["pinned"])
        self.assertEqual(payload["rtk"]["telemetry"]["state"], "disabled")


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

    def test_pack_defaults_to_pinned_rtk_when_present_else_native_and_opt_out(self):
        marker = os.path.join(self.d, "rtk-run.txt")
        env = self.fake_rtk_env(
            "import sys\n"
            f"open({marker!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "else:\n"
            "    sys.stdout.write('RTK_FILTERED\\n' + sys.stdin.read())\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        auto = self.ctx("pack", "--profile", "reviewer", "--turns", "1", env=env)
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertIn("adapter: `rtk-shell-output`", auto.stdout)
        self.assertIn("adapter_status: `ok`", auto.stdout)
        with open(marker, encoding="utf-8") as fh:
            calls = fh.read()
        self.assertIn("git log", calls)

        native = self.ctx("pack", "--profile", "reviewer", "--turns", "1", "--adapter", "native", env=env)
        self.assertEqual(native.returncode, 0, native.stderr)
        self.assertNotIn("adapter: `rtk-shell-output`", native.stdout)

        absent_env = dict(os.environ)
        absent_env["PATH"] = os.path.join(self.d, "empty-bin")
        os.makedirs(absent_env["PATH"], exist_ok=True)
        fake_git = os.path.join(absent_env["PATH"], "git")
        with open(fake_git, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n")
        os.chmod(fake_git, 0o755)
        absent = self.ctx("pack", "--profile", "reviewer", "--turns", "1", env=absent_env)
        self.assertEqual(absent.returncode, 0, absent.stderr)
        self.assertNotIn("adapter: `rtk-shell-output`", absent.stdout)

    def test_pack_auto_degrades_corrupt_rtk_manifest_to_native(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "rtk-shell-output.json")
        cases = {
            "broken_json": "{not valid json",
            "non_object_json": "[1, 2, 3]",
        }
        for label, body in cases.items():
            with self.subTest(label=label):
                with open(adapter, "w", encoding="utf-8") as fh:
                    fh.write(body)
                auto = self.ctx("pack", "--profile", "reviewer", "--turns", "1")
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertIn("M8Shift Context Pack", auto.stdout)
                self.assertNotIn("adapter: `rtk-shell-output`", auto.stdout)

                explicit = self.ctx("pack", "--profile", "reviewer", "--turns", "1", "--adapter", "rtk-shell-output")
                self.assertNotEqual(explicit.returncode, 0)
                self.assertIn("m8shift-context:", explicit.stderr)


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
        env = self.fake_rtk_env("import sys\nsys.stdout.write(sys.stdin.read())\n")
        self.assertEqual(self.ctx("adapters", "init", "--force", env=env).returncode, 0)
        shown = self.ctx("adapters", "show", "rtk-shell-output")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        manifest = json.loads(shown.stdout)
        self.assertEqual(manifest["command"], ["rtk", "$M8SHIFT_ADAPTER_MODE_ARGS"])
        self.assertEqual(manifest["trusted_executable"], self.trusted_rtk_identity())
        self.assertEqual(manifest["modes"]["err"], ["err"])
        self.assertEqual(manifest["modes"]["git-diff"], ["git", "diff"])
        self.assertIn("git-diff", manifest["policy"]["forbidden_modes"])

        checked = self.ctx(
            "adapters", "check", "rtk-shell-output", "--json",
            env=env,
        )
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
        env = self.fake_rtk_env(
            "import sys\n"
            "lines = sys.stdin.read().splitlines(True)\n"
            "sys.stdout.write(''.join(line for line in lines if not line.startswith('INFO noisy')))\n"
        )
        self.write_json(".m8shift/context/adapters/fake-filter.json", {
            "schema": "m8shift.adapter.v1",
            "name": "fake-filter",
            "type": "shell_output_filter",
            "version": "0.1.0",
            "authority": "advisory",
            "command": ["rtk"],
            "trusted_executable": self.trusted_rtk_identity(),
            "capabilities": ["filter_errors"],
            "input_schema": "m8shift.shell_output_filter.request.v1",
            "output_schema": "m8shift.shell_output_filter.response.v1",
            "mutates_core": False,
            "mutates_repo": False,
            "requires_env": [],
            "timeout_seconds": 10,
            "max_stdout_bytes": 4096,
            "max_stderr_bytes": 4096,
            "failure_policy": "fail_closed",
            "modes": {"err": []},
        })
        run_result = self.ctx(
            "adapters", "run", "fake-filter", "--mode", "err", "--stdin", "--json",
            stdin="INFO noisy\nERROR keep me\n",
            env=env,
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

    def test_adapter_check_rejects_paths_interpreters_core_and_missing_binary(self):
        self.assertEqual(self.ctx("init").returncode, 0)

        def manifest(name, command):
            self.write_json(f".m8shift/context/adapters/{name}.json", {
                "schema": "m8shift.adapter.v1",
                "name": name,
                "type": "shell_output_filter",
                "version": "0.1.0",
                "authority": "advisory",
                "command": command,
                "capabilities": [],
                "input_schema": "m8shift.shell_output_filter.request.v1",
                "output_schema": "m8shift.shell_output_filter.response.v1",
                "mutates_core": False,
                "mutates_repo": False,
                "requires_env": [],
                "timeout_seconds": 10,
                "max_stdout_bytes": 4096,
                "max_stderr_bytes": 4096,
                "failure_policy": "fail_closed",
                "modes": {"err": []},
            })

        cases = {
            "abs-path": (["/tmp/evil"], "adapter.program_path"),
            "rel-path": (["./evil"], "adapter.program_path"),
            "traversal": (["../../../tmp/evil"], "adapter.program_path"),
            "interpreter": (["python3", "-c", "print(1)"], "adapter.program_not_allowed"),
            "core": (["m8shift.py", "release"], "adapter.program_denied"),
        }
        for name, (command, expected) in cases.items():
            with self.subTest(name=name):
                manifest(name, command)
                checked = self.ctx("adapters", "check", name, "--json")
                self.assertEqual(checked.returncode, 1, checked.stdout)
                self.assertIn(expected, {row["check"] for row in json.loads(checked.stdout)["findings"]})

        manifest("missing-rtk", ["rtk"])
        checked = self.ctx(
            "adapters", "check", "missing-rtk", "--json",
            env={**os.environ, "PATH": os.path.join(self.d, "empty-bin")},
        )
        self.assertEqual(checked.returncode, 1, checked.stdout)
        self.assertIn("adapter.executable_missing", {row["check"] for row in json.loads(checked.stdout)["findings"]})

    def test_adapter_check_and_run_reject_resolved_core_symlink(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        env = self.symlinked_rtk_to_core_env()

        checked = self.ctx("adapters", "check", "rtk-shell-output", "--json", env=env)
        self.assertEqual(checked.returncode, 1, checked.stdout)
        self.assertIn(
            "adapter.program_resolved_denied",
            {row["check"] for row in json.loads(checked.stdout)["findings"]},
        )

        result = self.ctx(
            "adapters", "run", "rtk-shell-output", "--mode", "err", "--stdin",
            stdin="ERROR should not execute core\n",
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resolves to a M8Shift relay binary", result.stderr)

    def test_adapter_run_rejects_renamed_core_copy_named_rtk(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        trusted_env = self.fake_rtk_env("import sys\nsys.stdout.write(sys.stdin.read())\n")
        self.assertEqual(self.ctx("adapters", "init", "--force", env=trusted_env).returncode, 0)

        hijack_bin = os.path.join(self.d, "copy-hijack")
        os.makedirs(hijack_bin, exist_ok=True)
        shutil.copy(os.path.join(self.d, "m8shift.py"), os.path.join(hijack_bin, "rtk"))
        os.chmod(os.path.join(hijack_bin, "rtk"), 0o755)
        hijack_env = os.environ.copy()
        hijack_env["PATH"] = hijack_bin + os.pathsep + hijack_env.get("PATH", "")

        checked = self.ctx("adapters", "check", "rtk-shell-output", "--json", env=hijack_env)
        self.assertEqual(checked.returncode, 1, checked.stdout)
        self.assertIn(
            "adapter.program_identity_mismatch",
            {row["check"] for row in json.loads(checked.stdout)["findings"]},
        )

        result = self.ctx(
            "adapters", "run", "rtk-shell-output", "--mode", "err", "--stdin",
            stdin="ERROR should not execute renamed core\n",
            env=hijack_env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected", result.stderr)

    def test_adapter_run_rejects_wrapper_named_rtk(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        trusted_env = self.fake_rtk_env("import sys\nsys.stdout.write(sys.stdin.read())\n")
        self.assertEqual(self.ctx("adapters", "init", "--force", env=trusted_env).returncode, 0)
        witness = os.path.join(self.d, "wrapper-executed.txt")
        core = os.path.join(self.d, "m8shift.py")
        hijack_env = self.rtk_hijack_env(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            f"open({witness!r}, 'w', encoding='utf-8').write('PWNED')\n"
            f"os.execv(sys.executable, [sys.executable, {core!r}, 'status'])\n",
            dirname="wrapper-hijack",
        )

        checked = self.ctx("adapters", "check", "rtk-shell-output", "--json", env=hijack_env)
        self.assertEqual(checked.returncode, 1, checked.stdout)
        self.assertIn(
            "adapter.program_identity_mismatch",
            {row["check"] for row in json.loads(checked.stdout)["findings"]},
        )

        result = self.ctx(
            "adapters", "run", "rtk-shell-output", "--mode", "err", "--stdin",
            stdin="ERROR should not execute wrapper\n",
            env=hijack_env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected", result.stderr)
        self.assertFalse(os.path.exists(witness))

    def test_adapter_run_caps_stderr_and_falls_back_without_buffering_unbounded(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        env = self.fake_rtk_env("import sys\nsys.stderr.write('x' * 1000)\nsys.stdout.write('SHOULD NOT WIN\\n')\n")
        self.write_json(".m8shift/context/adapters/noisy-stderr.json", {
            "schema": "m8shift.adapter.v1",
            "name": "noisy-stderr",
            "type": "shell_output_filter",
            "version": "0.1.0",
            "authority": "advisory",
            "command": ["rtk"],
            "trusted_executable": self.trusted_rtk_identity(),
            "capabilities": [],
            "input_schema": "m8shift.shell_output_filter.request.v1",
            "output_schema": "m8shift.shell_output_filter.response.v1",
            "mutates_core": False,
            "mutates_repo": False,
            "requires_env": [],
            "timeout_seconds": 10,
            "max_stdout_bytes": 4096,
            "max_stderr_bytes": 100,
            "failure_policy": "fallback_original",
            "modes": {"err": []},
        })
        result = self.ctx(
            "adapters", "run", "noisy-stderr", "--mode", "err", "--stdin", "--json",
            stdin="ERROR original\n",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["fallback_used"])
        self.assertIn("stderr exceeded limit", payload["error"])
        self.assertEqual(payload["filtered_text"], "ERROR original\n")

    def test_adapter_input_rejects_symlink_escape(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        env = self.fake_rtk_env("import sys\nsys.stdout.write(sys.stdin.read())\n")
        self.assertEqual(self.ctx("adapters", "init", "--force", env=env).returncode, 0)
        outside = tempfile.NamedTemporaryFile("w", delete=False)
        self.addCleanup(lambda: os.path.exists(outside.name) and os.unlink(outside.name))
        with outside:
            outside.write("SECRET OUTSIDE\n")
        os.symlink(outside.name, os.path.join(self.d, "linked-outside.txt"))
        result = self.ctx(
            "adapters", "run", "rtk-shell-output", "--mode", "err", "--input", "linked-outside.txt",
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes project root", result.stderr)


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
