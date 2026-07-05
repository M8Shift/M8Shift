#!/usr/bin/env bash
# M8Shift local installer.
#
# Intended one-liner:
#   curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --agents claude,codex
#
# Supported platforms (#24): macOS (standard Terminal), Linux, WSL, and Git Bash on
# Windows. This is explicitly a BASH script (arrays, pipefail) — pipe it to `bash`,
# not `sh`; every listed platform ships or bundles bash. Native Windows without
# Git Bash: use install.ps1 (kept in lockstep for the core components).
#
# This script installs M8Shift into the current project directory by downloading the
# standalone CLI files, then runs `m8shift.py init`. Core install requires only
# Python 3.8+, one downloader (curl/wget/Python urllib), write permission in the
# target directory, and SHA-256 support. It does not use sudo, does not modify PATH,
# does not create a daemon, and needs no package manager. Optional helpers (git for
# worktree features, RTK, Headroom) are advisory: absent or unsupported ones degrade
# with a clear message and never block the core install.

set -euo pipefail

INSTALLER_VERSION="1.2.0"
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
HEADROOM_CHOICE="${M8SHIFT_INSTALL_HEADROOM:-no}"  # yes|no (experimental, explicit opt-in)
DRY_RUN=0
RTK_VERSION="${M8SHIFT_INSTALL_RTK_VERSION:-v0.43.0}"
RTK_BASE_URL="${M8SHIFT_INSTALL_RTK_BASE_URL:-}"
RTK_SOURCE_BUILD=0
HEADROOM_PACKAGE="headroom-ai==0.28.0"
HEADROOM_RUNTIME_PACKAGES="onnxruntime==1.27.0 transformers==5.12.1"
HEADROOM_KOMPRESS_MODEL="chopratejas/kompress-v2-base"
VERIFY_EXPLICIT=""   # --verify sets 1, --no-verify sets 0; otherwise env/default decide
VERIFY_DOWNLOADS=1   # resolved after arg parsing (verification is ON by default)
CHECKSUMS_URL="${M8SHIFT_INSTALL_CHECKSUMS_URL:-}"
CHECKSUMS_TEXT=""
EXPECTED_SHA256S=""
PYTHON_BIN="${PYTHON:-python3}"
HELPER_FAILURES=""   # opt-in helper failures never block the core install (#24)

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
  --with-rtk          With consent already given, install optional RTK portably if absent.
  --no-rtk            Do not prompt for or install RTK; if present on normal PATH,
                      telemetry is still disabled.
  --rtk-version VER   RTK release tag for portable install (default: v0.43.0).
  --allow-source-build
                      Allow RTK Cargo/Rust source build fallback when no
                      same-tag-checksummed prebuilt release asset matches this host.
  --with-headroom     EXPERIMENTAL: install pinned headroom-ai + Kompress model into a local venv.
  --no-headroom       Do not install optional headroom-ai (default).
  --dry-run           Print the install plan and prerequisites; do not download or write files.
  --ref REF            Git ref used for downloads when --base-url is not set (default: main).
  --base-url URL      Download base URL (default: GitHub raw for --ref).
  --verify            Force checksum verification (already the default).
  --no-verify         Skip checksum verification.
  --checksums URL     Use a custom checksums URL or local path (implies verification).
  --sha256 FILE:HEX   Pin one expected SHA-256 manually; repeatable.
  -h, --help          Show this help.
  --version           Show installer version.

The installer is local-only: no sudo, no PATH mutation, no background service, no
package manager required. It is a bash script (macOS Terminal, Linux, WSL, Git Bash
on Windows); native Windows without Git Bash uses install.ps1 instead.
Verification is enabled by default; --no-verify disables it.
Optional helpers are advisory: capabilities are detected before any helper setup and
reported as available / unavailable / skipped / installed (or "ask — will prompt"
when the interactive RTK default applies); an absent or unsupported helper degrades
with a clear message and never blocks the core install. An opted-in helper
(--with-rtk / --with-headroom) that fails prints a prominent warning and the core
install continues to init; the overall exit stays 0 when the core install succeeded.
Security note: verification checks integrity against the selected ref's manifest;
for out-of-band trust, pin a reviewed digest with --sha256 or use a signed tag.
RTK is optional. When installed or already present on normal PATH, this installer runs
`rtk telemetry disable` to keep telemetry off by default. With --with-rtk,
M8Shift downloads the matching RTK release asset, verifies it against the
same release tag's checksums.txt (GitHub/TLS trust model), installs it under
.m8shift/bin, records local provenance, and identity-pins the adapter manifest.
Cargo/Rust source builds are disabled unless --allow-source-build is explicit.
Headroom is experimental, pinned to headroom-ai==0.28.0 + onnxruntime==1.27.0
+ transformers==5.12.1, downloads the Kompress model at install time, and
remains explicit opt-in.
EOF
  printf '\n'
  print_prerequisites
}

die() {
  printf 'm8shift install: %s\n' "$*" >&2
  exit 1
}

helper_failed() {
  # #24 ruling: optional helpers NEVER block the core install. Record the
  # failure, warn prominently, and let the run continue toward init; the
  # overall exit stays 0 when the core install itself succeeds.
  local helper="$1"
  local hint="$2"
  HELPER_FAILURES="${HELPER_FAILURES:+$HELPER_FAILURES }$helper"
  printf '✗ optional %s install failed — continuing core install; %s\n' "$helper" "$hint" >&2
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

path_under() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import os
import sys

path, parent = map(os.path.realpath, sys.argv[1:3])
try:
    ok = os.path.commonpath([path, parent]) == parent
except ValueError:
    ok = False
sys.exit(0 if ok else 1)
PY
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
    m8shift.py|m8shift-worktree.py|m8shift-runtime.py|m8shift-context.py|m8shift-headroom.py) ;;
    *) die "--sha256 file must be m8shift.py, m8shift-worktree.py, m8shift-runtime.py, m8shift-context.py, or m8shift-headroom.py" ;;
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

validate_rtk_version() {
  case "$RTK_VERSION" in
    ""|-*|*..*|*\\*|*" "*|*"	"*|*"
"*)
      die "unsafe --rtk-version: $RTK_VERSION"
      ;;
  esac
}

rtk_host_asset() {
  local os arch
  os="$(uname -s 2>/dev/null || printf unknown)"
  arch="$(uname -m 2>/dev/null || printf unknown)"
  case "$os" in
    Darwin)
      case "$arch" in
        arm64|aarch64) printf 'rtk-aarch64-apple-darwin.tar.gz\n' ;;
        x86_64|amd64) printf 'rtk-x86_64-apple-darwin.tar.gz\n' ;;
        *) return 1 ;;
      esac
      ;;
    Linux)
      case "$arch" in
        arm64|aarch64) printf 'rtk-aarch64-unknown-linux-gnu.tar.gz\n' ;;
        x86_64|amd64) printf 'rtk-x86_64-unknown-linux-musl.tar.gz\n' ;;
        *) return 1 ;;
      esac
      ;;
    MINGW*|MSYS*|CYGWIN*)
      case "$arch" in
        x86_64|amd64) printf 'rtk-x86_64-pc-windows-msvc.zip\n' ;;
        *) return 1 ;;
      esac
      ;;
    *)
      return 1
      ;;
  esac
}

print_prerequisites() {
  cat <<EOF
Prerequisites:
  core install: Python 3.8+ (stdlib only), write permission in the target directory,
    one downloader (curl, wget, or Python urllib), and SHA-256 support (sha256sum,
    shasum, or Python hashlib) for the default verification.
  shell: bash — macOS standard Terminal, Linux, WSL, or Git Bash on Windows; native
    Windows without Git Bash uses install.ps1 instead.
  never needed: sudo, PATH changes, daemons/services, or a package manager (package
    managers may provide the prerequisites, e.g. apt/dnf install python3, but are
    never the only path).
  optional git: only worktree features (m8shift-worktree.py) and anchor
    case-renaming use Git; the core relay installs and runs without it.
  optional RTK (--with-rtk): tar for macOS/Linux .tar.gz assets; unzip or Python zipfile for Git Bash/Windows .zip assets; Cargo/Rust only with --allow-source-build.
  optional Headroom (--with-headroom): Python venv + pip; pinned headroom-ai==0.28.0 + onnxruntime==1.27.0 + transformers==5.12.1, install-time Kompress model download/cache; macOS requires an arm64-native Python because no x86_64 wheel is available.
EOF
}

print_capabilities() {
  # #24: detect optional-helper capabilities BEFORE any helper setup and report one
  # clear line each (available / unavailable / skipped / installed). Advisory only:
  # nothing here ever blocks or mutates the core install.
  printf 'Optional helper capabilities:\n'
  if command -v git >/dev/null 2>&1; then
    printf '  git: available — worktree features (m8shift-worktree.py) can use it\n'
  else
    printf '  git: unavailable — worktree features (m8shift-worktree.py) need Git; the core install is unaffected\n'
  fi
  local existing_rtk asset
  existing_rtk="$(command -v rtk 2>/dev/null || true)"
  case "$RTK_CHOICE" in
    yes|YES|1|true|True|TRUE)
      if [ -n "$existing_rtk" ]; then
        printf '  rtk: installed — found at %s (telemetry will be disabled)\n' "$existing_rtk"
      elif asset="$(rtk_host_asset)"; then
        printf '  rtk: available — prebuilt release asset %s matches this host\n' "$asset"
      else
        printf '  rtk: unavailable — no prebuilt release asset for this host; Cargo/Rust source build requires --allow-source-build\n'
      fi
      ;;
    *)
      if [ -n "$existing_rtk" ]; then
        printf '  rtk: installed — found at %s\n' "$existing_rtk"
      elif { [ "$RTK_CHOICE" = "ask" ] || [ -z "$RTK_CHOICE" ]; } && [ -t 0 ]; then
        # honest ask-mode report: an interactive run WILL prompt later (offer_rtk)
        printf '  rtk: ask — will prompt for the optional install (--with-rtk / --no-rtk decide up front)\n'
      else
        printf '  rtk: skipped — explicit opt-in (--with-rtk)\n'
      fi
      ;;
  esac
  case "$HEADROOM_CHOICE" in
    yes|YES|1|true|True|TRUE)
      if [ "${PYTHON_OK:-1}" -eq 1 ] && "$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1; then
        printf '  headroom: available — Python venv module present (experimental, pinned, fail-closed)\n'
      else
        printf '  headroom: unavailable — Python venv module missing (install python3-venv/ensurepip); --with-headroom fails closed\n'
      fi
      ;;
    *)
      printf '  headroom: skipped — explicit opt-in (--with-headroom)\n'
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
    --rtk-version)
      need_value "$1" "${2:-}"
      RTK_VERSION="$2"
      shift 2
      ;;
    --allow-source-build)
      RTK_SOURCE_BUILD=1
      shift
      ;;
    --with-headroom)
      HEADROOM_CHOICE=yes
      shift
      ;;
    --no-headroom)
      HEADROOM_CHOICE=no
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

# Python status is COMPUTED here but only fatal outside --dry-run: the plan-only
# path stays lockstep with install.ps1 -DryRun and prints an honest status line
# instead of dying, so a python-less review/CI host can still read the plan.
PYTHON_OK=1
PYTHON_STATUS=""
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_OK=0
  PYTHON_STATUS="MISSING (required)"
elif ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
  PYTHON_OK=0
  PYTHON_STATUS="TOO OLD — 3.8+ required (reports: $("$PYTHON_BIN" --version 2>&1 || printf unknown))"
else
  PYTHON_STATUS="ok ($("$PYTHON_BIN" --version 2>&1 || printf unknown))"
fi
if [ "$DRY_RUN" -ne 1 ] && [ "$PYTHON_OK" -ne 1 ]; then
  case "$PYTHON_STATUS" in
    MISSING*) die "$PYTHON_BIN is required" ;;
    *) die "Python 3.8+ is required ($PYTHON_BIN reports: $("$PYTHON_BIN" --version 2>&1 || printf unknown))" ;;
  esac
fi
validate_ref
validate_rtk_version

if [ -z "$BASE_URL" ]; then
  BASE_URL="https://raw.githubusercontent.com/M8Shift/M8Shift/$REF"
fi
BASE_URL="${BASE_URL%/}"
if [ -z "$RTK_BASE_URL" ]; then
  RTK_BASE_URL="https://github.com/rtk-ai/rtk/releases/download/$RTK_VERSION"
fi
RTK_BASE_URL="${RTK_BASE_URL%/}"
if [ -z "$CHECKSUMS_URL" ]; then
  CHECKSUMS_URL="$BASE_URL/checksums.sha256"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  print_prerequisites
  printf '\n'
  print_capabilities
  cat <<EOF

Dry run plan:
  python: $PYTHON_BIN — $PYTHON_STATUS
  target: $TARGET_DIR
  ref: $REF
  base URL: $BASE_URL
  checksums: $CHECKSUMS_URL
  agents: $AGENTS
  download worktree/runtime/context: $WITH_WORKTREE/$WITH_RUNTIME/$WITH_CONTEXT
  run init: $RUN_INIT
  RTK: $RTK_CHOICE (release $RTK_VERSION, $RTK_BASE_URL)
  RTK source build fallback: $RTK_SOURCE_BUILD
  Headroom: $HEADROOM_CHOICE (experimental)
  Headroom package: $HEADROOM_PACKAGE
  Headroom runtime: $HEADROOM_RUNTIME_PACKAGES
  Headroom model: $HEADROOM_KOMPRESS_MODEL, downloaded/cached at install time; runtime stays offline

No files were downloaded or written.
EOF
  exit 0
fi

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
print_prerequisites
print_capabilities

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
  if [ "$HEADROOM_CHOICE" = "yes" ] || [ "$HEADROOM_CHOICE" = "YES" ] || [ "$HEADROOM_CHOICE" = "1" ] || [ "$HEADROOM_CHOICE" = "true" ] || [ "$HEADROOM_CHOICE" = "True" ] || [ "$HEADROOM_CHOICE" = "TRUE" ]; then
    printf '%s' "$EXPECTED_SHA256S" | grep -q ' m8shift-headroom.py$' || return 1
  fi
  return 0
}

rtk_local_bin_dir() {
  printf '%s/.m8shift/bin\n' "$TARGET_DIR"
}

rtk_local_command() {
  local bin
  bin="$(rtk_local_bin_dir)"
  if [ -x "$bin/rtk" ]; then
    printf '%s/rtk\n' "$bin"
  elif [ -x "$bin/rtk.exe" ]; then
    printf '%s/rtk.exe\n' "$bin"
  fi
}

rtk_command() {
  local allow_project_local="${1:-0}"
  local existing
  existing="$(command -v rtk 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    if [ "$allow_project_local" != "1" ] && path_under "$existing" "$(rtk_local_bin_dir)"; then
      return 1
    fi
    printf '%s\n' "$existing"
    return 0
  fi
  if [ "$allow_project_local" = "1" ]; then
    rtk_local_command
  fi
}

pin_context_adapters() {
  [ "$WITH_CONTEXT" -eq 1 ] || return 0
  [ -f "$TARGET_DIR/m8shift-context.py" ] || return 0
  local extra_path="${1:-}"
  local allow_project_local="${2:-0}"
  local local_bin
  local_bin="$(rtk_local_bin_dir)"
  local path_prefix="$local_bin"
  if [ -n "$extra_path" ]; then
    path_prefix="$extra_path:$path_prefix"
  fi
  local args="adapters init --force"
  if [ "$allow_project_local" = "1" ]; then
    args="$args --allow-project-local-adapters"
  fi
  if (cd "$TARGET_DIR" && PATH="$path_prefix:$PATH" "$PYTHON_BIN" ./m8shift-context.py $args >/dev/null 2>&1); then
    printf '✓ context adapter manifests identity-pinned\n'
  else
    printf 'warning: could not identity-pin context adapters; run `%s m8shift-context.py adapters init --force` manually after reviewing PATH\n' "$PYTHON_BIN" >&2
  fi
}

rtk_disable_telemetry() {
  local allow_project_local="${1:-0}"
  local cmd
  cmd="$(rtk_command "$allow_project_local" || true)"
  if [ -n "$cmd" ]; then
    if "$cmd" telemetry disable >/dev/null 2>&1; then
      printf '✓ rtk telemetry disabled\n'
    else
      printf 'warning: could not disable rtk telemetry; run `rtk telemetry disable` manually\n' >&2
    fi
  fi
}

rtk_extract_archive() {
  local asset="$1"
  local archive="$2"
  local dest_dir="$3"
  local tmp_dir="$TARGET_DIR/.rtk-extract.$$"
  rm -rf "$tmp_dir"
  mkdir -p "$tmp_dir" "$dest_dir"
  case "$asset" in
    *.tar.gz)
      command -v tar >/dev/null 2>&1 || die "tar is required to extract $asset"
      tar -xzf "$archive" -C "$tmp_dir"
      ;;
    *.zip)
      if command -v unzip >/dev/null 2>&1; then
        unzip -q "$archive" -d "$tmp_dir"
      else
        "$PYTHON_BIN" - "$archive" "$tmp_dir" <<'PY'
import sys
import zipfile

archive, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(dest)
PY
      fi
      ;;
    *)
      die "unsupported RTK asset format: $asset"
      ;;
  esac
  local found
  found="$(find "$tmp_dir" -type f \( -name rtk -o -name rtk.exe \) | head -n 1)"
  [ -n "$found" ] || die "RTK archive did not contain rtk/rtk.exe"
  case "$asset" in
    *.zip) cp "$found" "$dest_dir/rtk.exe"; chmod +x "$dest_dir/rtk.exe" ;;
    *) cp "$found" "$dest_dir/rtk"; chmod +x "$dest_dir/rtk" ;;
  esac
  rm -rf "$tmp_dir"
}

write_rtk_provenance() {
  local asset="$1"
  local asset_sha="$2"
  local cmd
  cmd="$(rtk_local_command || true)"
  [ -n "$cmd" ] || die "RTK installed but local command was not found"
  local bin_sha
  bin_sha="$(file_sha256 "$cmd")"
  "$PYTHON_BIN" - "$cmd" "$bin_sha" "$asset" "$asset_sha" "$RTK_VERSION" "$(rtk_local_bin_dir)/rtk.provenance.json" <<'PY'
import json
import os
import sys

path, sha, asset, asset_sha, version, out_path = sys.argv[1:]
payload = {
    "schema": "m8shift.installer.tool_provenance.v1",
    "program": "rtk",
    "path": os.path.realpath(path),
    "sha256": sha,
    "asset": asset,
    "asset_sha256": asset_sha,
    "version": version,
    "source": "rtk-ai/rtk GitHub release asset",
    "trust_model": "release asset verified against checksums.txt from the same GitHub release tag over TLS",
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

install_rtk_prebuilt() {
  local existing
  existing="$(rtk_command || true)"
  if [ -n "$existing" ]; then
    printf '→ using existing RTK at %s\n' "$existing"
    rtk_disable_telemetry
    pin_context_adapters
    return 0
  fi

  local asset
  asset="$(rtk_host_asset)" || return 1
  local checksums_tmp="$TARGET_DIR/.rtk-checksums.tmp.$$"
  local archive_tmp="$TARGET_DIR/.$asset.tmp.$$"
  local expected actual
  rm -f "$checksums_tmp" "$archive_tmp"
  printf '→ downloading RTK %s checksums\n' "$RTK_VERSION"
  download_to "$RTK_BASE_URL/checksums.txt" "$checksums_tmp"
  expected="$(awk -v name="$asset" '$2 == name { print $1; exit }' "$checksums_tmp")"
  [ -n "$expected" ] || die "no RTK checksum found for $asset in checksums.txt"
  printf '→ downloading optional RTK asset %s\n' "$asset"
  download_to "$RTK_BASE_URL/$asset" "$archive_tmp"
  actual="$(file_sha256 "$archive_tmp")"
  if [ "$actual" != "$expected" ]; then
    die "RTK checksum mismatch for $asset: expected $expected, got $actual"
  fi
  printf '✓ verified %s\n' "$asset"
  rtk_extract_archive "$asset" "$archive_tmp" "$(rtk_local_bin_dir)"
  write_rtk_provenance "$asset" "$actual"
  rm -f "$checksums_tmp" "$archive_tmp"
  printf '✓ RTK installed in %s\n' "$(rtk_local_bin_dir)"
  rtk_disable_telemetry 1
  pin_context_adapters "" 1
}

install_rtk_cargo_fallback() {
  [ "$RTK_SOURCE_BUILD" -eq 1 ] || return 1
  command -v cargo >/dev/null 2>&1 || return 1
  printf '→ attempting optional RTK cargo fallback from tag %s\n' "$RTK_VERSION"
  cargo install --git https://github.com/rtk-ai/rtk --tag "$RTK_VERSION" --locked rtk
}

install_rtk_portable() {
  if install_rtk_prebuilt; then
    return 0
  fi
  printf 'warning: no RTK prebuilt asset matched this OS/architecture\n' >&2
  if [ "$RTK_SOURCE_BUILD" -ne 1 ]; then
    printf 'warning: RTK source-build fallback is disabled; rerun with --allow-source-build after reviewing the Cargo/Rust trust model\n' >&2
    return 1
  fi
  printf 'warning: trying Cargo/Rust source-build fallback from reviewed tag %s\n' "$RTK_VERSION" >&2
  if install_rtk_cargo_fallback; then
    rtk_disable_telemetry
    pin_context_adapters
    return 0
  fi
  return 1
}

offer_rtk() {
  # Opt-in flows run the helper in a SUBSHELL: internal `die`s (broken mirror,
  # missing checksum, unsupported host) exit only the subshell, degrade to a
  # helper_failed warning, and the core install continues to init (#24).
  case "$RTK_CHOICE" in
    yes|YES|1|true|True|TRUE)
      ( install_rtk_portable ) \
        || helper_failed rtk "rerun with --with-rtk after fixing, or use --no-rtk to silence the offer"
      ;;
    no|NO|0|false|False|FALSE)
      rtk_disable_telemetry
      if [ -n "$(rtk_command || true)" ]; then
        pin_context_adapters
      fi
      ;;
    ask|"")
      if [ -n "$(rtk_command || true)" ]; then
        rtk_disable_telemetry
        pin_context_adapters
      elif [ -t 0 ]; then
        printf 'Install optional RTK for token-saving shell output filtering from release assets verified against same-tag checksums? [y/N] '
        IFS= read -r answer || answer=""
        case "$answer" in
          y|Y|yes|YES)
            ( install_rtk_portable ) \
              || helper_failed rtk "rerun with --with-rtk after fixing, or use --no-rtk to silence the offer"
            ;;
          *) printf '→ skipping optional RTK install\n' ;;
        esac
      else
        printf '→ optional RTK not installed; rerun with --with-rtk to install same-tag-checksummed release assets\n'
      fi
      ;;
    *)
      die "invalid RTK choice: $RTK_CHOICE (expected ask, yes, or no)"
      ;;
  esac
}

headroom_venv_dir() {
  printf '%s/.m8shift/venvs/headroom\n' "$TARGET_DIR"
}

headroom_python() {
  local venv
  venv="$(headroom_venv_dir)"
  if [ -x "$venv/bin/python" ]; then
    printf '%s/bin/python\n' "$venv"
  elif [ -x "$venv/Scripts/python.exe" ]; then
    printf '%s/Scripts/python.exe\n' "$venv"
  fi
}

headroom_bin_dir() {
  local venv
  venv="$(headroom_venv_dir)"
  if [ -d "$venv/bin" ]; then
    printf '%s/bin\n' "$venv"
  elif [ -d "$venv/Scripts" ]; then
    printf '%s/Scripts\n' "$venv"
  fi
}

headroom_fail() {
  local message="$1"
  rm -rf "$(headroom_venv_dir)"
  die "$message"
}

python_machine() {
  "$1" - <<'PY'
import platform
print(platform.machine())
PY
}

require_headroom_python_arch() {
  local os_name host_arch py_arch
  os_name="$(uname -s 2>/dev/null || printf unknown)"
  host_arch="$(uname -m 2>/dev/null || printf unknown)"
  py_arch="$(python_machine "$PYTHON_BIN")"
  if [ "$os_name" = "Darwin" ]; then
    case "$host_arch:$py_arch" in
      arm64:arm64|arm64:aarch64) return 0 ;;
      *)
        die "Headroom --with-headroom requires an arm64-native Python on macOS; x86_64/Rosetta Python would fall back to source builds because no macOS x86_64 wheel is available"
        ;;
    esac
  fi
}

headroom_preload_model() {
  local hp="$1"
  HEADROOM_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1 "$hp" - "$HEADROOM_KOMPRESS_MODEL" <<'PY'
import sys

model_id = sys.argv[1]
try:
    from headroom.transforms.kompress_compressor import ensure_background_download
except Exception as exc:
    print(f"headroom.transforms.kompress_compressor.ensure_background_download unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)

try:
    ensure_background_download(model_id=model_id)
except Exception as exc:
    print(f"Kompress model download/cache failed for {model_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)

print(f"preloaded Kompress model {model_id}")
PY
}

write_headroom_launcher() {
  local hp="$1"
  local source="$TARGET_DIR/m8shift-headroom.py"
  local launcher="$2"
  [ -f "$source" ] || headroom_fail "m8shift-headroom.py is required for --with-headroom"
  "$PYTHON_BIN" - "$hp" "$source" "$launcher" <<'PY'
import os
import shlex
import sys

hp, source, launcher = sys.argv[1:]
body = "#!/bin/sh\nexec " + shlex.quote(hp) + " " + shlex.quote(source) + ' "$@"\n'
with open(launcher, "w", encoding="utf-8") as fh:
    fh.write(body)
os.chmod(launcher, 0o755)
PY
}

write_headroom_provenance() {
  local launcher="$1"
  local out_path="$2"
  local sha
  sha="$(file_sha256 "$launcher")"
  M8SHIFT_HEADROOM_RUNTIME_PACKAGES="$HEADROOM_RUNTIME_PACKAGES" M8SHIFT_HEADROOM_MODEL="$HEADROOM_KOMPRESS_MODEL" \
    "$PYTHON_BIN" - "$launcher" "$sha" "$HEADROOM_PACKAGE" "$out_path" <<'PY'
import json
import os
import sys

path, sha, package, out_path = sys.argv[1:]
payload = {
    "schema": "m8shift.installer.tool_provenance.v1",
    "program": "m8shift-headroom",
    "path": os.path.realpath(path),
    "sha256": sha,
    "package": package,
    "runtime_packages": os.environ.get("M8SHIFT_HEADROOM_RUNTIME_PACKAGES", ""),
    "model": os.environ.get("M8SHIFT_HEADROOM_MODEL", "Kompress"),
    "model_cache": "downloaded at install time; runtime wrapper runs offline/cache-only",
    "source": "headroom-ai pinned pip package plus M8Shift wrapper launcher",
    "trust_model": "pip package pin over configured pip index plus local launcher SHA-256 identity",
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

install_headroom() {
  printf '→ optional Headroom install is EXPERIMENTAL and fail-closed\n'
  printf '  package: %s + %s\n' "$HEADROOM_PACKAGE" "$HEADROOM_RUNTIME_PACKAGES"
  require_headroom_python_arch
  local venv
  venv="$(headroom_venv_dir)"
  rm -rf "$venv"
  "$PYTHON_BIN" -m venv "$venv" >/dev/null 2>&1 || headroom_fail "could not create Headroom venv at $venv; install python3-venv/ensurepip and retry"
  local hp
  hp="$(headroom_python)"
  [ -n "$hp" ] || headroom_fail "Headroom venv was created but no Python executable was found"
  "$hp" -m pip install --upgrade pip >/dev/null 2>&1 || headroom_fail "could not upgrade pip in Headroom venv"
  "$hp" -m pip install "$HEADROOM_PACKAGE" $HEADROOM_RUNTIME_PACKAGES || headroom_fail "could not install pinned $HEADROOM_PACKAGE + $HEADROOM_RUNTIME_PACKAGES"
  printf '✓ %s + %s installed in %s\n' "$HEADROOM_PACKAGE" "$HEADROOM_RUNTIME_PACKAGES" "$venv"
  printf '→ downloading/caching Kompress model for offline runtime\n'
  headroom_preload_model "$hp" || headroom_fail "could not preload Kompress model $HEADROOM_KOMPRESS_MODEL; Headroom runtime would not be offline-ready"
  local hbin
  hbin="$(headroom_bin_dir)"
  [ -n "$hbin" ] || headroom_fail "Headroom venv bin directory not found"
  local launcher="$hbin/m8shift-headroom"
  write_headroom_launcher "$hp" "$launcher"
  write_headroom_provenance "$launcher" "$hbin/m8shift-headroom.provenance.json"
  cp "$hbin/m8shift-headroom.provenance.json" "$hbin/headroom.provenance.json"
  printf '✓ m8shift-headroom launcher installed in %s\n' "$launcher"
  printf '✓ Headroom provenance written to %s\n' "$hbin/m8shift-headroom.provenance.json"
  pin_context_adapters "$hbin" 1
}

offer_headroom() {
  case "$HEADROOM_CHOICE" in
    yes|YES|1|true|True|TRUE)
      # Subshell containment (#24): headroom_fail still cleans the venv and
      # exits fail-closed, but ONLY out of the helper — the opt-in failure
      # degrades to a warning and the core install continues to init.
      ( install_headroom ) \
        || helper_failed headroom "rerun with --with-headroom after fixing, or use --no-headroom to silence the offer"
      ;;
    no|NO|0|false|False|FALSE|"")
      ;;
    *)
      die "invalid Headroom choice: $HEADROOM_CHOICE (expected yes or no)"
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
if [ "$HEADROOM_CHOICE" = "yes" ] || [ "$HEADROOM_CHOICE" = "YES" ] || [ "$HEADROOM_CHOICE" = "1" ] || [ "$HEADROOM_CHOICE" = "true" ] || [ "$HEADROOM_CHOICE" = "True" ] || [ "$HEADROOM_CHOICE" = "TRUE" ]; then
  download_file "m8shift-headroom.py"
fi

offer_rtk
offer_headroom

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

if [ -n "$(rtk_local_command || true)" ]; then
  cat <<EOF

Optional RTK:
  RTK was installed locally under .m8shift/bin and identity-pinned for M8Shift context adapters.
  To call rtk directly from your shell without a global install:
    export PATH="$TARGET_DIR/.m8shift/bin:\$PATH"
EOF
fi

# the success blurb is filesystem-gated: a failed opt-in (venv cleaned by
# headroom_fail) must not claim an install that did not happen
if { [ "$HEADROOM_CHOICE" = "yes" ] || [ "$HEADROOM_CHOICE" = "YES" ] || [ "$HEADROOM_CHOICE" = "1" ] || [ "$HEADROOM_CHOICE" = "true" ] || [ "$HEADROOM_CHOICE" = "True" ] || [ "$HEADROOM_CHOICE" = "TRUE" ]; } \
    && [ -n "$(headroom_python || true)" ]; then
  cat <<EOF

Optional Headroom:
  headroom-ai==0.28.0 and the Kompress model were installed under .m8shift/venvs/headroom.
  Runtime use stays offline through .m8shift/venvs/headroom/bin/m8shift-headroom.
EOF
fi

if [ -n "$HELPER_FAILURES" ]; then
  printf '\nwarning: optional helper install failed for: %s\n' "$HELPER_FAILURES" >&2
  printf 'warning: the core install above succeeded (exit 0); rerun the failed helper with --with-rtk / --with-headroom after fixing, or use --no-rtk / --no-headroom to silence the offer\n' >&2
fi
