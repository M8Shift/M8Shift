#!/usr/bin/env python3
"""Read-only, exact-tip verification of unittest discovery on a checked-out commit.

This is an independent public implementation; it never executes test methods.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()


def inspect(repo, commit="HEAD"):
    repo = Path(repo).resolve()
    sha = git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    head = git(repo, "rev-parse", "HEAD")
    if sha != head:
        raise ValueError("requested commit is not the checked-out HEAD")
    if git(repo, "status", "--porcelain", "--", "tests"):
        raise ValueError("test directory has uncommitted changes")
    tracked = [s for s in git(repo, "ls-tree", "-r", "--name-only", sha, "--", "tests").splitlines()
               if Path(s).name.startswith("test_") and s.endswith(".py")]
    if not tracked:
        raise ValueError("no tracked test modules")
    # Isolate discovery in a fresh interpreter, with no test methods run.
    probe = '''import json,unittest,sys
suite=unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
def flatten(node):
 for item in node:
  if isinstance(item,unittest.TestSuite): yield from flatten(item)
  else: yield item
cases=list(flatten(suite))
errors=[str(case) for case in cases if case.__class__.__name__ in ("_FailedTest",)]
print(json.dumps({"count":len(cases),"errors":errors}))
'''
    p = subprocess.run([sys.executable, "-B", "-c", probe], cwd=repo,
                       capture_output=True, text=True, timeout=90, check=False)
    if p.returncode:
        raise ValueError("unittest discovery subprocess failed")
    try:
        report = json.loads(p.stdout)
    except ValueError as exc:
        raise ValueError("invalid discovery report") from exc
    if report.get("errors") or not isinstance(report.get("count"), int) or report["count"] < 1:
        raise ValueError("unittest discovery failed or found no tests")
    return {"schema": "m8shift.test-loading.v1", "commit": sha,
            "tracked_test_modules": len(tracked), "discovered_cases": report["count"],
            "status": "passed", "scope": "unittest discovery only; no test methods executed"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=".")
    p.add_argument("--commit", default="HEAD")
    args = p.parse_args(argv)
    try:
        result = inspect(args.repo, args.commit)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
