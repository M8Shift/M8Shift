#!/usr/bin/env bash
# M8Shift local installer.
#
# Intended one-liner:
#   curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --agents claude,codex
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
WITH_RUNTIME=1
WITH_CONTEXT=1
FORCE_INIT=0
RTK_CHOICE="${M8SHIFT_INSTALL_RTK:-ask}"  # ask|yes|no
VERIFY_EXPLICIT=""   # --verify sets 1, --no-verify sets 0; otherwise env/default decide
VERIFY_DOWNLOADS=1   # resolved after arg parsing (verification is ON by default)
CHECKSUMS_URL="${M8SHIFT_INSTALL_CHECKSUMS_URL:-}"
CHECKSUMS_TEXT=""
EXPECTED_SHA256S=""
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
M8Shift installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --agents claude,codex
  bash install.sh [options]

Options:
  --dir DIR            Install into DIR instead of the current directory.
  --agents A,B         Active roster passed to `m8shift.py init` (default: claude,codex).
  --name NAME          Project name passed to `m8shift.py init --name`.
  --lang CODE          Language passed to `m8shift.py init --lang` when bundled.
  --force             Pass `--force` to init (reinitialize M8SHIFT.md).
  --no-init           Download files only; do not run init.
  --no-worktree       Do not download m8shift-worktree.py.
  --no-runtime        Do not download m8shift-runtime.py.
  --no-context        Do not download m8shift-context.py.
  --with-rtk          With consent already given, install optional RTK via Homebrew if absent.
  --no-rtk            Do not prompt for or install RTK; if present, telemetry is still disabled.
  --ref REF            Git ref used for downloads when --base-url is not set (default: main).
  --base-url URL      Download base URL (default: GitHub raw for --ref).
  --verify            Force checksum verification (already the default).
  --no-verify         Skip checksum verification.
  --checksums URL     Use a custom checksums URL or local path (implies verification).
  --sha256 FILE:HEX   Pin one expected SHA-256 manually; repeatable.
  -h, --help          Show this help.
  --version           Show installer version.

The installer is local-only: no sudo, no PATH mutation, no background service.
Verification is enabled by default; --no-verify disables it.
Security note: verification checks integrity against the selected ref's manifest;
for out-of-band trust, pin a reviewed digest with --sha256 or use a signed tag.
RTK is optional. When installed or already present, this installer runs
`rtk telemetry disable` to keep telemetry off by default.
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
    m8shift.py|m8shift-worktree.py|m8shift-runtime.py|m8shift-context.py) ;;
    *) die "--sha256 file must be m8shift.py, m8shift-worktree.py, m8shift-runtime.py, or m8shift-context.py" ;;
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
    --no-runtime)
      WITH_RUNTIME=0
      shift
      ;;
    --no-context)
      WITH_CONTEXT=0
      shift
      ;;
    --with-rtk)
      RTK_CHOICE=yes
      shift
      ;;
    --no-rtk)
      RTK_CHOICE=no
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
      VERIFY_EXPLICIT=1
      shift
      ;;
    --no-verify)
      VERIFY_EXPLICIT=0
      shift
      ;;
    --checksums)
      need_value "$1" "${2:-}"
      CHECKSUMS_URL="$2"
      VERIFY_EXPLICIT=1
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

# Verification is ON by default (mirrors install.ps1). --no-verify or a falsey
# M8SHIFT_INSTALL_VERIFY ("0/false/no") disables it; --verify / --checksums force it on.
if [ "$VERIFY_EXPLICIT" = "0" ]; then
  VERIFY_DOWNLOADS=0
elif [ "$VERIFY_EXPLICIT" = "1" ]; then
  VERIFY_DOWNLOADS=1
elif [ -n "${M8SHIFT_INSTALL_VERIFY:-}" ]; then
  case "$M8SHIFT_INSTALL_VERIFY" in
    0|false|False|FALSE|no|No|NO) VERIFY_DOWNLOADS=0 ;;
    *) VERIFY_DOWNLOADS=1 ;;
  esac
else
  VERIFY_DOWNLOADS=1
fi

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

# Manual --sha256 pins are self-sufficient: when they cover every file we will download,
# skip the manifest so out-of-band pinning works even against a mirror with no manifest.
pins_cover_downloads() {
  printf '%s' "$EXPECTED_SHA256S" | grep -q ' m8shift.py$' || return 1
  if [ "$WITH_WORKTREE" -eq 1 ]; then
    printf '%s' "$EXPECTED_SHA256S" | grep -q ' m8shift-worktree.py$' || return 1
  fi
  if [ "$WITH_RUNTIME" -eq 1 ]; then
    printf '%s' "$EXPECTED_SHA256S" | grep -q ' m8shift-runtime.py$' || return 1
  fi
  if [ "$WITH_CONTEXT" -eq 1 ]; then
    printf '%s' "$EXPECTED_SHA256S" | grep -q ' m8shift-context.py$' || return 1
  fi
  return 0
}

rtk_disable_telemetry() {
  if command -v rtk >/dev/null 2>&1; then
    if rtk telemetry disable >/dev/null 2>&1; then
      printf '✓ rtk telemetry disabled\n'
    else
      printf 'warning: could not disable rtk telemetry; run `rtk telemetry disable` manually\n' >&2
    fi
  fi
}

install_rtk_with_brew() {
  if command -v rtk >/dev/null 2>&1; then
    rtk_disable_telemetry
    return 0
  fi
  command -v brew >/dev/null 2>&1 || die "Homebrew is required for --with-rtk; install RTK manually or rerun with --no-rtk"
  printf '→ installing optional RTK via Homebrew\n'
  brew install rtk
  command -v rtk >/dev/null 2>&1 || die "brew completed but rtk was not found on PATH"
  rtk_disable_telemetry
}

offer_rtk() {
  case "$RTK_CHOICE" in
    yes|YES|1|true|True|TRUE)
      install_rtk_with_brew
      ;;
    no|NO|0|false|False|FALSE)
      rtk_disable_telemetry
      ;;
    ask|"")
      if command -v rtk >/dev/null 2>&1; then
        rtk_disable_telemetry
      elif [ -t 0 ]; then
        printf 'Install optional RTK for token-saving shell output filtering via Homebrew? [y/N] '
        IFS= read -r answer || answer=""
        case "$answer" in
          y|Y|yes|YES) install_rtk_with_brew ;;
          *) printf '→ skipping optional RTK install\n' ;;
        esac
      else
        printf '→ optional RTK not installed; rerun with --with-rtk to install via Homebrew\n'
      fi
      ;;
    *)
      die "invalid RTK choice: $RTK_CHOICE (expected ask, yes, or no)"
      ;;
  esac
}

if [ "$VERIFY_DOWNLOADS" = "1" ] && ! pins_cover_downloads; then
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
if [ "$WITH_RUNTIME" -eq 1 ]; then
  download_file "m8shift-runtime.py"
fi
if [ "$WITH_CONTEXT" -eq 1 ]; then
  download_file "m8shift-context.py"
fi

offer_rtk

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
