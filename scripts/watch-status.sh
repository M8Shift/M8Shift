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
#
# Examples:
#   scripts/watch-status.sh --for agent-a
#   scripts/watch-status.sh --interval 5 --changes-only
set -uo pipefail
M8SHIFT_RUNNER_VERSION="3.62.0"
export M8SHIFT_RUNNER_VERSION

usage() {
  cat <<'EOF'
Usage: watch-status.sh [--for AGENT] [--interval SECONDS] [--clear] [--changes-only] [--once]

Open the read-only M8Shift status monitor through the installed relay engine.

All monitor parameters are forwarded to `m8shift.py watch`. Set M8SHIFT_ROOT to
select a relay root or M8SHIFT_ENGINE to select an explicit engine script.

Examples:
  scripts/watch-status.sh --for agent-a
  scripts/watch-status.sh --interval 5 --changes-only
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --version) printf 'watch-status.sh %s\n' "$M8SHIFT_RUNNER_VERSION"; exit 0 ;;
esac

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
