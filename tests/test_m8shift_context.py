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
        bindir = tempfile.mkdtemp(prefix="m8ctx-system-rkt-")
        self.addCleanup(shutil.rmtree, bindir, True)
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "rtk")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n" + body)
        os.chmod(path, 0o755)
        self.fake_rtk_path = path
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        return env

    def fake_headroom_env(self, body):
        bindir = tempfile.mkdtemp(prefix="m8ctx-system-headroom-")
        self.addCleanup(shutil.rmtree, bindir, True)
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "headroom")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n" + body)
        os.chmod(path, 0o755)
        self.fake_headroom_path = path
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

    def trusted_headroom_identity(self, path=None):
        path = path or self.fake_headroom_path
        real = os.path.realpath(path)
        h = hashlib.sha256()
        with open(real, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return {"program": "headroom", "path": real, "sha256": h.hexdigest()}

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
        self.assertEqual(payload["rtk"]["telemetry"]["state"], "not-reported")

    def test_status_and_doctor_show_rtk_state_and_last_pack_ratio(self):
        off = self.ctx("status")
        self.assertEqual(off.returncode, 0, off.stderr)
        self.assertIn("RTK: OFF (native)", off.stdout)

        env = self.fake_rtk_env(
            "import sys\n"
            "if sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "else:\n"
            "    sys.stdout.write('RTK_FILTERED\\n' + sys.stdin.read())\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        packed = self.ctx("pack", "--profile", "reviewer", "--turns", "1", "--write", "--json", env=env)
        self.assertEqual(packed.returncode, 0, packed.stderr)

        status = self.ctx("status", "--json", env=env)
        self.assertEqual(status.returncode, 0, status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual(payload["rtk"]["state"], "on")
        self.assertTrue(payload["rtk"]["pinned"])
        self.assertIsNotNone(payload["rtk"]["last_pack"]["compression_ratio"])

        human = self.ctx("status", env=env)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("RTK: ON (pinned, compressing packs)", human.stdout)
        self.assertIn("last pack:", human.stdout)

        doctor = self.ctx("doctor", env=env)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("RTK: ON (pinned, compressing packs)", doctor.stdout)
        self.assertIn("last pack:", doctor.stdout)

    def test_status_doctor_report_corrupt_rtk_manifest_and_metrics_without_abort(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "rtk-shell-output.json")
        with open(adapter, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        with open(os.path.join(self.d, ".m8shift", "context", "metrics.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("{bad-json}\n")

        status = self.ctx("status", "--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        status_payload = json.loads(status.stdout)
        self.assertEqual(status_payload["rtk"]["state"], "off")
        self.assertIn("adapter.manifest_unreadable", {f["check"] for f in status_payload["rtk"]["findings"]})
        self.assertIn("metrics.unreadable", {f["check"] for f in status_payload["rtk"]["findings"]})

        doctor = self.ctx("doctor", "--json")
        self.assertNotIn("m8shift-context:", doctor.stderr)
        self.assertIn(doctor.returncode, (0, 1))
        doctor_payload = json.loads(doctor.stdout)
        checks = {f["check"] for f in doctor_payload["findings"]}
        self.assertIn("adapter.manifest_unreadable", checks)
        self.assertIn("metrics.unreadable", checks)

    def test_status_doctor_report_oversize_and_nonregular_rtk_without_traceback(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "rtk-shell-output.json")
        bindir = os.path.join(self.d, "bin")
        os.makedirs(bindir, exist_ok=True)
        env = os.environ.copy()
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")

        def write_manifest(trusted_path):
            with open(adapter, "w", encoding="utf-8") as fh:
                json.dump({
                    "schema": "m8shift.adapter.v1",
                    "name": "rtk-shell-output",
                    "type": "shell_output_filter",
                    "authority": "advisory",
                    "command": ["rtk", "$M8SHIFT_ADAPTER_MODE_ARGS"],
                    "mutates_core": False,
                    "mutates_repo": False,
                    "trusted_executable": {
                        "program": "rtk",
                        "path": trusted_path,
                        "sha256": "0" * 64,
                    },
                }, fh)

        def assert_safe():
            status = subprocess.run(
                [sys.executable, "m8shift-context.py", "status", "--json"],
                cwd=self.d, env=env, capture_output=True, text=True, timeout=4,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertNotIn("Traceback", status.stderr + status.stdout)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["rtk"]["state"], "off")
            self.assertIn("adapter.program_identity_mismatch", {f["check"] for f in status_payload["rtk"]["findings"]})

            doctor = subprocess.run(
                [sys.executable, "m8shift-context.py", "doctor", "--json"],
                cwd=self.d, env=env, capture_output=True, text=True, timeout=4,
            )
            self.assertIn(doctor.returncode, (0, 1))
            self.assertNotIn("Traceback", doctor.stderr + doctor.stdout)
            self.assertIn("adapter.program_identity_mismatch", {f["check"] for f in json.loads(doctor.stdout)["findings"]})

        rtk = os.path.join(bindir, "rtk")
        with open(rtk, "wb") as fh:
            fh.truncate(513 * 1024 * 1024)
        os.chmod(rtk, 0o755)
        write_manifest(os.path.realpath(rtk))
        assert_safe()

        with open(rtk, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys\nsys.stdout.write('ok')\n")
        os.chmod(rtk, 0o755)
        if hasattr(os, "mkfifo"):
            fifo = os.path.join(self.d, "rtk-fifo")
            os.mkfifo(fifo)
            write_manifest(fifo)
            assert_safe()


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


class TestContextCompression(ContextBase):
    def test_compression_routing_signal_defaults_and_internal_fail_safe(self):
        ctx = load_context_module()
        self.assertEqual(ctx.normalize_compression_access_mode("garbage"), "retrieve")

        class EmptyArgs:
            pass

        self.assertEqual(ctx.compression_routing_signals(EmptyArgs()), {
            "access_mode": "retrieve",
            "whole_content": False,
        })

    def test_compress_writes_redacted_record_and_bounded_retrieve(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        slack_token = "xoxb-" + "1234567890-" + "abcdefghijklmnop"
        stripe_key = "sk_" + "live_" + "1234567890abcdef"
        raw = "\n".join([
            "INFO boot",
            "password=super-secret",
            "MYSECRET=uppercase-secret",
            "aws_secret_access_key=aws-secret-value",
            f"SLACK={slack_token}",
            "GOOGLE=AIza" + ("A" * 35),
            f"STRIPE={stripe_key}",
            "URL=https://user:urlpassword@example.com/db",
            "ERROR failed in /tmp/project/tests/test_app.py",
            "exit code 2",
            *(["NOISY repeated line"] * 5),
        ]) + "\n"

        result = self.ctx(
            "compress", "--id", "rec1", "--type", "test_output", "--agent", "codex", "--backend", "builtin", "--stdin", "--json",
            stdin=raw,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "m8shift.compressed_context_record.v1")
        self.assertEqual(payload["adapter_result"]["schema"], "m8shift.adapter.result.v1")
        self.assertEqual(payload["context_digest"]["schema"], "m8shift.context_digest.v1")
        self.assertEqual(payload["handoff_digest"]["schema"], "m8shift.handoff_digest.v1")
        self.assertEqual(payload["raw_output_reference"]["schema"], "m8shift.raw_output_reference.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["fallback_used"])
        self.assertEqual(payload["access_mode"], "retrieve")
        self.assertFalse(payload["whole_content"])
        self.assertIn("[REDACTED]", payload["adapter_result"]["filtered_text"])
        self.assertNotIn("super-secret", json.dumps(payload))
        for secret in (
            "uppercase-secret",
            "aws-secret-value",
            slack_token,
            "AIza" + ("A" * 35),
            stripe_key,
            "urlpassword",
        ):
            self.assertNotIn(secret, json.dumps(payload))

        raw_path = os.path.join(self.d, ".m8shift", "context", "compression", "raw", "rec1.raw.txt")
        record_path = os.path.join(self.d, ".m8shift", "context", "compression", "records", "rec1.json")
        with open(record_path, encoding="utf-8") as fh:
            stored_record = json.load(fh)
        self.assertEqual(stored_record["access_mode"], "retrieve")
        self.assertFalse(stored_record["whole_content"])
        with open(raw_path, encoding="utf-8") as fh:
            stored_raw = fh.read()
        self.assertIn("password=[REDACTED]", stored_raw)
        self.assertNotIn("super-secret", stored_raw)
        self.assertIn("MYSECRET=[REDACTED]", stored_raw)
        self.assertIn("aws_secret_access_key=[REDACTED]", stored_raw)
        for secret in (
            "uppercase-secret",
            "aws-secret-value",
            slack_token,
            "AIza" + ("A" * 35),
            stripe_key,
            "urlpassword",
        ):
            self.assertNotIn(secret, stored_raw)

        retrieved = self.ctx("retrieve", "rec1", "--lines", "3", "--json")
        self.assertEqual(retrieved.returncode, 0, retrieved.stderr)
        retrieved_payload = json.loads(retrieved.stdout)
        self.assertTrue(retrieved_payload["bounded"])
        self.assertLessEqual(len(retrieved_payload["content"].splitlines()), 3)
        pending = []
        for dirpath, _, filenames in os.walk(os.path.join(self.d, ".m8shift", "context", "compression")):
            pending.extend(name for name in filenames if ".pending." in name)
        self.assertEqual(pending, [])

    def test_retrieve_accepts_legacy_record_without_routing_signal_fields(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        record_id = "legacy-record"
        base = os.path.join(self.d, ".m8shift", "context", "compression")
        record_dir = os.path.join(base, "records")
        raw_dir = os.path.join(base, "raw")
        compact_dir = os.path.join(base, "compact")
        for path in (record_dir, raw_dir, compact_dir):
            os.makedirs(path, exist_ok=True)
        raw_text = "legacy raw line 1\nlegacy raw line 2\n"
        compact_text = "legacy compact line\n"
        with open(os.path.join(raw_dir, f"{record_id}.raw.txt"), "w", encoding="utf-8") as fh:
            fh.write(raw_text)
        with open(os.path.join(compact_dir, f"{record_id}.compact.txt"), "w", encoding="utf-8") as fh:
            fh.write(compact_text)
        legacy_record = {
            "schema": "m8shift.compressed_context_record.v1",
            "id": record_id,
            "content_type": "report",
            "backend": "builtin",
            "requested_backend": "auto",
            "raw_output_reference": {
                "schema": "m8shift.raw_output_reference.v1",
                "record_id": record_id,
                "path": f".m8shift/context/compression/raw/{record_id}.raw.txt",
                "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            },
            "adapter_result": {
                "schema": "m8shift.adapter.result.v1",
                "filtered_sha256": hashlib.sha256(compact_text.encode("utf-8")).hexdigest(),
            },
        }
        with open(os.path.join(record_dir, f"{record_id}.json"), "w", encoding="utf-8") as fh:
            json.dump(legacy_record, fh)

        raw = self.ctx("retrieve", record_id, "--lines", "2", "--json")
        self.assertEqual(raw.returncode, 0, raw.stderr + raw.stdout)
        raw_payload = json.loads(raw.stdout)
        self.assertEqual(raw_payload["source"], "raw")
        self.assertIn("legacy raw line 2", raw_payload["content"])

        compact = self.ctx("retrieve", record_id, "--compact", "--lines", "1", "--json")
        self.assertEqual(compact.returncode, 0, compact.stderr + compact.stdout)
        compact_payload = json.loads(compact.stdout)
        self.assertEqual(compact_payload["source"], "compact")
        self.assertIn("legacy compact line", compact_payload["content"])

    def test_retrieve_refuses_raw_hash_mismatch(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        compressed = self.ctx(
            "compress", "--id", "tamper-raw", "--stdin", "--json",
            stdin="original raw\n",
        )
        self.assertEqual(compressed.returncode, 0, compressed.stderr + compressed.stdout)
        raw_path = os.path.join(self.d, ".m8shift", "context", "compression", "raw", "tamper-raw.raw.txt")
        with open(raw_path, "w", encoding="utf-8") as fh:
            fh.write("tampered raw\n")

        retrieved = self.ctx("retrieve", "tamper-raw", "--json")
        self.assertNotEqual(retrieved.returncode, 0)
        self.assertIn("raw hash mismatch", retrieved.stderr)
        self.assertNotIn("tampered raw", retrieved.stdout)

    def test_retrieve_refuses_compact_hash_mismatch(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        compressed = self.ctx(
            "compress", "--id", "tamper-compact", "--stdin", "--json",
            stdin="original compact source\n",
        )
        self.assertEqual(compressed.returncode, 0, compressed.stderr + compressed.stdout)
        compact_path = os.path.join(self.d, ".m8shift", "context", "compression", "compact", "tamper-compact.compact.txt")
        with open(compact_path, "w", encoding="utf-8") as fh:
            fh.write("tampered compact\n")

        retrieved = self.ctx("retrieve", "tamper-compact", "--compact", "--json")
        self.assertNotEqual(retrieved.returncode, 0)
        self.assertIn("compact hash mismatch", retrieved.stderr)
        self.assertNotIn("tampered compact", retrieved.stdout)

    def test_compress_rejects_traversal_record_id(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        result = self.ctx("compress", "--id", "../bad", "--stdin", stdin="raw\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe record id", result.stderr)
        self.assertNotIn("Traceback", result.stderr + result.stdout)

        colon = self.ctx("compress", "--id", "bad:id", "--stdin", stdin="raw\n")
        self.assertNotEqual(colon.returncode, 0)
        self.assertIn("unsafe record id", colon.stderr)
        self.assertNotIn("Traceback", colon.stderr + colon.stdout)

    def test_retrieve_rejects_redos_and_oversize_grep(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        result = self.ctx("compress", "--id", "grep1", "--stdin", stdin="aaaaaaaaaaaaaaaaaaaa\nERROR line\n")
        self.assertEqual(result.returncode, 0, result.stderr)

        redos = self.ctx("retrieve", "grep1", "--grep", "(a+)+$")
        self.assertNotEqual(redos.returncode, 0)
        self.assertIn("unsafe grep pattern", redos.stderr)
        self.assertNotIn("Traceback", redos.stderr + redos.stdout)

        counted = self.ctx("retrieve", "grep1", "--grep", "(a?){28}a{28}")
        self.assertNotEqual(counted.returncode, 0)
        self.assertIn("unsafe grep pattern", counted.stderr)
        self.assertNotIn("Traceback", counted.stderr + counted.stdout)

        counted_30 = self.ctx("retrieve", "grep1", "--grep", "(a?){30}a{30}")
        self.assertNotEqual(counted_30.returncode, 0)
        self.assertIn("unsafe grep pattern", counted_30.stderr)
        self.assertNotIn("Traceback", counted_30.stderr + counted_30.stdout)

        too_long = self.ctx("retrieve", "grep1", "--grep", "a" * 129)
        self.assertNotEqual(too_long.returncode, 0)
        self.assertIn("unsafe grep pattern", too_long.stderr)
        self.assertNotIn("Traceback", too_long.stderr + too_long.stdout)

    def test_missing_or_malformed_config_redacts_and_reference_only_fail_safe(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        config = os.path.join(self.d, ".m8shift", "context-compression.json")
        os.unlink(config)

        missing = self.ctx(
            "compress", "--id", "missingcfg", "--stdin", "--json",
            stdin="token=abc123secret\nERROR raw remains referenced\n",
        )
        self.assertEqual(missing.returncode, 0, missing.stderr)
        payload = json.loads(missing.stdout)
        self.assertEqual(payload["status"], "reference_only")
        self.assertTrue(payload["fallback_used"])
        self.assertIn("compression.config_missing", {row["check"] for row in payload["findings"]})
        self.assertNotIn("abc123secret", json.dumps(payload))
        with open(os.path.join(self.d, ".m8shift", "context", "compression", "raw", "missingcfg.raw.txt"), encoding="utf-8") as fh:
            self.assertNotIn("abc123secret", fh.read())

        with open(config, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        malformed = self.ctx(
            "compress", "--id", "badcfg", "--stdin", "--json",
            stdin="api_key=abc123secret\n",
        )
        self.assertEqual(malformed.returncode, 0, malformed.stderr)
        payload = json.loads(malformed.stdout)
        self.assertEqual(payload["status"], "reference_only")
        self.assertIn("compression.config_unreadable", {row["check"] for row in payload["findings"]})
        self.assertNotIn("abc123secret", json.dumps(payload))

    def test_backend_error_falls_back_to_reference_only_not_raw(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        result = self.ctx(
            "compress", "--id", "backenderr", "--backend", "missing-backend", "--stdin", "--json",
            stdin="password=super-secret\nfull raw should not be inline\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "reference_only")
        self.assertTrue(payload["fallback_used"])
        self.assertIn("unsupported or unavailable backend", payload["adapter_result"]["error"])
        self.assertIn("reference-only", payload["adapter_result"]["filtered_text"])
        self.assertNotIn("super-secret", json.dumps(payload))
        self.assertNotIn("full raw should not be inline", payload["adapter_result"]["filtered_text"])
        with open(os.path.join(self.d, ".m8shift", "context", "compression", "raw", "backenderr.raw.txt"), encoding="utf-8") as fh:
            self.assertNotIn("super-secret", fh.read())

    def test_auto_rtk_backend_uses_pinned_adapter_for_test_output(self):
        marker = os.path.join(self.d, "rtk-compress.txt")
        env = self.fake_rtk_env(
            "import sys\n"
            f"open({marker!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "else:\n"
            "    data = sys.stdin.read()\n"
            "    sys.stdout.write('RTK_COMPACT mode=' + ' '.join(sys.argv[1:]) + '\\n')\n"
            "    sys.stdout.write(data.replace('INFO noisy\\n', ''))\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        result = self.ctx(
            "compress", "--id", "rtk1", "--type", "test_output", "--stdin", "--json",
            stdin="password=super-secret\nINFO noisy\nERROR failed\nexit code 1\n",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "rtk-shell-output")
        self.assertEqual(payload["adapter_result"]["adapter"], "rtk-shell-output")
        self.assertEqual(payload["adapter_result"]["mode"], "test")
        self.assertIn("RTK_COMPACT mode=test", payload["adapter_result"]["filtered_text"])
        self.assertIn("exit code 1", payload["adapter_result"]["filtered_text"])
        self.assertNotIn("super-secret", json.dumps(payload))
        with open(marker, encoding="utf-8") as fh:
            self.assertIn("test", fh.read())

    def test_auto_rtk_backend_error_falls_back_to_builtin_not_raw(self):
        env = self.fake_rtk_env(
            "import sys\n"
            "if sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "else:\n"
            "    sys.stderr.write('rtk failed')\n"
            "    raise SystemExit(9)\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        result = self.ctx(
            "compress", "--id", "rtkfail", "--type", "test_output", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertEqual(payload["adapter_result"]["adapter"], "builtin")
        self.assertFalse(payload["fallback_used"])
        self.assertIn("compression.rtk_fallback", {row["check"] for row in payload["findings"]})
        self.assertNotIn("super-secret", json.dumps(payload))

    def test_drifted_rtk_manifest_mode_error_degrades_without_crash(self):
        env = self.fake_rtk_env(
            "import sys\n"
            "if sys.argv[1:] == ['telemetry', 'disable']:\n"
            "    print('disabled')\n"
            "elif sys.argv[1:] == ['telemetry', 'status']:\n"
            "    print('telemetry disabled')\n"
            "else:\n"
            "    sys.stdout.write(sys.stdin.read())\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "rtk-shell-output.json")
        with open(adapter, encoding="utf-8") as fh:
            manifest = json.load(fh)
        del manifest["modes"]["test"]
        with open(adapter, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        auto = self.ctx(
            "compress", "--id", "drift-auto", "--type", "test_output", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
            env=env,
        )
        self.assertEqual(auto.returncode, 0, auto.stderr + auto.stdout)
        self.assertNotIn("Traceback", auto.stderr + auto.stdout)
        payload = json.loads(auto.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertFalse(payload["fallback_used"])
        self.assertIn("compression.rtk_fallback", {row["check"] for row in payload["findings"]})
        self.assertNotIn("super-secret", json.dumps(payload))

        explicit = self.ctx(
            "compress", "--id", "drift-explicit", "--type", "test_output", "--backend", "rtk-shell-output", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
            env=env,
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr + explicit.stdout)
        self.assertNotIn("Traceback", explicit.stderr + explicit.stdout)
        payload = json.loads(explicit.stdout)
        self.assertEqual(payload["requested_backend"], "rtk-shell-output")
        self.assertEqual(payload["backend"], "rtk-shell-output")
        self.assertEqual(payload["status"], "reference_only")
        self.assertTrue(payload["fallback_used"])
        self.assertIn("adapter mode 'test' is not declared", payload["adapter_result"]["error"])
        self.assertNotIn("super-secret", json.dumps(payload))

    def test_auto_headroom_backend_requires_explicit_config_opt_in(self):
        marker = os.path.join(self.d, "headroom-compress.txt")
        env = self.fake_headroom_env(
            "import sys\n"
            f"open({marker!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "data = sys.stdin.read()\n"
            "sys.stdout.write('HEADROOM_COMPACT mode=' + ' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.stdout.write(data.replace('VERBOSE filler\\n', ''))\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        default_auto = self.ctx(
            "compress", "--id", "headroom-default-auto", "--type", "report", "--stdin", "--json",
            stdin="password=super-secret\nVERBOSE filler\nERROR failed\nexit code 1\n",
            env=env,
        )
        self.assertEqual(default_auto.returncode, 0, default_auto.stderr)
        payload = json.loads(default_auto.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertEqual(payload["adapter_result"]["adapter"], "builtin")
        self.assertFalse(os.path.exists(marker))
        self.assertNotIn("super-secret", json.dumps(payload))

        self.write_json(".m8shift/context-compression.json", {
            "schema": "m8shift.context_compression.config.v1",
            "backends": {"headroom_ext": {"auto_enabled": True}},
        })
        opt_in_auto = self.ctx(
            "compress", "--id", "headroom-opt-in-auto", "--type", "report", "--stdin", "--json",
            stdin="password=super-secret\nVERBOSE filler\nERROR failed\nexit code 1\n",
            env=env,
        )
        self.assertEqual(opt_in_auto.returncode, 0, opt_in_auto.stderr)
        payload = json.loads(opt_in_auto.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "headroom_ext")
        self.assertEqual(payload["adapter_result"]["adapter"], "headroom_ext")
        self.assertEqual(payload["adapter_result"]["mode"], "report")
        self.assertIn("HEADROOM_COMPACT mode=m8shift-transform report", payload["adapter_result"]["filtered_text"])
        self.assertIn("exit code 1", payload["adapter_result"]["filtered_text"])
        self.assertEqual(payload["access_mode"], "retrieve")
        self.assertFalse(payload["whole_content"])
        self.assertNotIn("super-secret", json.dumps(payload))
        with open(marker, encoding="utf-8") as fh:
            self.assertIn("m8shift-transform report", fh.read())

    def test_inline_and_whole_content_signals_do_not_auto_route_headroom_yet(self):
        marker = os.path.join(self.d, "headroom-signal.txt")
        env = self.fake_headroom_env(
            "import sys\n"
            f"open({marker!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.stdout.write('HEADROOM_SIGNAL\\n')\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)

        inline = self.ctx(
            "compress", "--id", "headroom-inline-auto", "--type", "report", "--access-mode", "inline", "--stdin", "--json",
            stdin="password=super-secret\nERROR inline\n",
            env=env,
        )
        self.assertEqual(inline.returncode, 0, inline.stderr + inline.stdout)
        payload = json.loads(inline.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertEqual(payload["adapter_result"]["adapter"], "builtin")
        self.assertEqual(payload["access_mode"], "inline")
        self.assertFalse(payload["whole_content"])
        self.assertNotIn("super-secret", json.dumps(payload))

        whole = self.ctx(
            "compress", "--id", "headroom-whole-auto", "--type", "report", "--whole-content", "--stdin", "--json",
            stdin="password=super-secret\nERROR whole\n",
            env=env,
        )
        self.assertEqual(whole.returncode, 0, whole.stderr + whole.stdout)
        payload = json.loads(whole.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertEqual(payload["adapter_result"]["adapter"], "builtin")
        self.assertEqual(payload["access_mode"], "retrieve")
        self.assertTrue(payload["whole_content"])
        self.assertNotIn("super-secret", json.dumps(payload))
        self.assertFalse(os.path.exists(marker))

    def test_explicit_headroom_backend_honors_pinned_adapter_without_auto_opt_in(self):
        env = self.fake_headroom_env(
            "import sys\n"
            "data = sys.stdin.read()\n"
            "sys.stdout.write('EXPLICIT_HEADROOM mode=' + ' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.stdout.write(data.replace('VERBOSE filler\\n', ''))\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        result = self.ctx(
            "compress", "--id", "headroom-explicit", "--type", "report", "--backend", "headroom_ext",
            "--access-mode", "inline", "--whole-content", "--stdin", "--json",
            stdin="password=super-secret\nVERBOSE filler\nERROR failed\nexit code 1\n",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["requested_backend"], "headroom_ext")
        self.assertEqual(payload["backend"], "headroom_ext")
        self.assertEqual(payload["adapter_result"]["adapter"], "headroom_ext")
        self.assertEqual(payload["access_mode"], "inline")
        self.assertTrue(payload["whole_content"])
        self.assertIn("EXPLICIT_HEADROOM mode=m8shift-transform report", payload["adapter_result"]["filtered_text"])
        self.assertNotIn("super-secret", json.dumps(payload))

    def test_unknown_access_mode_is_rejected(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        result = self.ctx(
            "compress", "--id", "bad-access-mode", "--type", "report", "--access-mode", "telepathy", "--stdin", "--json",
            stdin="raw\n",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)
        record_path = os.path.join(self.d, ".m8shift", "context", "compression", "records", "bad-access-mode.json")
        self.assertFalse(os.path.exists(record_path))

    def test_headroom_unpinned_or_absent_degrades_by_backend_mode(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        auto = self.ctx(
            "compress", "--id", "headroom-absent-auto", "--type", "report", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
        )
        self.assertEqual(auto.returncode, 0, auto.stderr + auto.stdout)
        payload = json.loads(auto.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertNotIn("compression.headroom_fallback", {row["check"] for row in payload["findings"]})
        self.assertNotIn("super-secret", json.dumps(payload))

        self.write_json(".m8shift/context-compression.json", {
            "schema": "m8shift.context_compression.config.v1",
            "backends": {"headroom_ext": {"auto_enabled": True}},
        })
        auto_opt_in = self.ctx(
            "compress", "--id", "headroom-absent-auto-opt-in", "--type", "report", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
        )
        self.assertEqual(auto_opt_in.returncode, 0, auto_opt_in.stderr + auto_opt_in.stdout)
        payload = json.loads(auto_opt_in.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertIn("compression.headroom_fallback", {row["check"] for row in payload["findings"]})
        self.assertNotIn("super-secret", json.dumps(payload))

        explicit = self.ctx(
            "compress", "--id", "headroom-absent-explicit", "--type", "report", "--backend", "headroom_ext", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr + explicit.stdout)
        payload = json.loads(explicit.stdout)
        self.assertEqual(payload["requested_backend"], "headroom_ext")
        self.assertEqual(payload["backend"], "headroom_ext")
        self.assertEqual(payload["status"], "reference_only")
        self.assertTrue(payload["fallback_used"])
        self.assertIn("headroom_ext", payload["adapter_result"]["adapter"])
        self.assertNotIn("super-secret", json.dumps(payload))

    def test_drifted_headroom_manifest_mode_error_degrades_without_crash(self):
        env = self.fake_headroom_env(
            "import sys\n"
            "sys.stdout.write(sys.stdin.read())\n"
        )
        self.assertEqual(self.ctx("init", env=env).returncode, 0)
        adapter = os.path.join(self.d, ".m8shift", "context", "adapters", "headroom_ext.json")
        with open(adapter, encoding="utf-8") as fh:
            manifest = json.load(fh)
        del manifest["modes"]["report"]
        with open(adapter, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        self.write_json(".m8shift/context-compression.json", {
            "schema": "m8shift.context_compression.config.v1",
            "backends": {"headroom_ext": {"auto_enabled": True}},
        })

        auto = self.ctx(
            "compress", "--id", "headroom-drift-auto", "--type", "report", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
            env=env,
        )
        self.assertEqual(auto.returncode, 0, auto.stderr + auto.stdout)
        self.assertNotIn("Traceback", auto.stderr + auto.stdout)
        payload = json.loads(auto.stdout)
        self.assertEqual(payload["requested_backend"], "auto")
        self.assertEqual(payload["backend"], "builtin")
        self.assertFalse(payload["fallback_used"])
        self.assertIn("compression.headroom_fallback", {row["check"] for row in payload["findings"]})
        self.assertNotIn("super-secret", json.dumps(payload))

        explicit = self.ctx(
            "compress", "--id", "headroom-drift-explicit", "--type", "report", "--backend", "headroom_ext", "--stdin", "--json",
            stdin="password=super-secret\nERROR original\nexit code 1\n",
            env=env,
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr + explicit.stdout)
        self.assertNotIn("Traceback", explicit.stderr + explicit.stdout)
        payload = json.loads(explicit.stdout)
        self.assertEqual(payload["requested_backend"], "headroom_ext")
        self.assertEqual(payload["backend"], "headroom_ext")
        self.assertEqual(payload["status"], "reference_only")
        self.assertTrue(payload["fallback_used"])
        self.assertIn("adapter mode 'report' is not declared", payload["adapter_result"]["error"])
        self.assertNotIn("super-secret", json.dumps(payload))

    def test_valid_schema_config_bad_numeric_values_do_not_traceback(self):
        self.assertEqual(self.ctx("init").returncode, 0)
        self.write_json(".m8shift/context-compression.json", {
            "schema": "m8shift.context_compression.config.v1",
            "retrieval": {
                "default_lines": "abc",
                "max_lines": "1.5",
                "max_grep_pattern_chars": "NaN",
                "max_grep_scan_bytes": "bad",
                "max_grep_line_chars": "bad",
            },
        })
        compressed = self.ctx("compress", "--id", "badnumeric", "--stdin", "--json", stdin="ERROR line\n")
        self.assertEqual(compressed.returncode, 0, compressed.stderr + compressed.stdout)
        self.assertNotIn("Traceback", compressed.stderr + compressed.stdout)
        retrieved = self.ctx("retrieve", "badnumeric", "--grep", "ERROR", "--json")
        self.assertEqual(retrieved.returncode, 0, retrieved.stderr + retrieved.stdout)
        self.assertNotIn("Traceback", retrieved.stderr + retrieved.stdout)


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
