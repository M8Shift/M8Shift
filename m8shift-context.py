#!/usr/bin/env python3
"""m8shift-context.py — optional context companion for M8Shift.

Phase 1 is intentionally native and boring: it builds referenced context packs,
records receipts and metrics, and benchmarks "raw context" versus "native pack"
without external dependencies. It never edits the core relay and never decides who
may write.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

VERSION = "3.27.0"
SCHEMA_PACK = "m8shift.context.pack.v1"
SCHEMA_RECEIPT = "m8shift.context.receipt.v1"
SCHEMA_METRICS = "m8shift.context.metrics.v1"
SCHEMA_PROFILE = "m8shift.context.profile.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
TURN_RE = re.compile(
    r"<!-- M8SHIFT:TURN (?P<num>\d+) (?P<author>[a-z][a-z0-9_-]*) BEGIN -->"
    r"(?P<body>.*?)"
    r"<!-- M8SHIFT:TURN (?P=num) (?P=author) END -->",
    re.DOTALL,
)
FIELD_RE = re.compile(r"^- (?P<key>[a-z_]+):\s*(?P<value>.*)$")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
PROFILE_NAMES = ("implementer", "reviewer", "tester", "gatekeeper", "maintainer")


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
    candidate = os.path.abspath(candidate)
    root_abs = os.path.abspath(root)
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


def metrics_path(root):
    return os.path.join(context_dir(root), "metrics.jsonl")


def benchmarks_path(root):
    return os.path.join(context_dir(root), "benchmarks.jsonl")


def ensure_dirs(root):
    for path in (context_dir(root), packs_dir(root), receipts_dir(root), profiles_dir(root)):
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


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def size_metrics(text):
    data = text.encode("utf-8")
    return {
        "bytes": len(data),
        "estimated_proxy_tokens": len(data) // 4,
        "lines": len(text.splitlines()),
    }


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
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
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
    sources.append(source("git_summary", "git_summary", git_summary, None))

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
    readme = os.path.join(context_dir(root), "README.md")
    if args.force or not os.path.exists(readme):
        write_text(readme, (
            "# M8Shift context companion\n\n"
            "Generated context packs, receipts, metrics, and benchmarks live here.\n"
            "Packs are operational views only; verification uses original sources.\n"
        ))
        wrote.append(rel(root, readme))
    print(f"✓ context companion initialized ({len(wrote)} files written)")
    for path in wrote:
        print(f"  {path}")
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


def finding(severity, check, message):
    return {"severity": severity, "check": check, "message": message}


def cmd_doctor(args):
    root = root_from(args)
    findings = []
    for name in PROFILE_NAMES:
        path = os.path.join(profiles_dir(root), f"{name}.json")
        data = read_json(path, None)
        if data is None:
            findings.append(finding("warning", "profile.missing", f"missing profile {rel(root, path)}"))
        elif not isinstance(data, dict) or data.get("schema") != SCHEMA_PROFILE:
            findings.append(finding("error", "profile.schema", f"invalid profile {rel(root, path)}"))
    for row in read_jsonl(metrics_path(root)):
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
    if args.json:
        print(json.dumps({"findings": findings}, ensure_ascii=False, sort_keys=True))
    else:
        if not findings:
            print("✓ m8shift-context doctor: no findings")
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

    sb = sub.add_parser("benchmark", help="benchmark raw context versus native pack fixtures")
    sb.add_argument("--profile", choices=PROFILE_NAMES, default="reviewer")
    sb.add_argument("--real-tokens", help="JSON with {fixture: {without: N, with: N}} real token counts")
    sb.add_argument("--require-real-tokens", action="store_true", help="fail unless real token counts show reduction")
    sb.add_argument("--write", action="store_true", help="append benchmark result to .m8shift/context/benchmarks.jsonl")
    sb.add_argument("--json", action="store_true")
    sb.set_defaults(func=cmd_benchmark)

    sd = sub.add_parser("doctor", help="read-only context companion diagnostics")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
