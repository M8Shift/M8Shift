#!/usr/bin/env python3
"""Repeatable scrub-check history benchmark (LOT 4 gate 2; stdlib only).

Builds deterministic synthetic repositories and measures the current scanner.
This is measurement infrastructure, not an algorithm selection.  The default
matrix is intentionally small; pass the full design matrix explicitly:

  python3 scripts/benchmark-scrub-check.py --terms 1,10,46,100 \\
      --commits 100,1000,5000 --repeats 3 --json results.json
"""
import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_scanner():
    path = os.path.join(ROOT, "scripts", "scrub-check.py")
    spec = importlib.util.spec_from_file_location("scrub_check_bench", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_repo(repo, commits, terms):
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "benchmark@example.invalid")
    git(repo, "config", "user.name", "scrub benchmark")
    path = os.path.join(repo, "fixture.txt")
    for i in range(commits):
        # Deterministic count changes exercise pickaxe without leaking real data.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("commit %d SyntheticBenchTerm%03d\n" % (i, i % terms))
        git(repo, "add", "fixture.txt")
        git(repo, "commit", "-q", "-m", "fixture-%06d" % i)


def measure(mod, repo, denylist, max_commits):
    count = [0]

    def counted(cmd, cwd):
        count[0] += 1
        return mod.run_git(cmd, cwd)

    out, err = io.StringIO(), io.StringIO()
    started = time.perf_counter()
    rc = mod.main(["--repo", repo, "--denylist", denylist,
                   "--max-commits", str(max_commits)], out=out, err=err,
                  run=counted)
    return {"seconds": round(time.perf_counter() - started, 6), "rc": rc,
            "git_subprocesses": count[0], "stdout_bytes": len(out.getvalue()),
            "stderr_bytes": len(err.getvalue())}


def csv_ints(value):
    values = [int(x) for x in value.split(",")]
    if not values or any(x < 1 for x in values):
        raise argparse.ArgumentTypeError("expected comma-separated positive integers")
    return values


def main(argv=None):
    ap = argparse.ArgumentParser(
        usage="%(prog)s [--terms N,...] [--commits N,...] [--repeats N] [--json PATH]",
        description="Benchmark confidential denylist scanning with fabricated repositories.",
        epilog="""example:
  benchmark-scrub-check.py --terms 1,10 --commits 100,1000 --repeats 2""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terms", type=csv_ints, default=csv_ints("1,10"))
    ap.add_argument("--commits", type=csv_ints, default=csv_ints("100"))
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--json", metavar="PATH", help="also write exact JSON results")
    args = ap.parse_args(argv)
    if args.repeats < 1:
        ap.error("--repeats must be positive")
    mod, results = load_scanner(), []
    root = tempfile.mkdtemp(prefix="m8-scrub-benchmark-")
    try:
        for commits in args.commits:
            for terms in args.terms:
                repo = os.path.join(root, "c%d-t%d" % (commits, terms))
                os.makedirs(repo)
                build_repo(repo, commits, terms)
                denylist = os.path.join(repo, "denylist.txt")
                with open(denylist, "w", encoding="utf-8") as fh:
                    fh.writelines("SyntheticBenchTerm%03d\n" % i
                                  for i in range(terms))
                for repeat in range(args.repeats):
                    row = {"commits": commits, "terms": terms,
                           "run": "cold" if repeat == 0 else "warm",
                           "repeat": repeat}
                    row.update(measure(mod, repo, denylist, commits))
                    results.append(row)
                    print(json.dumps(row, sort_keys=True))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"schema": "m8shift.scrub-benchmark/1",
                       "results": results}, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
