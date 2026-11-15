#!/usr/bin/env python3
"""Read-only terrain probe for the M8Shift onboarding conductor (#378).

The onboarding doctrine: a guessed path is paid for later, an absent
prerequisite is a finding before the first write, and a launched lane is
reported by what was verified. This probe is the finding half — it NEVER
writes, and its verdict gates the conductor before any installation begins.

Facts may be injected as a JSON object through M8SHIFT_ONBOARD_PROBE_FACTS
(the same test seam family as M8SHIFT_LISTENER_BACKEND_PROBE): any probed
fact present in the object replaces the live observation. The seam exists
for hermetic tests and never touches a real system either way.

Exit codes: 0 = no blocking finding; 3 = at least one blocking finding;
2 = argparse refusal. `--json` prints one machine-readable object either way.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

PROBE_FACTS_ENV = "M8SHIFT_ONBOARD_PROBE_FACTS"
PYTHON_FLOOR = (3, 12)


def injected_facts(env=None):
    raw = (env if env is not None else os.environ).get(PROBE_FACTS_ENV, "")
    if not raw.strip():
        return {}
    try:
        facts = json.loads(raw)
    except ValueError:
        raise SystemExit("onboard-probe: %s is not valid JSON" % PROBE_FACTS_ENV)
    if not isinstance(facts, dict):
        raise SystemExit("onboard-probe: %s must be a JSON object" % PROBE_FACTS_ENV)
    return facts


POSIX_PROBE_MARKER = "m8shift-posix-ok"


def _candidate_executes_posix(argv):
    """A candidate proves itself by EXECUTING one bounded POSIX command.

    Classifying a basename lies: WSL without a distribution still answers
    `--status`, and Windows ships a System32 `bash.exe` that is only the WSL
    launcher. The only honest test is running `sh`-compatible code through the
    candidate and reading the marker back.
    """
    try:
        probe = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0 and POSIX_PROBE_MARKER in probe.stdout


def probe_windows_posix_shell(facts):
    """On Windows, M8Shift assumes a POSIX shell: WSL first, Git Bash second.

    Absence of both is a FINDING stated before anything is written, never a
    mid-install failure. Off Windows the native shell qualifies. Every
    candidate must EXECUTE the marker probe — presence on PATH proves nothing.
    """
    if "posix_shell" in facts:
        return str(facts["posix_shell"])
    if "wsl" in facts or "git_bash" in facts:
        if facts.get("wsl"):
            return "wsl"
        if facts.get("git_bash"):
            return "git-bash"
        return "none"
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl and _candidate_executes_posix(
            [wsl, "-e", "sh", "-c", "echo %s" % POSIX_PROBE_MARKER]):
        return "wsl"
    candidates = [shutil.which("bash.exe"), shutil.which("bash"),
                  os.path.join(os.environ.get("ProgramFiles",
                                              r"C:\Program Files"),
                               "Git", "bin", "bash.exe"),
                  os.path.join(os.environ.get("ProgramFiles(x86)",
                                              r"C:\Program Files (x86)"),
                               "Git", "bin", "bash.exe")]
    for bash in candidates:
        if bash and os.path.isfile(bash) and _candidate_executes_posix(
                [bash, "-c", "echo %s" % POSIX_PROBE_MARKER]):
            return "git-bash"
    return "none"


def probe_terrain(env=None):
    facts = injected_facts(env)
    system = str(facts.get("os", platform.system()))
    report = {"schema": "m8shift.onboard.terrain.v1", "os": system,
              "blocking": [], "advisory": []}

    if "python_version" in facts:
        py = tuple(int(p) for p in str(facts["python_version"]).split("."))[:2]
        py_present = bool(facts.get("python_present", True))
    else:
        py = sys.version_info[:2]
        py_present = True
    report["python"] = {"present": py_present,
                        "version": ".".join(str(p) for p in py) if py_present else "",
                        "floor": ".".join(str(p) for p in PYTHON_FLOOR)}
    if not py_present:
        report["blocking"].append(
            "python is absent; the M8Shift core is a Python 3.12+ script and "
            "cannot run without it")
    elif py < PYTHON_FLOOR:
        report["blocking"].append(
            "python %s is below the 3.12 floor introduced by v4.0.0 "
            "(CVE-driven; see the release notes)" % report["python"]["version"])

    git_present = bool(facts.get("git", shutil.which("git") is not None))
    report["git"] = {"present": git_present}
    if not git_present:
        report["advisory"].append(
            "git is absent: the CORE install works without it (Python download "
            "and hashing fallbacks), but forge coordination and hooks will not")

    if system.lower().startswith("win"):
        shell = probe_windows_posix_shell(facts)
        report["posix_shell"] = shell
        if shell == "none":
            report["blocking"].append(
                "Windows without WSL and without Git Bash: M8Shift assumes a "
                "POSIX shell. Install WSL (preferred: `wsl --install` from an "
                "administrator PowerShell, then reboot) or Git for Windows "
                "(ships Git Bash), then run this probe again. Nothing was "
                "written; the installation has not begun.")
    else:
        report["posix_shell"] = "native"

    return report


def update_check(target, source):
    """Read-only drift check between an installed instance and a source.

    Both are LOCAL paths the operator or agent names explicitly — this probe
    never reaches for the network on its own. The drift family: an instance
    created months ago runs a version nobody checked (#312 tree drift, #334
    loaded-versus-on-disk skew) — invisible until someone looks.

    Equal VERSION constants are NOT currency: a tampered or stale core at the
    right VERSION would pass a string compare. The verdict is anchored to the
    source's checksum manifest — the target core's bytes must hash to exactly
    the digest the source manifest pins for m8shift.py. A source without a
    readable manifest entry yields `unverifiable`, never `current`.
    """
    import hashlib
    import re
    out = {"schema": "m8shift.onboard.update-check.v2",
           "target": target, "source": source}
    vpat = re.compile(r'^VERSION = "(\d+\.\d+\.\d+)"', re.M)
    for key, root in (("installed", target), ("available", source)):
        core = os.path.join(root, "m8shift.py")
        if not os.path.isfile(core):
            raise SystemExit("onboard-probe: no m8shift.py under %s" % root)
        with open(core, encoding="utf-8") as fh:
            match = vpat.search(fh.read())
        if not match:
            raise SystemExit("onboard-probe: no VERSION constant in %s" % core)
        out[key] = match.group(1)
    manifest = os.path.join(source, "checksums.sha256")
    pinned = ""
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as fh:
            for line in fh:
                entry = re.match(r"^([0-9a-f]{64})  m8shift\.py$", line.strip())
                if entry:
                    pinned = entry.group(1)
                    break
    if not pinned:
        out["verdict"] = "unverifiable"
        out["detail"] = ("the source has no readable checksums.sha256 entry "
                         "for m8shift.py; refusing to certify currency "
                         "without byte evidence")
        out["current"] = False
        return out
    with open(os.path.join(target, "m8shift.py"), "rb") as fh:
        actual = hashlib.sha256(fh.read()).hexdigest()
    out["core_digest_matches"] = actual == pinned
    if out["installed"] != out["available"]:
        out["verdict"] = "drift"
        out["detail"] = ("installed %s, available %s" %
                         (out["installed"], out["available"]))
    elif not out["core_digest_matches"]:
        out["verdict"] = "drift"
        out["detail"] = ("VERSION matches (%s) but the installed core bytes "
                         "do not hash to the source manifest digest — a "
                         "tampered or stale core at the right VERSION"
                         % out["installed"])
    else:
        out["verdict"] = "current"
        out["detail"] = "core bytes match the source manifest digest"
    out["current"] = out["verdict"] == "current"
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="onboard-probe.py",
        description="Read-only M8Shift onboarding terrain probe (#378).")
    parser.add_argument("--json", action="store_true",
                        help="print the machine-readable report")
    parser.add_argument("--update-check", action="store_true",
                        help="compare an installed instance version with a "
                             "named local source instead of probing terrain")
    parser.add_argument("--target", help="installed instance root (update check)")
    parser.add_argument("--source", help="release source root (update check)")
    args = parser.parse_args(argv)

    if args.update_check:
        if not args.target or not args.source:
            parser.error("--update-check requires --target and --source")
        report = update_check(args.target, args.source)
        print(json.dumps(report, sort_keys=True) if args.json else
              ("kit is current (%s): %s" % (report["installed"],
                                            report["detail"])
               if report["current"] else
               "kit %s: %s — see the upgrade block in the release notes"
               % (report["verdict"], report["detail"])))
        return 0 if report["current"] else 3

    report = probe_terrain()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("os: %s · python: %s · git: %s · posix shell: %s" % (
            report["os"],
            report["python"]["version"] or "absent",
            "present" if report["git"]["present"] else "absent",
            report["posix_shell"]))
        for finding in report["blocking"]:
            print("BLOCKING: %s" % finding)
        for finding in report["advisory"]:
            print("advisory: %s" % finding)
    return 3 if report["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
