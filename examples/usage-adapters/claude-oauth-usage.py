#!/usr/bin/env python3
"""Example OPERATOR usage adapter — Claude Code OAuth quota (RFC 040 Phase 4).

This is a *reference example the operator adopts*, NOT part of the M8Shift core or
companions. M8Shift's charter is no-network; this script is the network actor. It
runs ONLY if you point the disabled `claude-quota-keychain` adapter at it and set
`enabled:true` (`m8shift-runtime.py usage adapters`). M8Shift then runs it as a
plain argv and reads its stdout — M8Shift never opens the socket itself.

Default credential source on macOS:
  - macOS Keychain generic-password service: `Claude Code-credentials`
  - command: `security find-generic-password -s "Claude Code-credentials" -w`
  - token field: `claudeAiOauth.accessToken`
  - expiry field: `claudeAiOauth.expiresAt` (epoch milliseconds)

Non-macOS / test override:
  - no plaintext credential file is used by default;
  - an operator may explicitly set `M8SHIFT_CLAUDE_CREDENTIALS` to a local JSON
    file for a controlled environment, but this is never the default.

Honesty / safety:
  - a percent is a ratio; it is emitted as `used_ratio`, never as `used`/`limit`
    tokens;
  - it is fail-open: ANY error (missing/expired credential, Keychain ACL prompt
    timeout/denial, network failure, unexpected shape) prints an empty official
    fixture so M8Shift records "unknown" and never pauses on a bad read;
  - it prints ONLY aggregate ratio + reset instant — no access token, refresh
    token, raw credential JSON, account identity, or endpoint response body.

This example is intentionally NOT in checksums.sha256: it is reference material to
copy and adapt, not a verified shipped component. Review it before enabling it.
"""

import datetime as dt
import json
import math
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
KEYCHAIN_TIMEOUT_S = 5

# endpoint window name -> M8Shift normalized window kind
WINDOW_KINDS = {"five_hour": "session_5h", "session": "session_5h",
                "seven_day": "weekly", "week": "weekly", "weekly": "weekly"}


def _iso(value):
    """Pass through a UTC ISO string, or convert an epoch-seconds number to one.
    Never raises: a non-finite or out-of-range numeric timestamp returns None."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value):
        try:
            return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _now_ms():
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def build_fixture(payload, now_iso):
    """Pure mapping (unit-testable, no network): an OAuth usage payload ->
    m8shift.usage.fixture.v1 with per-window `used_ratio`. Unknown/invalid windows
    are skipped; a percent is NEVER written into a token field."""
    windows = []
    raw_windows = payload.get("windows") if isinstance(payload, dict) else None
    for win in raw_windows or []:
        if not isinstance(win, dict):
            continue
        kind = WINDOW_KINDS.get(win.get("kind") or win.get("window"))
        remaining = win.get("remainingPercent")
        if remaining is None:
            remaining = win.get("remaining_percent")
        if kind is None or isinstance(remaining, bool) \
                or not isinstance(remaining, (int, float)):
            continue
        percent = float(remaining)
        if not math.isfinite(percent):        # NaN/Inf (json accepts them) → skip, stay fail-open
            continue
        used_ratio = 1.0 - max(0.0, min(100.0, percent)) / 100.0
        windows.append({"kind": kind, "used_ratio": round(used_ratio, 4),
                        "resets_at": _iso(win.get("resetsAt") or win.get("resets_at"))})
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": "claude",
        "provenance": "official",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": windows,
    }


def _empty_fixture(now_iso):
    """Fail-open: an official fixture with no windows -> decision_ratio null ->
    M8Shift records 'unknown' and never pauses."""
    return {"schema": "m8shift.usage.fixture.v1", "agent": "claude",
            "provenance": "official", "captured_at": now_iso,
            "used_tokens": None, "limit_tokens": None, "windows": []}


def _parse_credentials_blob(text, now_ms):
    """Return an access token or None. Never returns identity/refresh-token data."""
    try:
        creds = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(creds, dict):
        return None
    holder = creds.get("claudeAiOauth")
    if not isinstance(holder, dict):
        return None
    expires_at = holder.get("expiresAt")
    if isinstance(expires_at, str):
        try:
            expires_at = int(expires_at)
        except ValueError:
            return None
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)) \
            or not math.isfinite(float(expires_at)) or float(expires_at) <= now_ms:
        return None
    token = holder.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    return token


def _read_keychain_blob(run=subprocess.run, timeout_s=KEYCHAIN_TIMEOUT_S):
    argv = ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"]
    completed = run(argv, capture_output=True, text=True, timeout=timeout_s, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return completed.stdout


def _read_explicit_credentials_file(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_access_token(env=None, system=None, run=subprocess.run, now_ms=None):
    """Load only the access token, in memory. Any failure returns None."""
    env = os.environ if env is None else env
    system = platform.system() if system is None else system
    now_ms = _now_ms() if now_ms is None else now_ms
    try:
        explicit_path = env.get("M8SHIFT_CLAUDE_CREDENTIALS")
        if explicit_path:
            blob = _read_explicit_credentials_file(explicit_path)
        elif system == "Darwin":
            blob = _read_keychain_blob(run=run)
        else:
            return None
    except (OSError, subprocess.SubprocessError, TimeoutError, TypeError, ValueError,
            AttributeError):
        return None
    return _parse_credentials_blob(blob, now_ms) if blob else None


def _fetch(token):
    req = urllib.request.Request(
        USAGE_URL, headers={"Authorization": f"Bearer {token}",
                            "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=10) as resp:   # noqa: S310 (https literal)
        return json.loads(resp.read().decode("utf-8"))


def main(env=None, fetch=_fetch, token_loader=_load_access_token, out=None):
    out = sys.stdout if out is None else out
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        token = token_loader(env=env, now_ms=int(now.timestamp() * 1000))
        if not token:
            fixture = _empty_fixture(now_iso)
        else:
            fixture = build_fixture(fetch(token), now_iso)
    except (OSError, ValueError, TypeError, AttributeError, OverflowError,
            urllib.error.URLError, json.JSONDecodeError, subprocess.SubprocessError):
        fixture = _empty_fixture(now_iso)               # fail-open, never raise
    json.dump(fixture, out)
    out.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
