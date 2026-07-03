#!/usr/bin/env python3
"""End-to-end e2e harness for M8Shift.

Two tiers share one Markdown case format and one assertion path:

* Tier A (default) is hermetic and deterministic: it drives a copied m8shift.py in a
  temporary directory and computes the expected artifact with a local arithmetic stub
  instead of any model or network process.
* Tier B is an OPT-IN live tier, gated by the M8SHIFT_LIVE_E2E env var being truthy AND
  a real agent CLI command being configured and resolvable. When ON, the SAME case is
  produced by the configured agent command instead of the stub; when the gate is off it
  SKIPS CLEANLY (clear message, exit 0, no failure). Network is allowed ONLY on Tier B.

This runner is advisory: it never replaces or gates the relay protocol.
"""
import argparse
import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

VERSION = "3.45.0"
HERE = os.path.dirname(os.path.abspath(__file__))

LIVE_ENV = "M8SHIFT_LIVE_E2E"      # truthy => attempt Tier B
AGENT_CMD_ENV = "M8SHIFT_E2E_AGENT_CMD"  # argv template (shlex-split, no shell)
TRUTHY = {"1", "true", "yes", "on"}


def die(message):
    raise SystemExit(message)


def env_truthy(name):
    return os.environ.get(name, "").strip().lower() in TRUTHY


def read_case(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"```m8shift-e2e\n(.*?)\n```", text, re.DOTALL)
    if not match:
        die(f"{path}: missing ```m8shift-e2e fenced block")
    data = {}
    for n, line in enumerate(match.group(1).splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            die(f"{path}: invalid case line {n}: {line!r}")
        data[key.strip()] = value.strip()
    for key in ("name", "artifact", "expression", "expected"):
        if not data.get(key):
            die(f"{path}: missing required key {key!r}")
    return data


def eval_int(node):
    if isinstance(node, ast.Expression):
        return eval_int(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -eval_int(node.operand)
    if isinstance(node, ast.BinOp):
        left = eval_int(node.left)
        right = eval_int(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
    die("case expression must use only integer literals with +, -, or *")


def compute(expression):
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        die(f"invalid expression {expression!r}: {e}")
    return str(eval_int(tree))


def run(cmd, cwd, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        die("command failed: {}\nstdout:\n{}\nstderr:\n{}".format(
            " ".join(cmd), r.stdout, r.stderr,
        ))
    return r


def artifact_path(work, artifact):
    candidate = os.path.abspath(os.path.join(work, artifact))
    root = os.path.abspath(work)
    if candidate != root and candidate.startswith(root + os.sep):
        return candidate
    die(f"artifact path must stay inside the e2e work directory: {artifact!r}")


def assert_artifact(case_path, case, artifact_file, artifact_name):
    expected = case["expected"].rstrip("\n") + "\n"
    with open(artifact_file, encoding="utf-8") as f:
        got = f.read()
    # Reading the artifact back transitively asserts compute(expr) == expected; it does
    # NOT capture the producing CLI's own stdout end to end.
    if got != expected:
        die(f"{case_path}: artifact mismatch for {artifact_name!r}: {got!r} != {expected!r}")


def stub_produce(case, artifact_file):
    """Tier A: deterministic local stub — no model, no network."""
    actual = compute(case["expression"])
    with open(artifact_file, "w", encoding="utf-8") as f:
        f.write(actual + "\n")
    return actual


def agent_argv():
    """Configured live-agent argv (env-driven, shlex-split, never shell-evaluated)."""
    return shlex.split(os.environ.get(AGENT_CMD_ENV, ""))


def live_gate_reason():
    """Return None when Tier B may run, else a human-readable skip reason."""
    if not env_truthy(LIVE_ENV):
        return f"{LIVE_ENV} not truthy"
    argv = agent_argv()
    if not argv:
        return f"{AGENT_CMD_ENV} unset"
    if shutil.which(argv[0]) is None:
        return f"agent CLI {argv[0]!r} not found on PATH"
    return None


def agent_produce(case, work, artifact_name):
    """Tier B: drive the configured real agent CLI to produce the artifact.

    The prompt is passed to the agent via the M8SHIFT_PROMPT env var and via a literal
    `{prompt}` placeholder substituted in the configured argv. Network is allowed here.
    """
    prompt = (
        "Compute the integer result of the arithmetic expression "
        f"{case['expression']!r} and write only that result followed by a newline to "
        f"the file {artifact_name!r} (relative to the current working directory). "
        "Do not write anything else."
    )
    argv = [tok.replace("{prompt}", prompt) for tok in agent_argv()]
    env = dict(os.environ)
    env["M8SHIFT_PROMPT"] = prompt
    run(argv, work, env=env)
    return "live"


def run_case(case_path, m8shift_py, keep=False, live=False):
    case = read_case(case_path)
    work = tempfile.mkdtemp(prefix="m8shift-e2e-")
    try:
        shutil.copy(m8shift_py, os.path.join(work, "m8shift.py"))
        run([sys.executable, "m8shift.py", "init", "--name", case["name"]], work)
        run([sys.executable, "m8shift.py", "claim", "claude"], work)
        run([sys.executable, "m8shift.py", "status", "--for", "claude"], work)

        artifact_file = artifact_path(work, case["artifact"])
        if live:
            actual = agent_produce(case, work, case["artifact"])
        else:
            actual = stub_produce(case, artifact_file)
        assert_artifact(case_path, case, artifact_file, case["artifact"])

        run([
            sys.executable, "m8shift.py", "append", "claude", "--to", "codex",
            "--ask", "verify artifact",
            "--done", f"computed {case['expression']} = {case['expected']}",
            "--files", case["artifact"],
        ], work)
        tier = "B/live" if live else "A"
        print(f"OK [{tier}] {case['name']}: {case['artifact']} == {case['expected']} ({actual})")
        return 0
    finally:
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run M8Shift e2e cases (Tier A hermetic; Tier B opt-in live).")
    ap.add_argument("--version", action="version", version=f"m8shift-e2e.py {VERSION}")
    ap.add_argument("case", help="Markdown case file under tests/e2e/")
    ap.add_argument("--m8shift-py", default=os.path.join(HERE, "m8shift.py"))
    ap.add_argument("--keep", action="store_true", help="keep the temporary run directory")
    ap.add_argument(
        "--live", action="store_true",
        help=(f"run Tier B against the configured agent CLI; requires {LIVE_ENV} truthy "
              f"and {AGENT_CMD_ENV} resolvable, else skips cleanly (exit 0)"),
    )
    args = ap.parse_args(argv)

    if args.live:
        reason = live_gate_reason()
        if reason is not None:
            print(f"SKIP Tier B live e2e: {reason}")
            return 0
        return run_case(args.case, args.m8shift_py, keep=args.keep, live=True)
    return run_case(args.case, args.m8shift_py, keep=args.keep, live=False)


if __name__ == "__main__":
    sys.exit(main())
