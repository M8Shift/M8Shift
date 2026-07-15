#!/usr/bin/env python3
"""Operator-gated, reversible refresh of an adopted relay's live scripts."""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile


class HelpfulArgumentParser(argparse.ArgumentParser):
    """Print command help plus a valid required-argument shape on errors."""

    def error(self, message):
        parts = [self.prog]
        for action in self._actions:
            if action.dest == "help" or not action.required:
                continue
            if action.option_strings:
                parts.append(action.option_strings[-1])
            if action.nargs != 0:
                parts.append(str(action.metavar or action.dest.upper()))
        old = self.epilog
        self.epilog = ((old + "\n\n") if old else "") + \
            "required invocation example:\n  " + " ".join(parts)
        self.print_help(sys.stderr)
        self.epilog = old
        self.exit(2, "\n%s: error: %s\n" % (self.prog, message))


LIVE_SCRIPTS = (
    "m8shift.py", "m8shift-top.py", "m8shift-runtime.py", "m8shift-context.py",
    "m8shift-worktree.py", "m8shift-headroom.py", "m8shift-i18n.py", "m8shift-e2e.py",
)


def git(source, *args):
    return subprocess.run(["git", "-C", source, *args], capture_output=True, text=True)


def source_authority(source, expected_ref):
    if not os.path.isfile(os.path.join(source, "m8shift.py")):
        return False, "source has no m8shift.py"
    head = git(source, "rev-parse", "HEAD")
    ref = git(source, "rev-parse", expected_ref)
    dirty = git(source, "status", "--porcelain")
    if head.returncode or ref.returncode or dirty.returncode:
        return False, "source must be a readable git checkout"
    if dirty.stdout.strip():
        return False, "source checkout has local changes"
    if head.stdout.strip() != ref.stdout.strip():
        return False, "source HEAD does not equal %s" % expected_ref
    return True, head.stdout.strip()


def snapshot(target, backup):
    candidates = [*LIVE_SCRIPTS, os.path.join(".m8shift", "kit.json"),
                  os.path.join(".m8shift", "update-audit.jsonl")]
    rels = [rel for rel in candidates if os.path.isfile(os.path.join(target, rel))]
    for rel in rels:
        dest = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(target, rel), dest)
    with open(os.path.join(backup, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"files": rels, "absent": [r for r in candidates if r not in rels]}, fh,
                  indent=2)
    return rels, [r for r in candidates if r not in rels]


def restore(target, backup, rels, absent=()):
    for rel in rels:
        src, dest = os.path.join(backup, rel), os.path.join(target, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".m8shift-rollback-")
        os.close(fd)
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    for rel in absent:
        path = os.path.join(target, rel)
        if os.path.isfile(path) and not os.path.islink(path):
            os.unlink(path)


def main(argv=None):
    p = HelpfulArgumentParser(
        usage="%(prog)s --source DIR --target DIR [--expected-ref REF] [--apply]",
        description="Validate and reversibly refresh an adopted relay from a clean release checkout.",
        epilog="""example:
  m8shift-self-update.py --source ./release --target ./my-project --apply""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", metavar="DIR", required=True,
                   help="clean checkout containing merged release")
    p.add_argument("--target", metavar="DIR", required=True,
                   help="initialized live relay directory")
    p.add_argument("--expected-ref", default="origin/main",
                   help="source ref HEAD must equal (default: origin/main)")
    p.add_argument("--apply", action="store_true",
                   help="perform the refresh; without this flag only a dry-run is run")
    args = p.parse_args(argv)
    source, target = map(os.path.realpath, (args.source, args.target))
    ok, authority = source_authority(source, args.expected_ref)
    if not ok:
        p.error(authority)
    driver = os.path.join(source, "m8shift.py")
    command = [sys.executable, driver, "update", "--target", target, "--source", source,
               "--components", "core,companions", "--json"]
    if not args.apply:
        command.append("--dry-run")
        return subprocess.run(command).returncode

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(target, ".m8shift", "update-backups", stamp)
    os.makedirs(backup, exist_ok=False)
    rels, absent = snapshot(target, backup)
    result = subprocess.run(command)
    if result.returncode:
        restore(target, backup, rels, absent)
        print("self-update failed; restored %d files from %s" % (len(rels), backup),
              file=sys.stderr)
        return result.returncode
    print("self-update complete from %s; rollback snapshot: %s" % (authority[:12], backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
