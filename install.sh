#!/usr/bin/env bash
# M8Shift local installer.
#
# Intended one-liner:
#   curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash
#
# This script installs M8Shift into the current project directory by downloading the
# standalone CLI files, then runs `m8shift.py init`. It does not use sudo, does not
# modify PATH, and does not create a daemon.

set -euo pipefail

INSTALLER_VERSION="1.0.0"
BASE_URL="${M8SHIFT_INSTALL_BASE_URL:-https://raw.githubusercontent.com/M8Shift/M8Shift/main}"
TARGET_DIR="${M8SHIFT_INSTALL_DIR:-$PWD}"
AGENTS="claude,codex"
PROJECT_NAME=""
LANG_CODE=""
RUN_INIT=1
WITH_WORKTREE=1
FORCE_INIT=0
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
M8Shift installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash
  bash install.sh [options]

Options:
  --dir DIR            Install into DIR instead of the current directory.
  --agents A,B         Active roster passed to `m8shift.py init` (default: claude,codex).
  --name NAME          Project name passed to `m8shift.py init --name`.
  --lang CODE          Language passed to `m8shift.py init --lang` when bundled.
  --force             Pass `--force` to init (reinitialize M8SHIFT.md).
  --no-init           Download files only; do not run init.
  --no-worktree       Do not download m8shift-worktree.py.
  --base-url URL      Download base URL (default: GitHub raw main branch).
  -h, --help          Show this help.
  --version           Show installer version.

The installer is local-only: no sudo, no PATH mutation, no background service.
EOF
}

die() {
  printf 'm8shift install: %s\n' "$*" >&2
  exit 1
}

need_value() {
  [ "${2:-}" ] || die "$1 requires a value"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      need_value "$1" "${2:-}"
      TARGET_DIR="$2"
      shift 2
      ;;
    --agents)
      need_value "$1" "${2:-}"
      AGENTS="$2"
      shift 2
      ;;
    --name)
      need_value "$1" "${2:-}"
      PROJECT_NAME="$2"
      shift 2
      ;;
    --lang)
      need_value "$1" "${2:-}"
      LANG_CODE="$2"
      shift 2
      ;;
    --force)
      FORCE_INIT=1
      shift
      ;;
    --no-init)
      RUN_INIT=0
      shift
      ;;
    --no-worktree)
      WITH_WORKTREE=0
      shift
      ;;
    --base-url)
      need_value "$1" "${2:-}"
      BASE_URL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --version)
      printf 'm8shift install.sh %s\n' "$INSTALLER_VERSION"
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN is required"

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
BASE_URL="${BASE_URL%/}"

download_file() {
  name="$1"
  url="$BASE_URL/$name"
  dest="$TARGET_DIR/$name"
  tmp="$TARGET_DIR/.$name.tmp.$$"
  rm -f "$tmp"

  printf '→ downloading %s\n' "$name"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp" "$url"
  else
    "$PYTHON_BIN" - "$url" "$tmp" <<'PY'
import sys
from urllib.request import urlopen

url, dest = sys.argv[1], sys.argv[2]
with urlopen(url, timeout=30) as response, open(dest, "wb") as out:
    out.write(response.read())
PY
  fi

  chmod +x "$tmp"
  mv "$tmp" "$dest"
}

download_file "m8shift.py"
if [ "$WITH_WORKTREE" -eq 1 ]; then
  download_file "m8shift-worktree.py"
fi

if [ "$RUN_INIT" -eq 1 ]; then
  init_cmd=("$PYTHON_BIN" "./m8shift.py" "init" "--agents" "$AGENTS")
  if [ -n "$PROJECT_NAME" ]; then
    init_cmd+=("--name" "$PROJECT_NAME")
  fi
  if [ -n "$LANG_CODE" ]; then
    init_cmd+=("--lang" "$LANG_CODE")
  fi
  if [ "$FORCE_INIT" -eq 1 ]; then
    init_cmd+=("--force")
  fi

  printf '→ initializing M8Shift in %s\n' "$TARGET_DIR"
  (cd "$TARGET_DIR" && "${init_cmd[@]}")
fi

cat <<EOF

✓ M8Shift installed in $TARGET_DIR

Next:
  cd "$TARGET_DIR"
  $PYTHON_BIN m8shift.py status
  $PYTHON_BIN m8shift.py next ${AGENTS%%,*}
EOF
