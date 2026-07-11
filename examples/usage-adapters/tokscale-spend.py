#!/usr/bin/env python3
"""Example OPERATOR usage adapter — tokscale local spend aggregation (RFC 040, #103).

This is a *reference example the operator adopts*, NOT part of the M8Shift core
or companions. M8Shift's charter is no-network; this script is the runtime
boundary. It runs ONLY if you enable the disabled `tokscale-spend` adapter in
`.m8shift/usage/adapters.json`, point its placeholder `command` at YOUR local
tokscale install, and M8Shift then runs it as a plain argv and reads stdout —
M8Shift never talks to tokscale (or any network) itself.

What it reads: tokscale (https://github.com/junhoyeo/tokscale) is a local CLI
that aggregates token/cost spend from AI coding agents' LOCAL session logs and
offers non-interactive JSON output (e.g. `tokscale usage --json`,
`tokscale --json`, `tokscale monthly --json`).

Honesty / safety:
  - SPEND data, not quota: the fixture carries `used_tokens` only —
    `limit_tokens` stays null and NO windows are invented. Provenance is
    `local_estimate`, never `official`: spend-reporting is not usage-window
    gating (official windows stay with the Keychain/app-server adapters); it
    may gate only through the operator's explicit budget.json bridge.
  - Costs (dollars) are tokscale's business and are deliberately NOT copied
    into the fixture (the schema is token-denominated).
  - COMPARTMENTALIZATION BOUNDARY (RFC 052): this adapter must NEVER invoke
    `tokscale submit` (or login/autosubmit) — that publishes usage to a public
    leaderboard. Usage data never leaves the machine through M8Shift. The
    guard below refuses any command whose argv mentions a submit-like verb
    BEFORE launching anything; keep it that way.
  - Fail-open: ANY error prints an empty local_estimate fixture so M8Shift
    records "unknown" and never pauses on a bad read.
  - Aggregate-only output: token totals, no session content, no identity.

This example is intentionally NOT in checksums.sha256: it is reference
material to copy and adapt, not a verified shipped component. Review it before
enabling it.
"""

import contextlib
import datetime as dt
import json
import subprocess
import sys

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


def _now_iso(now=None):
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_fixture(agent, now_iso):
    """Fail-open: no tokens -> unknown spend, never a pause."""
    return {
        "schema": "m8shift.usage.fixture.v1",
        "agent": agent,
        "provenance": "local_estimate",
        "captured_at": now_iso,
        "used_tokens": None,
        "limit_tokens": None,
        "windows": [],
    }


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

    Prefers an explicit total key at each object (never adding its parts on
    top — no double counting); otherwise sums recognized part keys, then
    recurses into child containers. Unknown fields are ignored. Never raises.
    """
    if budget is None:
        budget = [_MAX_NODES]
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return 0
    budget[0] -= 1
    if isinstance(node, list):
        return sum(_sum_tokens(item, depth + 1, budget) for item in node)
    if not isinstance(node, dict):
        return 0
    for key in _TOTAL_KEYS:
        total = _as_count(node.get(key))
        if total is not None:
            return total
    subtotal = 0
    for key in _PART_KEYS:
        part = _as_count(node.get(key))
        if part is not None:
            subtotal += part
    for value in node.values():
        if isinstance(value, (dict, list)):
            subtotal += _sum_tokens(value, depth + 1, budget)
    return subtotal


def build_fixture(payload, agent, now_iso):
    """Pure mapping: tokscale JSON -> m8shift.usage.fixture.v1 SPEND fixture.

    Never raises; never copies raw provider fields, costs, or session content
    into the fixture; never invents windows or limits.
    """
    try:
        total = _sum_tokens(payload)
        fixture = _empty_fixture(agent, now_iso)
        if total > 0:
            fixture["used_tokens"] = total
        return fixture
    except Exception:
        return _empty_fixture(agent, now_iso)


def _forbidden(command):
    """True when the argv mentions a leaderboard/cloud verb (RFC 052 guard)."""
    return any(verb in str(part).lower() for part in command
               for verb in FORBIDDEN_VERBS)


def _run_tokscale(command=None, run=subprocess.run, timeout_s=TOKSCALE_TIMEOUT_S):
    """Launch the local tokscale CLI (argv, bounded). Any failure returns None.

    The never-submit guard fires BEFORE any process is launched: a command
    that mentions submit/autosubmit/login is refused outright.
    """
    command = list(TOKSCALE_CMD if command is None else command)
    if _forbidden(command):
        return None
    try:
        proc = run(command, capture_output=True, text=True, timeout=timeout_s)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    if len(proc.stdout) > STDOUT_CAP_BYTES:
        return None
    try:
        return json.loads(proc.stdout)
    except (ValueError, RecursionError):
        return None


def main(out=None, now=None, read_spend=None, agent="claude"):
    out = sys.stdout if out is None else out
    now_iso = _now_iso(now)
    try:
        payload = read_spend() if read_spend is not None else _run_tokscale()
        fixture = (build_fixture(payload, agent, now_iso)
                   if payload is not None else _empty_fixture(agent, now_iso))
    except Exception:
        fixture = _empty_fixture(agent, now_iso)
    with contextlib.suppress(BrokenPipeError, OSError, ValueError):
        json.dump(fixture, out)
        out.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(agent=sys.argv[1] if len(sys.argv) > 1 else "claude"))
