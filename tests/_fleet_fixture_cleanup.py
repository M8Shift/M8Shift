"""Test-only process census scoped to explicitly created fleet fixture roots."""
import os
from pathlib import Path
import shlex
import subprocess


def owned_listener_processes(roots):
    """Return fixture PIDs, not a global kill list; fail when census is unavailable."""
    roots = [os.path.realpath(root) for root in roots]
    if not roots:
        return []
    try:
        result = subprocess.run(["ps", "-ww", "-axo", "pid=,command="],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError("fleet fixture process census unavailable") from exc
    if result.returncode != 0:
        raise AssertionError("fleet fixture process census failed")
    expected = {str(Path(root) / name) for root in roots
                for name in ("m8shift-runtime.py", "examples/headless_runner.py")}
    matches = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        try:
            argv = shlex.split(parts[1])
        except ValueError:
            # Generated fixture paths contain no spaces or quotes. An unmatched
            # quote elsewhere must not hide an exact fixture script token.
            argv = parts[1].split()
        if expected.intersection(argv):
            matches.append(int(parts[0]))
    return sorted(set(matches))
