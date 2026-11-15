"""Onboarding terrain, byte identity and executable nominal sequence (#567)."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base
REPO = base.REPO
run_installer = base.run_installer


class TestOnboardingConductor(unittest.TestCase):
    """#378 — the bootstrap conductor: terrain before writes, every path
    provided, launched lanes verified, and a document that cannot drift from
    what these witnesses execute."""

    PROBE = os.path.join(REPO, "scripts", "onboard-probe.py")
    DOC = os.path.join(REPO, "docs", "en", "onboarding.md")

    def probe(self, facts, *args, cwd=None, pycache_prefix=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("M8SHIFT_")}
        env["M8SHIFT_ONBOARD_PROBE_FACTS"] = json.dumps(facts)
        if pycache_prefix is not None:
            env["PYTHONPYCACHEPREFIX"] = pycache_prefix
        return subprocess.run(
            [sys.executable, "-B", self.PROBE, *args], cwd=cwd,
            capture_output=True, text=True, timeout=30, env=env)

    def load_probe(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "m8shift_onboard_probe_test", self.PROBE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_windows_without_posix_shell_is_refused_before_any_write(self):
        """The ticket's named acceptance: a stub agent on a fake Windows with
        neither WSL nor Git Bash is REFUSED with an explanation, and nothing
        is written."""
        scratch = tempfile.mkdtemp(prefix="m8shift-onboard-refusal-")
        self.addCleanup(shutil.rmtree, scratch, True)
        cache = tempfile.mkdtemp(prefix="m8shift-onboard-pycache-")
        self.addCleanup(shutil.rmtree, cache, True)
        r = self.probe({"os": "Windows", "wsl": False, "git_bash": False,
                        "python_version": "3.12", "git": True},
                       "--json", cwd=scratch, pycache_prefix=cache)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(report["posix_shell"], "none")
        blocking = " ".join(report["blocking"])
        self.assertIn("WSL", blocking)
        self.assertIn("Git", blocking)
        self.assertIn("Nothing was written", blocking)
        self.assertEqual(os.listdir(scratch), [],
                         "the refusal path must not write anything")
        self.assertEqual(os.listdir(cache), [],
                         "'never writes' includes bytecode caches: the probe "
                         "runs under -B and the isolated prefix must stay empty")

    def test_a_complete_system_raises_no_blocking_finding(self):
        """The control the ticket demands: without it, 'it refuses' would
        prove only that it always refuses."""
        for facts in ({"os": "Linux", "python_version": "3.12", "git": True},
                      {"os": "Windows", "wsl": True,
                       "python_version": "3.13", "git": True},
                      {"os": "Windows", "wsl": False, "git_bash": True,
                       "python_version": "3.12", "git": True}):
            with self.subTest(facts=facts):
                r = self.probe(facts, "--json")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(json.loads(r.stdout)["blocking"], [])

    def test_a_missing_git_is_advisory_never_blocking(self):
        r = self.probe({"os": "Linux", "python_version": "3.12", "git": False},
                       "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(report["blocking"], [])
        self.assertTrue(any("git" in a for a in report["advisory"]))

    def documented_sequence(self):
        with open(self.DOC, encoding="utf-8") as fh:
            text = fh.read()
        blocks = re.findall(r"```sequence\n(.*?)```", text, re.S)
        self.assertEqual(len(blocks), 1,
                         "exactly ONE canonical sequence block: a second block "
                         "would be an invisible fork of the executable contract")
        lines = [l.strip() for l in blocks[0].splitlines() if l.strip()]
        self.assertEqual(len(lines), 8, "the canonical sequence changed shape; "
                                        "update this witness WITH the document")
        self.assertTrue(any(l.startswith("#") and "provider entry" in l
                            for l in lines),
                        "the confirmed-provider-edit marker vanished from the "
                        "canonical sequence")
        return lines

    def test_stop_after_install_leaves_no_instance(self):
        """Ticket requirement: stopping after installation leaves the verified
        kit and NOTHING initialized — the installer's default init would have
        created a default-roster instance before any question was answered."""
        src = tempfile.mkdtemp(prefix="m8shift-onboard-src-")
        self.addCleanup(shutil.rmtree, src, True)
        os.makedirs(os.path.join(src, "examples"))
        for f in ("m8shift.py", "m8shift-top.py", "m8shift-worktree.py",
                  "m8shift-runtime.py", "m8shift-context.py", "checksums.sha256"):
            shutil.copy(os.path.join(REPO, f), src)
        shutil.copy(os.path.join(REPO, "examples", "headless_runner.py"),
                    os.path.join(src, "examples"))
        parent = tempfile.mkdtemp(prefix="m8shift-onboard-stop-")
        self.addCleanup(shutil.rmtree, parent, True)
        target = os.path.join(parent, "kit only")
        r = run_installer(["bash", os.path.join(REPO, "install.sh"),
                           "--dir", target, "--no-init", "--with-runner",
                           "--base-url", "file://" + src])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(target, "m8shift.py")))
        self.assertTrue(os.path.isfile(
            os.path.join(target, "examples", "headless_runner.py")))
        self.assertFalse(os.path.exists(os.path.join(target, "M8SHIFT.md")),
                         "stop-after-install must leave NO instance")

    def test_the_nominal_sequence_is_the_document_executed(self):
        """Every command comes from the document's canonical block, shlex-split
        with the operator's answers substituted (the instance path carries a
        SPACE on purpose) and one declared hermetic override; the roster is
        NOT the installer default; the launched lane is verified ALIVE and
        resident through status --json, and stopped in cleanup."""
        src = tempfile.mkdtemp(prefix="m8shift-onboard-src-")
        self.addCleanup(shutil.rmtree, src, True)
        os.makedirs(os.path.join(src, "examples"))
        for f in ("m8shift.py", "m8shift-top.py", "m8shift-worktree.py",
                  "m8shift-runtime.py", "m8shift-context.py", "checksums.sha256"):
            shutil.copy(os.path.join(REPO, f), src)
        shutil.copy(os.path.join(REPO, "examples", "headless_runner.py"),
                    os.path.join(src, "examples"))
        parent = tempfile.mkdtemp(prefix="m8shift-onboard-nominal-")
        self.addCleanup(shutil.rmtree, parent, True)
        instance = os.path.join(parent, "demo shift")

        answers = {"<INSTANCE_DIR>": instance, "<INSTANCE_NAME>": "demo-shift",
                   "<ROSTER>": "agy,codex", "<AGENT>": "codex"}
        # Declared hermetic overrides: the source injection, and a pinned
        # local lifecycle backend — the document's auto backend is right for a
        # real operator host, but a witness must not depend on launchd/systemd
        # service scheduling inside a temporary directory.
        hermetic = {"bash install.sh": ["--base-url", "file://" + src],
                    "listener start": ["--backend", "local"]}
        launched = []
        def stop_lane():
            if launched:
                subprocess.run(
                    [sys.executable,
                     os.path.join(instance, "m8shift-runtime.py"),
                     "listener", "stop", "--agent", answers["<AGENT>"]],
                    cwd=instance, capture_output=True, text=True, timeout=30)
        self.addCleanup(stop_lane)

        env = {k: v for k, v in os.environ.items()
               if not k.startswith("M8SHIFT_")}
        env["M8SHIFT_ONBOARD_PROBE_FACTS"] = json.dumps(
            {"os": "Linux", "python_version": "3.12", "git": True})
        status_json = ""
        for step in self.documented_sequence():
            with self.subTest(step=step):
                if step.startswith("#"):
                    providers = os.path.join(instance, ".m8shift",
                                             "providers.json")
                    with open(providers, encoding="utf-8") as fh:
                        conf = json.load(fh)
                    stub = os.path.join(instance, "stub-provider.py")
                    with open(stub, "w", encoding="utf-8") as fh:
                        fh.write(
                            "import subprocess, sys\n"
                            "subprocess.run([sys.executable, 'm8shift.py',"
                            " 'status'], capture_output=True)\n")
                    for entry in conf.get("agents", []):
                        if entry.get("name") == answers["<AGENT>"]:
                            entry["mode"] = "headless"
                            entry["model"] = "stub-model-1"
                            entry["argv"] = [sys.executable, stub,
                                             "$M8SHIFT_PROMPT"]
                    with open(providers, "w", encoding="utf-8") as fh:
                        json.dump(conf, fh, indent=2)
                    continue
                cwd = REPO
                if step.startswith('cd "<INSTANCE_DIR>" && '):
                    cwd = instance
                    step = step[len('cd "<INSTANCE_DIR>" && '):]
                for placeholder, value in answers.items():
                    step = step.replace(placeholder, value)
                argv = shlex.split(step)
                if argv[0] == "python3":
                    argv[0] = sys.executable
                joined = " ".join(argv)
                for marker, extra in hermetic.items():
                    if all(tok in joined for tok in marker.split()):
                        argv += extra
                if "listener" in argv and "start" in argv:
                    launched.append(True)
                r = subprocess.run(argv, cwd=cwd, capture_output=True,
                                   text=True, timeout=120, env=env)
                self.assertEqual(r.returncode, 0,
                                 step + "\n" + r.stdout + r.stderr)
                if "status" in argv and "--json" in argv:
                    status_json = r.stdout
        self.assertTrue(os.path.isfile(os.path.join(instance, "M8SHIFT.md")))
        with open(os.path.join(instance, "M8SHIFT.md"), encoding="utf-8") as fh:
            self.assertIn("agy,codex", fh.read())
        status = json.loads(status_json)
        self.assertEqual(status.get("status"), "ALIVE", status_json)
        self.assertTrue(status.get("process_resident"), status_json)
        self.assertEqual(os.path.realpath(status.get("relay_root", "")),
                         os.path.realpath(instance), status_json)
        # Residency is not the promise — INVOCATION is. A notify-only lane is
        # also ALIVE and resident; the conductor promised a provider-invoking
        # runner, and these three fields are what distinguish it.
        self.assertTrue(status.get("can_invoke_agent"), status_json)
        self.assertFalse(status.get("notify_only"), status_json)
        self.assertEqual(status.get("coverage"), "invoker", status_json)
        stop_lane()
        after = subprocess.run(
            [sys.executable, os.path.join(instance, "m8shift-runtime.py"),
             "listener", "status", "--agent", answers["<AGENT>"], "--json"],
            cwd=instance, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(json.loads(after.stdout).get("status"), "ALIVE",
                            "the witness lane must not survive the witness")

    def _fake_kit(self, version, body="", manifest=True):
        import hashlib
        d = tempfile.mkdtemp(prefix="m8shift-onboard-kit-")
        self.addCleanup(shutil.rmtree, d, True)
        core = 'VERSION = "%s"\n%s' % (version, body)
        with open(os.path.join(d, "m8shift.py"), "w", encoding="utf-8") as fh:
            fh.write(core)
        if manifest:
            digest = hashlib.sha256(core.encode()).hexdigest()
            with open(os.path.join(d, "checksums.sha256"), "w",
                      encoding="utf-8") as fh:
                fh.write("%s  m8shift.py\n" % digest)
        return d

    def test_update_check_is_anchored_to_bytes_never_version_strings(self):
        """Review finding: equal VERSION constants must never certify currency
        — a tampered core at the right VERSION would pass a string compare."""
        source = self._fake_kit("4.2.0")
        version_drift = self._fake_kit("4.1.0", manifest=False)
        r = self.probe({}, "--update-check", "--target", version_drift,
                       "--source", source, "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["verdict"], "drift")

        same_version_divergent_bytes = self._fake_kit(
            "4.2.0", body="# tampered\n", manifest=False)
        r = self.probe({}, "--update-check",
                       "--target", same_version_divergent_bytes,
                       "--source", source, "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(report["verdict"], "drift")
        self.assertFalse(report["core_digest_matches"])
        self.assertIn("bytes", report["detail"])

        truly_current = self._fake_kit("4.2.0", manifest=False)
        r = self.probe({}, "--update-check", "--target", truly_current,
                       "--source", source, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["verdict"], "current")

        unverifiable_source = self._fake_kit("4.2.0", manifest=False)
        r = self.probe({}, "--update-check", "--target", truly_current,
                       "--source", unverifiable_source, "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["verdict"], "unverifiable")

    def test_windows_candidates_must_execute_posix_not_merely_exist(self):
        """Review reproductions: WSL answering --status without a distribution,
        and the System32 bash.exe launcher, must both classify as none; a bash
        that actually executes the marker probe classifies as git-bash."""
        module = self.load_probe()
        bindir = tempfile.mkdtemp(prefix="m8shift-onboard-fakebin-")
        self.addCleanup(shutil.rmtree, bindir, True)

        launcher = os.path.join(bindir, "bash")
        with open(launcher, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 1\n")   # System32-style: runs, no POSIX
        os.chmod(launcher, 0o755)
        real = os.path.join(bindir, "realbash")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nshift\nsh -c \"$@\"\n" )
        os.chmod(real, 0o755)

        with mock.patch.object(module.shutil, "which",
                               side_effect=lambda n: launcher
                               if n in ("bash", "bash.exe") else None), \
             mock.patch.dict(module.os.environ,
                             {"ProgramFiles": bindir + "/nope",
                              "ProgramFiles(x86)": bindir + "/nope"}):
            self.assertEqual(module.probe_windows_posix_shell({}), "none")

        with mock.patch.object(module.shutil, "which",
                               side_effect=lambda n: real
                               if n in ("bash", "bash.exe") else None), \
             mock.patch.dict(module.os.environ,
                             {"ProgramFiles": bindir + "/nope",
                              "ProgramFiles(x86)": bindir + "/nope"}):
            self.assertEqual(module.probe_windows_posix_shell({}), "git-bash")

        fake_wsl = os.path.join(bindir, "wsl")
        with open(fake_wsl, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n[ \"$1\" = --status ] && exit 0\nexit 1\n")
        os.chmod(fake_wsl, 0o755)
        with mock.patch.object(module.shutil, "which",
                               side_effect=lambda n: fake_wsl
                               if n in ("wsl", "wsl.exe") else None), \
             mock.patch.dict(module.os.environ,
                             {"ProgramFiles": bindir + "/nope",
                              "ProgramFiles(x86)": bindir + "/nope"}):
            self.assertEqual(module.probe_windows_posix_shell({}), "none",
                             "a WSL that answers --status but cannot execute "
                             "sh has no usable distribution")
