#!/usr/bin/env python3
"""Example OPERATOR usage adapter — Claude Code remaining-quota (RFC 040 Phase 3).

This is a *reference example the operator adopts*, NOT part of the M8Shift core or
companions. M8Shift's charter is no-network; this script is the network actor. It
runs ONLY if you point a disabled `claude-quota` adapter at it and set enabled:true
(`m8shift-runtime.py usage adapters`), and M8Shift then runs it as a plain argv and
reads its stdout — M8Shift never opens the socket itself.

What it does:
  1. reads the Claude Code OAuth access token from ~/.claude/.credentials.json
     (override the path with M8SHIFT_CLAUDE_CREDENTIALS);
  2. GETs the client's own usage endpoint (api.anthropic.com/api/oauth/usage),
     which reports a REMAINING PERCENT per window (a ratio, never a token count);
  3. prints one m8shift.usage.fixture.v1 object mapping each window to `used_ratio`
     (= 1 - remainingPercent/100) + `resets_at`, provenance "official".

Honesty / safety:
  - a percent is a ratio; it is emitted as `used_ratio`, never as `used`/`limit`
    tokens (the Slice-1 normalizer derives decision_ratio from used_ratio directly);
  - it is fail-open: ANY error (missing credential, network failure, unexpected
    shape) prints an empty official fixture so M8Shift records "unknown" and never
    pauses on a bad read;
  - it prints ONLY the aggregate ratio + reset instant — no token content, no
    account identity, no raw token. The credential is read locally and used only
    for the Authorization header; it is never printed.

This example is intentionally NOT in checksums.sha256: it is reference material to
copy and adapt, not a verified shipped component. Review it before enabling it.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS = os.environ.get(
    "M8SHIFT_CLAUDE_CREDENTIALS",
    os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json"))
# endpoint window name -> M8Shift normalized window kind
WINDOW_KINDS = {"five_hour": "session_5h", "session": "session_5h",
                "seven_day": "weekly", "week": "weekly", "weekly": "weekly"}


def _iso(value):
    """Pass through a UTC ISO string, or convert an epoch-seconds number to one."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    return None


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
        used_ratio = 1.0 - max(0.0, min(100.0, float(remaining))) / 100.0
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


def _read_token(path):
    with open(path, encoding="utf-8") as fh:
        creds = json.load(fh)
    # Claude Code stores the OAuth material under a provider key; accept a few shapes.
    for holder in (creds, creds.get("claudeAiOauth"), creds.get("oauth")):
        if isinstance(holder, dict):
            token = holder.get("accessToken") or holder.get("access_token")
            if isinstance(token, str) and token:
                return token
    raise ValueError("no access token in credentials")


def _fetch(token):
    req = urllib.request.Request(
        USAGE_URL, headers={"Authorization": f"Bearer {token}",
                            "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=10) as resp:   # noqa: S310 (https literal)
        return json.loads(resp.read().decode("utf-8"))


def main():
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        payload = _fetch(_read_token(CREDENTIALS))
        fixture = build_fixture(payload, now_iso)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        fixture = _empty_fixture(now_iso)               # fail-open, never raise
    json.dump(fixture, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
