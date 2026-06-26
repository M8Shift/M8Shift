#!/usr/bin/env python3
"""Deterministic Tier-A e2e harness for M8Shift.

This runner is advisory: it drives a copied m8shift.py in a temporary directory and
uses a deterministic local stub instead of any model/network process.
"""
import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = "3.26.0"
HERE = os.path.dirname(os.path.abspath(__file__))


def die(message):
    raise SystemExit(message)


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


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
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


def run_case(case_path, m8shift_py, keep=False):
    case = read_case(case_path)
    work = tempfile.mkdtemp(prefix="m8shift-e2e-")
    try:
        shutil.copy(m8shift_py, os.path.join(work, "m8shift.py"))
        run([sys.executable, "m8shift.py", "init", "--name", case["name"]], work)
        run([sys.executable, "m8shift.py", "claim", "claude"], work)
        run([sys.executable, "m8shift.py", "status", "--for", "claude"], work)

        actual = compute(case["expression"])
        artifact = artifact_path(work, case["artifact"])
        with open(artifact, "w", encoding="utf-8") as f:
            f.write(actual + "\n")

        expected = case["expected"].rstrip("\n") + "\n"
        with open(artifact, encoding="utf-8") as f:
            got = f.read()
        if got != expected:
            die(f"{case_path}: artifact mismatch for {case['artifact']!r}: {got!r} != {expected!r}")

        run([
            sys.executable, "m8shift.py", "append", "claude", "--to", "codex",
            "--ask", "verify deterministic artifact",
            "--done", f"computed {case['expression']} = {actual}",
            "--files", case["artifact"],
        ], work)
        print(f"OK {case['name']}: {case['artifact']} == {actual}")
        return 0
    finally:
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run deterministic M8Shift Tier-A e2e cases.")
    ap.add_argument("--version", action="version", version=f"m8shift-e2e.py {VERSION}")
    ap.add_argument("case", help="Markdown case file under tests/e2e/")
    ap.add_argument("--m8shift-py", default=os.path.join(HERE, "m8shift.py"))
    ap.add_argument("--keep", action="store_true", help="keep the temporary run directory")
    args = ap.parse_args(argv)
    return run_case(args.case, args.m8shift_py, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
