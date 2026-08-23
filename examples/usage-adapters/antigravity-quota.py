#!/usr/bin/env python3
"""Example OPERATOR usage adapter — Antigravity local quota summary (#335).

This reference adapter is disabled by default.  When an operator enables the
``agy-antigravity-quota`` registry entry, it discovers the running Antigravity
language server, reads its CSRF token in memory, and calls the provider's local
``RetrieveUserQuotaSummary`` Connect-RPC endpoint.  M8Shift itself never opens
the socket and never receives the token or raw response.

The endpoint returns two model groups, each with a weekly and a five-hour
bucket.  Selection is therefore explicit: ``--bucket-prefix`` must identify one
group by every selected bucket's ``bucketId`` prefix.  Array order and display
labels are never used as identity.  The emitted selection receipt records that
decision together with the source method and installed client version.

Safety and honesty:
  * only aggregate remaining fractions and reset instants are emitted;
  * the explicit provider ``window`` field selects weekly versus five-hour;
  * credits, account identity, descriptions, raw bodies, process argv, and the
    CSRF token are never printed or persisted;
  * discovery/RPC/schema failures emit an unavailable official fixture and
    return zero, so a failed observation can never manufacture a ratio.
"""

import argparse
import contextlib
import datetime as dt
import http.client
import json
import math
import os
import plistlib
import re
import shlex
import subprocess
import sys


AGENT = "agy"
APP_PLIST = "/Applications/Antigravity.app/Contents/Info.plist"
LANGUAGE_SERVER_MARKER = "/Antigravity.app/Contents/Resources/bin/language_server"
RPC_METHOD = (
    "exa.language_server_pb.LanguageServerService/"
    "RetrieveUserQuotaSummary"
)
RPC_PATH = "/" + RPC_METHOD
RPC_BODY = json.dumps({"metadata": {
    "ideName": "antigravity",
    "extensionName": "antigravity",
    "locale": "en",
}}, separators=(",", ":"))
WINDOW_KINDS = {"weekly": "weekly", "5h": "session_5h"}
PREFIX_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,39}\Z")
DISCOVERY_TIMEOUT_S = 3
# #363: bounded, because this adapter's whole output is capped. Beyond it the
# record stops growing; the count of surviving windows still shows what landed.
MAX_DROPPED_WINDOWS = 10
RPC_TIMEOUT_S = 3
MAX_RESPONSE_BYTES = 64 * 1024


def _now_iso(now=None):
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _client_version(path=APP_PLIST):
    try:
        with open(path, "rb") as fh:
            payload = plistlib.load(fh)
        value = payload.get("CFBundleShortVersionString")
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", value):
            return value
    except (OSError, plistlib.InvalidFileException, AttributeError, TypeError, ValueError):
        pass
    return "unknown"


def _selection(bucket_prefix, client_version):
    return {
        "strategy": "bucket_id_prefix",
        "value": bucket_prefix,
        "source_method": RPC_METHOD,
        "client_version": client_version,
    }


def _empty_fixture(now_iso, bucket_prefix, client_version, reason):
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": AGENT,
        "provenance": "official",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": [],
        "dropped": [],
        "measurement": {"state": "unavailable", "reason": reason},
        "selection": _selection(bucket_prefix, client_version),
    }


def _groups(payload):
    response = payload.get("response") if isinstance(payload, dict) else None
    groups = response.get("groups") if isinstance(response, dict) else None
    return groups if isinstance(groups, list) else []


def build_fixture(payload, now_iso, bucket_prefix, client_version="unknown"):
    """Pure mapping from the observed RPC shape to usage fixture v1.

    Group order, display names, quota fractions, and method provenance are never
    inferred.  Exactly one group must contain buckets matching ``bucket_prefix``.
    """
    if not isinstance(bucket_prefix, str) or not PREFIX_RE.fullmatch(bucket_prefix):
        return _empty_fixture(now_iso, "invalid", client_version,
                              "invalid_bucket_prefix")
    candidates = []
    for group in _groups(payload):
        if not isinstance(group, dict):
            continue
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue
        selected = [bucket for bucket in buckets
                    if isinstance(bucket, dict)
                    and isinstance(bucket.get("bucketId"), str)
                    and bucket["bucketId"].startswith(bucket_prefix)]
        if selected:
            candidates.append(selected)
    if len(candidates) != 1:
        reason = "bucket_group_not_found" if not candidates else "ambiguous_bucket_group"
        return _empty_fixture(now_iso, bucket_prefix, client_version, reason)

    observed_at = _utc_datetime(now_iso)
    if observed_at is None:
        return _empty_fixture(now_iso, bucket_prefix, client_version,
                              "invalid_observation_time")
    mapped_kinds = [WINDOW_KINDS.get(bucket.get("window"))
                    for bucket in candidates[0]]
    known_kinds = [kind for kind in mapped_kinds if kind is not None]
    if len(known_kinds) != len(set(known_kinds)):
        return _empty_fixture(now_iso, bucket_prefix, client_version,
                              "ambiguous_bucket_window")

    windows = []
    expired_window = False
    # #363: a window dropped while a sibling survives used to leave no trace at
    # all -- the document reported "measured" and top simply showed one gauge
    # fewer, with no reason anywhere. Per-bucket rejection stays (refusing the
    # whole document because one bucket is stale would silence the adapter on the
    # real payload); what is added is the record of what was dropped and why.
    dropped = []

    def drop(kind_value, reason):
        if len(dropped) < MAX_DROPPED_WINDOWS:
            # kind is null rather than a string for an unrecognized window: an
            # invented label would read like a real window kind.
            dropped.append({"kind": kind_value, "reason": reason})

    for bucket in candidates[0]:
        window = bucket.get("window")
        kind = WINDOW_KINDS.get(window)
        remaining = bucket.get("remainingFraction")
        reset_raw = bucket.get("resetTime")
        if kind is None or isinstance(remaining, bool) \
                or not isinstance(remaining, (int, float)):
            drop(kind, "invalid_type")
            continue
        try:
            remaining_value = float(remaining)
            if not math.isfinite(remaining_value) \
                    or not 0.0 <= remaining_value <= 1.0:
                drop(kind, "out_of_bounds")
                continue
        except (OverflowError, TypeError, ValueError):
            drop(kind, "out_of_bounds")
            continue
        reset_at = _utc_datetime(reset_raw)
        if reset_raw is not None:
            if reset_at is None:
                drop(kind, "invalid_timestamp")
                continue
            if reset_at <= observed_at:
                expired_window = True
                drop(kind, "expired")
                continue
        resets_at = (reset_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                     if reset_at is not None else None)
        used_ratio = 1.0 - remaining_value
        windows.append({
            "kind": kind,
            "used_ratio": round(used_ratio, 8),
            "resets_at": resets_at,
        })

    fixture = _empty_fixture(now_iso, bucket_prefix, client_version,
                             ("expired_bucket_window" if expired_window
                              else "no_usable_windows"))
    fixture["windows"] = windows
    fixture["dropped"] = dropped
    if windows:
        fixture["measurement"] = {"state": "measured", "reason": None}
    return fixture


def _run_bounded(argv):
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=DISCOVERY_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
        return None
    if completed.returncode != 0 or len(completed.stdout) > MAX_RESPONSE_BYTES:
        return None
    return completed.stdout.decode("utf-8", errors="replace")


def _language_server_credentials():
    """Return ``(pid, csrf_token)`` in memory; never expose the argv."""
    pid_output = _run_bounded(["pgrep", "-f", LANGUAGE_SERVER_MARKER])
    if pid_output is None:
        return None
    for raw_pid in pid_output.splitlines():
        try:
            pid = int(raw_pid.strip())
        except ValueError:
            continue
        output = _run_bounded(["ps", "-p", str(pid), "-o", "command="])
        if output is None or LANGUAGE_SERVER_MARKER not in output:
            continue
        try:
            fields = shlex.split(output.strip())
        except ValueError:
            continue
        token = None
        for idx, field in enumerate(fields):
            if field in ("--csrf_token", "--csrf-token", "--csrfToken"):
                if idx + 1 < len(fields):
                    token = fields[idx + 1]
                break
            for prefix in ("--csrf_token=", "--csrf-token=", "--csrfToken="):
                if field.startswith(prefix):
                    token = field[len(prefix):]
                    break
            if token is not None:
                break
        if isinstance(token, str) and token:
            return pid, token
    return None


def _listener_ports(pid):
    output = _run_bounded([
        "lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN", "-Fn",
    ])
    if output is None:
        return []
    ports = set()
    for line in output.splitlines():
        match = re.fullmatch(r"n(?:127\.0\.0\.1|\*):([0-9]{1,5})", line)
        if match and 0 < int(match.group(1)) <= 65535:
            ports.add(int(match.group(1)))
    return sorted(ports)


def _rpc(port, csrf_token):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=RPC_TIMEOUT_S)
    try:
        connection.request("POST", RPC_PATH, body=RPC_BODY, headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": csrf_token,
        })
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if not 200 <= response.status < 300 or len(body) > MAX_RESPONSE_BYTES:
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, http.client.HTTPException, json.JSONDecodeError,
            UnicodeDecodeError, ValueError):
        return None
    finally:
        with contextlib.suppress(OSError):
            connection.close()


def _read_quota_summary():
    credentials = _language_server_credentials()
    if credentials is None:
        return None
    pid, token = credentials
    for port in _listener_ports(pid):
        payload = _rpc(port, token)
        if payload is not None:
            return payload
    return None


def main(bucket_prefix, *, read_summary=_read_quota_summary, out=None, now=None,
         version_reader=_client_version):
    out = sys.stdout if out is None else out
    now_iso = _now_iso(now)
    client_version = version_reader()
    try:
        payload = read_summary()
        if payload is None:
            fixture = _empty_fixture(now_iso, bucket_prefix, client_version,
                                     "language_server_unavailable")
        else:
            fixture = build_fixture(payload, now_iso, bucket_prefix, client_version)
    except Exception:
        fixture = _empty_fixture(now_iso, bucket_prefix, client_version,
                                 "adapter_unavailable")
    with contextlib.suppress(BrokenPipeError, OSError, ValueError):
        json.dump(fixture, out, separators=(",", ":"))
        out.write("\n")
    return 0


def _parser():
    parser = argparse.ArgumentParser(
        description="Read Antigravity quota windows from its local language server.",
        epilog="example: antigravity-quota.py --bucket-prefix gemini-",
    )
    parser.add_argument(
        "--bucket-prefix", required=True,
        help="explicit bucketId prefix selecting one model group (for example gemini-)",
    )
    return parser


if __name__ == "__main__":
    args = _parser().parse_args()
    if not PREFIX_RE.fullmatch(args.bucket_prefix):
        _parser().error("--bucket-prefix must match [a-z0-9][a-z0-9_.-]{0,39}")
    sys.exit(main(args.bucket_prefix))
