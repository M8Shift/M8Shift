#!/usr/bin/env python3
"""Benchmark M8Shift's process-per-command CLI startup cost.

The benchmark compares the source script with its precompiled bytecode.  Extra
standalone builds (for example Nuitka or PyInstaller output) can be supplied via
``--candidate NAME=/path/to/executable``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import py_compile
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


def measure(argv: list[str], cwd: Path, runs: int, env: dict[str, str]) -> dict[str, float]:
    samples = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        proc = subprocess.run(
            argv + ["status", "--for", "codex"],
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if proc.returncode:
            raise RuntimeError(f"{' '.join(argv)} failed: {proc.stderr.strip()}")
        samples.append(elapsed)
    ordered = sorted(samples)
    return {
        "first_ms": round(samples[0], 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 3),
        "mean_ms": round(statistics.fmean(samples), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        usage="%(prog)s [--runs N] [--candidate NAME=EXECUTABLE] [--json]",
        description="Benchmark m8shift.py interpreter startup and read-only command latency.",
        epilog="""example:
  benchmark-startup.py --runs 50 --json""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument(
        "--candidate", action="append", default=[], metavar="NAME=EXECUTABLE",
        help="benchmark an optional standalone build (repeatable)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")

    root = Path(__file__).resolve().parents[1]
    source = root / "m8shift.py"
    with tempfile.TemporaryDirectory(prefix="m8shift-benchmark-") as raw_tmp:
        relay = Path(raw_tmp)
        env = {key: value for key, value in os.environ.items() if not key.startswith("M8SHIFT_")}
        shutil.copy2(source, relay / "m8shift.py")
        subprocess.run(
            [sys.executable, "m8shift.py", "init", "--agents", "claude,codex"],
            cwd=relay, env=env, check=True, stdout=subprocess.DEVNULL,
        )
        pyc = relay / "m8shift.pyc"
        py_compile.compile(str(relay / "m8shift.py"), cfile=str(pyc), doraise=True)

        candidates: dict[str, list[str]] = {
            "source": [sys.executable, str(relay / "m8shift.py")],
            "pyc": [sys.executable, str(pyc)],
        }
        for value in args.candidate:
            name, separator, executable = value.partition("=")
            if not separator or not name or not executable:
                parser.error("--candidate must be NAME=EXECUTABLE")
            candidates[name] = [str(Path(executable).expanduser().resolve())]

        results = {
            name: measure(command, relay, args.runs, env)
            for name, command in candidates.items()
        }
        report = {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "runs": args.runs,
            "command": "status --for codex",
            "results": results,
        }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Python {report['python']} on {report['platform']}; {args.runs} fresh processes")
        print("candidate\tfirst ms\tmedian ms\tp95 ms\tmean ms")
        for name, result in results.items():
            print(f"{name}\t{result['first_ms']:.3f}\t{result['median_ms']:.3f}\t"
                  f"{result['p95_ms']:.3f}\t{result['mean_ms']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
