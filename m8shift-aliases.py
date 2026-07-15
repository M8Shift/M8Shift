#!/usr/bin/env python3
"""Print or install portable shell aliases for the M8Shift companions."""

import argparse
import os
import shlex
import sys
from pathlib import Path


BEGIN = "# >>> m8shift aliases >>>"
END = "# <<< m8shift aliases <<<"


def detect_shell() -> str:
    shell = Path(os.environ.get("SHELL", "")).name.lower()
    if "zsh" in shell:
        return "zsh"
    return "bash"


def default_rc(shell: str) -> Path:
    # Git Bash uses the same POSIX syntax and HOME-based rc as bash.
    return Path.home() / (".zshrc" if shell == "zsh" else ".bashrc")


def alias_block(script_dir: Path) -> str:
    python = shlex.quote(sys.executable or "python3")
    core = shlex.quote(str(script_dir / "m8shift.py"))
    top = shlex.quote(str(script_dir / "m8shift-top.py"))
    return (
        f"{BEGIN}\n"
        f"alias m8shift={shlex.quote(f'{python} {core}')}\n"
        f"alias m8shift-top={shlex.quote(f'{python} {top}')}\n"
        f"{END}\n"
    )


def replace_block(existing: str, block: str) -> str:
    start = existing.find(BEGIN)
    end = existing.find(END, start + len(BEGIN)) if start >= 0 else -1
    if start >= 0 and end >= 0:
        end += len(END)
        if end < len(existing) and existing[end] == "\n":
            end += 1
        return existing[:start] + block + existing[end:]
    separator = "" if not existing or existing.endswith("\n") else "\n"
    return existing + separator + block


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        usage="%(prog)s [--write] [--shell SHELL] [--rc FILE]",
        description="Print portable M8Shift aliases, or idempotently install them in a shell rc file.",
        epilog="""examples:
  m8shift-aliases.py
  m8shift-aliases.py --write --shell zsh
  m8shift-aliases.py --write --shell git-bash --rc ~/.bashrc""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true", help="write the marked alias block")
    parser.add_argument("--shell", metavar="SHELL", choices=("auto", "bash", "zsh", "git-bash"),
                        default="auto", help="shell syntax to print or install (default: auto)")
    parser.add_argument("--rc", metavar="FILE", type=Path,
                        help="override the destination rc file used with --write")
    args = parser.parse_args(argv)

    shell = detect_shell() if args.shell == "auto" else args.shell
    block = alias_block(Path(__file__).resolve().parent)
    if not args.write:
        sys.stdout.write(block)
        return 0

    rc = args.rc.expanduser() if args.rc else default_rc(shell)
    existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
    updated = replace_block(existing, block)
    if updated != existing:
        rc.parent.mkdir(parents=True, exist_ok=True)
        rc.write_text(updated, encoding="utf-8")
    print(f"M8Shift aliases installed in {rc}")
    print(f"Reload with: source {shlex.quote(str(rc))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
