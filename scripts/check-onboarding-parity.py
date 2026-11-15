#!/usr/bin/env python3
"""Compare local conductor command blocks without editing or fetching either copy."""
import argparse
import json
from pathlib import Path
import re
import sys

LIMIT = 1024 * 1024


def normalize_command(line):
    """Conservative lexical comparison; never discard quoting or escapes."""
    result, quote, escaped, pending_space = [], None, False, False
    for char in line.lstrip():
        if escaped:
            result.append(char)
            escaped = False
            continue
        if quote is None and char.isspace():
            pending_space = bool(result)
            continue
        if pending_space:
            result.append(" ")
            pending_space = False
        result.append(char)
        if char == chr(92) and quote != "'":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
    return "".join(result)


def commands(path):
    with Path(path).open(encoding="utf-8") as handle:
        text = handle.read(LIMIT + 1)
    if len(text) > LIMIT:
        raise ValueError("document exceeds the comparison limit")
    blocks = re.findall(r"^```(?:sequence|sh|bash|shell)\s*\n(.*?)^```\s*$", text, re.M | re.S)
    if not blocks:
        raise ValueError("no conductor command blocks found")
    return [tuple(normalize_command(line) for line in block.splitlines()
                  if line.strip() and not line.lstrip().startswith("#")) for block in blocks]


def compare(source, site):
    left, right = commands(source), commands(site)
    differences = [index + 1 for index in range(max(len(left), len(right)))
                   if index >= len(left) or index >= len(right) or left[index] != right[index]]
    return {"schema": "m8shift.onboarding.parity.v1", "read_only": True,
            "status": "diverged" if differences else "matched",
            "source_blocks": len(left), "site_blocks": len(right),
            "differing_blocks": differences}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--site", required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(args.source, args.site)
    except (OSError, UnicodeError, ValueError):
        print(json.dumps({"status": "unverifiable", "reason": "bounded_command_comparison_failed"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "matched" else 1


if __name__ == "__main__":
    sys.exit(main())
