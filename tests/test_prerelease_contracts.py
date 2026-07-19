import importlib.util
import io
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parallel_scrub_worker_failure_is_ordered_and_fail_closed(tmp_path):
    scrub = load_module("scrub_check_contract", ROOT / "scripts" / "scrub-check.py")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("hit\nerror\nclean\n", encoding="utf-8")
    releases = {term: threading.Event() for term in ("hit", "error", "clean")}

    def run(cmd, repo):
        term = cmd[cmd.index("-e") + 1] if "grep" in cmd else cmd[cmd.index("-S") + 1]
        if "log" in cmd:
            releases[term].wait(2)
            if term == "error":
                raise subprocess.SubprocessError("worker failed")
            return SimpleNamespace(returncode=0, stdout=("a" * 40 + "\n") if term == "hit" else "", stderr="")
        # Complete histories out of order while tip scans remain deterministic.
        releases[{"hit": "clean", "error": "error", "clean": "hit"}[term]].set()
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    out, err = io.StringIO(), io.StringIO()
    rc = scrub.main(["--repo", str(ROOT), "--denylist", str(denylist)], out, err, run)
    assert rc == 2
    assert "ERROR running git log" in err.getvalue()
    assert "scrub-check: clean" not in out.getvalue()
    # The first rule's completed hit is emitted before the second rule's error.
    assert out.getvalue().startswith("HISTORY hit:")

    def nonzero(cmd, repo):
        if "log" in cmd:
            return SimpleNamespace(returncode=128, stdout="", stderr="bad history")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    out, err = io.StringIO(), io.StringIO()
    rc = scrub.main(["--repo", str(ROOT), "--denylist", str(denylist)], out, err, nonzero)
    assert rc == 2
    assert "ERROR git log rc=128" in err.getvalue()
    assert "scrub-check: clean" not in out.getvalue()


def test_ci_dependency_installs_are_hash_closed():
    workflows = list((ROOT / ".github" / "workflows").glob("*.yml"))
    installs = []
    for path in workflows:
        installs += [line for line in path.read_text(encoding="utf-8").splitlines()
                     if re.search(r"\bpip\s+install\b", line)]
    assert installs
    assert all("--require-hashes" in line and "-r " in line for line in installs)
    locks = {ROOT / line.split("-r ", 1)[1].strip().split()[0] for line in installs}
    for lock in locks:
        text = lock.read_text(encoding="utf-8")
        requirements = [line for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith(("#", "--hash"))]
        assert requirements and text.count("--hash=sha256:") >= len(requirements)


def test_status_role_state_matrix_and_snapshot_shape():
    engine = load_module("m8shift_contract", ROOT / "m8shift.py")
    cases = {"IDLE": ("idle", "idle"), "AWAITING_CODEX": ("awaiting", "idle"),
             "AWAITING_CLAUDE": ("idle", "awaiting"),
             "WORKING_CODEX": ("working", "idle"),
             "WORKING_CLAUDE": ("idle", "working"), "PAUSED": ("paused", "paused"),
             "DONE": ("done", "done")}
    for state, expected in cases.items():
        lock = {"state": state}
        assert (engine._status_role_state(lock, "codex"),
                engine._status_role_state(lock, "claude")) == expected
    snap = engine.status_snapshot_v1(
        {"state": "IDLE", "agents": "claude,codex"}, None,
        {"started_at": "-", "duration_seconds": 0}, [])
    assert set(snap) == {"schema", "agents", "listeners", "attention", "last_turn", "ledger", "pen",
                         "activity", "activity_limit", "activity_truncated", "gateway"}
    assert snap["schema"] == "m8shift.status/1"
    assert all(set(row) == {"id", "model", "model_source", "effort",
                            "effort_source", "role_state", "usage"}
               for row in snap["agents"])
    assert all(set(row["usage"]) == {
        "available", "last_known", "captured_at", "age_seconds",
        "freshness", "stale", "windows",
    } for row in snap["agents"])


def test_top_rejects_absent_malformed_and_future_snapshot(tmp_path):
    top = load_module("m8shift_top_contract", ROOT / "m8shift-top.py")
    engine = tmp_path / "engine.py"
    for payload in ({}, {"snapshot": "bad"}, {"snapshot": {"schema": "m8shift.status/2"}}):
        engine.write_text("import json; print(json.dumps(%r))\n" % payload, encoding="utf-8")
        try:
            top.load_snapshot(str(engine), str(tmp_path))
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid/future snapshot accepted")


def test_extended_snapshot_remains_additive_for_top_consumer():
    engine = load_module("m8shift_additive_engine", ROOT / "m8shift.py")
    top = load_module("m8shift_additive_top", ROOT / "m8shift-top.py")
    with mock.patch.object(engine, "_usage_rows", return_value=[]):
        snap = engine.status_snapshot_v1(
            {"state": "IDLE", "agents": "claude,codex"}, None,
            {"started_at": "-", "duration_seconds": 0}, [])
    merged = top._merge_status_payload({"snapshot": snap, "state": "IDLE"})
    assert merged["schema"] == "m8shift.status/1"
    for row in merged["agents"]:
        assert row["usage"]["freshness"] == "unknown"
        assert row["usage"]["captured_at"] is None
        assert row["usage"]["age_seconds"] is None


def test_skill_release_surface_and_safety_boundaries():
    expected = {"adversarial-verifier", "ci-triage", "leak-warden", "release-manager"}
    boundary = {"adversarial-verifier": "Never leave a mutation in the tree",
                "ci-triage": "Never patch an unnamed failure",
                "leak-warden": "never commit or print its terms",
                "release-manager": "Ask rather than guessing"}
    assert expected <= {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    for name in expected:
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n") and "\n---\n" in text[4:]
        assert boundary[name] in text
        assert not re.search(r"/(?:Users|home)/[^/\s]+/", text)
