#!/usr/bin/env python3
"""m8shift-context.py — optional context companion for M8Shift.

Phase 1 is intentionally native and boring: it builds referenced context packs,
records receipts and metrics, and benchmarks "raw context" versus "native pack"
without external dependencies. It never edits the core relay and never decides who
may write.
"""
import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time

VERSION = "3.38.0"
SCHEMA_PACK = "m8shift.context.pack.v1"
SCHEMA_RECEIPT = "m8shift.context.receipt.v1"
SCHEMA_METRICS = "m8shift.context.metrics.v1"
SCHEMA_PROFILE = "m8shift.context.profile.v1"
SCHEMA_ADAPTER = "m8shift.adapter.v1"
SCHEMA_ADAPTER_RESULT = "m8shift.adapter.result.v1"
SCHEMA_COMPRESSED_CONTEXT_RECORD = "m8shift.compressed_context_record.v1"
SCHEMA_CONTEXT_DIGEST = "m8shift.context_digest.v1"
SCHEMA_HANDOFF_DIGEST = "m8shift.handoff_digest.v1"
SCHEMA_RAW_OUTPUT_REFERENCE = "m8shift.raw_output_reference.v1"
SCHEMA_COMPRESSION_CONFIG = "m8shift.context_compression.config.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
TURN_RE = re.compile(
    r"<!-- M8SHIFT:TURN (?P<num>\d+) (?P<author>[a-z][a-z0-9_-]*) BEGIN -->"
    r"(?P<body>.*?)"
    r"<!-- M8SHIFT:TURN (?P=num) (?P=author) END -->",
    re.DOTALL,
)
FIELD_RE = re.compile(r"^- (?P<key>[a-z_]+):\s*(?P<value>.*)$")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
COMPRESSION_RECORD_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
PROFILE_NAMES = ("implementer", "reviewer", "tester", "gatekeeper", "maintainer")
GIT_TIMEOUT_SECONDS = 10
MAX_HASH_BYTES = 512 * 1024 * 1024
DEFAULT_RETRIEVAL_LINES = 80
MAX_RETRIEVAL_LINES = 500
MAX_GREP_PATTERN_CHARS = 128
MAX_GREP_SCAN_BYTES = 1024 * 1024
MAX_GREP_LINE_CHARS = 4096
COMPRESSION_RTK_CONTENT_TYPES = {"shell_output", "test_output", "logs", "log", "git_output"}
ADAPTER_TYPES = {"shell_output_filter", "context_transform", "reporter", "doctor_check"}
ADAPTER_AUTHORITIES = {"read_only", "advisory", "host_action", "mutating_m8shift_command"}
ADAPTER_FAILURE_POLICIES = {"fallback_original", "fail_closed"}
ADAPTER_NAME_RE = re.compile(r"[a-z][a-z0-9_.:-]{0,127}\Z")
ADAPTER_PROGRAM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}\Z")
ALLOWED_ADAPTER_PROGRAMS = {"rtk"}
DENIED_ADAPTER_PROGRAMS = {"m8shift.py", "m8shift-runtime.py", "m8shift-worktree.py", "m8shift-context.py"}


DEFAULT_ADAPTERS = {
    "rtk-shell-output": {
        "schema": SCHEMA_ADAPTER,
        "name": "rtk-shell-output",
        "type": "shell_output_filter",
        "version": "0.1.0",
        "authority": "advisory",
        "command": ["rtk", "$M8SHIFT_ADAPTER_MODE_ARGS"],
        "capabilities": ["filter_errors", "compact_tests", "compact_logs", "compact_listings"],
        "input_schema": "m8shift.shell_output_filter.request.v1",
        "output_schema": "m8shift.shell_output_filter.response.v1",
        "mutates_core": False,
        "mutates_repo": False,
        "requires_env": [],
        "timeout_seconds": 30,
        "max_stdout_bytes": 1048576,
        "max_stderr_bytes": 65536,
        "failure_policy": "fallback_original",
        "modes": {
            "err": ["err"],
            "test": ["test"],
            "log": ["git", "log"],
            "ls": ["ls"],
            "git-diff": ["git", "diff"],
        },
        "policy": {
            "recommended_modes": ["err", "test", "log", "ls"],
            "forbidden_modes": {
                "git-diff": (
                    "Do not use RTK git diff for code review: Round 2 measurement found it "
                    "lossy for hunks; read raw diffs instead."
                )
            },
            "not_evidence": True,
            "operator_installs": "RTK is not bundled; install rtk separately on the host.",
            "network": "M8Shift invokes RTK only as a local argv subprocess; telemetry is disabled on init/adapters init when rtk is present.",
        },
    },
}


DEFAULT_COMPRESSION_CONFIG = {
    "schema": SCHEMA_COMPRESSION_CONFIG,
    "enabled": True,
    "default_backend": "auto",
    "measurement": {
        "estimate_basis": "proxy_bytes_div_4",
        "measure_before_send": True,
        "record_metrics": True,
    },
    "thresholds": {
        "compress_above_tokens": 2000,
        "reference_only_above_tokens": 20000,
        "warn_above_tokens": 90000,
        "hard_limit_tokens": 120000,
    },
    "policy": {
        "preserve_raw": True,
        "redact_before_store": True,
        "include_raw_ref": True,
        "include_token_estimates": True,
        "never_compress": ["secrets", "credentials", "private_keys", "tokens"],
    },
    "retrieval": {
        "default_lines": DEFAULT_RETRIEVAL_LINES,
        "max_lines": MAX_RETRIEVAL_LINES,
        "max_grep_pattern_chars": MAX_GREP_PATTERN_CHARS,
        "max_grep_scan_bytes": MAX_GREP_SCAN_BYTES,
        "max_grep_line_chars": MAX_GREP_LINE_CHARS,
    },
    "redaction": {
        "pattern_set": "m8shift.secret_patterns.v2",
    },
}

SECRET_PATTERNS = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        "authorization_header",
        re.compile(r"(?im)^(\s*Authorization\s*:\s*(?:Bearer|Basic)\s+)\S+"),
        r"\1[REDACTED]",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        "Bearer [REDACTED]",
    ),
    (
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        "slack_token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        "[REDACTED_SLACK_TOKEN]",
    ),
    (
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        "[REDACTED_GOOGLE_API_KEY]",
    ),
    (
        "stripe_key",
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}\b"),
        "[REDACTED_STRIPE_KEY]",
    ),
    (
        "openai_key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        "anthropic_key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "[REDACTED_AWS_KEY]",
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        "url_inline_credentials",
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@\s/]+(@)"),
        r"\1[REDACTED]\2",
    ),
    (
        "assignment_secret_identifier",
        re.compile(
            r"(?i)\b([A-Za-z0-9_.-]*(?:secret|token|api[_-]?key|apikey|password|passwd|access[_-]?key|private[_-]?key)[A-Za-z0-9_.-]*)"
            r"(\s*[:=]\s*)"
            r"([\"']?)[^\s\"']+([\"']?)"
        ),
        r"\1\2\3[REDACTED]\4",
    ),
    (
        "assignment_secret",
        re.compile(
            r"(?i)\b(api[_-]?key|token|password|passwd|secret|access[_-]?token|private[_-]?key)\b"
            r"(\s*[:=]\s*)"
            r"([\"']?)[^\s\"']+([\"']?)"
        ),
        r"\1\2\3[REDACTED]\4",
    ),
)

ERROR_LINE_RE = re.compile(r"\b(error|exception|traceback|failed|failure|fatal|warning|assertionerror)\b", re.IGNORECASE)
EXIT_CODE_RE = re.compile(r"\b(?:exit(?:ed)?(?:\s+code)?|returncode|return code|rc)\s*[:=]?\s*(-?\d+)\b", re.IGNORECASE)
PATH_RE = re.compile(r"(?:(?:[A-Za-z]:)?[/\\][^\s:;]+|[A-Za-z0-9_.@%+=:-]+(?:/[A-Za-z0-9_.@%+=:-]+)+)")
UNSAFE_GREP_RE = re.compile(r"(\([^)]*[+*?][^)]*\)[+*?{]|\[[^\]]*[+*?][^\]]*\][+*?{]|(?:\.\*){3,}|\{\d+(?:,\d*)?\})")


DEFAULT_PROFILES = {
    "implementer": {
        "purpose": "Enough scoped context to implement and verify one assigned change.",
        "include": ["relay_status", "latest_handoff", "tasks", "memory", "git_summary", "selected_files"],
        "limits": {"target_proxy_tokens": 12000, "raw_log_inline_limit_lines": 80, "code_snippet_inline_limit_lines": 120},
        "required_preservation": ["ask", "done", "decision", "files", "blocked_on", "waiver_reason"],
    },
    "reviewer": {
        "purpose": "Enough evidence to review independently without copying raw session history.",
        "include": ["relay_status", "latest_handoff", "tasks", "git_summary", "selected_files"],
        "limits": {"target_proxy_tokens": 12000, "raw_log_inline_limit_lines": 80, "code_snippet_inline_limit_lines": 120},
        "required_preservation": ["ask", "done", "decision", "files", "test failures", "source references"],
    },
    "tester": {
        "purpose": "Commands, failures, changed files, and reproduction context.",
        "include": ["relay_status", "latest_handoff", "git_summary", "selected_files"],
        "limits": {"target_proxy_tokens": 8000, "raw_log_inline_limit_lines": 120, "code_snippet_inline_limit_lines": 80},
        "required_preservation": ["ask", "done", "files", "commands", "test failures"],
    },
    "gatekeeper": {
        "purpose": "Build a compact task packet before delegation or handoff.",
        "include": ["relay_status", "latest_handoff", "tasks", "memory", "git_summary"],
        "limits": {"target_proxy_tokens": 6000, "raw_log_inline_limit_lines": 60, "code_snippet_inline_limit_lines": 80},
        "required_preservation": ["objective", "scope", "constraints", "decisions", "expected output"],
    },
    "maintainer": {
        "purpose": "Decisions, risks, open questions, and next-session notes.",
        "include": ["relay_status", "latest_handoff", "tasks", "memory", "git_summary"],
        "limits": {"target_proxy_tokens": 10000, "raw_log_inline_limit_lines": 80, "code_snippet_inline_limit_lines": 80},
        "required_preservation": ["decision", "rationale", "blocked_on", "risks", "source references"],
    },
}


def die(message):
    raise SystemExit(f"m8shift-context: {message}")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t=None):
    return (t or now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def root_from(args):
    return os.path.abspath(args.root or os.environ.get("M8SHIFT_ROOT") or HERE)


def rel(root, path):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def safe_join(root, path, label="path"):
    if not path:
        die(f"{label} is empty")
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    candidate = os.path.realpath(os.path.abspath(candidate))
    root_abs = os.path.realpath(os.path.abspath(root))
    try:
        common = os.path.commonpath([root_abs, candidate])
    except ValueError:
        common = ""
    if common != root_abs:
        die(f"{label} escapes project root: {path!r}")
    return candidate


def context_dir(root):
    return os.path.join(root, ".m8shift", "context")


def packs_dir(root):
    return os.path.join(context_dir(root), "packs")


def receipts_dir(root):
    return os.path.join(context_dir(root), "receipts")


def profiles_dir(root):
    return os.path.join(context_dir(root), "profiles")


def adapters_dir(root):
    return os.path.join(context_dir(root), "adapters")


def compression_dir(root):
    return os.path.join(context_dir(root), "compression")


def compression_records_dir(root):
    return os.path.join(compression_dir(root), "records")


def compression_raw_dir(root):
    return os.path.join(compression_dir(root), "raw")


def compression_compact_dir(root):
    return os.path.join(compression_dir(root), "compact")


def compression_config_path(root):
    return os.path.join(root, ".m8shift", "context-compression.json")


def metrics_path(root):
    return os.path.join(context_dir(root), "metrics.jsonl")


def benchmarks_path(root):
    return os.path.join(context_dir(root), "benchmarks.jsonl")


def ensure_dirs(root):
    for path in (
        context_dir(root),
        packs_dir(root),
        receipts_dir(root),
        profiles_dir(root),
        adapters_dir(root),
        compression_dir(root),
        compression_records_dir(root),
        compression_raw_dir(root),
        compression_compact_dir(root),
    ):
        os.makedirs(path, exist_ok=True)


def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return default
    except OSError as e:
        die(f"cannot read {path}: {e}")


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as e:
        die(f"cannot read JSON {path}: {e}")


def read_json_diagnostic(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return default, None
    except (OSError, json.JSONDecodeError, RecursionError, ValueError) as e:
        return default, str(e)
    return data, None


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as e:
                    die(f"{path}:{n}: {e}")
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        return []
    return rows


def read_jsonl_diagnostic(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, RecursionError, ValueError) as e:
                    return rows, f"{path}:{n}: {e}"
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return [], str(e)
    return rows, None


def latest_context_metrics(root):
    rows, err = read_jsonl_diagnostic(metrics_path(root))
    findings = []
    if err:
        findings.append(finding("warning", "metrics.unreadable", f"{rel(root, metrics_path(root))}: {err}"))
    if not rows:
        return None, findings
    row = rows[-1]
    return {
        "pack_id": row.get("pack_id", ""),
        "profile": row.get("profile", ""),
        "compression_ratio": row.get("compression_ratio"),
        "estimated_proxy_tokens_before": row.get("estimated_proxy_tokens_before"),
        "estimated_proxy_tokens_after": row.get("estimated_proxy_tokens_after"),
        "timestamp_utc": row.get("timestamp_utc", ""),
    }, findings


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("not a regular file")
    if st.st_size > MAX_HASH_BYTES:
        raise ValueError(f"file too large to hash ({st.st_size} bytes > {MAX_HASH_BYTES})")
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as e:
        die(f"cannot hash {path}: {e}")
    return h.hexdigest()


def size_metrics(text):
    data = text.encode("utf-8")
    return {
        "bytes": len(data),
        "estimated_proxy_tokens": len(data) // 4,
        "lines": len(text.splitlines()),
    }


def merge_dict(base, override):
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def default_compression_config():
    return copy.deepcopy(DEFAULT_COMPRESSION_CONFIG)


def load_compression_config(root):
    path = compression_config_path(root)
    data, err = read_json_diagnostic(path, None)
    if err:
        return default_compression_config(), [
            finding("warning", "compression.config_unreadable", f"{rel(root, path)}: {err}; using redacted reference-only fail-safe")
        ], True
    if data is None:
        return default_compression_config(), [
            finding("warning", "compression.config_missing", f"{rel(root, path)} is missing; using redacted reference-only fail-safe")
        ], True
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_COMPRESSION_CONFIG:
        return default_compression_config(), [
            finding("warning", "compression.config_schema", f"{rel(root, path)} has invalid schema; using redacted reference-only fail-safe")
        ], True
    return merge_dict(DEFAULT_COMPRESSION_CONFIG, data), [], False


def compression_policy(config):
    policy = config.get("policy")
    return policy if isinstance(policy, dict) else {}


def compression_retrieval(config):
    retrieval = config.get("retrieval")
    return retrieval if isinstance(retrieval, dict) else {}


def bounded_int(value, default, minimum, maximum):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def retrieval_int(config, key, default, minimum, maximum):
    return bounded_int(compression_retrieval(config).get(key, default), default, minimum, maximum)


def redaction_enabled(config):
    return bool(compression_policy(config).get("redact_before_store", True))


def redact_text(text, config):
    if not redaction_enabled(config):
        redaction = config.get("redaction")
        redaction = redaction if isinstance(redaction, dict) else {}
        return text, {
            "enabled": False,
            "pattern_set": redaction.get("pattern_set", "disabled"),
            "applied_count": 0,
            "matches": {},
        }
    redacted = text
    matches = {}
    applied = 0
    for name, pattern, repl in SECRET_PATTERNS:
        redacted, count = pattern.subn(repl, redacted)
        if count:
            matches[name] = count
            applied += count
    return redacted, {
        "enabled": True,
        "pattern_set": "m8shift.secret_patterns.v2",
        "applied_count": applied,
        "matches": matches,
    }


def valid_record_id(record_id, label="record id"):
    if not COMPRESSION_RECORD_ID_RE.fullmatch(record_id or ""):
        die(f"unsafe {label}: {record_id!r}")
    return record_id


def record_json_path(root, record_id):
    valid_record_id(record_id)
    return safe_join(root, os.path.join(compression_records_dir(root), f"{record_id}.json"), "record path")


def record_raw_path(root, record_id):
    valid_record_id(record_id)
    return safe_join(root, os.path.join(compression_raw_dir(root), f"{record_id}.raw.txt"), "raw reference path")


def record_compact_path(root, record_id):
    valid_record_id(record_id)
    return safe_join(root, os.path.join(compression_compact_dir(root), f"{record_id}.compact.txt"), "compact reference path")


def truncate_lines(text, limit):
    lines = text.splitlines()
    if limit <= 0 or len(lines) <= limit:
        return text, False
    omitted = len(lines) - limit
    return "\n".join(lines[:limit] + [f"... [{omitted} lines omitted by m8shift-context native packer]"]), True


def parse_lock(text):
    start = "<!-- M8SHIFT:LOCK:BEGIN -->"
    end = "<!-- M8SHIFT:LOCK:END -->"
    if start not in text or end not in text:
        return {}
    body = text.split(start, 1)[1].split(end, 1)[0]
    out = {}
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_turn_fields(body):
    fields = {}
    extra = []
    current = None
    for line in body.strip("\n").splitlines():
        m = FIELD_RE.match(line)
        if m:
            current = m.group("key")
            fields[current] = m.group("value")
        elif current and (line.startswith("  ") or line.startswith("\t")):
            fields[current] += "\n" + line.strip()
        else:
            extra.append(line)
    if extra:
        fields["body"] = "\n".join(extra).strip()
    return fields


def parse_turns(text):
    turns = []
    for m in TURN_RE.finditer(text):
        fields = parse_turn_fields(m.group("body"))
        fields.update({"turn": int(m.group("num")), "author": m.group("author")})
        turns.append(fields)
    return turns


def git(root, args):
    try:
        r = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def load_profile(root, name):
    if name not in PROFILE_NAMES:
        die(f"unknown profile {name!r}")
    path = os.path.join(profiles_dir(root), f"{name}.json")
    data = read_json(path, None)
    if isinstance(data, dict) and data.get("schema") == SCHEMA_PROFILE:
        return data
    base = DEFAULT_PROFILES[name].copy()
    base.update({"schema": SCHEMA_PROFILE, "name": name})
    return base


def default_profile_json(name):
    data = DEFAULT_PROFILES[name].copy()
    data.update({"schema": SCHEMA_PROFILE, "name": name})
    return data


def latest_turns(turns, count):
    if count <= 0:
        return []
    return sorted(turns, key=lambda t: t.get("turn", 0))[-count:]


def source(source_id, kind, content, path=None, **extra):
    row = {
        "source_id": source_id,
        "kind": kind,
        "path": path,
        "sha256": sha256_text(content),
        "metrics": size_metrics(content),
    }
    row.update(extra)
    return row


def collect_context(root, args, profile):
    relay = read_text(os.path.join(root, "M8SHIFT.md"))
    lock = parse_lock(relay)
    turns = parse_turns(relay)
    selected = latest_turns(turns, args.turns)
    adapter_status = select_context_adapter(root, args)
    sources = [
        source("relay_lock", "core_status", json.dumps(lock, ensure_ascii=False, sort_keys=True), "M8SHIFT.md"),
        source("latest_turns", "handoff_turns", json.dumps(selected, ensure_ascii=False, sort_keys=True), "M8SHIFT.md"),
    ]

    tasks = read_text(os.path.join(root, "M8SHIFT.tasks.md"))
    if tasks:
        clipped, truncated = truncate_lines(tasks, profile["limits"]["raw_log_inline_limit_lines"])
        sources.append(source("tasks", "task_ledger", clipped, "M8SHIFT.tasks.md", truncated=truncated))

    memory = read_text(os.path.join(root, "M8SHIFT.memory.md"))
    if memory:
        clipped, truncated = truncate_lines(memory, profile["limits"]["raw_log_inline_limit_lines"])
        sources.append(source("memory", "memory", clipped, "M8SHIFT.memory.md", truncated=truncated))

    git_summary = "\n".join([
        "$ git status --short --branch",
        git(root, ["status", "--short", "--branch"]),
        "",
        "$ git diff --stat",
        git(root, ["diff", "--stat"]),
        "",
        "$ git diff --name-only",
        git(root, ["diff", "--name-only"]),
    ]).strip() + "\n"
    git_summary, git_adapter = filter_shell_output(root, args, adapter_status, git_summary, "log")
    sources.append(source("git_summary", "git_summary", git_summary, None, adapter=git_adapter))

    for i, relpath in enumerate(args.include or [], 1):
        path = safe_join(root, relpath, "include path")
        body = read_text(path)
        clipped, truncated = truncate_lines(body, profile["limits"]["code_snippet_inline_limit_lines"])
        sources.append(source(f"included_file_{i}", "selected_file", clipped, rel(root, path), truncated=truncated))

    raw_input = "\n\n".join(s.get("source_id", "") + "\n" + read_source_content(root, s) for s in sources)
    return {"lock": lock, "turns": selected, "sources": sources, "raw_input": raw_input}


def read_source_content(root, src):
    path = src.get("path")
    if path in {"M8SHIFT.md", "M8SHIFT.tasks.md", "M8SHIFT.memory.md"}:
        return read_text(os.path.join(root, path))
    if src.get("kind") == "git_summary":
        return git(root, ["status", "--short", "--branch"])
    return ""


def fenced(label, text):
    if not text:
        text = "—"
    return f"```text\n{text.rstrip()}\n```"


def render_pack(root, profile_name, profile, collected, args, pack_id):
    lock = collected["lock"]
    turns = collected["turns"]
    lines = [
        "# M8Shift Context Pack",
        "",
        f"- schema: `{SCHEMA_PACK}`",
        f"- pack_id: `{pack_id}`",
        f"- generated_at: `{iso()}`",
        f"- profile: `{profile_name}`",
        f"- agent: `{args.agent or '—'}`",
        f"- m8shift_context_version: `{VERSION}`",
        "",
        "> This pack is an operational view, not evidence. Verify against original files,",
        "> original logs, retrieved originals, tests, and diffs.",
        "",
        "## Relay status",
        "",
        fenced("lock", "\n".join(f"{k}: {v}" for k, v in sorted(lock.items()))),
        "",
        "## Latest handoff contract fields",
        "",
    ]
    if not turns:
        lines.extend(["No turn found.", ""])
    for turn in turns:
        lines.extend([
            f"### Turn {turn.get('turn')} — {turn.get('from', turn.get('author', '—'))} → {turn.get('to', '—')}",
            "",
            "#### ask (verbatim)",
            "",
            fenced("ask", turn.get("ask", "—")),
            "",
            "#### done (verbatim)",
            "",
            fenced("done", turn.get("done", "—")),
            "",
        ])
        decisions = [k for k in ("decision", "decisions", "waiver_reason", "blocked_on") if turn.get(k)]
        if decisions:
            lines.extend(["#### decisions / blockers (verbatim)", ""])
            lines.append(fenced("decisions", "\n".join(f"{k}: {turn[k]}" for k in decisions)))
            lines.append("")
        if turn.get("files"):
            lines.extend(["#### files", "", fenced("files", turn["files"]), ""])

    lines.extend(["## Supporting sources", ""])
    for src in collected["sources"]:
        lines.extend([
            f"### {src['source_id']} — {src['kind']}",
            "",
            f"- path: `{src.get('path') or '—'}`",
            f"- sha256: `{src['sha256']}`",
            f"- bytes: `{src['metrics']['bytes']}`",
            f"- proxy_tokens: `{src['metrics']['estimated_proxy_tokens']}`",
            f"- lines: `{src['metrics']['lines']}`",
        ])
        if src.get("truncated"):
            lines.append("- truncated: `true`")
        if src.get("adapter", {}).get("name"):
            adapter = src["adapter"]
            lines.append(f"- adapter: `{adapter.get('name')}`")
            lines.append(f"- adapter_mode: `{adapter.get('mode')}`")
            lines.append(f"- adapter_status: `{adapter.get('status')}`")
            if adapter.get("fallback_reason"):
                lines.append(f"- adapter_fallback_reason: `{adapter.get('fallback_reason')}`")
        lines.append("")

    lines.extend([
        "## Source references",
        "",
        "| source_id | kind | path | sha256 |",
        "|---|---|---|---|",
    ])
    for src in collected["sources"]:
        lines.append(f"| `{src['source_id']}` | `{src['kind']}` | `{src.get('path') or '—'}` | `{src['sha256']}` |")
    lines.append("")
    return "\n".join(lines)


def metrics_row(pack_id, profile, input_text, output_text, warnings=None, real=None):
    before = size_metrics(input_text)
    after = size_metrics(output_text)
    ratio = 0 if before["bytes"] == 0 else round(after["bytes"] / before["bytes"], 6)
    row = {
        "schema": SCHEMA_METRICS,
        "timestamp_utc": iso(),
        "pack_id": pack_id,
        "profile": profile,
        "input_bytes": before["bytes"],
        "output_bytes": after["bytes"],
        "estimated_proxy_tokens_before": before["estimated_proxy_tokens"],
        "estimated_proxy_tokens_after": after["estimated_proxy_tokens"],
        "line_count_before": before["lines"],
        "line_count_after": after["lines"],
        "compression_ratio": ratio,
        "required_fields_preserved": True,
        "real_tokens_before": None,
        "real_tokens_after": None,
        "real_token_reduction": None,
        "warnings": warnings or [],
    }
    if real:
        rb, ra = real.get("before"), real.get("after")
        if isinstance(rb, int) and isinstance(ra, int):
            row["real_tokens_before"] = rb
            row["real_tokens_after"] = ra
            row["real_token_reduction"] = rb - ra
    return row


def receipt_row(root, pack_id, pack_path, collected, metrics):
    return {
        "schema": SCHEMA_RECEIPT,
        "timestamp_utc": iso(),
        "pack_id": pack_id,
        "tool": "m8shift-context.py",
        "version": VERSION,
        "artifact": {
            "kind": "context_pack",
            "path": rel(root, pack_path),
            "sha256": sha256_text(read_text(pack_path)),
            "content_type": "text/markdown",
        },
        "metrics": metrics,
        "references": [
            {
                "source_id": src["source_id"],
                "kind": src["kind"],
                "path": src.get("path"),
                "sha256": src["sha256"],
            }
            for src in collected["sources"]
        ],
        "warning": "Compressed or compacted context is not evidence; verify against originals.",
    }


def cmd_init(args):
    root = root_from(args)
    ensure_dirs(root)
    wrote = []
    for name in PROFILE_NAMES:
        path = os.path.join(profiles_dir(root), f"{name}.json")
        if os.path.exists(path) and not args.force:
            continue
        write_json(path, default_profile_json(name))
        wrote.append(rel(root, path))
    for name in DEFAULT_ADAPTERS:
        path = os.path.join(adapters_dir(root), f"{name}.json")
        if os.path.exists(path) and not args.force:
            continue
        write_json(path, default_adapter_manifest(name))
        wrote.append(rel(root, path))
    config_path = compression_config_path(root)
    if args.force or not os.path.exists(config_path):
        write_json(config_path, default_compression_config())
        wrote.append(rel(root, config_path))
    readme = os.path.join(context_dir(root), "README.md")
    if args.force or not os.path.exists(readme):
        write_text(readme, (
            "# M8Shift context companion\n\n"
            "Generated context packs, receipts, metrics, adapter manifests, compression records, and benchmarks live here.\n"
            "Packs are operational views only; verification uses original sources.\n"
            "Compression records store redacted raw references and compact digests under `compression/`.\n"
            "When RTK is present and identity-pinned, packs may use the RTK shell-output adapter by default; use `pack --adapter native` to opt out.\n"
        ))
        wrote.append(rel(root, readme))
    telemetry = rtk_telemetry_disable()
    print(f"✓ context companion initialized ({len(wrote)} files written)")
    for path in wrote:
        print(f"  {path}")
    if telemetry.get("present"):
        print(f"✓ rtk telemetry disable attempted (disabled={str(telemetry.get('disabled')).lower()})")
    return 0


def pack_output_path(root, args, pack_id):
    if args.output:
        return safe_join(root, args.output, "output path")
    return os.path.join(packs_dir(root), f"{pack_id}.md")


def cmd_pack(args):
    root = root_from(args)
    profile = load_profile(root, args.profile)
    pack_id = f"ctx_{iso().replace('-', '').replace(':', '')}_{args.profile}"
    collected = collect_context(root, args, profile)
    body = render_pack(root, args.profile, profile, collected, args, pack_id)
    metrics = metrics_row(pack_id, args.profile, collected["raw_input"], body)
    if args.write or args.output:
        ensure_dirs(root)
        out = pack_output_path(root, args, pack_id)
        write_text(out, body)
        receipt = receipt_row(root, pack_id, out, collected, metrics)
        write_json(os.path.join(receipts_dir(root), f"{pack_id}.json"), receipt)
        append_jsonl(metrics_path(root), metrics)
        if args.json:
            print(json.dumps({"pack": rel(root, out), "receipt": receipt, "metrics": metrics}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"✓ wrote {rel(root, out)}")
        return 0
    if args.json:
        print(json.dumps({"pack_id": pack_id, "content": body, "metrics": metrics}, ensure_ascii=False, sort_keys=True))
    else:
        print(body)
    return 0


def latest_json_file(path):
    try:
        files = [os.path.join(path, p) for p in os.listdir(path) if p.endswith(".json")]
    except FileNotFoundError:
        return None
    return max(files, key=os.path.getmtime) if files else None


def cmd_receipt(args):
    root = root_from(args)
    if args.id:
        if not SAFE_ID_RE.fullmatch(args.id):
            die("unsafe receipt id")
        path = os.path.join(receipts_dir(root), f"{args.id}.json")
    else:
        path = latest_json_file(receipts_dir(root))
    if not path or not os.path.exists(path):
        die("no receipt found")
    data = read_json(path, {})
    if args.json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{data.get('pack_id', '—')} {data.get('artifact', {}).get('path', '—')}")
    return 0


def cmd_metrics(args):
    root = root_from(args)
    rows = read_jsonl(metrics_path(root))
    if args.last:
        rows = rows[-1:]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row.get('pack_id')} profile={row.get('profile')} "
                f"proxy={row.get('estimated_proxy_tokens_before')}→{row.get('estimated_proxy_tokens_after')} "
                f"real={row.get('real_tokens_before')}→{row.get('real_tokens_after')}"
            )
    return 0


def fixture_text(size):
    ask = "Implement the context companion; preserve ask/done/decision fields verbatim."
    done = "Baseline collected. Native pack should reference sources instead of pasting logs."
    decision = "Compression is never evidence; originals remain the source of truth."
    repeated = {
        "small": 20,
        "medium": 180,
        "large": 900,
    }[size]
    logs = "\n".join(f"log line {i}: noisy but non-essential detail" for i in range(repeated))
    return (
        f"- ask: {ask}\n"
        f"- done: {done}\n"
        f"- decision: {decision}\n\n"
        "## Raw logs\n"
        f"{logs}\n"
    )


def native_compact_fixture(text):
    fields = []
    logs = []
    for line in text.splitlines():
        if line.startswith(("- ask:", "- done:", "- decision:", "- decisions:")):
            fields.append(line)
        elif line.startswith("log line "):
            logs.append(line)
    kept_logs = logs[:8]
    omitted = max(0, len(logs) - len(kept_logs))
    out = ["# Native compact fixture", "", "## Preserved contract fields", *fields, "", "## Log excerpt", *kept_logs]
    if omitted:
        out.append(f"... [{omitted} log lines omitted; original fixture remains the evidence]")
    out.extend(["", "## Source references", "- fixture: built-in"])
    return "\n".join(out) + "\n"


def load_real_tokens(path):
    if not path:
        return {}
    data = read_json(path, {})
    if not isinstance(data, dict):
        die("--real-tokens must be a JSON object")
    return data


def real_pair(data, fixture):
    row = data.get(fixture, {})
    if not isinstance(row, dict):
        return None
    before = row.get("without")
    after = row.get("with")
    if isinstance(before, int) and isinstance(after, int):
        return {"before": before, "after": after}
    return None


def cmd_benchmark(args):
    root = root_from(args)
    real_counts = load_real_tokens(args.real_tokens)
    rows = []
    warnings = []
    for name in ("small", "medium", "large"):
        raw = fixture_text(name)
        packed = native_compact_fixture(raw)
        real = real_pair(real_counts, name)
        row = metrics_row(f"benchmark_{name}_{args.profile}", args.profile, raw, packed, real=real)
        row["fixture"] = name
        row["mode"] = "without_vs_native_pack"
        row["ship_gate_passed"] = bool(
            isinstance(row["real_tokens_before"], int)
            and isinstance(row["real_tokens_after"], int)
            and row["real_tokens_after"] < row["real_tokens_before"]
            and row["estimated_proxy_tokens_after"] < row["estimated_proxy_tokens_before"]
        )
        if row["real_tokens_before"] is None:
            row["warnings"].append("missing real token counts; proxy-only benchmark cannot green-light shipping")
            warnings.append(f"{name}: missing real token counts")
        rows.append(row)
    gate = all(row["ship_gate_passed"] for row in rows)
    result = {
        "schema": "m8shift.context.benchmark.v1",
        "timestamp_utc": iso(),
        "profile": args.profile,
        "fixtures": rows,
        "ship_gate_passed": gate,
        "warnings": warnings,
    }
    if args.write:
        ensure_dirs(root)
        append_jsonl(benchmarks_path(root), result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['fixture']}: proxy "
                f"{row['estimated_proxy_tokens_before']}→{row['estimated_proxy_tokens_after']} "
                f"real {row['real_tokens_before']}→{row['real_tokens_after']} "
                f"gate={'pass' if row['ship_gate_passed'] else 'hold'}"
            )
        print(f"ship_gate_passed={'true' if gate else 'false'}")
    if args.require_real_tokens and not gate:
        return 1
    return 0


def adapter_path(root, name):
    if not ADAPTER_NAME_RE.fullmatch(name or ""):
        die(f"unsafe adapter name {name!r}")
    return os.path.join(adapters_dir(root), f"{name}.json")


def load_adapter(root, name):
    path = adapter_path(root, name)
    data = read_json(path, None)
    if data is None and name in DEFAULT_ADAPTERS:
        return DEFAULT_ADAPTERS[name]
    if not isinstance(data, dict):
        die(f"adapter manifest not found: {name}")
    return data


def load_adapter_diagnostic(root, name):
    path = adapter_path(root, name)
    data, err = read_json_diagnostic(path, None)
    if err:
        return None, [finding("error", "adapter.manifest_unreadable", f"{name}: cannot read adapter manifest: {err}")]
    if data is None:
        if name in DEFAULT_ADAPTERS:
            return DEFAULT_ADAPTERS[name], []
        return None, [finding("error", "adapter.missing", f"adapter manifest not found: {name}")]
    if not isinstance(data, dict):
        return None, [finding("error", "adapter.schema", f"{name}: manifest is not a JSON object")]
    return data, []


def load_adapter_for_auto(root, name):
    path = adapter_path(root, name)
    if not os.path.exists(path):
        if name in DEFAULT_ADAPTERS:
            return DEFAULT_ADAPTERS[name], []
        return None, [finding("error", "adapter.missing", f"adapter manifest not found: {name}")]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return None, [finding("error", "adapter.manifest_unreadable", f"{name}: cannot read adapter manifest: {e}")]
    if not isinstance(data, dict):
        return None, [finding("error", "adapter.schema", f"{name}: manifest is not a JSON object")]
    return data, []


def adapter_identity_for_program(program):
    resolved = shutil_which(program)
    if not resolved:
        return None
    real = os.path.realpath(resolved)
    try:
        digest = sha256_file(real)
    except (OSError, ValueError):
        return None
    return {
        "program": program,
        "path": real,
        "sha256": digest,
    }


def default_adapter_manifest(name):
    manifest = copy.deepcopy(DEFAULT_ADAPTERS[name])
    command = manifest.get("command")
    if isinstance(command, list) and command:
        identity = adapter_identity_for_program(command[0])
        if identity:
            manifest["trusted_executable"] = identity
    return manifest


def adapter_findings(manifest, check_executable=True):
    findings = []
    if not isinstance(manifest, dict):
        return [finding("error", "adapter.schema", "manifest is not a JSON object")]
    name = manifest.get("name", "")
    if manifest.get("schema") != SCHEMA_ADAPTER:
        findings.append(finding("error", "adapter.schema", f"{name or '<unknown>'}: expected {SCHEMA_ADAPTER}"))
    if not ADAPTER_NAME_RE.fullmatch(name):
        findings.append(finding("error", "adapter.name", "adapter name is invalid"))
    if manifest.get("type") not in ADAPTER_TYPES:
        findings.append(finding("error", "adapter.type", f"{name}: unsupported adapter type"))
    if manifest.get("authority") not in ADAPTER_AUTHORITIES:
        findings.append(finding("error", "adapter.authority", f"{name}: unsupported authority"))
    if manifest.get("authority") != "advisory":
        findings.append(finding("error", "adapter.authority", f"{name}: shell-output filters must remain advisory"))
    command = manifest.get("command")
    if isinstance(command, str):
        findings.append(finding("error", "adapter.command_string", f"{name}: command must be an argv array, not a shell string"))
    elif not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        findings.append(finding("error", "adapter.command", f"{name}: command must be a non-empty argv array"))
    elif command:
        program = command[0]
        if "/" in program or "\\" in program or program in {".", ".."} or program.startswith("-"):
            findings.append(finding("error", "adapter.program_path", f"{name}: command[0] must be a bare allowlisted program name"))
        elif not ADAPTER_PROGRAM_RE.fullmatch(program):
            findings.append(finding("error", "adapter.program_name", f"{name}: command[0] is not a safe program name"))
        elif program in DENIED_ADAPTER_PROGRAMS:
            findings.append(finding("error", "adapter.program_denied", f"{name}: command[0] may not be a M8Shift relay binary"))
        elif program not in ALLOWED_ADAPTER_PROGRAMS:
            findings.append(finding("error", "adapter.program_not_allowed", f"{name}: command[0] {program!r} is not in the adapter allowlist"))
        elif check_executable:
            resolved = shutil_which(program)
            if resolved is None:
                findings.append(finding("error", "adapter.executable_missing", f"{name}: executable {program!r} not found on PATH"))
            elif adapter_resolves_to_denied_program(resolved):
                findings.append(finding("error", "adapter.program_resolved_denied", f"{name}: executable {program!r} resolves to a M8Shift relay binary"))
            else:
                findings.extend(adapter_identity_findings(manifest, program, resolved))
    if manifest.get("mutates_core") is not False:
        findings.append(finding("error", "adapter.mutates_core", f"{name}: mutates_core must be false"))
    if manifest.get("mutates_repo") is not False:
        findings.append(finding("error", "adapter.mutates_repo", f"{name}: mutates_repo must be false"))
    timeout = manifest.get("timeout_seconds")
    if not isinstance(timeout, int) or not (1 <= timeout <= 300):
        findings.append(finding("error", "adapter.timeout", f"{name}: timeout_seconds must be 1..300"))
    max_stdout = manifest.get("max_stdout_bytes")
    if not isinstance(max_stdout, int) or not (1 <= max_stdout <= 10 * 1024 * 1024):
        findings.append(finding("error", "adapter.max_stdout", f"{name}: max_stdout_bytes must be 1..10485760"))
    max_stderr = manifest.get("max_stderr_bytes", 65536)
    if not isinstance(max_stderr, int) or not (1 <= max_stderr <= 10 * 1024 * 1024):
        findings.append(finding("error", "adapter.max_stderr", f"{name}: max_stderr_bytes must be 1..10485760"))
    if manifest.get("failure_policy") not in ADAPTER_FAILURE_POLICIES:
        findings.append(finding("error", "adapter.failure_policy", f"{name}: unsupported failure_policy"))
    requires_env = manifest.get("requires_env", [])
    if not isinstance(requires_env, list) or not all(isinstance(v, str) and re.fullmatch(r"[A-Z_][A-Z0-9_]*", v) for v in requires_env):
        findings.append(finding("error", "adapter.requires_env", f"{name}: requires_env must be env var names"))
    for env_name in requires_env if isinstance(requires_env, list) else []:
        if env_name not in os.environ:
            findings.append(finding("error", "adapter.env_missing", f"{name}: missing env {env_name}"))
    modes = manifest.get("modes", {})
    if modes and (not isinstance(modes, dict) or not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) and x for x in v) for k, v in modes.items())):
        findings.append(finding("error", "adapter.modes", f"{name}: modes must map names to argv fragments"))
    return findings


def shutil_which(executable):
    for folder in os.environ.get("PATH", os.defpath).split(os.pathsep):
        path = os.path.join(folder, executable)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def adapter_resolves_to_denied_program(path):
    return os.path.basename(os.path.realpath(path)) in DENIED_ADAPTER_PROGRAMS


def adapter_identity_findings(manifest, program, resolved):
    name = manifest.get("name", "")
    trusted = manifest.get("trusted_executable")
    if not isinstance(trusted, dict):
        return [finding("error", "adapter.trusted_executable", f"{name}: missing trusted executable identity; rerun `adapters init --force` with a trusted {program!r} on PATH")]
    expected_program = trusted.get("program")
    expected_path = trusted.get("path")
    expected_sha = trusted.get("sha256")
    if expected_program != program:
        return [finding("error", "adapter.trusted_executable", f"{name}: trusted executable program must be {program!r}")]
    if not isinstance(expected_path, str) or not os.path.isabs(expected_path):
        return [finding("error", "adapter.trusted_executable", f"{name}: trusted executable path must be absolute")]
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        return [finding("error", "adapter.trusted_executable", f"{name}: trusted executable sha256 is invalid")]
    real = os.path.realpath(resolved)
    if real != expected_path:
        return [finding("error", "adapter.program_identity_mismatch", f"{name}: executable {program!r} resolved to {real}, expected {expected_path}")]
    try:
        actual_sha = sha256_file(real)
    except (OSError, ValueError) as e:
        return [finding("error", "adapter.program_identity_mismatch", f"{name}: cannot hash executable {program!r}: {e}")]
    if actual_sha != expected_sha:
        return [finding("error", "adapter.program_identity_mismatch", f"{name}: executable {program!r} sha256 {actual_sha} does not match trusted sha256 {expected_sha}")]
    return []


def adapter_mode_args(manifest, mode):
    modes = manifest.get("modes") if isinstance(manifest.get("modes"), dict) else {}
    if mode:
        if mode not in modes:
            die(f"adapter mode {mode!r} is not declared by {manifest.get('name')}")
        forbidden = manifest.get("policy", {}).get("forbidden_modes", {})
        if isinstance(forbidden, dict) and mode in forbidden:
            die(f"adapter mode {mode!r} is forbidden: {forbidden[mode]}")
        return modes.get(mode, [])
    return []


def render_adapter_command(manifest, mode):
    mode_args = adapter_mode_args(manifest, mode)
    out = []
    for arg in manifest.get("command", []):
        if arg == "$M8SHIFT_ADAPTER_MODE_ARGS":
            out.extend(mode_args)
        elif arg == "$M8SHIFT_ADAPTER_MODE":
            out.append(mode)
        else:
            out.append(arg)
    if out:
        resolved = shutil_which(out[0])
        if not resolved:
            die(f"adapter executable not found on PATH: {out[0]}")
        if adapter_resolves_to_denied_program(resolved):
            die(f"adapter executable resolves to a M8Shift relay binary: {out[0]}")
        identity_errors = adapter_identity_findings(manifest, out[0], resolved)
        if identity_errors:
            die("; ".join(row["message"] for row in identity_errors))
        out[0] = resolved
    return out


def adapter_env(manifest):
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    for key in manifest.get("requires_env", []):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def read_adapter_input(root, args):
    if args.stdin:
        return sys.stdin.read()
    if args.input:
        return read_text(safe_join(root, args.input, "input path"))
    die("adapter run requires --stdin or --input")


def adapter_result(manifest, *, mode, original, filtered, fallback_used=False, error="", stderr=""):
    return {
        "schema": SCHEMA_ADAPTER_RESULT,
        "adapter": manifest.get("name", ""),
        "adapter_type": manifest.get("type", ""),
        "mode": mode,
        "status": "fallback" if fallback_used else "ok",
        "fallback_used": fallback_used,
        "error": error,
        "stderr": stderr,
        "input_schema": manifest.get("input_schema", ""),
        "output_schema": manifest.get("output_schema", ""),
        "original_sha256": sha256_text(original),
        "filtered_sha256": sha256_text(filtered),
        "original_metrics": size_metrics(original),
        "filtered_metrics": size_metrics(filtered),
        "filtered_text": filtered,
        "warning": "Adapter output is an operational view, not evidence; verify against raw output when decisions depend on exact text.",
    }


def read_limited_stream(pipe, limit, chunks, overflow, label, stop_event):
    total = 0
    try:
        while not stop_event.is_set():
            chunk = pipe.read(4096)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                overflow.append(f"{label} exceeded limit {limit} bytes")
                stop_event.set()
                break
            chunks.append(chunk)
    finally:
        with contextlib.suppress(Exception):
            pipe.close()


def run_adapter_process(root, manifest, mode, text):
    command = render_adapter_command(manifest, mode)
    stdout_chunks = []
    stderr_chunks = []
    overflow = []
    stop_event = threading.Event()
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=root,
            env=adapter_env(manifest),
        )
    except OSError as e:
        return None, str(e), ""
    readers = [
        threading.Thread(
            target=read_limited_stream,
            args=(proc.stdout, manifest.get("max_stdout_bytes", 1048576), stdout_chunks, overflow, "stdout", stop_event),
            daemon=True,
        ),
        threading.Thread(
            target=read_limited_stream,
            args=(proc.stderr, manifest.get("max_stderr_bytes", 65536), stderr_chunks, overflow, "stderr", stop_event),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    input_error = ""
    try:
        if proc.stdin:
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()
    except (BrokenPipeError, OSError) as e:
        input_error = str(e)
    deadline = time.monotonic() + manifest.get("timeout_seconds", 30)
    while proc.poll() is None:
        if overflow:
            proc.kill()
            break
        if time.monotonic() > deadline:
            proc.kill()
            overflow.append(f"adapter timed out after {manifest.get('timeout_seconds', 30)}s")
            break
        time.sleep(0.01)
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
    stop_event.set()
    for reader in readers:
        reader.join(timeout=1)
    stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if overflow:
        return None, "; ".join(overflow), stderr
    if input_error and proc.returncode not in (0, None):
        return None, input_error, stderr
    if proc.returncode != 0:
        return None, f"adapter exited {proc.returncode}", stderr
    return stdout, "", stderr


def select_context_adapter(root, args):
    choice = getattr(args, "adapter", "auto") or "auto"
    if choice == "native":
        return {"selected": "native", "manifest": None, "reason": "operator opt-out"}
    if choice == "rtk-shell-output":
        manifest = load_adapter(root, "rtk-shell-output")
        findings = adapter_findings(manifest)
        errors = [row for row in findings if row["severity"] == "error"]
        if errors:
            die("; ".join(row["message"] for row in errors))
        return {"selected": "rtk-shell-output", "manifest": manifest, "reason": "operator-selected adapter"}
    manifest, findings = load_adapter_for_auto(root, "rtk-shell-output")
    if findings or manifest is None:
        return {
            "selected": "native",
            "manifest": None,
            "reason": "rtk manifest invalid; native fallback",
            "findings": findings,
        }
    findings = adapter_findings(manifest)
    errors = [row for row in findings if row["severity"] == "error"]
    if errors:
        return {
            "selected": "native",
            "manifest": None,
            "reason": "rtk absent, unpinned, or invalid; native fallback",
            "findings": errors,
        }
    return {"selected": "rtk-shell-output", "manifest": manifest, "reason": "rtk present and identity-pinned"}


def filter_shell_output(root, args, adapter_status, text, mode):
    manifest = adapter_status.get("manifest")
    if not manifest:
        return text, {}
    filtered, error, stderr = run_adapter_process(root, manifest, mode, text)
    if filtered is None:
        if manifest.get("failure_policy") != "fallback_original":
            die(error or "adapter failed")
        return text, {
            "name": manifest.get("name", ""),
            "mode": mode,
            "status": "fallback",
            "fallback_reason": error,
            "stderr": stderr,
        }
    return filtered, {
        "name": manifest.get("name", ""),
        "mode": mode,
        "status": "ok",
    }


def read_compression_input(root, args):
    if args.stdin:
        return sys.stdin.read()
    if args.input:
        return read_text(safe_join(root, args.input, "input path"))
    die("compress requires --stdin or --input")


def builtin_manifest():
    return {
        "schema": SCHEMA_ADAPTER,
        "name": "builtin",
        "type": "context_transform",
        "version": VERSION,
        "authority": "advisory",
        "input_schema": "text/plain",
        "output_schema": SCHEMA_COMPRESSED_CONTEXT_RECORD,
        "mutates_core": False,
        "mutates_repo": False,
        "failure_policy": "fail_closed",
    }


def collapse_repeated_lines(lines):
    out = []
    groups = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j] == line:
            j += 1
        count = j - i
        if count >= 3:
            out.append(line)
            marker = f"... [previous line repeated {count - 1} more times]"
            out.append(marker)
            groups.append({"line": line[:240], "count": count})
        else:
            out.extend(lines[i:j])
        i = j
    return out, groups


def head_tail_lines(lines, total_limit):
    if total_limit <= 0 or len(lines) <= total_limit:
        return lines, 0
    head = max(1, total_limit // 2)
    tail = max(1, total_limit - head - 1)
    omitted = len(lines) - head - tail
    return lines[:head] + [f"... [{omitted} lines omitted; retrieve bounded raw reference for evidence]"] + lines[-tail:], omitted


def unique_limited(values, limit):
    out = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def extract_builtin_signals(text):
    lines = text.splitlines()
    error_lines = []
    exit_codes = []
    paths = []
    for number, line in enumerate(lines, 1):
        if ERROR_LINE_RE.search(line):
            error_lines.append({"line": number, "text": line[:500]})
        for match in EXIT_CODE_RE.finditer(line):
            exit_codes.append(match.group(1))
        for match in PATH_RE.finditer(line):
            paths.append(match.group(0).rstrip(".,);]\"'"))
    return {
        "errors": error_lines[:30],
        "exit_codes": unique_limited(exit_codes, 10),
        "paths": unique_limited(paths, 30),
    }


def render_builtin_digest(record_id, text, content_type, config):
    max_lines = retrieval_int(config, "max_lines", MAX_RETRIEVAL_LINES, 1, MAX_RETRIEVAL_LINES)
    line_limit = retrieval_int(config, "default_lines", DEFAULT_RETRIEVAL_LINES, 1, max_lines)
    lines = text.splitlines()
    collapsed, repeated_groups = collapse_repeated_lines(lines)
    excerpt_lines, omitted = head_tail_lines(collapsed, line_limit)
    signals = extract_builtin_signals(text)
    status = "failed" if signals["errors"] or any(code not in {"0", ""} for code in signals["exit_codes"]) else "unknown"
    out = [
        "# M8Shift builtin context digest",
        "",
        f"- record_id: `{record_id}`",
        f"- content_type: `{content_type}`",
        f"- status: `{status}`",
        f"- source_lines: `{len(lines)}`",
        f"- source_bytes: `{size_metrics(text)['bytes']}`",
        f"- bounded_raw_retrieval: `true`",
        "",
    ]
    if signals["exit_codes"]:
        out.extend(["## Exit codes", ""])
        out.extend(f"- `{code}`" for code in signals["exit_codes"])
        out.append("")
    if signals["errors"]:
        out.extend(["## Error / warning lines", ""])
        for row in signals["errors"]:
            out.append(f"- L{row['line']}: {row['text']}")
        out.append("")
    if signals["paths"]:
        out.extend(["## Paths detected", ""])
        out.extend(f"- `{path}`" for path in signals["paths"])
        out.append("")
    if repeated_groups:
        out.extend(["## Repeated-line collapses", ""])
        for group in repeated_groups[:20]:
            out.append(f"- `{group['count']}` × `{group['line']}`")
        out.append("")
    out.extend(["## Head/tail excerpt", "", "```text"])
    out.extend(excerpt_lines)
    out.append("```")
    if omitted:
        out.extend(["", f"> {omitted} collapsed lines omitted. Use bounded retrieval for raw evidence."])
    return "\n".join(out).rstrip() + "\n", signals, repeated_groups, omitted


def render_external_backend_digest(record_id, backend, text, compact_text, content_type, config):
    max_lines = retrieval_int(config, "max_lines", MAX_RETRIEVAL_LINES, 1, MAX_RETRIEVAL_LINES)
    line_limit = retrieval_int(config, "default_lines", DEFAULT_RETRIEVAL_LINES, 1, max_lines)
    signals = extract_builtin_signals(text)
    excerpt_lines, omitted = head_tail_lines(compact_text.splitlines(), line_limit)
    status = "failed" if signals["errors"] or any(code not in {"0", ""} for code in signals["exit_codes"]) else "unknown"
    out = [
        f"# M8Shift {backend} context digest",
        "",
        f"- record_id: `{record_id}`",
        f"- backend: `{backend}`",
        f"- content_type: `{content_type}`",
        f"- status: `{status}`",
        f"- source_lines: `{len(text.splitlines())}`",
        f"- compact_lines: `{len(compact_text.splitlines())}`",
        f"- bounded_raw_retrieval: `true`",
        "",
    ]
    if signals["exit_codes"]:
        out.extend(["## Exit codes preserved from redacted raw", ""])
        out.extend(f"- `{code}`" for code in signals["exit_codes"])
        out.append("")
    if signals["errors"]:
        out.extend(["## Error / warning lines preserved from redacted raw", ""])
        for row in signals["errors"]:
            out.append(f"- L{row['line']}: {row['text']}")
        out.append("")
    if signals["paths"]:
        out.extend(["## Paths detected in redacted raw", ""])
        out.extend(f"- `{path}`" for path in signals["paths"])
        out.append("")
    out.extend(["## Adapter compact output", "", "```text"])
    out.extend(excerpt_lines)
    out.append("```")
    if omitted:
        out.extend(["", f"> {omitted} compact lines omitted. Use bounded retrieval for raw evidence."])
    return "\n".join(out).rstrip() + "\n", signals, [], omitted


def reference_only_text(record_id, raw_ref, reason):
    return (
        "# M8Shift reference-only context digest\n\n"
        f"- record_id: `{record_id}`\n"
        f"- raw_ref: `{raw_ref}`\n"
        f"- reason: `{reason or 'fail-closed reference-only'}`\n"
        "- inline_raw: `false`\n"
        "- bounded_raw_retrieval: `true`\n\n"
        "> Compression failed closed. Retrieve bounded redacted raw evidence explicitly.\n"
    )


def make_context_digest(record_id, content_type, raw_ref, compact_ref, signals, fallback_used, reason):
    errors = signals.get("errors", []) if isinstance(signals, dict) else []
    exit_codes = signals.get("exit_codes", []) if isinstance(signals, dict) else []
    status = "reference_only" if fallback_used else ("failed" if errors or any(code not in {"0", ""} for code in exit_codes) else "unknown")
    return {
        "schema": SCHEMA_CONTEXT_DIGEST,
        "record_id": record_id,
        "content_type": content_type,
        "status": status,
        "summary": reason if fallback_used else "Compact digest generated from redacted raw content.",
        "errors": errors[:10],
        "exit_codes": exit_codes,
        "paths": (signals.get("paths", []) if isinstance(signals, dict) else [])[:20],
        "raw_ref": raw_ref,
        "compact_ref": compact_ref,
        "bounded_retrieval_required": True,
        "not_evidence": True,
    }


def make_handoff_digest(record_id, agent, content_type, raw_ref, compact_ref, fallback_used, reason):
    return {
        "schema": SCHEMA_HANDOFF_DIGEST,
        "record_id": record_id,
        "agent": agent or "",
        "content_type": content_type,
        "summary": reason if fallback_used else "Use the compact digest for orientation and the bounded raw reference for verification.",
        "evidence": [
            {"kind": "raw_output_reference", "record_id": record_id, "path": raw_ref, "bounded": True},
            {"kind": "compact_digest", "record_id": record_id, "path": compact_ref, "bounded": True},
        ],
        "next_actions": [],
        "not_evidence": True,
    }


def compression_record_id(args):
    if args.id:
        return valid_record_id(args.id)
    stamp = iso().replace("-", "").replace(":", "")
    suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", (args.type or "context").strip("-"))[:40] or "context"
    return valid_record_id(f"ccr-{stamp}-{suffix}")


def compression_backend_result(*, filtered, error="", extras=None, manifest=None, backend="", mode="", findings=None):
    return {
        "filtered": filtered,
        "error": error,
        "extras": extras or ({}, [], 0),
        "manifest": manifest or builtin_manifest(),
        "backend": backend or "builtin",
        "mode": mode or "",
        "findings": findings or [],
    }


def builtin_backend_result(args, redacted, config, findings=None):
    filtered, signals, repeated_groups, omitted_lines = render_builtin_digest(args.id, redacted, args.type, config)
    return compression_backend_result(
        filtered=filtered,
        extras=(signals, repeated_groups, omitted_lines),
        manifest=builtin_manifest(),
        backend="builtin",
        mode=args.type,
        findings=findings,
    )


def rtk_mode_for_content_type(content_type):
    return {
        "test_output": "test",
        "shell_output": "err",
        "logs": "log",
        "log": "log",
        "git_output": "log",
    }.get(content_type, "err")


def compression_rtk_result(root, args, redacted, config, explicit=False):
    manifest, findings = load_adapter_for_auto(root, "rtk-shell-output")
    if manifest is None:
        reason = "; ".join(row["message"] for row in findings) or "rtk-shell-output adapter unavailable"
        if explicit:
            return compression_backend_result(filtered=None, error=reason, backend="rtk-shell-output", findings=findings)
        return builtin_backend_result(args, redacted, config, findings + [
            finding("warning", "compression.rtk_fallback", f"RTK unavailable; builtin fallback: {reason}")
        ])
    findings.extend(adapter_findings(manifest))
    errors = [row for row in findings if row["severity"] == "error"]
    if errors:
        reason = "; ".join(row["message"] for row in errors)
        if explicit:
            return compression_backend_result(filtered=None, error=reason, manifest=manifest, backend="rtk-shell-output", findings=findings)
        return builtin_backend_result(args, redacted, config, findings + [
            finding("warning", "compression.rtk_fallback", f"RTK invalid; builtin fallback: {reason}")
        ])
    mode = rtk_mode_for_content_type(args.type)
    try:
        compact, error, stderr = run_adapter_process(root, manifest, mode, redacted)
    except SystemExit as e:
        compact, error, stderr = None, str(e), ""
    if compact is None:
        reason = error or "rtk-shell-output adapter failed"
        if explicit:
            return compression_backend_result(filtered=None, error=reason, manifest=manifest, backend="rtk-shell-output", mode=mode, findings=findings)
        return builtin_backend_result(args, redacted, config, findings + [
            finding("warning", "compression.rtk_fallback", f"RTK failed; builtin fallback: {reason}")
        ])
    filtered, signals, repeated_groups, omitted_lines = render_external_backend_digest(
        args.id,
        "rtk-shell-output",
        redacted,
        compact,
        args.type,
        config,
    )
    if stderr:
        findings.append(finding("info", "compression.rtk_stderr", stderr[:500]))
    return compression_backend_result(
        filtered=filtered,
        extras=(signals, repeated_groups, omitted_lines),
        manifest=manifest,
        backend="rtk-shell-output",
        mode=mode,
        findings=findings,
    )


def compact_backend(root, args, redacted, config, config_fail_safe):
    if config_fail_safe:
        return compression_backend_result(filtered=None, error="missing or malformed compression config", backend=args.backend)
    if not ADAPTER_NAME_RE.fullmatch(args.backend or ""):
        return compression_backend_result(filtered=None, error=f"unsafe backend id {args.backend!r}", backend=args.backend)
    if args.backend == "builtin":
        return builtin_backend_result(args, redacted, config)
    if args.backend == "rtk-shell-output":
        return compression_rtk_result(root, args, redacted, config, explicit=True)
    if args.backend == "auto":
        if args.type in COMPRESSION_RTK_CONTENT_TYPES:
            return compression_rtk_result(root, args, redacted, config, explicit=False)
        return builtin_backend_result(args, redacted, config)
    return compression_backend_result(filtered=None, error=f"unsupported or unavailable backend {args.backend!r}", backend=args.backend)


def cmd_compress(args):
    root = root_from(args)
    ensure_dirs(root)
    args.id = compression_record_id(args)
    config, config_findings, config_fail_safe = load_compression_config(root)
    raw = read_compression_input(root, args)
    try:
        redacted, redaction = redact_text(raw, config)
    except Exception as e:  # defensive fail-closed boundary; redaction should not raise.
        config_findings.append(finding("error", "compression.redaction_failed", f"redaction failed: {e}"))
        redacted = ""
        redaction = {"enabled": True, "pattern_set": "m8shift.secret_patterns.v2", "applied_count": 0, "matches": {}, "failed": True}
        config_fail_safe = True
    raw_path = record_raw_path(root, args.id)
    compact_path = record_compact_path(root, args.id)
    record_path = record_json_path(root, args.id)
    write_text(raw_path, redacted)
    raw_ref = rel(root, raw_path)
    compact_ref = rel(root, compact_path)

    backend_result = compact_backend(root, args, redacted, config, config_fail_safe)
    filtered = backend_result["filtered"]
    backend_error = backend_result["error"]
    extras = backend_result["extras"]
    manifest = backend_result["manifest"]
    backend_findings = backend_result["findings"]
    fallback_used = filtered is None
    signals = {}
    repeated_groups = []
    omitted_lines = 0
    if fallback_used:
        filtered = reference_only_text(args.id, raw_ref, backend_error)
    else:
        signals, repeated_groups, omitted_lines = extras
    write_text(compact_path, filtered)

    result = adapter_result(
        manifest,
        mode=backend_result["mode"] or args.type,
        original=raw,
        filtered=filtered,
        fallback_used=fallback_used,
        error=backend_error or "",
        stderr="",
    )
    before = size_metrics(raw)
    after = size_metrics(filtered)
    ratio = 0 if before["bytes"] == 0 else round(after["bytes"] / before["bytes"], 6)
    raw_reference = {
        "schema": SCHEMA_RAW_OUTPUT_REFERENCE,
        "record_id": args.id,
        "path": raw_ref,
        "sha256": sha256_text(redacted),
        "metrics": size_metrics(redacted),
        "redacted": redaction_enabled(config),
        "redaction": redaction,
        "bounded_retrieval_required": True,
    }
    context_digest = make_context_digest(args.id, args.type, raw_ref, compact_ref, signals, fallback_used, backend_error)
    handoff_digest = make_handoff_digest(args.id, args.agent, args.type, raw_ref, compact_ref, fallback_used, backend_error)
    record = {
        "schema": SCHEMA_COMPRESSED_CONTEXT_RECORD,
        "id": args.id,
        "created_at": iso(),
        "agent": args.agent or "",
        "content_type": args.type,
        "backend": backend_result["backend"],
        "requested_backend": args.backend,
        "backend_version": manifest.get("version", ""),
        "adapter_result": result,
        "context_digest": context_digest,
        "handoff_digest": handoff_digest,
        "raw_output_reference": raw_reference,
        "estimated_proxy_tokens_before": before["estimated_proxy_tokens"],
        "estimated_proxy_tokens_after": after["estimated_proxy_tokens"],
        "compression_ratio": ratio,
        "estimate_basis": "proxy_bytes_div_4",
        "reversible": True,
        "fallback_used": fallback_used,
        "status": "reference_only" if fallback_used else "ok",
        "storage": {
            "record_ref": rel(root, record_path),
            "raw_ref": raw_ref,
            "compact_ref": compact_ref,
        },
        "config": {
            "path": rel(root, compression_config_path(root)),
            "valid": not config_fail_safe,
        },
        "redaction": redaction,
        "builtin": {
            "signals": signals,
            "repeated_groups": repeated_groups[:20],
            "omitted_excerpt_lines": omitted_lines,
        },
        "findings": config_findings + backend_findings,
        "warning": "Compressed context is operational orientation, not evidence; verify against bounded raw references.",
    }
    write_json(record_path, record)
    if args.json:
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    else:
        print(f"✓ wrote {rel(root, record_path)}")
        if fallback_used:
            print(f"  reference-only: {backend_error}")
    return 0


def parse_line_selector(selector, config):
    max_lines = retrieval_int(config, "max_lines", MAX_RETRIEVAL_LINES, 1, MAX_RETRIEVAL_LINES)
    default_lines = retrieval_int(config, "default_lines", DEFAULT_RETRIEVAL_LINES, 1, max_lines)
    if not selector:
        return 1, min(default_lines, max_lines)
    if ":" in selector:
        start_s, end_s = selector.split(":", 1)
        if not start_s.isdigit() or not end_s.isdigit():
            die("lines selector must be N or START:END")
        start = max(1, int(start_s))
        end = max(start, int(end_s))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
        return start, end
    if not selector.isdigit():
        die("lines selector must be N or START:END")
    count = max(1, min(int(selector), max_lines))
    return 1, count


def validate_grep_pattern(pattern, config):
    max_chars = retrieval_int(config, "max_grep_pattern_chars", MAX_GREP_PATTERN_CHARS, 1, MAX_GREP_PATTERN_CHARS)
    if len(pattern) > max_chars:
        die(f"unsafe grep pattern: too long ({len(pattern)} > {max_chars})")
    if "\x00" in pattern:
        die("unsafe grep pattern: NUL byte")
    if UNSAFE_GREP_RE.search(pattern):
        die("unsafe grep pattern: nested or repeated wildcard quantifier")
    try:
        return re.compile(pattern)
    except re.error as e:
        die(f"unsafe grep pattern: {e}")


def bounded_text_window(text, start, end):
    lines = text.splitlines()
    total = len(lines)
    selected = lines[start - 1:end]
    truncated = start > 1 or end < total
    return "\n".join(selected), truncated, total


def bounded_grep(text, pattern, config, limit):
    max_bytes = retrieval_int(config, "max_grep_scan_bytes", MAX_GREP_SCAN_BYTES, 1, MAX_GREP_SCAN_BYTES)
    max_line_chars = retrieval_int(config, "max_grep_line_chars", MAX_GREP_LINE_CHARS, 1, MAX_GREP_LINE_CHARS)
    chunk = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
    regex = validate_grep_pattern(pattern, config)
    matches = []
    for number, line in enumerate(chunk.splitlines(), 1):
        bounded_line = line[:max_line_chars]
        if regex.search(bounded_line):
            matches.append({"line": number, "text": bounded_line})
            if len(matches) >= limit:
                break
    scanned_truncated = len(text.encode("utf-8")) > max_bytes
    return matches, scanned_truncated


def cmd_retrieve(args):
    root = root_from(args)
    record_id = valid_record_id(args.id)
    config, config_findings, _ = load_compression_config(root)
    record_path = record_json_path(root, record_id)
    record = read_json(record_path, None)
    if not isinstance(record, dict) or record.get("schema") != SCHEMA_COMPRESSED_CONTEXT_RECORD:
        die(f"record not found or invalid: {record_id}")
    source = "compact" if args.compact else "raw"
    path = record_compact_path(root, record_id) if args.compact else record_raw_path(root, record_id)
    text = read_text(path)
    start, end = parse_line_selector(args.lines, config)
    max_count = end - start + 1
    if args.grep:
        matches, scan_truncated = bounded_grep(text, args.grep, config, max_count)
        content = "\n".join(f"{row['line']}:{row['text']}" for row in matches)
        truncated = scan_truncated or len(matches) >= max_count
        lines = {"selector": args.lines or str(max_count), "returned": len(matches), "grep": args.grep}
    else:
        content, truncated, total = bounded_text_window(text, start, end)
        lines = {"start": start, "end": end, "total": total}
    payload = {
        "schema": "m8shift.context.retrieve.v1",
        "record_id": record_id,
        "source": source,
        "path": rel(root, path),
        "bounded": True,
        "lines": lines,
        "truncated": truncated,
        "content": content,
        "findings": config_findings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(content)
        if truncated:
            print("[m8shift-context: output truncated; use an explicit bounded --lines range]", file=sys.stderr)
    return 0


def rtk_telemetry_disable():
    resolved = shutil_which("rtk")
    if not resolved:
        return {"present": False, "disabled": False, "detail": "rtk not found"}
    try:
        proc = subprocess.run(
            [resolved, "telemetry", "disable"],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"present": True, "disabled": False, "path": os.path.realpath(resolved), "detail": str(e)}
    return {
        "present": True,
        "disabled": proc.returncode == 0,
        "path": os.path.realpath(resolved),
        "returncode": proc.returncode,
        "detail": (proc.stdout or proc.stderr).strip(),
    }


def rtk_telemetry_status():
    resolved = shutil_which("rtk")
    if not resolved:
        return {"present": False, "state": "absent", "detail": "rtk not found"}
    try:
        proc = subprocess.run(
            [resolved, "telemetry", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"present": True, "state": "unknown", "path": os.path.realpath(resolved), "detail": str(e)}
    detail = (proc.stdout or proc.stderr).strip()
    lowered = detail.lower()
    if "disabled" in lowered or "off" in lowered:
        state = "disabled"
    elif "enabled" in lowered or "on" in lowered:
        state = "enabled"
    else:
        state = "unknown" if proc.returncode != 0 else "reported"
    return {
        "present": True,
        "state": state,
        "path": os.path.realpath(resolved),
        "returncode": proc.returncode,
        "detail": detail,
    }


def rtk_status(root):
    resolved = shutil_which("rtk")
    last_pack, findings = latest_context_metrics(root)
    manifest, manifest_findings = load_adapter_diagnostic(root, "rtk-shell-output")
    findings.extend(manifest_findings)
    status = {
        "present": bool(resolved),
        "pinned": False,
        "path": os.path.realpath(resolved) if resolved else "",
        "telemetry": rtk_telemetry_status(),
        "network": "M8Shift uses RTK only as a local argv subprocess and disables telemetry on context setup.",
        "last_pack": last_pack,
    }
    if not resolved:
        status["state"] = "off"
        status["label"] = "RTK: OFF (native)"
        status["reason"] = "rtk not found; native context pack path"
        status["findings"] = findings
        return status
    errors = [row for row in findings if row["severity"] == "error"]
    if manifest is not None:
        errors.extend(row for row in adapter_findings(manifest) if row["severity"] == "error")
    status["pinned"] = not errors
    status["findings"] = findings + [row for row in errors if row not in findings]
    status["state"] = "on" if status["pinned"] else "off"
    status["label"] = "RTK: ON (pinned, compressing packs)" if status["pinned"] else "RTK: OFF (native)"
    status["reason"] = "pinned, compressing packs" if status["pinned"] else "rtk absent, unpinned, or invalid; native context pack path"
    return status


def cmd_adapters_init(args):
    root = root_from(args)
    ensure_dirs(root)
    wrote = []
    for name in DEFAULT_ADAPTERS:
        path = adapter_path(root, name)
        if os.path.exists(path) and not args.force:
            continue
        write_json(path, default_adapter_manifest(name))
        wrote.append(rel(root, path))
    telemetry = rtk_telemetry_disable()
    if args.json:
        print(json.dumps({"written": wrote, "adapters": sorted(DEFAULT_ADAPTERS), "rtk_telemetry": telemetry}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"✓ adapter manifests ready ({len(wrote)} file(s) written)")
        for path in wrote:
            print(f"  {path}")
        if telemetry.get("present"):
            print(f"✓ rtk telemetry disable attempted (disabled={str(telemetry.get('disabled')).lower()})")
    return 0


def cmd_adapters_list(args):
    root = root_from(args)
    names = set(DEFAULT_ADAPTERS)
    if os.path.isdir(adapters_dir(root)):
        for entry in os.listdir(adapters_dir(root)):
            if entry.endswith(".json"):
                names.add(entry[:-5])
    if args.json:
        print(json.dumps({"adapters": sorted(names)}, ensure_ascii=False, sort_keys=True))
    else:
        for name in sorted(names):
            print(name)
    return 0


def cmd_adapters_show(args):
    root = root_from(args)
    manifest = load_adapter(root, args.name)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def cmd_adapters_check(args):
    root = root_from(args)
    if args.name:
        names = [args.name]
    else:
        names = set(DEFAULT_ADAPTERS)
        if os.path.isdir(adapters_dir(root)):
            names.update(entry[:-5] for entry in os.listdir(adapters_dir(root)) if entry.endswith(".json"))
        names = sorted(names)
    manifests = [load_adapter(root, name) for name in names]
    findings = []
    for manifest in manifests:
        findings.extend(adapter_findings(manifest))
    ok = not any(row["severity"] == "error" for row in findings)
    if args.json:
        print(json.dumps({"ok": ok, "findings": findings}, ensure_ascii=False, sort_keys=True))
    else:
        if not findings:
            print("✓ adapter manifests OK")
        for row in findings:
            print(f"{row['severity']}: {row['check']}: {row['message']}")
    return 0 if ok else 1


def cmd_adapters_run(args):
    root = root_from(args)
    manifest = load_adapter(root, args.name)
    adapter_mode_args(manifest, args.mode)  # enforce forbidden modes before any executable lookup
    findings = adapter_findings(manifest)
    errors = [row for row in findings if row["severity"] == "error"]
    if errors:
        die("; ".join(row["message"] for row in errors))
    original = read_adapter_input(root, args)
    filtered, error, stderr = run_adapter_process(root, manifest, args.mode, original)
    fallback_used = filtered is None
    if fallback_used:
        if manifest.get("failure_policy") != "fallback_original":
            die(error or "adapter failed")
        filtered = original
    result = adapter_result(
        manifest,
        mode=args.mode,
        original=original,
        filtered=filtered,
        fallback_used=fallback_used,
        error=error,
        stderr=stderr,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(result["filtered_text"], end="" if result["filtered_text"].endswith("\n") else "\n")
        if fallback_used:
            print(f"[m8shift-context adapter fallback: {error}]", file=sys.stderr)
    return 0


def finding(severity, check, message):
    return {"severity": severity, "check": check, "message": message}


def print_rtk_status(rtk):
    print(rtk.get("label", "RTK: OFF (native)"))
    print(
        "  detail: "
        f"present={str(rtk.get('present')).lower()} "
        f"pinned={str(rtk.get('pinned')).lower()} "
        f"telemetry={rtk.get('telemetry', {}).get('state', 'unknown')}"
    )
    if rtk.get("last_pack"):
        last = rtk["last_pack"]
        print(
            "  last pack: "
            f"{last.get('pack_id') or '-'} ratio={last.get('compression_ratio')} "
            f"proxy={last.get('estimated_proxy_tokens_before')}→{last.get('estimated_proxy_tokens_after')}"
        )


def cmd_status(args):
    root = root_from(args)
    rtk = rtk_status(root)
    if args.json:
        print(json.dumps({"rtk": rtk}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"m8shift-context.py v{VERSION}")
        print_rtk_status(rtk)
    return 0


def cmd_doctor(args):
    root = root_from(args)
    findings = []
    _, compression_findings, compression_fail_safe = load_compression_config(root)
    findings.extend(compression_findings)
    if compression_fail_safe:
        findings.append(finding("warning", "compression.fail_safe", "context compression will redact and fall back to reference-only until config is valid"))
    for name in PROFILE_NAMES:
        path = os.path.join(profiles_dir(root), f"{name}.json")
        data = read_json(path, None)
        if data is None:
            findings.append(finding("warning", "profile.missing", f"missing profile {rel(root, path)}"))
        elif not isinstance(data, dict) or data.get("schema") != SCHEMA_PROFILE:
            findings.append(finding("error", "profile.schema", f"invalid profile {rel(root, path)}"))
    metrics_rows, metrics_err = read_jsonl_diagnostic(metrics_path(root))
    if metrics_err:
        findings.append(finding("warning", "metrics.unreadable", f"{rel(root, metrics_path(root))}: {metrics_err}"))
    for row in metrics_rows:
        if row.get("schema") != SCHEMA_METRICS:
            findings.append(finding("error", "metrics.schema", "metrics row has invalid schema"))
        if row.get("real_tokens_before") is None:
            findings.append(finding("info", "metrics.proxy_only", f"{row.get('pack_id')} has no real token counts"))
    for receipt_name in os.listdir(receipts_dir(root)) if os.path.isdir(receipts_dir(root)) else []:
        if not receipt_name.endswith(".json"):
            continue
        receipt = read_json(os.path.join(receipts_dir(root), receipt_name), {})
        if not receipt.get("references"):
            findings.append(finding("error", "receipt.references", f"{receipt_name} has no source references"))
    adapter_names = set(DEFAULT_ADAPTERS)
    if os.path.isdir(adapters_dir(root)):
        adapter_names.update(entry[:-5] for entry in os.listdir(adapters_dir(root)) if entry.endswith(".json"))
    for name in sorted(adapter_names):
        manifest, manifest_findings = load_adapter_diagnostic(root, name)
        findings.extend(manifest_findings)
        if manifest is not None:
            findings.extend(adapter_findings(manifest, check_executable=False))
    rtk = rtk_status(root)
    for row in rtk.get("findings", []):
        if row not in findings:
            findings.append(row)
    if args.json:
        print(json.dumps({"findings": findings, "rtk": rtk}, ensure_ascii=False, sort_keys=True))
    else:
        if not findings:
            print("✓ m8shift-context doctor: no findings")
        print_rtk_status(rtk)
        for row in findings:
            print(f"{row['severity']}: {row['check']}: {row['message']}")
    return 1 if any(row["severity"] == "error" for row in findings) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Optional M8Shift context companion (native Phase 1).")
    p.add_argument("--version", action="version", version=f"m8shift-context.py {VERSION}")
    p.add_argument("--root", help="project root (default: $M8SHIFT_ROOT or script directory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    si = sub.add_parser("init", help="create native context companion profile scaffold")
    si.add_argument("--force", action="store_true")
    si.set_defaults(func=cmd_init)

    sp = sub.add_parser("pack", help="build a referenced native context pack")
    sp.add_argument("--profile", choices=PROFILE_NAMES, default="reviewer")
    sp.add_argument("--agent", default="")
    sp.add_argument("--turns", type=int, default=3)
    sp.add_argument("--include", action="append", default=[], help="include one project-relative file excerpt")
    sp.add_argument("--write", action="store_true", help="write pack, receipt, and metrics under .m8shift/context/")
    sp.add_argument("--output", help="write pack to this project-relative path")
    sp.add_argument("--adapter", choices=("auto", "native", "rtk-shell-output"), default="auto",
                    help="shell-output adapter for noisy context sources; default auto uses pinned RTK when available")
    sp.add_argument("--no-rtk", action="store_const", const="native", dest="adapter",
                    help="alias for --adapter native")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_pack)

    sr = sub.add_parser("receipt", help="show a context pack receipt")
    sr.add_argument("--id", help="receipt id / pack id")
    sr.add_argument("--last", action="store_true", help="show latest receipt (default)")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(func=cmd_receipt)

    sm = sub.add_parser("metrics", help="show context metrics")
    sm.add_argument("--last", action="store_true")
    sm.add_argument("--json", action="store_true")
    sm.set_defaults(func=cmd_metrics)

    sc = sub.add_parser("compress", help="write a redacted compressed-context record from raw input")
    sc.add_argument("--id", help="record id (safe id only)")
    sc.add_argument("--agent", default="")
    sc.add_argument("--type", default="context", help="content type label, e.g. test_output or shell_output")
    sc.add_argument("--backend", default="auto", help="compression backend id (default: auto)")
    csrc = sc.add_mutually_exclusive_group(required=True)
    csrc.add_argument("--stdin", action="store_true", help="read raw content from stdin")
    csrc.add_argument("--input", help="read raw content from a project-relative file")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_compress)

    sret = sub.add_parser("retrieve", help="retrieve bounded raw or compact content by record id")
    sret.add_argument("id", help="compressed context record id")
    sret.add_argument("--compact", action="store_true", help="retrieve compact digest instead of redacted raw reference")
    sret.add_argument("--lines", help="bounded line selector: N or START:END (default 80)")
    sret.add_argument("--grep", help="bounded native stdlib re scan")
    sret.add_argument("--json", action="store_true")
    sret.set_defaults(func=cmd_retrieve)

    ss = sub.add_parser("status", help="show context companion status, including RTK adapter state")
    ss.add_argument("--json", action="store_true")
    ss.set_defaults(func=cmd_status)

    sb = sub.add_parser("benchmark", help="benchmark raw context versus native pack fixtures")
    sb.add_argument("--profile", choices=PROFILE_NAMES, default="reviewer")
    sb.add_argument("--real-tokens", help="JSON with {fixture: {without: N, with: N}} real token counts")
    sb.add_argument("--require-real-tokens", action="store_true", help="fail unless real token counts show reduction")
    sb.add_argument("--write", action="store_true", help="append benchmark result to .m8shift/context/benchmarks.jsonl")
    sb.add_argument("--json", action="store_true")
    sb.set_defaults(func=cmd_benchmark)

    sa = sub.add_parser("adapters", help="Phase-2 external adapter manifests and bounded runner")
    sa_sub = sa.add_subparsers(dest="verb", required=True)
    sai = sa_sub.add_parser("init", help="write shipped adapter manifests")
    sai.add_argument("--force", action="store_true")
    sai.add_argument("--json", action="store_true")
    sai.set_defaults(func=cmd_adapters_init)
    sal = sa_sub.add_parser("list", help="list known adapter manifests")
    sal.add_argument("--json", action="store_true")
    sal.set_defaults(func=cmd_adapters_list)
    sas = sa_sub.add_parser("show", help="show one adapter manifest")
    sas.add_argument("name")
    sas.set_defaults(func=cmd_adapters_show)
    sac = sa_sub.add_parser("check", help="validate adapter manifests")
    sac.add_argument("name", nargs="?")
    sac.add_argument("--json", action="store_true")
    sac.set_defaults(func=cmd_adapters_check)
    sar = sa_sub.add_parser("run", help="run one advisory adapter with bounded argv-only execution")
    sar.add_argument("name")
    sar.add_argument("--mode", required=True)
    src = sar.add_mutually_exclusive_group(required=True)
    src.add_argument("--stdin", action="store_true", help="read raw adapter input from stdin")
    src.add_argument("--input", help="read raw adapter input from a project-relative file")
    sar.add_argument("--json", action="store_true")
    sar.set_defaults(func=cmd_adapters_run)

    sd = sub.add_parser("doctor", help="read-only context companion diagnostics")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
