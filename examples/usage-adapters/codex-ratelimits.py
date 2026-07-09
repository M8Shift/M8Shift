#!/usr/bin/env python3
"""Example OPERATOR usage adapter — Codex CLI app-server rate limits (RFC 040).

This is a *reference example the operator adopts*, NOT part of the M8Shift core or
companions. M8Shift's charter is no-network; this script is the runtime boundary.
It runs ONLY if you enable the disabled `codex-ratelimits` adapter in
`.m8shift/usage/adapters.json`. M8Shift then runs it as a plain argv and reads its
stdout — M8Shift never talks to provider APIs itself.

Verified local protocol shape:
  - command: `codex app-server --stdio`
  - transport: newline-delimited JSON-RPC on stdio
  - required first call: `initialize`
  - rate-limit call: `account/rateLimits/read`
  - honesty note: this read uses the app-server experimental API surface, so the
    shape may drift; fail-open behavior is part of the contract.

Honesty / safety:
  - provider `usedPercent` is emitted as `used_ratio`, never as token counts;
  - only the known 5-hour (300 min) and weekly (10080 min) windows are mapped;
  - it is fail-open: ANY error prints an empty official fixture so M8Shift records
    "unknown" and never pauses on a bad read;
  - it prints ONLY aggregate ratio + reset instant — no account identity, credits,
    plan type, raw response body, stderr, or provider bucket names.

This example is intentionally NOT in checksums.sha256: it is reference material to
copy and adapt, not a verified shipped component. Review it before enabling it.
"""

import contextlib
import datetime as dt
import json
import math
import subprocess
import sys

APP_SERVER_CMD = ["codex", "app-server", "--stdio"]
APP_SERVER_TIMEOUT_S = 10
WINDOW_KIND_BY_DURATION_MIN = {300: "session_5h", 10080: "weekly"}


def _now_iso(now=None):
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_epoch_seconds(value):
    """Convert a Unix-seconds timestamp to UTC ISO. Invalid values return None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return dt.datetime.fromtimestamp(numeric, tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _empty_fixture(now_iso):
    """Fail-open: no windows -> decision_ratio null -> unknown, never a pause."""
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": "codex",
        "provenance": "official",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": [],
    }


def _result_from_jsonrpc(payload):
    if not isinstance(payload, dict) or "error" in payload:
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def _select_rate_limit_snapshot(result):
    """Prefer the explicit `codex` bucket, otherwise the top-level snapshot."""
    if not isinstance(result, dict):
        return None
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and isinstance(by_id.get("codex"), dict):
        return by_id["codex"]
    top = result.get("rateLimits")
    return top if isinstance(top, dict) else None


def _window_kind(raw_window):
    duration = raw_window.get("windowDurationMins")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    try:
        duration_i = int(duration)
    except (TypeError, ValueError, OverflowError):
        return None
    return WINDOW_KIND_BY_DURATION_MIN.get(duration_i)


def _window_to_fixture(raw_window):
    if not isinstance(raw_window, dict):
        return None
    kind = _window_kind(raw_window)
    used = raw_window.get("usedPercent")
    if kind is None or isinstance(used, bool) or not isinstance(used, (int, float)):
        return None
    try:
        percent = float(used)
        if not math.isfinite(percent):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    reset_raw = raw_window.get("resetsAt")
    resets_at = _iso_epoch_seconds(reset_raw)
    if reset_raw is not None and resets_at is None:
        return None
    used_ratio = max(0.0, min(100.0, percent)) / 100.0
    return {"kind": kind, "used_ratio": round(used_ratio, 4), "resets_at": resets_at}


def build_fixture(payload, now_iso):
    """Pure mapping: JSON-RPC response -> m8shift.usage.fixture.v1.

    Unknown shapes and unknown windows are skipped. The function never raises and
    never copies raw provider fields into the fixture.
    """
    try:
        result = _result_from_jsonrpc(payload)
        snapshot = _select_rate_limit_snapshot(result)
        windows = []
        if isinstance(snapshot, dict):
            for field in ("primary", "secondary"):
                win = _window_to_fixture(snapshot.get(field))
                if win is not None:
                    windows.append(win)
        fixture = _empty_fixture(now_iso)
        fixture["windows"] = windows
        return fixture
    except Exception:
        return _empty_fixture(now_iso)


def _call_app_server(command=None, popen=subprocess.Popen, timeout_s=APP_SERVER_TIMEOUT_S):
    """Call the local Codex app-server. Any failure returns None."""
    command = list(APP_SERVER_CMD if command is None else command)
    initialize = {
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "m8shift-codex-ratelimits", "version": "0"},
            "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
        },
    }
    read_limits = {"id": 2, "method": "account/rateLimits/read", "params": None}
    stdin = json.dumps(initialize, separators=(",", ":")) + "\n" \
        + json.dumps(read_limits, separators=(",", ":")) + "\n"
    proc = None
    def kill_reap():
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.communicate(timeout=1)
    try:
        proc = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        stdout, _stderr = proc.communicate(input=stdin, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        kill_reap()
        return None
    except Exception:
        kill_reap()
        return None
    for line in (stdout or "").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("id") == 2:
            return payload
    return None


def main(out=None, now=None, read_limits=None):
    out = sys.stdout if out is None else out
    now_iso = _now_iso(now)
    try:
        payload = read_limits() if read_limits is not None else _call_app_server()
        fixture = build_fixture(payload, now_iso) if payload is not None else _empty_fixture(now_iso)
    except Exception:
        fixture = _empty_fixture(now_iso)
    with contextlib.suppress(BrokenPipeError, OSError, ValueError):
        json.dump(fixture, out)
        out.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
