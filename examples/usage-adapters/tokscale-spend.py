#!/usr/bin/env python3
"""Example OPERATOR usage adapter — tokscale quota relay + spend compatibility.

This is a *reference example the operator adopts*, NOT part of the M8Shift core
or companions. M8Shift's charter is no-network; this script is the runtime
boundary. It runs ONLY if you enable the disabled `tokscale-spend` adapter in
`.m8shift/usage/adapters.json`, point its placeholder `command` at YOUR local
tokscale install, and M8Shift then runs it as a plain argv and reads stdout —
M8Shift never talks to tokscale (or any network) itself.

What it reads: tokscale (https://github.com/junhoyeo/tokscale) is a local CLI.
The default `tokscale usage --json` command returns vendor-reported subscription
quota metrics.  A live, redacted v4.13.0 capture (#316) pinned the array shape as
`provider -> metrics[] -> {label, used_percent, remaining_percent, resets_at}`.
Older operator overrides that return local token totals remain accepted as the
legacy spend path.

Honesty / safety:
  - QUOTA data is `proxy_reported`: tokscale relays each vendor's own quota
    endpoint, but the extra relay hop is retained honestly. It is never labeled
    `official`, and it is not authoritative reset evidence. Percentages become
    ratio-native windows; they are never written into token-named fields.
  - Legacy SPEND data remains `local_estimate`: `used_tokens` only, no invented
    limits/windows, and gating only through an explicit budget.json bridge.
  - Costs (dollars) are tokscale's business and are deliberately NOT copied
    into the fixture (the schema is token-denominated).
  - COMPARTMENTALIZATION BOUNDARY (RFC 052): this adapter must NEVER invoke
    `tokscale submit` (or login/autosubmit) — that publishes usage to a public
    leaderboard. Usage data never leaves the machine through M8Shift. The
    guard below refuses any command whose argv mentions a submit-like verb
    BEFORE launching anything; keep it that way.
  - Fail-open: ANY command/provider/schema error prints an unavailable or
    degraded proxy_reported fixture so M8Shift records "unknown" and never
    pauses on a bad read.
  - Aggregate-only output: token totals, no session content, no identity.

This example is intentionally NOT in checksums.sha256: it is reference
material to copy and adapt, not a verified shipped component. Review it before
enabling it.
"""

import contextlib
import argparse
import datetime as dt
import json
import subprocess
import sys
import threading

# Placeholder — the operator points this at their local install (see the
# scaffold entry in .m8shift/usage/adapters.json). Never a network fetch.
TOKSCALE_CMD = ["tokscale", "usage", "--json"]
TOKSCALE_TIMEOUT_S = 15
STDOUT_CAP_BYTES = 1 * 1024 * 1024   # aggregate JSON only; anything bigger is wrong
# Leaderboard/cloud verbs this adapter refuses to launch (RFC 052 boundary).
FORBIDDEN_VERBS = ("submit", "autosubmit", "login")
# Token-count keys the tolerant reader recognizes (ints only).
_TOTAL_KEYS = ("totalTokens", "total_tokens", "total")
_PART_KEYS = ("inputTokens", "input_tokens", "outputTokens", "output_tokens",
              "cacheTokens", "cache_tokens", "cacheReadTokens", "cache_read_tokens",
              "cacheCreationTokens", "cache_creation_tokens",
              "reasoningTokens", "reasoning_tokens")
_MAX_DEPTH = 4
_MAX_NODES = 10000
_QUOTA_PROVIDER_BY_AGENT = {"claude": "claude", "codex": "codex"}


def _now_iso(now=None):
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_spend_fixture(agent, now_iso):
    """Legacy fail-open: no tokens -> unknown spend, never a pause."""
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": agent,
        "provenance": "local_estimate",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": [],
    }


def _quota_fixture(agent, now_iso, windows=(), state="measured", reason=None):
    """Privacy-minimal ratio fixture for vendor data relayed by tokscale."""
    measurement = {"state": state}
    if reason is not None:
        measurement["reason"] = reason
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": agent,
        "provenance": "proxy_reported",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": list(windows),
        "measurement": measurement,
    }


def _as_percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        percent = float(value)
    except (OverflowError, ValueError):
        return None
    return percent if 0.0 <= percent <= 100.0 else None


def _utc_iso(value):
    """Normalize only timezone-aware ISO-8601 strings; never guess a timezone."""
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, TypeError, ValueError):
        return None


def _quota_kind_and_model(label):
    if not isinstance(label, str) or not label or len(label) > 80:
        return None, None
    clean = label.strip()
    if not clean or any(ord(ch) < 32 or ord(ch) == 127 for ch in clean):
        return None, None
    lowered = clean.lower()
    if lowered == "session" or "session" in lowered or "5h" in lowered:
        return "session_5h", None
    if "weekly" in lowered:
        model = clean[:lowered.rfind("weekly")].strip(" -:()") or None
        return "weekly", model
    return None, None


def _quota_window(metric):
    if not isinstance(metric, dict):
        return None
    kind, model = _quota_kind_and_model(metric.get("label"))
    if kind is None:
        return None
    used = _as_percent(metric.get("used_percent"))
    remaining = _as_percent(metric.get("remaining_percent"))
    if used is None and remaining is None:
        return None
    if used is not None and remaining is not None and abs(used + remaining - 100.0) > 0.2:
        return None
    if used is None:
        used = 100.0 - remaining
    window = {
        "kind": kind,
        "used_ratio": round(used / 100.0, 4),
        "resets_at": _utc_iso(metric.get("resets_at")),
    }
    if model is not None:
        window["model"] = model
    return window


def _build_quota_fixture(payload, agent, now_iso):
    """Return None for a non-quota payload, otherwise a bounded quota fixture."""
    if not isinstance(payload, list):
        return None
    rows = payload[:64]
    # Legacy spend exporters may also emit arrays.  A list becomes quota-shaped
    # only when it carries tokscale's provider discriminator; otherwise let the
    # existing bounded token-sum reader handle it as spend.
    if not any(isinstance(row, dict) and isinstance(row.get("provider"), str)
               for row in rows):
        return None
    wanted = _QUOTA_PROVIDER_BY_AGENT.get(str(agent).lower(), str(agent).lower())
    provider = next((row for row in rows
                     if isinstance(row, dict)
                     and isinstance(row.get("provider"), str)
                     and row["provider"].lower() == wanted), None)
    if provider is None:
        return _quota_fixture(agent, now_iso, state="unavailable",
                              reason="provider_unavailable")
    metrics = provider.get("metrics")
    if not isinstance(metrics, list):
        return _quota_fixture(agent, now_iso, state="degraded",
                              reason="no_usable_windows")
    # Bound a drifting provider document and copy only normalized quota fields.
    windows = [window for window in (_quota_window(metric) for metric in metrics[:32])
               if window is not None]
    if not windows:
        return _quota_fixture(agent, now_iso, state="degraded",
                              reason="no_usable_windows")
    return _quota_fixture(agent, now_iso, windows=windows)


def _as_count(value):
    """A usable token count: a non-bool, non-negative int (or int-valued float)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    count = int(value)
    return count if count >= 0 else None


def _sum_tokens(node, depth=0, budget=None):
    """Bounded, version-tolerant token sum over an unknown tokscale JSON shape.

    Every object is exactly ONE of (no mixing — that is what prevents double
    counting a summary-plus-breakdown shape):
      1. an explicit-total leaf — a recognized total key wins outright (its
         part keys and children are NEVER added on top);
      2. a parts leaf — recognized part keys are summed and its child
         containers are NOT entered (a node carrying its own counts is a
         counting leaf; nested objects under it are treated as its breakdown
         of the same spend, e.g. {"inputTokens": 100, "usage":
         {"inputTokens": 100}} counts 100, not 200);
      3. a container — no total, no parts: recurse into children.
    Unknown fields are ignored. Never raises.

    Returns (tokens, recognized): `recognized` is True only when at least one
    recognized total/part key converted successfully somewhere — presence is
    tracked EXPLICITLY (never via list/sum truthiness), so a legitimate
    zero-valued leaf ({"inputTokens": 0}) is a recognized parts leaf that
    counts 0 and still shields its nested breakdown, while a payload with no
    recognized key at all stays unrecognized (unknown, not zero).
    """
    if budget is None:
        budget = [_MAX_NODES]
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return 0, False
    budget[0] -= 1
    if isinstance(node, list):
        subtotal, recognized = 0, False
        for item in node:
            tokens, seen = _sum_tokens(item, depth + 1, budget)
            subtotal += tokens
            recognized = recognized or seen
        return subtotal, recognized
    if not isinstance(node, dict):
        return 0, False
    for key in _TOTAL_KEYS:
        total = _as_count(node.get(key))
        if total is not None:
            return total, True
    part_counts = [count for count in
                   (_as_count(node.get(key)) for key in _PART_KEYS)
                   if count is not None]
    if len(part_counts) > 0:               # explicit presence, NOT truthiness
        return sum(part_counts), True
    subtotal, recognized = 0, False
    for value in node.values():
        if isinstance(value, (dict, list)):
            tokens, seen = _sum_tokens(value, depth + 1, budget)
            subtotal += tokens
            recognized = recognized or seen
    return subtotal, recognized


def build_fixture(payload, agent, now_iso):
    """Pure mapping: tokscale JSON -> quota fixture or legacy SPEND fixture.

    Never raises; never copies account/email/plan/cost/session fields into the
    fixture; never invents token counts or quota limits.
    """
    try:
        quota = _build_quota_fixture(payload, agent, now_iso)
        if quota is not None:
            return quota
        total, recognized = _sum_tokens(payload)
        fixture = _empty_spend_fixture(agent, now_iso)
        if recognized:
            # A recognized zero is DATA (0 tokens spent), not unknown; only a
            # payload with no recognized key at all stays used_tokens null.
            fixture["used_tokens"] = total
        return fixture
    except Exception:
        return (_quota_fixture(agent, now_iso, state="degraded",
                               reason="adapter_schema_error")
                if isinstance(payload, list)
                and any(isinstance(row, dict) and "provider" in row
                        for row in payload[:64])
                else _empty_spend_fixture(agent, now_iso))


def _forbidden(command):
    """True when an argv TOKEN is exactly a leaderboard/cloud verb (RFC 052).

    Exact per-token, case-insensitive matching: tokscale's dangerous verbs
    are subcommands, so they appear as whole argv tokens (`tokscale submit`,
    `tokscale autosubmit status`). Substring matching would make a benign
    path or argument merely CONTAINING such a word (e.g.
    `/opt/logins/tokscale`, `--note submitted`) fail open — an availability
    trap, not a safety gain. The guard still fires BEFORE any launch.
    """
    return any(str(part).lower() in FORBIDDEN_VERBS for part in command)


def _run_tokscale(command=None, popen=subprocess.Popen, timeout_s=TOKSCALE_TIMEOUT_S):
    """Launch the local tokscale CLI (argv, MEMORY-bounded). Any failure returns None.

    The never-submit guard fires BEFORE any process is launched: a command
    that mentions submit/autosubmit/login is refused outright.

    SECURITY (v3.60.0 adversarial hunt, LOW): the earlier `subprocess.run`
    materialized the child's ENTIRE stdout in memory and only checked the size
    cap AFTER — a post-hoc discard, not a bound, so a fast-writing tokscale
    could OOM the adapter before the cap or the timeout fired. This reader
    NEVER holds more than STDOUT_CAP_BYTES + one chunk: a daemon thread reads
    stdout chunk-by-chunk and STOPS at the cap; the main thread joins with the
    deadline (portable — no select on Windows pipes), and a timeout or overflow
    kills the child and returns None. Mirrors the runtime's own
    run_usage_adapter_bounded discipline.
    """
    command = list(TOKSCALE_CMD if command is None else command)
    if _forbidden(command):
        return None
    proc = None
    reader = None
    try:
        proc = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        state = {"chunks": [], "total": 0, "overflow": False}

        def _pump(stdout=proc.stdout):
            try:
                while state["total"] <= STDOUT_CAP_BYTES:
                    chunk = stdout.read(65536)      # bounded per-read
                    if not chunk:
                        return                       # EOF
                    state["chunks"].append(chunk)
                    state["total"] += len(chunk)
                state["overflow"] = True             # exceeded the cap → stop
            except Exception:
                pass                                 # reader error → treated as failure

        reader = threading.Thread(target=_pump, daemon=True)
        reader.start()
        reader.join(timeout=timeout_s)
        if reader.is_alive() or state["overflow"]:
            return None                              # deadline or overflow: bounded, discard
        rc = proc.wait(timeout=2)                    # does NOT read stdout — no race
        if rc != 0:
            return None
        data = "".join(state["chunks"])
        if not data or len(data) > STDOUT_CAP_BYTES:
            return None
        return json.loads(data)
    except (ValueError, RecursionError):
        return None
    except Exception:
        return None
    finally:
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()                          # unblock a hung/overflowing reader
            if reader is not None:
                reader.join(timeout=2)
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)
            with contextlib.suppress(Exception):
                if proc.stdout is not None:
                    proc.stdout.close()


def main(out=None, now=None, read_spend=None, agent="claude"):
    out = sys.stdout if out is None else out
    now_iso = _now_iso(now)
    try:
        payload = read_spend() if read_spend is not None else _run_tokscale()
        fixture = (build_fixture(payload, agent, now_iso)
                   if payload is not None else
                   _quota_fixture(agent, now_iso, state="unavailable",
                                  reason="adapter_unavailable"))
    except Exception:
        fixture = _quota_fixture(agent, now_iso, state="unavailable",
                                 reason="adapter_unavailable")
    with contextlib.suppress(BrokenPipeError, OSError, ValueError):
        json.dump(fixture, out)
        out.write("\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        usage="%(prog)s [AGENT]",
        description="Read tokscale vendor quota (or legacy spend) and emit a normalized fixture.",
        epilog="""example:
  tokscale-spend.py agent-a""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent", nargs="?", default="claude",
                        help="M8Shift agent/provider lane to select (default: claude)")
    cli = parser.parse_args()
    sys.exit(main(agent=cli.agent))
