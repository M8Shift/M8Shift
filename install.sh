#!/usr/bin/env bash
# M8Shift local installer.
#
# Intended one-liner:
#   curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
#
# This script installs M8Shift into the current project directory by downloading the
# standalone CLI files, then runs `m8shift.py init`. It does not use sudo, does not
# modify PATH, and does not create a daemon.

set -euo pipefail

INSTALLER_VERSION="1.0.0"
REF="${M8SHIFT_INSTALL_REF:-main}"
BASE_URL="${M8SHIFT_INSTALL_BASE_URL:-}"
TARGET_DIR="${M8SHIFT_INSTALL_DIR:-$PWD}"
AGENTS="claude,codex"
PROJECT_NAME=""
LANG_CODE=""
RUN_INIT=1
WITH_WORKTREE=1
FORCE_INIT=0
VERIFY_DOWNLOADS="${M8SHIFT_INSTALL_VERIFY:-0}"
CHECKSUMS_URL="${M8SHIFT_INSTALL_CHECKSUMS_URL:-}"
CHECKSUMS_TEXT=""
EXPECTED_SHA256S=""
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
M8Shift installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
  bash install.sh [options]

Options:
  --dir DIR            Install into DIR instead of the current directory.
  --agents A,B         Active roster passed to `m8shift.py init` (default: claude,codex).
  --name NAME          Project name passed to `m8shift.py init --name`.
  --lang CODE          Language passed to `m8shift.py init --lang` when bundled.
  --force             Pass `--force` to init (reinitialize M8SHIFT.md).
  --no-init           Download files only; do not run init.
  --no-worktree       Do not download m8shift-worktree.py.
  --ref REF            Git ref used for downloads when --base-url is not set (default: main).
  --base-url URL      Download base URL (default: GitHub raw for --ref).
  --verify            Verify downloaded files against checksums.sha256.
  --checksums URL     Use a custom checksums URL or local path for --verify.
  --sha256 FILE:HEX   Pin one expected SHA-256 manually; repeatable.
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

download_to() {
  local url="$1"
  local dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$url"
  else
    "$PYTHON_BIN" - "$url" "$dest" <<'PY'
import sys
from urllib.request import urlopen

url, dest = sys.argv[1], sys.argv[2]
with urlopen(url, timeout=30) as response, open(dest, "wb") as out:
    out.write(response.read())
PY
  fi
}

file_sha256() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    "$PYTHON_BIN" - "$path" <<'PY'
import hashlib
import sys

h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
  fi
}

expected_sha_for() {
  local name="$1"
  local manual
  manual="$(printf '%s\n' "$EXPECTED_SHA256S" | awk -v name="$name" '$2 == name { print $1; exit }')"
  if [ -n "$manual" ]; then
    printf '%s\n' "$manual"
    return
  fi
  printf '%s\n' "$CHECKSUMS_TEXT" | awk -v name="$name" '$2 == name { print $1; exit }'
}

verify_file() {
  local name="$1"
  local path="$2"
  local expected
  expected="$(expected_sha_for "$name")"
  if [ -z "$expected" ]; then
    if [ "$VERIFY_DOWNLOADS" = "1" ]; then
      die "no checksum found for $name"
    fi
    return
  fi
  local actual
  actual="$(file_sha256 "$path")"
  if [ "$actual" != "$expected" ]; then
    die "$name checksum mismatch: expected $expected, got $actual"
  fi
  printf '✓ verified %s\n' "$name"
}

add_expected_sha256() {
  local spec="$1"
  local name
  local hex
  case "$spec" in
    *:*) name="${spec%%:*}"; hex="${spec#*:}" ;;
    *=*) name="${spec%%=*}"; hex="${spec#*=}" ;;
    *) die "--sha256 expects FILE:HEX" ;;
  esac
  case "$name" in
    m8shift.py|m8shift-worktree.py) ;;
    *) die "--sha256 file must be m8shift.py or m8shift-worktree.py" ;;
  esac
  printf '%s' "$hex" | grep -Eiq '^[0-9a-f]{64}$' || die "--sha256 expects a 64-char hex digest"
  EXPECTED_SHA256S="${EXPECTED_SHA256S}${hex} ${name}
"
}

validate_ref() {
  case "$REF" in
    ""|-*|*..*|*\\*|*" "*|*"	"*|*"
"*)
      die "unsafe --ref: $REF"
      ;;
  esac
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
    --ref)
      need_value "$1" "${2:-}"
      REF="$2"
      shift 2
      ;;
    --base-url)
      need_value "$1" "${2:-}"
      BASE_URL="$2"
      shift 2
      ;;
    --verify)
      VERIFY_DOWNLOADS=1
      shift
      ;;
    --checksums)
      need_value "$1" "${2:-}"
      CHECKSUMS_URL="$2"
      VERIFY_DOWNLOADS=1
      shift 2
      ;;
    --sha256)
      need_value "$1" "${2:-}"
      add_expected_sha256 "$2"
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
validate_ref

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
if [ -z "$BASE_URL" ]; then
  BASE_URL="https://raw.githubusercontent.com/M8Shift/M8Shift/$REF"
fi
BASE_URL="${BASE_URL%/}"
if [ -z "$CHECKSUMS_URL" ]; then
  CHECKSUMS_URL="$BASE_URL/checksums.sha256"
fi

if [ "$VERIFY_DOWNLOADS" = "1" ]; then
  checksums_tmp="$TARGET_DIR/.checksums.sha256.tmp.$$"
  rm -f "$checksums_tmp"
  if [ -f "$CHECKSUMS_URL" ]; then
    printf '→ reading checksums\n'
    CHECKSUMS_TEXT="$(cat "$CHECKSUMS_URL")"
  else
    printf '→ downloading checksums\n'
    download_to "$CHECKSUMS_URL" "$checksums_tmp"
    CHECKSUMS_TEXT="$(cat "$checksums_tmp")"
    rm -f "$checksums_tmp"
  fi
fi

download_file() {
  local name="$1"
  local url="$BASE_URL/$name"
  local dest="$TARGET_DIR/$name"
  local tmp="$TARGET_DIR/.$name.tmp.$$"
  rm -f "$tmp"

  printf '→ downloading %s\n' "$name"
  download_to "$url" "$tmp"
  verify_file "$name" "$tmp"
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
