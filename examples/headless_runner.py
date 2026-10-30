#!/usr/bin/env python3
"""Example headless runner for M8Shift — REFERENCE, not part of `m8shift.py`.

`m8shift.py` is a passive coordinator: `wait` blocks a *process*, it cannot wake an
interactive agent UI (VS Code, …). The only way to a fully hands-off relay is to drive
a **headless** agent (e.g. `claude -p "<prompt>"`, `codex exec "<prompt>"`) in a loop.
This script is that loop, for ONE agent. Run one instance per headless agent; if the
other side is an interactive UI, a human still resumes it (that side stays manual).
`claude` and `codex` are only examples: the same wrapper pattern works with Gemini,
Vibe, or any cooperative agent CLI that can perform one M8Shift turn.

Design (the points a naive `while wait; do …` loop gets wrong):
  * It reads the LOCK `state` directly (a stable `key: value`) instead of `wait`'s
    return code, because `wait --once` returns rc 0 for BOTH "your turn" and `DONE` — a
    naive loop would relaunch forever at `DONE`.
  * A **designated IDLE starter** (`--start-on-idle`) avoids two agents both starting
    from `IDLE`.
  * **Heartbeat for long turns**: while the agent process is running, if this
    runner sees `WORKING_<me>` with less than 5 minutes before `expires`, it runs
    `python3 m8shift.py claim <me> --refresh` (RFC 047 refresh-only guard). This is a
    manual heartbeat: it can only EXTEND a lock this agent already holds — the core
    refuses it in every other state, so a heartbeat can never ghost-claim a fresh
    turn and never steals another agent's pen.
  * **Post-run classification (RFC 047)**: after the child exits, the runner re-reads
    the LOCK and the turn transcript. The authority is AUTHORSHIP, not a state diff:
    the run succeeded only if the relay is `DONE` or this agent authored a turn
    numbered greater than the pre-run turn. Otherwise the run is classified via a
    total table (non_completion / stuck_working / invalid_relay = failures that
    retry up to a cap; external_transition / suspended = neutral, no retry burn).
    The pen is always left for manual recovery (never force-steals).
  * **Run ledger**: every launched turn receives `M8SHIFT_RUN_ID` in the child
    environment and appends lifecycle events to `.m8shift/runtime/runs.jsonl`.
  * **Bounded backoff + retry cap**, and **static argv** (no shell eval).
  * **Resume-working (RFC 047 PR 2)**: `--resume-working --once` also wakes on this
    agent's OWN `WORKING_<me>` lock (holder == me): no claim is run (the pen is already
    held) and the child receives `M8SHIFT_RESUME_WORKING=1` so the provider knows to
    finish the held work and append/done instead of starting a fresh claim→work→append
    turn. Supervising listeners use this for the stuck-work retry.

Usage:
  examples/headless_runner.py claude --cmd claude -p "Apply M8SHIFT.protocol.md: take your
      turn (claim, work, append)." [--start-on-idle] [--interval 30] [--max-retries 3]

The agent command (everything after --cmd) is run verbatim as argv; it must, by itself,
perform exactly one turn against this project's M8SHIFT.md (claim → work → append).
Agents should inspect `m8shift.py status --json` and the listener profile before
launch. This runner writes immutable run plans plus bounded lifecycle metadata to
`.m8shift/runtime/`; provider output is not copied into durable logs.
"""
import argparse
import datetime as dt
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from zoneinfo import ZoneInfo  # stdlib since 3.9; the floor is 3.12


class HelpfulArgumentParser(argparse.ArgumentParser):
    """Print command help plus a valid required-argument shape on errors."""

    def error(self, message):
        parts = [self.prog]
        for action in self._actions:
            if action.dest == "help" or not action.required:
                continue
            if action.option_strings:
                parts.append(action.option_strings[-1])
            if action.nargs != 0:
                value = action.metavar or action.dest.upper()
                parts.append(str(value[0] if isinstance(value, tuple) else value))
        old = self.epilog
        self.epilog = ((old + "\n\n") if old else "") + \
            "required invocation example:\n  " + " ".join(parts)
        self.print_help(sys.stderr)
        self.epilog = old
        self.exit(2, "\n%s: error: %s\n" % (self.prog, message))


class RunnerInfrastructureError(Exception):
    """Stable internal signal for retryable pre-launch infrastructure failures."""

LOCK_BEGIN = "<!-- M8SHIFT:LOCK:BEGIN -->"
LOCK_END = "<!-- M8SHIFT:LOCK:END -->"
VERSION = "4.5.0"
RUNTIME_EVENT_SCHEMA = "m8shift.runtime.event.v1"
RUN_PLAN_SCHEMA = "m8shift.headless.run_plan.v1"
HANDSHAKE_SCHEMA = "m8shift.runner.handshake.v1"
HANDSHAKE_CAPABILITIES = (
    "bounded-tty-tee-v1",
    "environment-write-probe-v1",
    "review-artifact-delivery-v1",
    "runner-exit-v2",
)
HANDSHAKE_OPTIONS = (
    "--agent-model", "--cmd", "--cwd", "--env-allowlist",
    "--m8shift", "--m8shift-py", "--once", "--resume-working",
    "--provider", "--review-delivery", "--run-id", "--runtime-dir",
    "--start-on-idle",
)
TEE_CAPTURE_LIMIT = 64 * 1024
REVIEW_ARTIFACT_SCHEMA = "m8shift.review-artifact.v1"
REVIEW_ARTIFACT_DIRNAME = "reviews"
# A reviewer artefact is an explicit opt-in exception to the usual rule that
# provider output never reaches durable sidecars.  Keep its maximum equal to the
# tee cap: accepting a larger stream would silently persist only its tail.
REVIEW_ARTIFACT_MAX_BYTES = TEE_CAPTURE_LIMIT
ENVIRONMENT_SIGNATURES = {
    "filesystem_read_only": (
        "read-only file system",
        "read only file system",
    ),
    "workspace_trust_refused": (
        "workspace is not trusted",
        "workspace trust denied",
        "sandbox denied write access",
    ),
    "approval_required": (
        "approval is required",
        "approval required to run",
        "requires approval before",
        "permission request was not approved",
    ),
    "headless_permission_refused": (
        "headless mode cannot prompt for, so it was auto-denied",
        "add an allow-rule under permissions.allow in settings.json",
    ),
}
DEFAULT_HEARTBEAT_MARGIN_S = 5 * 60
DEFAULT_ENV_ALLOWLIST = "HOME,PATH,LANG,LC_ALL,LC_CTYPE,TERM,USER"
MANDATORY_ENV = ("M8SHIFT_ROOT", "M8SHIFT_AGENT", "M8SHIFT_RUN_ID", "M8SHIFT_TURN")
# RFC 047 PR 2: exported to the provider child ONLY when this run resumes an
# already-held WORKING_<agent> lock (--resume-working), so the provider can tell
# "finish the held turn, then append/done — do NOT claim" from a normal turn.
RESUME_ENV = "M8SHIFT_RESUME_WORKING"
AGENT_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/+~-]{0,127}\Z")
TURN_BEGIN_RE = re.compile(r"<!-- M8SHIFT:TURN (\d+) ([a-z][a-z0-9_-]*) BEGIN -->")
TURN_END_RE = re.compile(r"<!-- M8SHIFT:TURN \d+ [a-z][a-z0-9_-]* END -->")
TURN_BLOCK_RE = re.compile(
    r"<!-- M8SHIFT:TURN (?P<number>\d+) (?P<agent>[a-z][a-z0-9_-]*) BEGIN -->\r?\n"
    r"(?P<body>.*?)"
    r"<!-- M8SHIFT:TURN (?P=number) (?P=agent) END -->",
    re.DOTALL,
)
TURN_FIELD_RE = re.compile(r"^- ([a-z_][a-z0-9_]*):\s*(.*?)\s*$")
# RFC 047 total classification vocabulary (verify_post_run status values).
# ``review_delivered_pending`` proves a bounded reviewer artefact exists, but
# deliberately does NOT claim that the relay advanced.  ``none`` is retained
# only to read legacy plans; it is never a success because rc=0 proves nothing.
SUCCESS_STATUSES = ("completed", "advanced", "review_delivered_pending")
FAILURE_STATUSES = (
    "non_completion", "stuck_working", "invalid_relay", "unverified_read_only",
    # #377: the run authored a turn, but its premise was superseded (or the
    # answer was outrun) before certification — authored is not certified.
    "premise_superseded",
    "review_output_empty", "review_permission_refused", "review_provider_error",
    "review_artifact_stale", "review_relay_mutated",
    # #360: one label used to cover six conditions, including two security
    # refusals. Distinct reasons, so a verbose reviewer is never mistaken for a
    # planted symlink.
    "review_artifact_budget_invalid", "review_artifact_input_invalid",
    "review_artifact_unsafe_path", "review_artifact_write_failed",
    "review_artifact_truncation_empty", "review_return_receipt_invalid",
)
NEUTRAL_STATUSES = ("external_transition", "suspended")
TERMINAL_FAILURE_STATUSES = ("environment_blocked", "approval_required",
                             "headless_permission_refused")
PROVIDER_RATE_LIMIT_STATUSES = (
    "provider_rate_limited",
    "provider_rate_limited_reset_unknown",
)
PROVIDER_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
OPENAI_CODEX_LIMIT_RE = re.compile(
    r"^\s*(?:error:\s*)?you(?:'|\N{RIGHT SINGLE QUOTATION MARK})ve hit your "
    r"(?P<scope>weekly|5[- ]hour|session)\s+(?:usage\s+)?limit[.!]?\s+"
    r"(?:(?:try again|resets?)\s+(?:at|on)?\s*)"
    r"(?P<reset>[^\r\n]+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
PROVIDER_RESET_FORMATS = (
    "%b %d, %Y, %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y, %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def runner_handshake():
    """Print the bounded listener/runner compatibility contract."""
    print(json.dumps({
        "schema": HANDSHAKE_SCHEMA,
        "version": VERSION,
        "capabilities": list(HANDSHAKE_CAPABILITIES),
        "options": list(HANDSHAKE_OPTIONS),
    }, ensure_ascii=False, sort_keys=True))


class BoundedTTYTee:
    """Drain both child pipes, retain bounded bytes, echo only to real TTYs."""

    def __init__(self, proc, limit=TEE_CAPTURE_LIMIT):
        self.proc = proc
        self.limit = limit
        self._capture = bytearray()
        self._tail = bytearray()
        self._lock = threading.Lock()
        self._counts = {
            "stdout": {"bytes": 0, "lines": 0},
            "stderr": {"bytes": 0, "lines": 0},
        }
        self._last = {"stdout": b"", "stderr": b""}
        self._threads = []
        for name, pipe, target in (
                ("stdout", proc.stdout, sys.stdout),
                ("stderr", proc.stderr, sys.stderr)):
            thread = threading.Thread(
                target=self._drain, args=(name, pipe, target), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _drain(self, name, pipe, target):
        if pipe is None:
            return
        echo = bool(getattr(target, "isatty", lambda: False)())
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._counts[name]["bytes"] += len(chunk)
                    self._counts[name]["lines"] += chunk.count(b"\n")
                    self._last[name] = chunk[-1:]
                    room = self.limit - len(self._capture)
                    if room > 0:
                        self._capture.extend(chunk[:room])
                    self._tail.extend(chunk)
                    if len(self._tail) > self.limit:
                        del self._tail[:-self.limit]
                if echo:
                    target.write(chunk.decode("utf-8", errors="replace"))
                    target.flush()
        except OSError:
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    def finish(self, join_timeout=2.0):
        for thread in self._threads:
            thread.join(timeout=join_timeout)
        # A provider may leave a grandchild holding a copied pipe descriptor.
        # Daemon drainers are therefore bounded here instead of being joined
        # forever after the direct child has exited.
        with self._lock:
            counts = {name: dict(values) for name, values in self._counts.items()}
            for name in counts:
                if counts[name]["bytes"] and self._last[name] != b"\n":
                    counts[name]["lines"] += 1
            captured_head = bytes(self._capture)
            captured_tail = bytes(self._tail)
        text = (captured_head + b"\n" + captured_tail).decode(
            "utf-8", errors="replace").lower()
        signature_ids = sorted(
            signature_id for signature_id, needles in ENVIRONMENT_SIGNATURES.items()
            if any(needle in text for needle in needles))
        tail_text = captured_tail.decode("utf-8", errors="replace")
        turn_ends = list(TURN_END_RE.finditer(tail_text))
        final_output = (tail_text[turn_ends[-1].end():]
                        if turn_ends else tail_text)
        final_text = final_output.lower()
        final_signature_ids = sorted(
            signature_id for signature_id, needles in ENVIRONMENT_SIGNATURES.items()
            if any(needle in final_text for needle in needles))
        return {
            "bytes": sum(row["bytes"] for row in counts.values()),
            "lines": sum(row["lines"] for row in counts.values()),
            "streams": counts,
            "signature_ids": signature_ids,
            "final_signature_ids": final_signature_ids,
            # Ephemeral only: the caller classifies this bounded tail and never
            # copies it into a plan, event, listener state, notification, or log.
            "_final_text": final_output,
        }


def _provider_reset_datetime(raw):
    """Normalize one provider-owned reset instant with an actual timezone.

    IANA zones are resolved through the system tz database. Explicit numeric
    offsets are accepted as provider data. A timezone abbreviation or a naive
    timestamp is intentionally rejected instead of inventing an offset.
    """
    value = str(raw or "").strip().rstrip(".").strip()
    value = value[1:-1].strip() if value.startswith("(") and value.endswith(")") else value
    zone_name = ""
    zone = None
    zone_match = re.search(r"(?:\s+\()?([A-Za-z]+/[A-Za-z0-9_+.-]+)\)?$", value)
    if zone_match:
        zone_name = zone_match.group(1)
        value = value[:zone_match.start()].rstrip()
        try:
            zone = ZoneInfo(zone_name)
        except (KeyError, ValueError):
            return None, ""
    else:
        iso_match = re.search(r"(Z|[+-]\d{2}:\d{2})$", value)
        if iso_match:
            zone_name = iso_match.group(1)
            try:
                parsed = dt.datetime.fromisoformat(
                    value[:-1] + "+00:00" if value.endswith("Z") else value)
            except ValueError:
                return None, ""
            return parsed.astimezone(dt.timezone.utc), zone_name
        return None, ""
    parsed = None
    for fmt in PROVIDER_RESET_FORMATS:
        try:
            parsed = dt.datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None, ""
    aware = parsed.replace(tzinfo=zone)
    # Reject DST gaps: a non-existent local wall time does not round-trip.
    if aware.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None) != parsed:
        return None, ""
    return aware.astimezone(dt.timezone.utc), zone_name


def classify_provider_terminal_output(provider, output_tail, returncode,
                                      relay_advanced, observed_at=None):
    """Transitional strict provider grammar for one terminal output tail.

    The provider adapter boundary will ultimately own these signatures. Until
    the runner can call that boundary without gaining routing authority, keep
    this grammar provider-keyed, final-output-only, bounded, and fail-closed.
    """
    if provider != "openai-codex" or returncode in (None, 0) or relay_advanced:
        return None
    text = str(output_tail or "")
    # A provider-owned terminal line is the complete final output. Prompt
    # quotes/prefixes and arbitrary surrounding transcript therefore cannot
    # become a hold signal.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    match = OPENAI_CODEX_LIMIT_RE.fullmatch(lines[0])
    if not match:
        return None
    scope = match.group("scope").lower().replace("-", "_").replace(" ", "_")
    scope = "session_5h" if scope in {"5_hour", "session"} else scope
    reset, timezone_name = _provider_reset_datetime(match.group("reset"))
    metadata = {
        "provider": provider,
        "scope": scope,
        "resets_at": None,
        "timezone": "",
        "evidence_id": "openai_codex_usage_limit_v1",
        "returncode": int(returncode),
    }
    if reset is None:
        return {
            "status": "provider_rate_limited_reset_unknown",
            "reason": "provider_rate_limited_reset_unknown",
            "metadata": metadata,
        }
    metadata["resets_at"] = reset.strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata["timezone"] = timezone_name
    current = observed_at or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    if reset <= current.astimezone(dt.timezone.utc):
        return {
            "status": "provider_rate_limited_reset_unknown",
            "reason": "provider_rate_limited_reset_unknown",
            "metadata": metadata,
        }
    return {
        "status": "provider_rate_limited",
        "reason": "provider_usage_limit",
        "metadata": metadata,
    }


def probe_directory_writable(path):
    """Return writable/blocked/ambiguous without persisting exception text."""
    try:
        if not os.path.isdir(path):
            return {"status": "ambiguous", "signature_id": "directory_missing"}
        if not os.access(path, os.W_OK):
            return {"status": "blocked", "signature_id": "write_access_denied"}
        probe = os.path.join(path, ".m8shift-write-probe-%s" % uuid.uuid4().hex)
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        os.unlink(probe)
        return {"status": "writable", "signature_id": "write_probe_ok"}
    except OSError as exc:
        try:
            if 'fd' in locals():
                os.close(fd)
        except OSError:
            pass
        try:
            if 'probe' in locals() and os.path.exists(probe):
                os.unlink(probe)
        except OSError:
            pass
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return {"status": "blocked", "signature_id": "write_probe_denied",
                    "exception_type": type(exc).__name__}
        return {"status": "ambiguous", "signature_id": "write_probe_error",
                "exception_type": type(exc).__name__}


def environment_probe(cwd, runtime_dir):
    """Probe both required write domains; any ambiguity stays retryable."""
    rows = {
        "cwd": probe_directory_writable(cwd),
        "runtime_dir": probe_directory_writable(runtime_dir),
    }
    statuses = {row["status"] for row in rows.values()}
    status = ("ambiguous" if "ambiguous" in statuses else
              "blocked" if "blocked" in statuses else "writable")
    signature_ids = sorted({row["signature_id"] for row in rows.values()})
    exception_types = sorted({row.get("exception_type", "") for row in rows.values()
                              if row.get("exception_type")})
    return {"status": status, "signature_ids": signature_ids,
            "exception_types": exception_types}


def confirmed_environment_block(pre_probe, post_probe):
    """A terminal block needs deterministic denial both before and after launch."""
    return (pre_probe.get("status") == "blocked"
            and post_probe.get("status") == "blocked")


def confirmed_approval_required(output_summary, returncode, relay_status,
                                timed_out=False):
    """Corroborate an advisory output signature before making it terminal.

    Provider text alone is never authoritative.  The bounded signature must be
    accompanied by a non-zero provider exit and an unchanged/failed relay
    classification for this invocation.  A stuck/timeout deadlock is sufficient;
    otherwise the signature must occur after the final captured relay transcript.
    """
    return (returncode not in (None, 0)
            and relay_status in FAILURE_STATUSES
            and "approval_required" in output_summary.get("signature_ids", ())
            and (relay_status == "stuck_working" or timed_out
                 or "approval_required" in
                 output_summary.get("final_signature_ids", ())))


AGY_HEADLESS_PERMISSION_RE = re.compile(
    r'^jetski: no output produced\s+[\N{EM DASH}-]\s+a tool required the '
    r'"([a-z][a-z0-9_.:-]{0,63})" permission that headless mode cannot prompt '
    r'for, so it was auto-denied\. add an allow-rule under permissions\.allow '
    r'in settings\.json \(e\.g\. .+\)\. alternatively, re-run with '
    r'--dangerously-skip-permissions to auto-approve all tools\.\s*$',
    re.IGNORECASE)


def confirmed_headless_permission_refusal(provider, output_summary):
    """Recognize AGY's exact headless refusal even though that CLI exits zero.

    Returns the bounded permission name when recognized, otherwise None. The name
    comes from the pattern's own capture group, so it carries that pattern's
    length and character bounds and is safe to render; the provider's raw line is
    never propagated."""
    if provider != "google-antigravity" \
            or "headless_permission_refused" not in output_summary.get(
                "final_signature_ids", ()):
        return None
    lines = [line.strip() for line in str(
        output_summary.get("_final_text", "")).splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    match = AGY_HEADLESS_PERMISSION_RE.fullmatch(lines[0])
    return match.group(1) if match else None


def read_lock(m8shift_path):
    """Return the LOCK fields as a dict, or None if the file/markers are missing."""
    try:
        with open(m8shift_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if LOCK_BEGIN not in text or LOCK_END not in text:
        return None
    body = text[text.index(LOCK_BEGIN) + len(LOCK_BEGIN):text.index(LOCK_END)]
    fields = {}
    for line in body.splitlines():
        m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def parse_turn_authors(text):
    """Return [(n, agent), ...] for every structurally closed relay turn."""
    return [(record["number"], record["agent"]) for record in parse_turn_records(text)]


def parse_turn_records(text):
    """Return closed-turn authors plus their machine-readable header fields.

    Only the field block before the first blank line is authoritative. A body that
    merely quotes ``- x_run_id: ...`` therefore cannot claim a runner execution.
    """
    records = []
    for match in TURN_BLOCK_RE.finditer(text):
        header = re.split(r"\r?\n\r?\n", match.group("body"), maxsplit=1)[0]
        fields = {}
        for line in header.splitlines():
            field = TURN_FIELD_RE.fullmatch(line)
            if field:
                fields[field.group(1)] = field.group(2)
        records.append({
            "number": int(match.group("number")),
            "agent": match.group("agent"),
            "fields": fields,
        })
    return records


def authored_by_me(m8shift_text_or_path, me, pre_turn, run_id=""):
    """RFC 047 authorship rule, positioned for #377: the sorted turn numbers
    authored by `me` with int(n) > int(pre_turn). When ``run_id`` is supplied,
    each matched turn must also carry the exact ``x_run_id`` field exported to
    this runner child. An empty list keeps the historical boolean contract for
    callers that only ask WHETHER something was authored; the numbers let the
    classifier ask WHERE the answer sits relative to its premise.

    Accepts either the relay text or a path to it. `pre_turn` is parsed defensively:
    a non-integer pre-turn means authorship can never be established (the caller's
    classification table handles the run via state rules instead).
    """
    text = m8shift_text_or_path
    if text is None:
        return []
    if "\n" not in text and os.path.isfile(text):
        try:
            with open(text, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return []
    try:
        pre = int(str(pre_turn).strip())
    except (TypeError, ValueError):
        return []
    return sorted(
        record["number"]
        for record in parse_turn_records(text)
        if record["agent"] == me
        and record["number"] > pre
        and (not run_id or record["fields"].get("x_run_id") == run_id)
    )


def read_relay_post_run(m8shift_path, attempts=3, delay=0.5):
    """Post-run relay read with a bounded re-read for transient errors (RFC 047).

    A missing file / OSError can be a transient window during an atomic replace:
    retry up to `attempts` reads over ~1 second. A readable file whose LOCK markers
    are missing is STABLE malformed content and classifies immediately, without
    burning the retry budget. Returns (lock_fields_or_None, text_or_None).
    """
    last_text = None
    for i in range(attempts):
        try:
            with open(m8shift_path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            if i + 1 < attempts:
                time.sleep(delay)
            continue
        last_text = text
        if LOCK_BEGIN not in text or LOCK_END not in text:
            return None, text          # stable malformed content: classify immediately
        body = text[text.index(LOCK_BEGIN) + len(LOCK_BEGIN):text.index(LOCK_END)]
        fields = {}
        for line in body.splitlines():
            m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        return fields, text
    return None, last_text


def log(msg):
    print(f"[m8shift-runner] {msg}", flush=True)


def iso_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id(agent):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{agent}-{uuid.uuid4().hex[:8]}"


def validate_run_id(run_id):
    if not RUN_ID_RE.fullmatch(run_id) or "/" in run_id or "\\" in run_id or ":" in run_id:
        raise SystemExit("invalid run id: expected a path-safe token")
    return run_id


def run_plan_path(runtime_dir, run_id):
    return os.path.join(runtime_dir, "run-plans", f"{run_id}.json")


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def turn_block_sha256(relay_text, turn_number):
    """SHA-256 of the exact closed turn block, or None when it cannot be read.

    One recognition of one signature: the review input fingerprint and the #377
    premise digest must never grow separate parsers of the same block format.
    """
    turn = _turn_int(turn_number)
    if turn is None or not isinstance(relay_text, str):
        return None
    for match in TURN_BLOCK_RE.finditer(relay_text):
        if int(match.group("number")) == turn:
            return sha256_text(match.group(0))
    return None


def review_input_snapshot(lock, relay_text):
    """Bind a reviewer artefact to the exact closed handoff it read.

    The LOCK itself changes when the coordinator claims the incoming turn, so a
    full-file digest would make every honest consumption look stale.  The input
    fingerprint is instead the exact closed turn referenced by the entry LOCK.
    The entry state/holder remain recorded for audit, while freshness later
    requires the same turn number and turn bytes.
    """
    turn = _turn_int(lock.get("turn", ""))
    if turn is None or not isinstance(relay_text, str):
        raise ValueError("review input has no valid relay turn")
    digest = turn_block_sha256(relay_text, turn)
    if digest is None:
        raise ValueError("review input turn is absent or not structurally closed")
    return {
        "state": lock.get("state", ""),
        "holder": lock.get("holder", ""),
        "turn": str(turn),
        "turn_sha256": digest,
    }


def review_artifact_path(runtime_dir, run_id):
    return os.path.join(runtime_dir, REVIEW_ARTIFACT_DIRNAME, f"{run_id}.json")


def review_artifact_relpath(run_id):
    return f"{REVIEW_ARTIFACT_DIRNAME}/{run_id}.json"


REVIEW_RETURN_RECEIPT_SCHEMA = "m8shift.review-return-receipt.v1"
REVIEW_RETURN_RECEIPT_DIRNAME = "review-returns"


def review_return_receipt_path(runtime_dir, run_id):
    return os.path.join(runtime_dir, REVIEW_RETURN_RECEIPT_DIRNAME, f"{run_id}.json")


def review_return_receipt_relpath(run_id):
    return f"{REVIEW_RETURN_RECEIPT_DIRNAME}/{run_id}.json"


def review_output_lines(text):
    return len(text.splitlines()) if text else 0


def truncate_utf8_on_character_boundary(text, max_bytes):
    """Largest prefix of `text` whose UTF-8 encoding fits in `max_bytes`, cut on a
    character boundary.

    Cutting on a byte boundary and decoding with errors="replace" desynchronizes
    the artifact: the recorded byte count and digest describe the raw prefix while
    the stored text re-encodes to something longer, with U+FFFD standing where a
    character was severed. Measured on 40 French accented characters capped at 41
    bytes: 41 bytes recorded, 43 bytes actually stored, two different digests. A
    receipt whose digest does not cover what it seals is worse than no digest, so
    the cut steps back to the start of the severed character and the strict decode
    below is guaranteed to succeed."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, encoded
    # Decoding the bounded prefix with ``ignore`` discards only an incomplete
    # trailing code point.  Re-encoding then gives the exact bytes represented
    # by the returned text.  Looking only at the last byte is insufficient: the
    # final byte of a *complete* multibyte character is also a continuation byte.
    cut_text = encoded[:max_bytes].decode("utf-8", errors="ignore")
    cut = cut_text.encode("utf-8")
    return cut_text, cut


def write_review_artifact(runtime_dir, plan, output_summary):
    """Create one private, immutable, bounded reviewer artefact.

    This is deliberately separate from the normal run ledger: the ledger keeps
    only stable metadata and digests, while an explicitly declared reviewer
    delivery is allowed to retain its final response for the coordinator.
    """
    delivery = plan.get("review_delivery") or {}
    text = output_summary.get("_final_text", "")
    if not isinstance(text, str) or not text.strip():
        return None, "review_output_empty"
    encoded = text.encode("utf-8")
    max_bytes = delivery.get("max_output_bytes", REVIEW_ARTIFACT_MAX_BYTES)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        return None, "review_artifact_budget_invalid"
    # #360: over the cap the review is TRUNCATED and delivered, never destroyed.
    # A bounded prefix of a review is a usable review with a stated truncation;
    # zero bytes is not. The measurements of a discarded document -- 93391 bytes,
    # 436 lines -- were all that survived the previous behaviour.
    original_bytes = max(len(encoded), output_summary.get("bytes", 0))
    original_lines = max(review_output_lines(text), output_summary.get("lines", 0))
    text, encoded = truncate_utf8_on_character_boundary(text, max_bytes)
    if not encoded:
        return None, "review_artifact_truncation_empty"
    truncated = len(encoded) < original_bytes
    input_snapshot = (plan.get("expected_transition") or {}).get("input")
    if not isinstance(input_snapshot, dict):
        return None, "review_artifact_input_invalid"
    artifact = {
        "schema": REVIEW_ARTIFACT_SCHEMA,
        "created_at": iso_now(),
        "run_id": plan["run_id"],
        "agent": plan["agent"],
        "provider": plan.get("provider", ""),
        "agent_model": plan.get("agent_model", ""),
        "input": input_snapshot,
        "output": {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
            "lines": review_output_lines(text),
            "text": text,
            # The digest above covers exactly these bytes, truncated or not.
            "truncated": truncated,
            "original_bytes": original_bytes,
            "original_lines": original_lines,
        },
    }
    path = review_artifact_path(runtime_dir, plan["run_id"])
    directory = os.path.dirname(path)
    try:
        if os.path.islink(runtime_dir) or os.path.islink(directory):
            # A security refusal, not a size problem. Collapsed into one label an
            # operator could not tell a verbose reviewer from a planted symlink.
            return None, "review_artifact_unsafe_path"
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.path.islink(directory) or os.path.lexists(path):
            return None, "review_artifact_unsafe_path"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(artifact, fh, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    except OSError:
        return None, "review_artifact_write_failed"
    body = canonical_json(artifact)
    return {
        "schema": REVIEW_ARTIFACT_SCHEMA,
        "path": review_artifact_relpath(plan["run_id"]),
        "sha256": sha256_text(body),
        "output_sha256": artifact["output"]["sha256"],
        "output_bytes": artifact["output"]["bytes"],
        "truncated": truncated,
        "original_bytes": original_bytes,
        "input": dict(input_snapshot),
    }, ""


def write_review_return_receipt(runtime_dir, plan, output_summary, returncode,
                                evidence_id=""):
    """Persist one redacted refusal receipt that can only return routing.

    This is not a review artifact and contains no provider text. It gives the
    original coordinator stable evidence for the narrow core `review-return`
    edge after a reviewer provider permission refusal.
    """
    input_snapshot = (plan.get("expected_transition") or {}).get("input")
    allowed_evidence = {
        "headless_permission_refused", "approval_required",
        "environment_write_probe",
    }
    evidence_ids = allowed_evidence.intersection(
        set(output_summary.get("signature_ids", ()))
        | set(output_summary.get("final_signature_ids", ())))
    if evidence_id:
        evidence_ids.add(evidence_id)
    evidence_ids = sorted(evidence_ids)
    if not isinstance(input_snapshot, dict) or not evidence_ids \
            or not isinstance(returncode, int):
        return None, "review_return_receipt_invalid"
    receipt = {
        "schema": REVIEW_RETURN_RECEIPT_SCHEMA,
        "created_at": iso_now(),
        "run_id": plan["run_id"],
        "agent": plan["agent"],
        "provider": plan.get("provider", ""),
        "input": input_snapshot,
        "outcome": {
            "status": "review_permission_refused",
            "evidence_ids": evidence_ids,
            "provider_returncode": returncode,
        },
    }
    path = review_return_receipt_path(runtime_dir, plan["run_id"])
    directory = os.path.dirname(path)
    try:
        if os.path.islink(runtime_dir) or os.path.islink(directory):
            return None, "review_return_receipt_invalid"
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.path.islink(directory) or os.path.lexists(path):
            return None, "review_return_receipt_invalid"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(receipt, fh, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    except OSError:
        return None, "review_return_receipt_invalid"
    body = canonical_json(receipt)
    return {
        "schema": REVIEW_RETURN_RECEIPT_SCHEMA,
        "path": review_return_receipt_relpath(plan["run_id"]),
        "sha256": sha256_text(body),
        "input": dict(input_snapshot),
        "outcome": "review_permission_refused",
    }, ""


def canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prompt_hash_for_argv(argv):
    """Hash the exact child input this runner controls.

    The reference runner remains provider-neutral: it receives an already-rendered
    argv command and does not parse provider-specific prompt flags. For RFC 028 the
    audited prompt hash is therefore the canonical rendered argv handed to the child.
    """
    return sha256_text(canonical_json({"argv": list(argv)}))


def normalize_env_allowlist(raw):
    names = []
    for token in (raw or "").split(","):
        name = token.strip()
        if not name:
            continue
        if not ENV_RE.fullmatch(name):
            raise SystemExit(f"invalid env allowlist entry {name!r}")
        if name not in names:
            names.append(name)
    for name in MANDATORY_ENV:
        if name not in names:
            names.append(name)
    return names


def resolve_argv(argv):
    if isinstance(argv, str):
        raise SystemExit("command argv must be an array, not a shell string")
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
        raise SystemExit("command argv must be a non-empty list of non-empty strings")
    exe = argv[0]
    if any(ch.isspace() for ch in exe):
        raise SystemExit("--cmd expects an executable followed by separate arguments, not a quoted "
                         "shell command; pass sh -c explicitly or use a script for pipes/redirection")
    if os.path.isabs(exe):
        if not os.path.isfile(exe) or not os.access(exe, os.X_OK):
            raise RunnerInfrastructureError("provider_executable_unavailable")
        resolved = exe
    elif "/" in exe or "\\" in exe:
        raise SystemExit("argv[0] must be a bare PATH program or an absolute path")
    else:
        resolved = shutil.which(exe)
        if not resolved:
            raise RunnerInfrastructureError("provider_executable_unavailable")
    return [resolved] + list(argv[1:])


def validate_run_plan(plan):
    required = {
        "schema", "created_at", "agent", "argv", "cwd", "run_id", "prompt_hash",
        "env_allowlist", "timeout", "kill_grace", "expected_transition",
    }
    missing = sorted(required - set(plan))
    if missing:
        raise SystemExit(f"run plan missing required field(s): {', '.join(missing)}")
    if plan["schema"] != RUN_PLAN_SCHEMA:
        raise SystemExit(f"run plan schema must be {RUN_PLAN_SCHEMA}")
    if not AGENT_RE.fullmatch(plan["agent"]):
        raise SystemExit("run plan agent is invalid")
    validate_run_id(plan["run_id"])
    if not isinstance(plan["cwd"], str) or not os.path.isabs(plan["cwd"]) or not os.path.isdir(plan["cwd"]):
        raise SystemExit("run plan cwd must be an existing absolute directory")
    if not re.fullmatch(r"[0-9a-f]{64}", plan["prompt_hash"]):
        raise SystemExit("run plan prompt_hash must be a sha256 hex digest")
    if not isinstance(plan["env_allowlist"], list) or not all(ENV_RE.fullmatch(v or "") for v in plan["env_allowlist"]):
        raise SystemExit("run plan env_allowlist must be an array of environment variable names")
    if not isinstance(plan["timeout"], int) or plan["timeout"] < 0:
        raise SystemExit("run plan timeout must be a non-negative integer")
    if not isinstance(plan["kill_grace"], int) or plan["kill_grace"] < 0:
        raise SystemExit("run plan kill_grace must be a non-negative integer")
    if not isinstance(plan.get("resume_working", False), bool):
        raise SystemExit("run plan resume_working must be a boolean")
    premise_digest = plan["expected_transition"].get("premise_sha256") \
        if isinstance(plan["expected_transition"], dict) else None
    if premise_digest is not None and (
            not isinstance(premise_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", premise_digest)):
        raise SystemExit("run plan premise_sha256 must be a sha256 hex digest")
    agent_model = plan.get("agent_model", "")
    if not isinstance(agent_model, str) or (agent_model and not MODEL_ID_RE.fullmatch(agent_model)):
        raise SystemExit("run plan agent_model must be a valid 1-128 character model id")
    provider = plan.get("provider", "")
    if not isinstance(provider, str) or (provider and not PROVIDER_RE.fullmatch(provider)):
        raise SystemExit("run plan provider must be a safe provider id")
    resolve_argv(plan["argv"])
    expected = plan["expected_transition"]
    if (not isinstance(expected, dict)
            or expected.get("type") not in {"core_state_advanced", "none", "review_artifact"}):
        raise SystemExit("run plan expected_transition must be an object with type "
                         "core_state_advanced, none, or review_artifact")
    delivery = plan.get("review_delivery", {"type": "none"})
    if not isinstance(delivery, dict) or delivery.get("type") not in {"none", "artifact"}:
        raise SystemExit("run plan review_delivery must be an object with type none or artifact")
    if delivery.get("type") == "artifact":
        required_delivery = {"type", "schema", "path", "max_output_bytes"}
        if set(delivery) != required_delivery or delivery.get("schema") != REVIEW_ARTIFACT_SCHEMA:
            raise SystemExit("run plan review_delivery artifact fields are invalid")
        if (delivery.get("path") != review_artifact_relpath(plan["run_id"])
                or not isinstance(delivery.get("max_output_bytes"), int)
                or not 1 <= delivery["max_output_bytes"] <= REVIEW_ARTIFACT_MAX_BYTES):
            raise SystemExit("run plan review_delivery artifact path or bound is invalid")
        input_snapshot = expected.get("input")
        if (expected.get("type") != "review_artifact" or not isinstance(input_snapshot, dict)
                or set(input_snapshot) != {"state", "holder", "turn", "turn_sha256"}
                or not isinstance(input_snapshot.get("state"), str)
                or not isinstance(input_snapshot.get("holder"), str)
                or _turn_int(input_snapshot.get("turn")) is None
                or not re.fullmatch(r"[0-9a-f]{64}", input_snapshot.get("turn_sha256", ""))):
            raise SystemExit("run plan review_delivery input fingerprint is invalid")
    elif expected.get("type") == "review_artifact":
        raise SystemExit("run plan review_artifact expectation requires artifact delivery")
    command = plan.get("command", {})
    if command:
        if command.get("shell") is not False:
            raise SystemExit("run plan command.shell must be false")
        if command.get("argv") != plan["argv"]:
            raise SystemExit("run plan command.argv must match top-level argv")
    return True


def expected_post_run(me, lk, run_id="", relay_text=None):
    expected = {
        "type": "core_state_advanced",
        "pre_state": lk.get("state", ""),
        "pre_holder": lk.get("holder", ""),
        "pre_turn": lk.get("turn", ""),
        "agent": me,
        "run_id": run_id,
        "stuck_state": f"WORKING_{me.upper()}",
        "success_rule": ("post relay is DONE OR this agent authored exactly the "
                         "direct successor of pre_turn (sole matched turn, "
                         "x_run_id bound, premise digest verified when present) "
                         "(RFC 047, #377)"),
    }
    # #377: identify the premise, never merely position it. The digest is only
    # recorded when the launch snapshot could actually read the pre-turn block;
    # a fabricated or absent digest must not exist, so the key is conditional.
    premise = turn_block_sha256(relay_text, lk.get("turn", ""))
    if premise:
        expected["premise_sha256"] = premise
    return expected


def resume_eligible(args, me, me_working, lk):
    """RFC 047 PR 2: an explicit --resume-working run may ALSO start from this
    agent's own WORKING lock (holder == agent). The pen is already held, so no
    claim happens — the provider finishes the work and appends/dones."""
    return bool(args.resume_working and lk
                and lk.get("state", "") == me_working
                and lk.get("holder", "") == me)


def make_run_plan(args, run_id, me, lk, resumed=False, relay_text=None):
    argv = resolve_argv(list(args.cmd))
    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        raise SystemExit(f"--cwd is not a directory: {args.cwd}")
    expected = expected_post_run(me, lk, run_id, relay_text=relay_text)
    review_delivery = getattr(args, "review_delivery", "none")
    if review_delivery == "artifact":
        try:
            input_snapshot = review_input_snapshot(lk, relay_text)
        except ValueError as exc:
            raise RunnerInfrastructureError("review_input_unavailable") from exc
        expected = {
            "type": "review_artifact",
            "pre_state": lk.get("state", ""),
            "pre_holder": lk.get("holder", ""),
            "pre_turn": lk.get("turn", ""),
            "agent": me,
            "run_id": run_id,
            "success_rule": ("a non-empty bounded review artifact with digest exists "
                             "for the unchanged input turn; relay advancement is not success"),
            "input": input_snapshot,
        }
    elif args.expected_transition == "none":
        expected = {
            "type": "none",
            "pre_state": lk.get("state", ""),
            "pre_turn": lk.get("turn", ""),
            "agent": me,
            "success_rule": "legacy read-only run; no verifiable delivery contract",
        }
    return {
        "schema": RUN_PLAN_SCHEMA,
        "created_at": iso_now(),
        "run_id": run_id,
        "agent": me,
        "agent_model": getattr(args, "agent_model", "") or "",
        "provider": getattr(args, "provider", "") or "",
        "argv": argv,
        "cwd": cwd,
        "prompt_hash": prompt_hash_for_argv(argv),
        "env_allowlist": normalize_env_allowlist(args.env_allowlist),
        "timeout": args.turn_timeout,
        "kill_grace": args.kill_grace,
        "resume_working": bool(resumed),
        "expected_transition": expected,
        "review_delivery": ({
            "type": "artifact",
            "schema": REVIEW_ARTIFACT_SCHEMA,
            "path": review_artifact_relpath(run_id),
            "max_output_bytes": REVIEW_ARTIFACT_MAX_BYTES,
        } if review_delivery == "artifact" else {"type": "none"}),
        "command": {
            "argv": argv,
            "shell": False,
        },
        "expected_post_run": expected,
        "source": {"tool": "headless_runner.py", "version": VERSION},
    }


def write_run_plan(runtime_dir, plan):
    validate_run_plan(plan)
    os.makedirs(os.path.join(runtime_dir, "run-plans"), exist_ok=True)
    path = run_plan_path(runtime_dir, plan["run_id"])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _turn_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def classify_post_run(expected, after, post_text):
    """RFC 047 total classification of one finished provider run → (status, reason).

    Evaluation order (per the RFC table): invalid relay, read-only expectation,
    DONE, authorship, turn reset, PAUSED, then per-state rows; anything else is an
    external transition. Authorship — a transcript turn by this agent numbered
    greater than pre_turn — is the success authority, never a state-only diff.
    """
    me = expected.get("agent", "")
    if after is None or not after.get("state", ""):
        return "invalid_relay", "post-run LOCK is missing or invalid after the bounded re-read"
    if expected.get("type") == "none":
        return "unverified_read_only", (
            "read-only run has no verifiable delivery contract; provider rc=0 is insufficient"
        )
    if expected.get("type") == "review_artifact":
        try:
            current_input = review_input_snapshot(after, post_text)
        except ValueError:
            return "review_artifact_stale", "the reviewed input turn is no longer available"
        entry = expected.get("input") or {}
        if (current_input.get("turn") != entry.get("turn")
                or current_input.get("turn_sha256") != entry.get("turn_sha256")):
            if authored_by_me(post_text, me, expected.get("pre_turn", ""),
                              expected.get("run_id", "")):
                return "review_relay_mutated", "reviewer authored a relay turn instead of artifact delivery"
            return "review_artifact_stale", "relay input changed while the reviewer was running"
        if (after.get("state") != entry.get("state")
                or after.get("holder") != entry.get("holder")):
            return "review_relay_mutated", "relay LOCK changed during reviewer artifact delivery"
        return "review_ready", "review input is unchanged; validate and store the artifact"
    state = after.get("state", "")
    if state == "DONE":
        return "completed", "relay session is DONE"
    authored = authored_by_me(post_text, me, expected.get("pre_turn", ""),
                              expected.get("run_id", ""))
    if authored:
        # #377: authorship alone proved a turn was written; it never proved the
        # premise was still current. The incident behind #320: a run published
        # an answer to a superseded premise and was recorded as a success.
        pre = _turn_int(expected.get("pre_turn"))
        successor = None if pre is None else pre + 1
        if successor not in authored:
            return "premise_superseded", (
                "this run authored a turn, but an intervening turn superseded "
                "the premise between the launch snapshot and the answer")
        if len(authored) > 1:
            # #393 review B2: a runner child has a one-turn contract. Two turns
            # under the same run id mean the certification cannot bind one answer
            # to the premise — the second answered a premise this plan never saw.
            return "premise_superseded", (
                "this run authored more than one turn; certification binds one "
                "answer to one premise and cannot cover a multi-turn run")
        # Deliberately NOT required: that the authored answer is still the newest
        # closed turn. RFC 047 t7 (review B2) protects ping-pong — a peer that
        # consumes the answer and replies within the run window is success, not
        # supersession. The #377 ticket's acceptance 3 asked for the stricter
        # rule; it is renounced here because it contradicts that merged contract.
        plan_digest = expected.get("premise_sha256", "")
        if plan_digest:
            current = turn_block_sha256(post_text, pre)
            if current is None:
                return "premise_superseded", (
                    "the premise block is no longer readable in the post-run "
                    "transcript; refusing to certify against an unverifiable premise")
            if current != plan_digest:
                return "premise_superseded", (
                    "the premise block changed between the plan snapshot and the "
                    "authored answer; the answer addresses a premise that no longer exists")
        return "advanced", ("this run authored exactly the direct successor of "
                            "its premise")
    pre_turn = _turn_int(expected.get("pre_turn"))
    post_turn = _turn_int(after.get("turn"))
    same = pre_turn is not None and post_turn == pre_turn
    if pre_turn is not None and (post_turn is None or post_turn < pre_turn):
        return "external_transition", "turn reset detected (operator reset / re-init during the run)"
    if state == "PAUSED":
        return "suspended", "relay is PAUSED (operator pause or usage cooldown)"
    if state == "IDLE":
        if same and expected.get("pre_state", "") == "IDLE":
            return "non_completion", "provider exited without starting the relay from IDLE"
        return "external_transition", "relay is IDLE without a turn authored by this agent"
    if state == f"AWAITING_{me.upper()}":
        if same:
            return "non_completion", "provider exited without claim/append/done"
        return "external_transition", "turn advanced but was not authored by this agent"
    if state == f"WORKING_{me.upper()}" and after.get("holder", "") == me:
        if same:
            if after.get("integrating"):
                return "external_transition", "integration merge in flight (active integrating sentinel)"
            return "stuck_working", "provider exited holding the pen without append"
        return "external_transition", "own working lock but the turn moved without this agent's authorship"
    return "external_transition", "relay moved to another state outside this run's authorship"


def verification_finding(status, run_id, reason):
    if status not in FAILURE_STATUSES:
        return None
    if status.startswith("review_"):
        return {
            "severity": "error",
            "check": f"headless.{status}",
            "message": f"run {run_id} reviewer delivery failed ({status}: {reason})",
            "hint": "Inspect the bounded reviewer result and relay freshness; no relay recovery is automatic.",
        }
    return {
        "severity": "error",
        "check": "headless.post_run_core_state",
        "message": (
            f"run {run_id} ended without relay completion or authorship "
            f"(status={status}: {reason})"
        ),
        "hint": "Inspect the relay and agent output; no automatic force recovery is performed.",
    }


def verify_post_run(plan, after, post_text=None):
    """Classify a finished run against its immutable plan (RFC 047).

    `after` is the post-run LOCK dict (None = invalid/missing after the bounded
    re-read in read_relay_post_run); `post_text` is the post-run relay text used
    for the authorship check. A reviewer artefact first reaches the internal
    ``review_ready`` state, then becomes success only after bounded persistence.
    Success statuses: completed / advanced / review_delivered_pending.
    Failures (retryable): non_completion / stuck_working / invalid_relay.
    Neutral (never burn retries): external_transition / suspended.
    """
    expected = plan.get("expected_transition") or plan["expected_post_run"]
    status, reason = classify_post_run(expected, after, post_text)
    actual = {
        "state": (after or {}).get("state", ""),
        "holder": (after or {}).get("holder", ""),
        "turn": (after or {}).get("turn", ""),
    }
    ok = status in SUCCESS_STATUSES
    finding = verification_finding(status, plan["run_id"], reason)
    return {
        "ok": ok,
        "status": status,
        "expected": expected,
        "actual": actual,
        "finding": finding,
        "reason": reason,
    }


def set_verification_status(plan, verification, status, reason, *, artifact=None,
                            return_receipt=None, provider_terminal=None):
    """Return one redacted, ledger-safe verification update."""
    result = dict(verification)
    result.update({
        "ok": status in SUCCESS_STATUSES,
        "status": status,
        "reason": reason,
        "finding": verification_finding(status, plan["run_id"], reason),
    })
    if artifact is not None:
        result["review_artifact"] = artifact
    if return_receipt is not None:
        result["review_return_receipt"] = return_receipt
    if provider_terminal is not None:
        result["provider_terminal"] = provider_terminal
    return result


def finalize_review_delivery(plan, verification, output_summary, returncode, runtime_dir):
    """Finish a ready reviewer run without granting it a relay-write success."""
    if verification.get("status") != "review_ready":
        return verification
    if returncode != 0:
        return set_verification_status(
            plan, verification, "review_provider_error", "provider exited non-zero before delivery")
    artifact, error = write_review_artifact(runtime_dir, plan, output_summary)
    if error:
        return set_verification_status(plan, verification, error, error)
    return set_verification_status(
        plan, verification, "review_delivered_pending",
        "bounded reviewer artifact delivered; coordinator consumption is still pending",
        artifact=artifact)


def run_ledger_has_event(args, run_id, event):
    if args.no_run_log:
        return False
    path = os.path.join(args.runtime_dir, "runs.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("run_id") == run_id and row.get("event") == event:
                    return True
    except OSError:
        return False
    return False


def child_env_for_plan(plan, lk, m8shift_path):
    env = {}
    for name in plan["env_allowlist"]:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update({
        "M8SHIFT_ROOT": os.path.dirname(os.path.abspath(m8shift_path)) or os.getcwd(),
        "M8SHIFT_RUN_ID": plan["run_id"],
        "M8SHIFT_AGENT": plan["agent"],
        "M8SHIFT_TURN": lk.get("turn", ""),
    })
    if plan.get("resume_working"):
        # Only a genuine resume launch (started from the agent's own WORKING lock)
        # carries the marker — a normal AWAITING/IDLE launch must never suggest to
        # the provider that a claim can be skipped.
        env[RESUME_ENV] = "1"
    if plan.get("agent_model"):
        # A provider pin is injected directly and wins over any ambient allowlisted
        # declaration. RFC 056 still records it as self-declared/unverified provenance.
        env["M8SHIFT_AGENT_MODEL"] = plan["agent_model"]
    return env


def append_run_event(args, event, run_id, agent, **fields):
    """Append one local runtime event.

    This is a companion-side diagnostic ledger, not core state. It never touches
    `M8SHIFT.md` and never grants or routes the pen.
    """
    if args.no_run_log:
        return
    lk = read_lock(args.m8shift) or {}
    row = {
        "schema": RUNTIME_EVENT_SCHEMA,
        "type": event,
        "event": event,
        "run_id": run_id,
        "agent": agent,
        "ts": iso_now(),
        "runner_version": VERSION,
        "source": {"tool": "headless_runner.py", "version": VERSION},
        "relay": {
            "state": lk.get("state", ""),
            "holder": lk.get("holder", ""),
            "turn": lk.get("turn", ""),
        },
        "idempotency_key": "",
        "payload": dict(fields),
    }
    row.update(fields)
    os.makedirs(args.runtime_dir, exist_ok=True)
    path = os.path.join(args.runtime_dir, "runs.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def validate_args(args):
    if not AGENT_RE.fullmatch(args.agent.lower()):
        raise SystemExit("invalid agent name: expected [a-z][a-z0-9_-]*")
    if args.run_id:
        validate_run_id(args.run_id)
    if args.interval < 1:
        raise SystemExit("--interval must be >= 1")
    if args.max_retries < 1:
        raise SystemExit("--max-retries must be >= 1")
    if args.max_backoff < 1:
        raise SystemExit("--max-backoff must be >= 1")
    if args.heartbeat_before_expiry < 0:
        raise SystemExit("--heartbeat-before-expiry must be >= 0")
    if args.turn_timeout < 0:
        raise SystemExit("--turn-timeout must be >= 0")
    if args.kill_grace < 0:
        raise SystemExit("--kill-grace must be >= 0")
    if args.resume_working and not args.once:
        raise SystemExit("--resume-working requires --once (it is a one-shot recovery "
                         "launch for an already-held WORKING lock, not a polling mode)")
    if args.review_delivery == "artifact" and not args.once:
        raise SystemExit("--review-delivery artifact requires --once; a listener must suppress "
                         "duplicate delivery for the unchanged input turn")
    if args.agent_model and not MODEL_ID_RE.fullmatch(args.agent_model):
        raise SystemExit("invalid agent model: expected a 1-128 character safe model id")
    if args.provider and not PROVIDER_RE.fullmatch(args.provider):
        raise SystemExit("invalid provider: expected [a-z][a-z0-9-]*")


def stop_child(proc, grace):
    """Terminate a timed-out child, then kill after the grace window."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def parse_iso_z(value):
    """Parse M8Shift's UTC `...Z` timestamp, returning None for absent/invalid values."""
    if not value or value == "-":
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        out = dt.datetime.fromisoformat(value)
        if out.tzinfo is None:
            out = out.replace(tzinfo=dt.timezone.utc)
        return out.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def maybe_refresh_ttl(args, me, me_working, run_id):
    """Refresh our own working lock when expiry is close. Never force-steals.

    RFC 047: the heartbeat is `claim <me> --refresh` — a refresh-only core guard that
    can only EXTEND a WORKING lock this agent already holds. A plain `claim` must
    never be used here: between this runner's pre-check and the core file lock, the
    provider may already have appended and the peer handed the turn back, and a plain
    claim would ghost-claim that fresh turn. A failed refresh is recorded as a
    sidecar event and the run continues to post-run classification (never aborts).
    """
    margin = max(0, args.heartbeat_before_expiry)
    if margin == 0:
        return
    lk = read_lock(args.m8shift) or {}
    if lk.get("state") != me_working or lk.get("holder") != me:
        return
    exp = parse_iso_z(lk.get("expires"))
    if exp is None:
        return
    remaining = (exp - dt.datetime.now(dt.timezone.utc)).total_seconds()
    if remaining > margin:
        return
    cmd = [sys.executable, args.m8shift_py, "claim", me, "--refresh"]
    try:
        r = subprocess.run(cmd, check=False, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        exception_type = type(e).__name__
        log(f"heartbeat failed to launch ({exception_type}; heartbeat_launch_error).")
        append_run_event(args, "run.heartbeat_failed", run_id, me,
                         detail="heartbeat_launch_error",
                         signature_id="heartbeat_launch_error",
                         exception_type=exception_type)
        return
    if r.returncode == 0:
        log(f"heartbeat refreshed TTL ({remaining:.0f}s remained).")
        append_run_event(args, "run.heartbeat", run_id, me, remaining_seconds=int(remaining))
    else:
        log(f"heartbeat refresh failed (heartbeat_refused; rc={r.returncode}).")
        append_run_event(args, "run.heartbeat_failed", run_id, me,
                         detail="heartbeat_refused",
                         signature_id="heartbeat_refused",
                         returncode=r.returncode)


def main():
    if sys.argv[1:] == ["--handshake"]:
        runner_handshake()
        return 0
    p = HelpfulArgumentParser(
        usage="%(prog)s AGENT [options] --cmd COMMAND [ARG ...]",
        description=("Run one bounded M8Shift agent turn from a persistent listener. "
                     "Inspect core status first; the runner records immutable plans and "
                     "bounded lifecycle metadata under .m8shift/runtime/ without owning "
                     "the relay pen or persisting provider output."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exit codes (RFC 047, one-shot --once):\n"
            "  0  success — relay completed/advanced, or a verified reviewer artifact is pending\n"
            "  1  run failure — non_completion, stuck_working, invalid_relay, partial/ledger\n"
            "     failure, or the consecutive-failure retry cap was reached\n"
            "  2  argv refusal — argparse rejected the runner invocation\n"
            "  3  external_transition — the relay moved outside this run's authorship (neutral,\n"
            "     never counted as a provider failure by a supervising listener)\n"
            "  4  suspended — relay is PAUSED (operator pause / usage cooldown; neutral)\n"
            "  5  infrastructure — launch failure, immutable run-plan collision, or turn timeout\n"
            "\n"
            "resume-working (RFC 047 PR 2):\n"
            "  --resume-working (with --once) also makes the run eligible when the relay is\n"
            "  WORKING_<agent> with holder == <agent>: the pen is ALREADY held, so no claim\n"
            "  happens — the child gets M8SHIFT_RESUME_WORKING=1 in its environment to signal\n"
            "  'finish the held work, then append/done; do not claim again'. The runner still\n"
            "  heartbeats the TTL via `claim <agent> --refresh` and classifies the run with\n"
            "  the normal table (authored newer turn => advanced; still WORKING same turn =>\n"
            "  stuck_working). The marker is never exported for AWAITING/IDLE launches.\n"
            "\n"
            "--cmd consumes separate argv tokens; it never evaluates a shell string.\n"
            "Keep runner options before --cmd. Quote individual arguments, not the whole command.\n"
            "For pipelines/redirection, invoke an explicit shell or a script.\n"
            "\n"
            "examples:\n"
            "  headless_runner.py agent-a --once --cmd codex exec --full-auto\n"
            "  headless_runner.py agent-b --start-on-idle --cmd claude -p\n"
            "  headless_runner.py agent-a --once --cmd sh -c \"command-one | command-two\"\n"
        ),
    )
    p.add_argument("--version", action="version", version=f"headless_runner.py {VERSION}")
    p.add_argument("agent", help="your agent name (must be in the M8SHIFT.md roster)")
    p.add_argument("--m8shift", default="M8SHIFT.md", help="path to M8SHIFT.md")
    p.add_argument("--start-on-idle", action="store_true",
                   help="this agent starts the relay when state is IDLE (designate ONE)")
    p.add_argument("--resume-working", action="store_true",
                   help="with --once: also start when state is WORKING_<agent> held by this "
                        "agent — resume an interrupted turn WITHOUT claiming; the child gets "
                        "M8SHIFT_RESUME_WORKING=1 (see epilog)")
    p.add_argument("--interval", type=int, default=30, help="poll seconds when waiting")
    p.add_argument("--max-retries", type=int, default=3,
                   help="consecutive failed turns before giving up")
    p.add_argument("--max-backoff", type=int, default=120, help="cap on backoff seconds")
    p.add_argument("--m8shift-py", default="m8shift.py",
                   help="path to m8shift.py used for heartbeat TTL refreshes")
    p.add_argument("--heartbeat-before-expiry", type=int, default=DEFAULT_HEARTBEAT_MARGIN_S,
                   help="seconds before expires to refresh while working; default 300 (5 min), 0 disables")
    p.add_argument("--turn-timeout", type=int, default=0,
                   help="maximum seconds for one agent turn; 0 disables timeout")
    p.add_argument("--kill-grace", type=int, default=10,
                   help="seconds to wait after terminate before kill on timeout")
    p.add_argument("--runtime-dir", default=os.path.join(".m8shift", "runtime"),
                   help="local runtime sidecar dir for runs.jsonl (default: .m8shift/runtime)")
    p.add_argument("--run-id", default="", help="optional path-safe run id (default: generated)")
    p.add_argument("--cwd", default=".", help="working directory for the child command; default current directory")
    p.add_argument("--env-allowlist", default=DEFAULT_ENV_ALLOWLIST,
                   help="comma-separated host env vars copied to the child; M8SHIFT_* vars are always added")
    p.add_argument("--agent-model", default="",
                   help="validated provider model pin exported as M8SHIFT_AGENT_MODEL")
    p.add_argument("--provider", default="",
                   help="validated provider adapter id for terminal-output classification")
    p.add_argument("--expected-transition", choices=("core_state_advanced", "none"),
                   default="core_state_advanced",
                   help="post-run relay transition expectation; none is legacy and never succeeds without proof")
    p.add_argument("--review-delivery", choices=("none", "artifact"), default="none",
                   help="explicit reviewer mode: artifact persists a bounded final response without moving the relay")
    p.add_argument("--no-run-log", action="store_true",
                   help="disable .m8shift/runtime/runs.jsonl lifecycle logging")
    p.add_argument("--once", action="store_true",
                   help="run at most one eligible turn, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="validate configuration, print the command argv as JSON, then exit")
    p.add_argument("--cmd", metavar="COMMAND", nargs=argparse.REMAINDER, required=True,
                   help="executable followed by separate argument tokens, not one quoted shell string; "
                        "for pipes/redirection use explicit sh -c or a script (runs ONE turn)")
    if len(sys.argv) == 1:
        p.print_help()
        return 0
    args = p.parse_args()
    if not args.cmd:
        p.error("--cmd requires the agent command (e.g. --cmd claude -p \"...\")")
    validate_args(args)

    me = args.agent.lower()
    me_working = f"WORKING_{me.upper()}"
    me_awaiting = f"AWAITING_{me.upper()}"
    fails = 0
    if args.dry_run:
        lk0 = read_lock(args.m8shift) or {"state": "IDLE", "turn": "0"}
        relay_text0 = None
        if args.review_delivery == "artifact":
            snapshot_lock, relay_text0 = read_relay_post_run(args.m8shift, attempts=1)
            if snapshot_lock is not None:
                lk0 = snapshot_lock
        try:
            plan = make_run_plan(args, validate_run_id(args.run_id or new_run_id(me)), me, lk0,
                                 resumed=resume_eligible(args, me, me_working, lk0),
                                 relay_text=relay_text0)
        except RunnerInfrastructureError:
            raise SystemExit("provider executable or reviewer input is unavailable")
        print(json.dumps({"agent": me, "cmd": plan["argv"], "run_plan": plan, "runner_version": VERSION}, sort_keys=True))
        return 0

    while True:
        lk = read_lock(args.m8shift)
        if lk is None:
            log(f"{args.m8shift}: not found / invalid LOCK — is the project init'd? waiting.")
            time.sleep(args.interval)
            continue
        state = lk.get("state", "")

        if state == "DONE":
            log("session DONE — exiting.")
            return 0

        resumed = resume_eligible(args, me, me_working, lk)
        my_turn = state == me_awaiting or (state == "IDLE" and args.start_on_idle) or resumed
        if not my_turn:
            time.sleep(args.interval)
            continue

        # Snapshot the relay before launch.  A second read keeps the immutable
        # plan tied to one real relay state rather than to a stale lock observed
        # at the top of this loop — and #377 digests the pre-turn block from it,
        # so `advanced` later certifies against an identified premise.
        snapshot_lock, relay_text = read_relay_post_run(args.m8shift, attempts=1)
        if snapshot_lock is None:
            # #393 review B1: launching without the snapshot would mint a
            # current-schema plan with no premise digest — indistinguishable from
            # a restored legacy plan, it reopens the rewritten-premise hole the
            # digest exists to close. Artifact or core, the launch is refused.
            log("relay snapshot is unavailable or invalid before provider launch; "
                "refusing to launch without an identified premise.")
            if args.once:
                return 5
            time.sleep(args.interval)
            continue
        lk = snapshot_lock
        state = lk.get("state", "")
        resumed = resume_eligible(args, me, me_working, lk)
        my_turn = state == me_awaiting or (state == "IDLE" and args.start_on_idle) or resumed
        if not my_turn:
            time.sleep(args.interval)
            continue
        # #393 review B1, residual form: a readable LOCK whose closed premise
        # block is absent from the very text just snapshotted would still mint a
        # digest-less current-schema plan. A nonzero premise that cannot be
        # digested refuses the launch; turn 0 is the explicit fresh-start
        # exception (a just-initialized relay may have no closed block yet).
        premise_turn = _turn_int(lk.get("turn", ""))
        if premise_turn is None or (
                premise_turn > 0
                and turn_block_sha256(relay_text, premise_turn) is None):
            log(f"the closed block for premise turn {lk.get('turn', '')!r} is not "
                "readable in the launch snapshot; refusing to launch without an "
                "identified premise.")
            if args.once:
                return 5
            time.sleep(args.interval)
            continue

        # It is our turn: run the headless agent for exactly one turn (static argv).
        if resumed:
            log(f"state={state} → resume-working: finishing the held turn (no claim; "
                f"child gets {RESUME_ENV}=1).")
        else:
            log(f"state={state} → running the agent for one turn.")
        run_id = validate_run_id(args.run_id or new_run_id(me))
        try:
            plan = make_run_plan(args, run_id, me, lk, resumed=resumed,
                                 relay_text=relay_text)
        except RunnerInfrastructureError:
            log("could not resolve the provider executable or reviewer input (launch_preflight_failed).")
            append_run_event(args, "run.launch_failed", run_id, me,
                             detail="launch_preflight_failed",
                             signature_id="launch_preflight_failed")
            return 5
        try:
            plan_path = write_run_plan(args.runtime_dir, plan)
        except FileExistsError:
            log(f"immutable run plan already exists for {run_id}; refusing to overwrite.")
            return 5
        append_run_event(args, "run.started", run_id, me, relay_state=state, relay_turn=lk.get("turn", ""),
                         run_plan=plan_path, run_plan_schema=RUN_PLAN_SCHEMA)
        child_env = child_env_for_plan(plan, lk, args.m8shift)
        pre_environment = environment_probe(plan["cwd"], args.runtime_dir)
        try:
            proc = subprocess.Popen(
                plan["argv"], cwd=plan["cwd"], env=child_env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            exception_type = type(e).__name__
            log(f"could not launch the agent ({exception_type}; provider_launch_error).")
            append_run_event(args, "run.launch_failed", run_id, me,
                             detail="provider_launch_error",
                             signature_id="provider_launch_error",
                             exception_type=exception_type)
            return 5
        tee = BoundedTTYTee(proc)
        started = time.monotonic()
        timed_out = False
        while True:
            elapsed = time.monotonic() - started
            if args.turn_timeout and elapsed > args.turn_timeout:
                timed_out = True
                log(f"turn timeout after {args.turn_timeout}s; terminating child.")
                stop_child(proc, args.kill_grace)
                append_run_event(args, "run.timeout", run_id, me, timeout_seconds=args.turn_timeout)
                break
            wait_for = min(args.interval, 30)
            if args.turn_timeout:
                wait_for = max(0.1, min(wait_for, args.turn_timeout - elapsed))
            try:
                proc.wait(timeout=wait_for)
                break
            except subprocess.TimeoutExpired:
                maybe_refresh_ttl(args, me, me_working, run_id)

        output_summary = tee.finish()
        post_environment = environment_probe(plan["cwd"], args.runtime_dir)
        output_fields = {
            "output_bytes": output_summary["bytes"],
            "output_lines": output_summary["lines"],
            "output_signature_ids": output_summary["signature_ids"],
            "output_final_signature_ids": output_summary["final_signature_ids"],
        }

        # Post-run classification (RFC 047): re-read the LOCK (bounded re-read for
        # transient read errors) and the transcript — authorship is the authority.
        after, post_text = read_relay_post_run(args.m8shift)
        verification = verify_post_run(plan, after, post_text)
        status = verification["status"]
        reason = verification.get("reason", "")
        terminal = classify_provider_terminal_output(
            plan.get("provider", ""), output_summary.get("_final_text", ""),
            proc.returncode, verification.get("ok", False))
        review_delivery = (plan.get("review_delivery") or {}).get("type") == "artifact"
        if review_delivery and status == "review_ready":
            # Reviewer delivery has distinct terminal outcomes.  A clean provider
            # exit alone remains insufficient: only finalize_review_delivery can
            # turn this into a successful (but relay-pending) result.
            permission_refused = (
                confirmed_headless_permission_refusal(
                    plan.get("provider", ""), output_summary)
                or (proc.returncode not in (None, 0)
                    and "approval_required" in output_summary.get("signature_ids", ())
                    and (timed_out or "approval_required" in
                         output_summary.get("final_signature_ids", ())))
            )
            environment_refused = confirmed_environment_block(
                pre_environment, post_environment)
            if environment_refused or permission_refused:
                receipt, receipt_error = write_review_return_receipt(
                    args.runtime_dir, plan, output_summary, proc.returncode,
                    evidence_id=("environment_write_probe"
                                 if environment_refused else ""))
                if receipt_error:
                    verification = set_verification_status(
                        plan, verification, receipt_error,
                        "reviewer permission refusal could not produce routing evidence")
                else:
                    verification = set_verification_status(
                        plan, verification, "review_permission_refused",
                        "reviewer provider cannot write the declared artifact or requires permission",
                        return_receipt=receipt)
            elif terminal is not None:
                verification = set_verification_status(
                    plan, verification, terminal["status"], terminal["reason"],
                    provider_terminal=terminal["metadata"])
            elif not timed_out:
                verification = finalize_review_delivery(
                    plan, verification, output_summary, proc.returncode, args.runtime_dir)
            status = verification["status"]
            reason = verification.get("reason", "")
        elif status in FAILURE_STATUSES and confirmed_headless_permission_refusal(
                plan.get("provider", ""), output_summary):
            # #359: the provider auto-denied a tool and exited zero, so the relay
            # never moved. Reported as non_completion this is indistinguishable
            # from a crash, a timeout or a quota wall — and it is deterministic,
            # so retrying spends paid inference on an outcome already decided.
            refused = confirmed_headless_permission_refusal(
                plan.get("provider", ""), output_summary)
            status = "headless_permission_refused"
            reason = f"provider auto-denied permission: {refused}"
            verification = dict(verification)
            verification.update({
                "ok": False,
                "status": status,
                "reason": reason,
                "finding": {
                    "severity": "error",
                    "check": "headless.permission_refused",
                    "message": f"provider auto-denied the {refused!r} permission",
                    "hint": (f"Grant {refused!r} under permissions.allow for this "
                             "provider, then restart the listener; retrying "
                             "cannot change a denied permission."),
                },
            })
        elif status in FAILURE_STATUSES and confirmed_environment_block(
                pre_environment, post_environment):
            status = "environment_blocked"
            reason = "write_probe_denied"
            verification = dict(verification)
            verification.update({
                "ok": False,
                "status": status,
                "reason": reason,
                "finding": {
                    "severity": "error",
                    "check": "headless.environment_write_probe",
                    "message": "provider environment is blocked (write_probe_denied)",
                    "hint": "Grant exact-project workspace write access, then restart the listener.",
                },
            })
        elif confirmed_approval_required(
                output_summary, proc.returncode, status, timed_out=timed_out):
            status = "approval_required"
            reason = "provider_permission_allowlist"
            verification = dict(verification)
            verification.update({
                "ok": False,
                "status": status,
                "reason": reason,
                "finding": {
                    "severity": "error",
                    "check": "headless.approval_required",
                    "message": "provider approval is required (approval_required)",
                    "hint": ("Add only the relay commands from "
                             ".m8shift/PROVIDER-PERMISSIONS.md to the provider's "
                             "documented headless permission allowlist, then restart."),
                },
            })
        elif status in FAILURE_STATUSES and terminal is not None:
            status = terminal["status"]
            reason = terminal["reason"]
            verification = dict(verification)
            verification.update({
                "ok": False,
                "status": status,
                "reason": reason,
                "provider_terminal": terminal["metadata"],
                "finding": {
                    "severity": "error",
                    "check": f"headless.{status}",
                    "message": status,
                    "hint": ("listener will apply the scoped usage hold"
                             if status == "provider_rate_limited" else
                             "operator must verify the reset before restarting"),
                },
            })
        if verification.get("review_artifact"):
            output_fields["review_artifact"] = verification["review_artifact"]
        if verification.get("review_return_receipt"):
            output_fields["review_return_receipt"] = verification["review_return_receipt"]
        post_snapshot = verification["actual"]
        pre_snapshot = {
            "state": lk.get("state", ""),
            "holder": lk.get("holder", ""),
            "turn": lk.get("turn", ""),
        }
        finding = verification.get("finding")
        findings = [finding] if finding else []
        ledger_ok = run_ledger_has_event(args, run_id, "run.started")
        if not ledger_ok:
            findings.append({
                "severity": "error",
                "check": "headless.run_ledger",
                "message": f"run {run_id} has no run.started ledger event",
            })
        if finding:
            append_run_event(args, "run.verification_failed", run_id, me,
                             verification=verification, runtime_findings=findings)
        process_ok = proc.returncode == 0
        success = (not timed_out) and process_ok and verification["ok"] and ledger_ok
        once_rc = 1
        # A timeout is transport state, not a replacement for a classification
        # whose own doctrine already says no retry.  Keep all three closed sets
        # explicit so adding a member changes this branch only through its named
        # policy constant (and the per-member witnesses fail closed).
        timeout_preserved_statuses = (
            TERMINAL_FAILURE_STATUSES
            + PROVIDER_RATE_LIMIT_STATUSES
            + NEUTRAL_STATUSES
        )
        if timed_out and status not in timeout_preserved_statuses:
            fails += 1
            once_rc = 5
            append_run_event(args, "run.ended", run_id, me, status="timeout",
                             returncode=proc.returncode, relay_state=post_snapshot["state"],
                             relay_turn=post_snapshot["turn"],
                             verification_ok=verification["ok"],
                             verification_status=status,
                             ledger_ok=ledger_ok,
                             success=False,
                             runtime_findings=findings, **output_fields)
        elif status in NEUTRAL_STATUSES:
            # external_transition / suspended are NEUTRAL: not a provider failure, so
            # the consecutive-failure counter stays UNCHANGED — sleep, back to polling.
            log(f"run ended {status}: {reason} (retry counter unchanged).")
            append_run_event(args, "run.ended", run_id, me, status=status,
                             returncode=proc.returncode, relay_state=post_snapshot["state"],
                             relay_turn=post_snapshot["turn"],
                             verification_ok=False,
                             verification_status=status,
                             ledger_ok=ledger_ok,
                             success=False,
                             reason=reason,
                             runtime_findings=findings, **output_fields)
            if args.once:
                return 3 if status == "external_transition" else 4
            time.sleep(args.interval)
            continue
        elif status in FAILURE_STATUSES + TERMINAL_FAILURE_STATUSES + \
                PROVIDER_RATE_LIMIT_STATUSES:
            # non_completion / stuck_working / invalid_relay are run failures even
            # when the provider exited rc 0 — never force-recovered, only retried.
            rate_limited = status in PROVIDER_RATE_LIMIT_STATUSES
            # A terminal status names a condition the same call cannot resolve --
            # a denied permission, a blocked workspace, a required approval. The
            # tuple has always been named terminal; until #359 it was folded into
            # the ordinary retry branch, so the name promised a termination the
            # code never performed. Neither it nor a rate limit consumes a retry.
            terminal = status in TERMINAL_FAILURE_STATUSES
            if not rate_limited and not terminal:
                fails += 1
                log(f"run classified {status}: {reason} ({fails}/{args.max_retries}).")
            elif terminal:
                log(f"run classified {status}: {reason} (terminal; retry counter "
                    "unchanged, lane stopping).")
            else:
                log(f"run classified {status}: {reason} (retry counter unchanged).")
            if status == "non_completion":
                append_run_event(args, "run.non_completion", run_id, me,
                                 pre=pre_snapshot, post=post_snapshot, reason=reason)
            append_run_event(args, "run.ended", run_id, me, status=status,
                             returncode=proc.returncode, relay_state=post_snapshot["state"],
                             relay_turn=post_snapshot["turn"],
                             verification_ok=False,
                             verification_status=status,
                             ledger_ok=ledger_ok,
                             success=False,
                             reason=reason,
                             provider_terminal=verification.get("provider_terminal"),
                             runtime_findings=findings, **output_fields)
            if rate_limited or terminal:
                return 1
        elif success:
            # completed/advanced are relay progress; review_delivered_pending is
            # only a verified sidecar delivery and must not be narrated as one.
            fails = 0
            append_run_event(args, "run.ended", run_id, me, status=status,
                             returncode=proc.returncode, relay_state=post_snapshot["state"],
                             relay_turn=post_snapshot["turn"],
                             verification_ok=True,
                             verification_status=status,
                             ledger_ok=True,
                             success=True,
                             runtime_findings=[], **output_fields)
            if args.once:
                return 0
        else:
            # relay classification succeeded but the process/ledger side failed.
            fails += 1
            if verification["ok"] and not process_ok:
                ended_status = "failed_partial"
                log(f"agent advanced the relay but exited non-zero ({fails}/{args.max_retries}).")
            else:
                ended_status = "failed_missing_ledger"
                log(f"agent advanced the relay but run ledger is incomplete ({fails}/{args.max_retries}).")
            append_run_event(args, "run.ended", run_id, me, status=ended_status,
                             returncode=proc.returncode, relay_state=post_snapshot["state"],
                             relay_turn=post_snapshot["turn"],
                             verification_ok=verification["ok"],
                             verification_status=status,
                             ledger_ok=ledger_ok,
                             success=False,
                             runtime_findings=findings, **output_fields)

        if fails >= args.max_retries:
            log("retry cap reached — stopping; leaving the pen for manual recovery.")
            append_run_event(args, "run.retry_cap", run_id, me, failures=fails)
            return 1
        if args.once:
            return once_rc
        if fails:
            time.sleep(min(args.interval * (2 ** fails), args.max_backoff))


if __name__ == "__main__":
    sys.exit(main())
