"""#412 first slice: durable unnamed warnings without relay or routing writes."""
import argparse
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ambient_env  # noqa: E402 - isolate before product imports
from tests import test_m8shift as base


class TestUsageCheckpointAdvice(base.CLIBase):
    def setUp(self):
        super().setUp()
        self.init()
        path = Path(self.d, "m8shift-runtime.py")
        shutil.copy(Path(base.REPO, path.name), path)
        spec = importlib.util.spec_from_file_location("checkpoint_runtime", path)
        self.rtmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rtmod)
        self.reset = self.rtmod.iso(self.rtmod.now() + dt.timedelta(hours=1))

    def rt(self, *args):
        return subprocess.run([sys.executable, "m8shift-runtime.py", *args],
                              cwd=self.d, capture_output=True, text=True, timeout=30)

    def seed(self, ratio, *, state="measured", reset=None):
        snapshot = {"schema": "m8shift.usage.snapshot.v1", "agent": "claude",
                    "captured_at": self.rtmod.iso(), "decision_ratio": ratio,
                    "measurement": {"state": state,
                                    "reason": None if state == "measured" else "probe_failed"},
                    "source": {"adapter": "test", "kind": "fixture", "provenance": "manual"},
                    "decision_window": {"kind": "weekly", "resets_at": reset or self.reset},
                    "windows": [{"kind": "weekly", "resets_at": reset or self.reset,
                                 "used_ratio": ratio}]}
        path = Path(self.rtmod.USAGE_LEDGER)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({"schema": self.rtmod.RUNTIME_EVENT_SCHEMA,
                                 "type": "usage.snapshot", "payload": {"snapshot": snapshot}}) + "\n")
        return snapshot

    def fixture(self, ratio, *, state="measured", reset=None):
        snapshot = self.seed(ratio, state=state, reset=reset)
        fixture = {"schema": "m8shift.usage.fixture.v1", "agent": "claude",
                   "captured_at": snapshot["captured_at"], "provenance": "manual",
                   "measurement": snapshot["measurement"], "windows": snapshot["windows"]}
        path = Path(self.d, ".m8shift", "usage", "fixture.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixture))
        Path(self.rtmod.USAGE_ADAPTERS).write_text(json.dumps({
            "schema": "m8shift.usage.adapters.v1", "adapters": [{
                "name": "test", "agent": "claude", "kind": "fixture", "enabled": True,
                "fixture_path": ".m8shift/usage/fixture.json", "timeout_s": 5}]}))

    def watch(self, ticks=1):
        return self.rt("usage", "watch", "--agent", "claude", "--max-ticks", str(ticks),
                       "--interval", "0.01", "--json")

    def events(self):
        return [row for line in Path(self.rtmod.USAGE_LEDGER).read_text().splitlines()
                if (row := json.loads(line)).get("type") == "usage.advisory"]

    def latch(self):
        return Path(self.rtmod.usage_advisory_latch_path("claude"))

    def protected(self):
        return {str(p): p.read_bytes() for p in Path(self.d).rglob("*")
                if p.is_file() and (p.name.startswith("M8SHIFT")
                                   or "usage-holds" in p.parts or "routing" in p.parts)}

    def test_guard_warns_deterministically_without_writes_or_named_target(self):
        self.seed(.9)
        before = {str(p): p.read_bytes() for p in Path(self.d).rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        first = self.rt("usage", "guard", "--agent", "claude", "--json")
        second = self.rt("usage", "guard", "--agent", "claude", "--json")
        self.assertEqual(first.returncode, 10, first.stdout + first.stderr)
        self.assertIn("advisories", json.loads(first.stdout))
        a = json.loads(first.stdout)["advisories"]
        self.assertEqual(a, json.loads(second.stdout)["advisories"])
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["authority"], "advisory")
        self.assertEqual(a[0]["action"], "checkpoint_or_cooldown")
        self.assertIsNone(a[0]["target_agent"])
        self.assertEqual(a[0]["provenance"], "manual")
        self.assertEqual(a[0]["resets_at"], self.reset)
        self.assertIn("checkpoint", self.rt("usage", "guard", "--agent", "claude").stdout)
        self.assertEqual(before, {str(p): p.read_bytes() for p in Path(self.d).rglob("*")
                                 if p.is_file() and "__pycache__" not in p.parts})

    def test_real_managed_watch_persists_once_across_ticks_and_process_restarts(self):
        self.fixture(.9)
        before = self.protected()
        result = self.watch(2)
        self.assertEqual(result.returncode, 10, result.stdout + result.stderr)
        ticks = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(ticks[0].get("advisory_persisted"), ticks[0])
        self.assertTrue(ticks[1]["advisory_suppressed"])
        self.assertEqual(len(self.events()), 1)
        first_bytes = self.latch().read_bytes()
        again = self.watch()
        self.assertEqual(again.returncode, 10, again.stdout + again.stderr)
        self.assertTrue(json.loads(again.stdout)["advisory_suppressed"])
        self.assertEqual(self.latch().read_bytes(), first_bytes)
        self.assertEqual(len(self.events()), 1)
        doctor = self.rt("doctor", "--json")
        named = [f for f in json.loads(doctor.stdout)["findings"] if f["check"] == "usage.advisory"]
        self.assertEqual(len(named), 1)
        self.assertIn("Recorded at", named[0]["message"])
        self.assertIn("90%", named[0]["message"])
        self.assertEqual(before, self.protected())

    def test_ok_limit_and_new_window_rearm_but_unknown_does_not_clear(self):
        self.fixture(.9)
        self.assertEqual(self.watch().returncode, 10)
        original = self.latch().read_bytes()
        self.fixture(.1, state="degraded")
        self.watch()
        self.assertEqual(self.latch().read_bytes(), original)
        self.fixture(.2)
        self.assertEqual(self.watch().returncode, 0)
        self.assertFalse(json.loads(self.latch().read_text())["active"])
        self.fixture(.9)
        self.assertEqual(self.watch().returncode, 10)
        self.assertEqual(len(self.events()), 2)
        self.fixture(1.0)
        self.watch()
        self.assertFalse(json.loads(self.latch().read_text())["active"])
        new_reset = self.rtmod.iso(self.rtmod.now() + dt.timedelta(hours=2))
        self.fixture(.9, reset=new_reset)
        self.assertEqual(self.watch().returncode, 10)
        self.assertEqual(len(self.events()), 3)
        self.assertNotEqual(self.events()[0]["idempotency_key"], self.events()[-1]["idempotency_key"])

    def test_corrupt_or_symlinked_latch_never_suppresses_the_pure_warning(self):
        self.fixture(.9)
        self.latch().parent.mkdir(parents=True)
        target = Path(self.d, "private-target.json")
        target.write_text("private-fixture-content")
        for state in ("corrupt", "symlink"):
            with self.subTest(state=state):
                if state == "corrupt":
                    self.latch().write_text("not-json-private-fixture-content")
                else:
                    self.latch().unlink()
                    self.latch().symlink_to(target)
                result = self.watch()
                self.assertEqual(result.returncode, 10, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(len(payload["advisories"]), 1)
                self.assertFalse(payload.get("advisory_suppressed"))
                self.assertIn("usage.advisory_latch", {f["check"] for f in payload["findings"]})
                self.assertEqual(self.events(), [])
                self.assertEqual(target.read_text(), "private-fixture-content")
                self.assertNotIn("private-fixture-content", result.stdout + result.stderr)

    def test_non_near_limit_receipts_do_not_create_an_advisory(self):
        for ratio, state in ((.2, "measured"), (1.0, "measured"), (.9, "degraded"),
                             (.9, "unavailable")):
            with self.subTest(ratio=ratio, state=state):
                self.seed(ratio, state=state)
                result = self.rt("usage", "guard", "--agent", "claude", "--json")
                self.assertEqual(json.loads(result.stdout)["advisories"], [])

    def test_guard_preserves_warning_with_unusable_window_metadata(self):
        self.seed(.9)
        path = Path(self.rtmod.USAGE_LEDGER)
        row = json.loads(path.read_text())
        row["payload"]["snapshot"]["decision_window"] = {"kind": [], "resets_at": []}
        path.write_text(json.dumps(row) + "\n")
        result = self.rt("usage", "guard", "--agent", "claude", "--json")
        self.assertEqual(result.returncode, 10, result.stdout + result.stderr)
        advice = json.loads(result.stdout)["advisories"][0]
        self.assertEqual(advice["window_kind"], "unknown")
        self.assertIsNone(advice["resets_at"])

    def test_publication_requires_current_lease_and_survives_audit_failure(self):
        self.seed(.9)
        rt = self.rtmod
        args = argparse.Namespace(warn_threshold=.8, limit_threshold=1., stale_after_minutes=30)
        _, payload = rt.usage_guard_evaluate(args, "claude", apply_mode=False)
        rt.write_usage_watch("claude", mode="advisory", interval=60, started=rt.iso(),
                             phase="running", pid=os.getpid(), lease_id="current")
        old = copy.deepcopy(payload)
        rt.persist_usage_checkpoint_advice(old, "claude", "old")
        self.assertFalse(self.latch().exists())
        self.assertIn("usage.advisory_owner", {f["check"] for f in old["findings"]})
        with mock.patch.object(rt, "append_jsonl", side_effect=OSError("private-detail")):
            rt.persist_usage_checkpoint_advice(payload, "claude", "current")
        self.assertTrue(payload["advisory_persisted"])
        self.assertIn("usage.advisory_io", {f["check"] for f in payload["findings"]})
        self.assertEqual(self.events(), [])
        self.assertEqual(rt.usage_advisory_doctor_findings()[0]["check"], "usage.advisory")
        self.assertNotIn("private-detail", json.dumps(payload))

    def test_inconsistent_latch_key_and_special_file_cannot_suppress_or_block(self):
        self.fixture(.9)
        self.assertEqual(self.watch().returncode, 10)
        doc = json.loads(self.latch().read_text())
        doc["event"]["payload"]["window_kind"] = "daily"
        self.latch().write_text(json.dumps(doc))
        result = self.watch()
        self.assertEqual(result.returncode, 10, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("advisory_suppressed"))
        self.assertIn("usage.advisory_latch", {f["check"] for f in payload["findings"]})
        if hasattr(os, "mkfifo"):
            self.latch().unlink()
            os.mkfifo(self.latch())
            latch, error = self.rtmod.read_usage_advisory_latch("claude")
            self.assertEqual(latch, {})
            self.assertIsNotNone(error)

    def test_stop_during_advisory_publication_propagates_and_releases_the_lock(self):
        self.seed(.9)
        rt = self.rtmod
        args = argparse.Namespace(warn_threshold=.8, limit_threshold=1., stale_after_minutes=30)
        _, payload = rt.usage_guard_evaluate(args, "claude", apply_mode=False)
        rt.write_usage_watch("claude", mode="advisory", interval=60, started=rt.iso(),
                             phase="running", pid=os.getpid(), lease_id="current")
        write = rt.write_fleet_json_atomic

        def write_then_stop(*args):
            write(*args)
            raise SystemExit(0)  # the actual managed-watch stop handler's exception

        with mock.patch.object(rt, "write_fleet_json_atomic", side_effect=write_then_stop):
            with self.assertRaises(SystemExit) as stopped:
                rt.persist_usage_checkpoint_advice(payload, "claude", "current")
        self.assertEqual(stopped.exception.code, 0)
        self.assertFalse(Path(rt.usage_watch_lock_path("claude")).exists())
        self.assertEqual(self.events(), [])
        self.assertEqual(rt.usage_advisory_doctor_findings()[0]["check"], "usage.advisory")
        self.assertNotIn("usage.advisory_io", {f["check"] for f in payload["findings"]})
