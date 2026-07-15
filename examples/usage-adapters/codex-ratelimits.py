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
import queue
import subprocess
import threading
import time
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


def _window_to_fixture(raw_window, model=None):
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
    out = {"kind": kind, "used_ratio": round(used_ratio, 4), "resets_at": resets_at}
    if isinstance(model, str) and model:
        out["model"] = model
    return out


def build_fixture(payload, now_iso):
    """Pure mapping: JSON-RPC response -> m8shift.usage.fixture.v1.

    Unknown shapes and unknown windows are skipped. The function never raises and
    never copies raw provider fields into the fixture.
    """
    try:
        result = _result_from_jsonrpc(payload)
        windows = []
        snapshot = _select_rate_limit_snapshot(result)
        if isinstance(snapshot, dict):
            for field in ("primary", "secondary"):
                win = _window_to_fixture(snapshot.get(field))
                if win is not None:
                    windows.append(win)
        # Preserve model-specific buckets too.  A provider can report the
        # aggregate 5h window as absent while one model is at its limit; dropping
        # these buckets made dashboards say "5h unavailable" at exhaustion.
        by_id = result.get("rateLimitsByLimitId") if isinstance(result, dict) else None
        if isinstance(by_id, dict):
            for model, bucket in by_id.items():
                if model == "codex" or not isinstance(model, str) or not isinstance(bucket, dict):
                    continue
                for field in ("primary", "secondary"):
                    win = _window_to_fixture(bucket.get(field), model=model)
                    # Model buckets are actionable here only at cooldown.  Healthy
                    # model rows would duplicate the aggregate 5h/weekly display.
                    if win is not None and win["used_ratio"] == 1.0:
                        windows.append(win)
        fixture = _empty_fixture(now_iso)
        fixture["windows"] = windows
        return fixture
    except Exception:
        return _empty_fixture(now_iso)


def _call_app_server(command=None, popen=subprocess.Popen, timeout_s=APP_SERVER_TIMEOUT_S):
    """Call the local Codex app-server. Any failure returns None.

    LIVE finding (2026-07-10, codex-cli 0.144.1): the app-server DROPS pending
    requests when stdin reaches EOF, so communicate()-style write-then-close
    loses the id=2 response and the server never exits on its own (timeout ->
    None). stdin therefore stays OPEN while stdout is read line-by-line until
    the id=2 response or the deadline; the server is then terminated.

    Bounded even against a SILENT LIVE server (#105 review round 1): a blocking
    readline would never return to a deadline check, so the reads happen on a
    DAEMON reader thread feeding a queue, and the main thread waits on the queue
    with the remaining deadline (portable — no select on Windows pipes). On
    timeout the function returns None and the finally kill closes the pipes,
    unblocking the reader; being a daemon thread it can never hold the process
    open. Total return time is bounded by timeout_s plus a small cleanup
    allowance (the 1s reap)."""
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
    proc = None
    reader = None
    try:
        proc = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        proc.stdin.write(json.dumps(initialize, separators=(",", ":")) + "\n")
        proc.stdin.write(json.dumps(read_limits, separators=(",", ":")) + "\n")
        proc.stdin.flush()
        lines = queue.Queue()

        def _pump(stdout=proc.stdout):
            try:
                for line in iter(stdout.readline, ""):
                    lines.put(line)
            except Exception:
                pass                                     # reader error → sentinel below
            finally:
                lines.put(None)                          # EOF/error sentinel

        reader = threading.Thread(target=_pump, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_s
        result = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break                                    # deadline: silent live server bounded
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                break                                    # deadline while blocked on the queue
            if line is None:
                break                                    # server exited / reader error (EOF)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("id") == 2:
                result = payload
                break
        return result
    except Exception:
        return None
    finally:
        # Cleanup order that never has two readers on stdout at once (#105 review round 2):
        # ONLY the _pump thread ever reads stdout. kill() closes the child's stdout write-end →
        # the reader hits EOF and exits; we JOIN it (bounded) BEFORE reaping, and reap with
        # wait() — which does NOT read stdout — so nothing races the reader. No communicate()
        # (which would read stdout concurrently). Streams are closed only after the reader joins.
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()                              # child dies → its stdout EOFs the reader
            if reader is not None:
                reader.join(timeout=2)                   # bounded; reader exits on the EOF above
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)                     # reap the child WITHOUT reading stdout
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                with contextlib.suppress(Exception):
                    if stream is not None:
                        stream.close()


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
    if len(sys.argv) > 1:
        if sys.argv[1:] in (["-h"], ["--help"]):
            print("usage: codex-ratelimits.py\n\n"
                  "Read Codex rate limits and emit a normalized JSON snapshot.\n\n"
                  "example:\n  codex-ratelimits.py")
            raise SystemExit(0)
        print("codex-ratelimits.py: error: no arguments are accepted\n"
              "try: codex-ratelimits.py --help", file=sys.stderr)
        raise SystemExit(2)
    sys.exit(main())
