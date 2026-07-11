#!/usr/bin/env bash
# watch-status.sh — thin wrapper around the M8Shift built-in live monitor.
#
# All arguments pass straight through to `m8shift.py watch`, so use its flags:
#   scripts/watch-status.sh [--for <agent>] [--interval N] [--clear] [--changes-only]
#   M8SHIFT_ROOT=/path/to/relay scripts/watch-status.sh --for codex
#
# Env:
#   M8SHIFT_ROOT    relay root passed to the engine (default: current dir)
#   M8SHIFT_ENGINE  explicit path to m8shift.py (overrides discovery)
set -uo pipefail
M8SHIFT_RUNNER_VERSION="3.57.0"

root="${M8SHIFT_ROOT:-$PWD}"

# Engine resolution: $M8SHIFT_ENGINE > $M8SHIFT_ROOT/m8shift.py > ./m8shift.py > PATH
if [ -n "${M8SHIFT_ENGINE:-}" ]; then
  engine="$M8SHIFT_ENGINE"
elif [ -f "$root/m8shift.py" ]; then
  engine="$root/m8shift.py"
elif [ -f "./m8shift.py" ]; then
  engine="./m8shift.py"
else
  engine="$(command -v m8shift.py || echo ./m8shift.py)"
fi

# Delegate to the engine's own live monitor (handles --for/--interval/--clear/
# --changes-only, its own loop, and Ctrl-C). No argument is consumed here, so
# `watch-status.sh --for codex` is forwarded verbatim.
exec env M8SHIFT_ROOT="$root" python3 "$engine" watch "$@"
