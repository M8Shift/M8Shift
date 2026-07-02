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

INSTALLER_VERSION="1.1.0"
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
  --with-rtk          With consent already given, install optional RTK portably if absent.
  --no-rtk            Do not prompt for or install RTK; if present, telemetry is still disabled.
  --rtk-version VER   RTK release tag for portable install (default: v0.43.0).
  --with-headroom     EXPERIMENTAL: install optional headroom-ai into a local venv.
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

The installer is local-only: no sudo, no PATH mutation, no background service.
Verification is enabled by default; --no-verify disables it.
Security note: verification checks integrity against the selected ref's manifest;
for out-of-band trust, pin a reviewed digest with --sha256 or use a signed tag.
RTK is optional. When installed or already present, this installer runs
`rtk telemetry disable` to keep telemetry off by default. With --with-rtk,
M8Shift downloads the matching RTK release asset, verifies it against
checksums.txt, installs it under .m8shift/bin, and identity-pins the adapter
manifest. Headroom is experimental and remains explicit opt-in.
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

validate_rtk_version() {
  case "$RTK_VERSION" in
    ""|-*|*..*|*\\*|*" "*|*"	"*|*"
"*)
      die "unsafe --rtk-version: $RTK_VERSION"
      ;;
  esac
}

print_prerequisites() {
  cat <<EOF
Prerequisites:
  required: Python 3.8+, git, and one downloader (curl, wget, or Python urllib).
  required for verification: sha256sum, shasum, or Python hashlib.
  optional RTK (--with-rtk): tar for macOS/Linux .tar.gz assets; unzip or Python zipfile for Git Bash/Windows .zip assets; cargo/Rust only as fallback.
  optional Headroom (--with-headroom): Python venv + pip; Rust/Cargo may be needed when headroom-ai builds cryptography from source.
EOF
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

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN is required"
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
  cat <<EOF

Dry run plan:
  target: $TARGET_DIR
  ref: $REF
  base URL: $BASE_URL
  checksums: $CHECKSUMS_URL
  agents: $AGENTS
  download worktree/runtime/context: $WITH_WORKTREE/$WITH_RUNTIME/$WITH_CONTEXT
  run init: $RUN_INIT
  RTK: $RTK_CHOICE (release $RTK_VERSION, $RTK_BASE_URL)
  Headroom: $HEADROOM_CHOICE (experimental)

No files were downloaded or written.
EOF
  exit 0
fi

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
print_prerequisites

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
  local existing
  existing="$(command -v rtk 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    printf '%s\n' "$existing"
    return 0
  fi
  rtk_local_command
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

pin_context_adapters() {
  [ "$WITH_CONTEXT" -eq 1 ] || return 0
  [ -f "$TARGET_DIR/m8shift-context.py" ] || return 0
  local extra_path="${1:-}"
  local local_bin
  local_bin="$(rtk_local_bin_dir)"
  local path_prefix="$local_bin"
  if [ -n "$extra_path" ]; then
    path_prefix="$extra_path:$path_prefix"
  fi
  if (cd "$TARGET_DIR" && PATH="$path_prefix:$PATH" "$PYTHON_BIN" ./m8shift-context.py adapters init --force >/dev/null 2>&1); then
    printf '✓ context adapter manifests identity-pinned\n'
  else
    printf 'warning: could not identity-pin context adapters; run `%s m8shift-context.py adapters init --force` manually after reviewing PATH\n' "$PYTHON_BIN" >&2
  fi
}

rtk_disable_telemetry() {
  local cmd
  cmd="$(rtk_command || true)"
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
  rm -f "$checksums_tmp" "$archive_tmp"
  printf '✓ RTK installed in %s\n' "$(rtk_local_bin_dir)"
  rtk_disable_telemetry
  pin_context_adapters
}

install_rtk_cargo_fallback() {
  command -v cargo >/dev/null 2>&1 || return 1
  printf '→ attempting optional RTK cargo fallback\n'
  cargo install --git https://github.com/rtk-ai/rtk --locked rtk
}

install_rtk_portable() {
  if install_rtk_prebuilt; then
    return 0
  fi
  printf 'warning: no RTK prebuilt asset matched this OS/architecture; trying cargo fallback if available\n' >&2
  if install_rtk_cargo_fallback; then
    rtk_disable_telemetry
    pin_context_adapters
    return 0
  fi
  return 1
}

offer_rtk() {
  case "$RTK_CHOICE" in
    yes|YES|1|true|True|TRUE)
      install_rtk_portable || die "optional RTK install failed; install RTK manually or rerun with --no-rtk"
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
        printf 'Install optional RTK for token-saving shell output filtering from verified release assets? [y/N] '
        IFS= read -r answer || answer=""
        case "$answer" in
          y|Y|yes|YES) install_rtk_portable || die "optional RTK install failed; install RTK manually or rerun with --no-rtk" ;;
          *) printf '→ skipping optional RTK install\n' ;;
        esac
      else
        printf '→ optional RTK not installed; rerun with --with-rtk to install verified release assets\n'
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

install_headroom() {
  printf '→ optional Headroom install is EXPERIMENTAL and never blocks base M8Shift install\n'
  printf '  package: headroom-ai; source builds may require Rust/Cargo for cryptography\n'
  local venv
  venv="$(headroom_venv_dir)"
  if ! "$PYTHON_BIN" -m venv "$venv" >/dev/null 2>&1; then
    printf 'warning: could not create Headroom venv at %s; install python3-venv/ensurepip and retry\n' "$venv" >&2
    return 0
  fi
  local hp
  hp="$(headroom_python)"
  if [ -z "$hp" ]; then
    printf 'warning: Headroom venv was created but no Python executable was found\n' >&2
    return 0
  fi
  if ! "$hp" -m pip install --upgrade pip >/dev/null 2>&1; then
    printf 'warning: could not upgrade pip in Headroom venv; continuing without Headroom\n' >&2
    return 0
  fi
  if ! "$hp" -m pip install headroom-ai; then
    printf 'warning: headroom-ai install failed; if cryptography builds from source, install Rust/Cargo and retry. Base M8Shift install continues.\n' >&2
    return 0
  fi
  printf '✓ headroom-ai installed in %s\n' "$venv"
  local hbin
  hbin="$(headroom_bin_dir)"
  if [ -n "$hbin" ]; then
    pin_context_adapters "$hbin"
  fi
}

offer_headroom() {
  case "$HEADROOM_CHOICE" in
    yes|YES|1|true|True|TRUE)
      install_headroom
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

if [ "$HEADROOM_CHOICE" = "yes" ] || [ "$HEADROOM_CHOICE" = "YES" ] || [ "$HEADROOM_CHOICE" = "1" ] || [ "$HEADROOM_CHOICE" = "true" ] || [ "$HEADROOM_CHOICE" = "True" ] || [ "$HEADROOM_CHOICE" = "TRUE" ]; then
  cat <<EOF

Optional Headroom:
  headroom-ai was requested as an experimental local venv install under .m8shift/venvs/headroom.
  If installation failed, install Python venv/pip and Rust/Cargo, then rerun with --with-headroom.
EOF
fi
