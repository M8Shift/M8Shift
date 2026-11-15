"""Repeated failures describe the current session, never historical sidecars."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base


class ListenerDiagnosticFreshness(base.CLIBase):
    def setUp(self):
        super().setUp()
        self.init()
        path = Path(self.d, "m8shift-runtime.py")
        shutil.copy(Path(base.REPO, path.name), path)
        spec = importlib.util.spec_from_file_location("runtime_diagnostic_freshness", path)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.session = self.runtime.current_relay_session()

    def findings(self, *, session=None, timestamp=None, success=False):
        runtime = self.runtime
        stamp = timestamp or runtime.iso()
        state = {"schema": runtime.LISTENER_STATE_SCHEMA, "agent": "claude",
                 "phase": "backoff", "consecutive_failures": 3,
                 "last_classification": "non_completion", "last_run_id": "failed-run",
                 "session": self.session if session is None else session, "updated_at": stamp}
        path = Path(runtime.listener_paths("claude")["state"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
        row = {"event": "run.ended", "agent": "claude", "session_id": state["session"],
               "ts": stamp, "status": "non_completion"}
        rows = [row, row]
        if success:
            rows.append(dict(row, ts=runtime.iso(), status="advanced"))
        Path(runtime.RUNS).write_text("\n".join(map(json.dumps, rows)) + "\n")
        with mock.patch.object(runtime, "listener_backend_probe", return_value={}):
            return runtime.listener_doctor_findings()

    def test_current_failures_have_one_advisory(self):
        found = [row for row in self.findings() if row["check"] == "listener.repeated_non_completion"]
        self.assertEqual(len(found), 1)

    def test_foreign_unbound_and_stale_failures_do_not_accuse_current_session(self):
        for fields in ({"session": "older-session"}, {"session": ""},
                       {"timestamp": "2020-01-01T00:00:00Z"}):
            with self.subTest(fields=fields):
                checks = {row["check"] for row in self.findings(**fields)}
                self.assertNotIn("listener.repeated_non_completion", checks)
                self.assertIn("listener.historical_state", checks)

    def test_newer_success_reconciles_old_sidecar_and_ledger_streak(self):
        stamp = self.runtime.iso(self.runtime.now() - self.runtime.dt.timedelta(seconds=10))
        checks = {row["check"] for row in self.findings(timestamp=stamp, success=True)}
        self.assertNotIn("listener.repeated_non_completion", checks)
