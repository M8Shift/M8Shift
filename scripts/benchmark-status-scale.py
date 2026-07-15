#!/usr/bin/env python3
"""Measure status scaling and prototype a safe in-memory turn-tail cache.

The cache is deliberately only a benchmark prototype.  It models the real
atomic-replace writer: the LOCK header may change length and the file inode may
change on every update.  Its watermark is therefore relative to the first turn,
and an anchor immediately before the watermark must still match.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


TURN_MARKER = b"<!-- M8SHIFT:TURN "
PREFIX_LIMIT = 64 * 1024
ANCHOR_BYTES = 256


def percentile(samples, fraction):
    ordered = sorted(samples)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))]


def summary(samples):
    return {
        "first_ms": round(samples[0], 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, .95), 3),
    }


def timed(fn, runs):
    samples = []
    result = None
    for _ in range(runs):
        started = time.perf_counter_ns()
        result = fn()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return summary(samples), result


def turn_block(number, body_bytes=768):
    agent, recipient = ("codex", "claude") if number % 2 else ("claude", "codex")
    body = "x" * body_bytes
    return (
        "<!-- M8SHIFT:TURN %d %s BEGIN -->\n"
        "- from:    %s\n- to:      %s\n- ask:     benchmark ask %d\n"
        "- done:    benchmark done %d\n- files:   —\n- handoff: %s\n"
        "- at:      2026-01-01T00:00:00Z\n\n%s\n"
        "<!-- M8SHIFT:TURN %d %s END -->\n"
    ) % (number, agent, agent, recipient, number, number, recipient, body, number, agent)


def relay_prefix(turn, note="synthetic benchmark"):
    holder = "claude" if turn % 2 else "codex"
    return (
        "<!-- M8SHIFT:LOCK:BEGIN -->\n"
        "holder: %s\nstate: AWAITING_%s\nagents: claude,codex\nlang: en\n"
        "session: 20260101T000000Z-00000000\nturn: %d\n"
        "since: 2026-01-01T00:00:00Z\nexpires: -\nnote: %s\n"
        "<!-- M8SHIFT:LOCK:END -->\n\n# Synthetic benchmark journal\n\n"
    ) % (holder, holder.upper(), turn, note)


def make_relay(root, turns, body_bytes):
    root.mkdir(parents=True, exist_ok=True)
    journal = relay_prefix(turns) + "".join(turn_block(n, body_bytes) for n in range(1, turns + 1))
    (root / "M8SHIFT.md").write_text(journal, encoding="utf-8")
    start = {"event": "start", "session_id": "20260101T000000Z-00000000",
             "at": "2026-01-01T00:00:00Z", "started_at": "2026-01-01T00:00:00Z"}
    (root / "M8SHIFT.sessions.jsonl").write_text(json.dumps(start) + "\n", encoding="utf-8")


def append_turn_atomic(root, number, body_bytes):
    path = root / "M8SHIFT.md"
    text = path.read_text(encoding="utf-8")
    marker = text.index(TURN_MARKER.decode())
    # Change LOCK length as production does, while preserving the immutable turn stream.
    updated = relay_prefix(number, "synthetic benchmark update %d" % number)
    updated += text[marker:].rstrip() + "\n\n" + turn_block(number, body_bytes)
    tmp = root / ".M8SHIFT.md.tmp"
    tmp.write_text(updated, encoding="utf-8")
    os.replace(str(tmp), str(path))


def load_engine(path):
    spec = importlib.util.spec_from_file_location("m8shift_benchmark_engine", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_top(path):
    spec = importlib.util.spec_from_file_location("m8shift_benchmark_top", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure_production_top(top, engine, root, turns, body_bytes, runs):
    """Measure RFC 069's shipped reader, not the earlier parse-only prototype."""
    reader = top.IncrementalStatusReader(str(engine), str(root))
    reader._prepare_engine()
    if reader._core is None:
        raise RuntimeError("production top reader could not import lockstep core")

    full_samples = []
    for _ in range(runs):
        reader._cache = None
        started = time.perf_counter_ns()
        reader.load(200)
        full_samples.append((time.perf_counter_ns() - started) / 1_000_000)
        if reader.mode != "full":
            raise AssertionError("production reader full benchmark did not use full mode")

    hit_result, _ = timed(lambda: reader.load(200), runs)
    if reader.mode != "incremental":
        raise AssertionError("production reader hit benchmark did not use incremental mode")

    append_samples = []
    for offset in range(1, runs + 1):
        append_turn_atomic(root, turns + offset, body_bytes)
        started = time.perf_counter_ns()
        reader.load(200)
        append_samples.append((time.perf_counter_ns() - started) / 1_000_000)
        if reader.mode != "incremental":
            raise AssertionError("production reader append benchmark fell back unexpectedly")
    return {
        "full": summary(full_samples),
        "cache_hit": hit_result,
        "one_append": summary(append_samples),
    }


def measure_status_variants(engine, root, python, runs):
    env = {key: value for key, value in os.environ.items() if not key.startswith("M8SHIFT_")}
    env["M8SHIFT_ROOT"] = str(root)
    commands = {
        "status": [python, str(engine), "status", "--json"],
        "status_O": [python, "-O", str(engine), "status", "--json"],
    }
    samples = {name: [] for name in commands}

    # Alternate order to keep thermal/background drift from consistently
    # favouring one interpreter mode.
    for run in range(runs):
        order = list(commands) if run % 2 == 0 else list(reversed(commands))
        for name in order:
            started = time.perf_counter_ns()
            proc = subprocess.run(commands[name], env=env, cwd=str(engine.parent),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            samples[name].append((time.perf_counter_ns() - started) / 1_000_000)
            if proc.returncode:
                raise RuntimeError(proc.stderr.strip() or "status failed")

    return {name: summary(values) for name, values in samples.items()}


class TurnTailCache:
    def __init__(self, parse_turns, turn_re):
        self.parse_turns = parse_turns
        self.turn_re = turn_re
        self.initialized = False
        self.stream_bytes = 0
        self.anchor = b""
        self.turns = []
        self.fallbacks = 0

    @staticmethod
    def _start(prefix):
        offset = prefix.find(TURN_MARKER)
        if offset < 0:
            raise ValueError("turn stream is outside bounded prefix")
        return offset

    def _full(self, path):
        data = path.read_bytes()
        start = self._start(data[:PREFIX_LIMIT])
        stream = data[start:]
        stream_text = stream.decode("utf-8")
        matches = list(self.turn_re.finditer(stream_text))
        self.turns = self.parse_turns(stream_text)
        # A malformed/truncated tail is not consumed.  If a later atomic
        # replacement completes it, the next delta starts at the last proven
        # record boundary and the newly complete turn remains visible.
        consumed = len(stream_text[:matches[-1].end()].encode("utf-8")) if matches else 0
        self.stream_bytes = consumed
        self.anchor = hashlib.sha256(stream[:consumed][-ANCHOR_BYTES:]).digest()
        self.initialized = True
        self.fallbacks += 1
        return self.turns

    def refresh(self, path):
        if not self.initialized:
            return self._full(path)
        with path.open("rb") as handle:
            prefix = handle.read(PREFIX_LIMIT)
            start = self._start(prefix)
            size = os.fstat(handle.fileno()).st_size
            new_stream_bytes = size - start
            if new_stream_bytes < self.stream_bytes:
                return self._full(path)
            anchor_start = start + self.stream_bytes - ANCHOR_BYTES
            handle.seek(max(start, anchor_start))
            old_tail = handle.read(min(ANCHOR_BYTES, self.stream_bytes))
            if hashlib.sha256(old_tail).digest() != self.anchor:
                return self._full(path)
            handle.seek(start + self.stream_bytes)
            delta = handle.read()
        if delta:
            delta_text = delta.decode("utf-8")
            matches = list(self.turn_re.finditer(delta_text))
            if matches:
                consumed = len(delta_text[:matches[-1].end()].encode("utf-8"))
                self.turns.extend(self.parse_turns(delta_text[:matches[-1].end()]))
                self.stream_bytes += consumed
                self.anchor = hashlib.sha256(
                    (old_tail + delta[:consumed])[-ANCHOR_BYTES:]).digest()
        return self.turns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-root", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--sizes", default="1000,5000,10000")
    parser.add_argument("--body-bytes", type=int, default=768)
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")

    repo = Path(__file__).resolve().parents[1]
    engine_path = repo / "m8shift.py"
    engine = load_engine(engine_path)
    top = load_top(repo / "m8shift-top.py")
    result = {"host": {"python": subprocess.check_output([args.python, "--version"], text=True,
                                                            stderr=subprocess.STDOUT).strip(),
                       "platform": sys.platform, "runs": args.runs},
              "synthetic": [], "real": None}

    if args.real_root:
        root = args.real_root.resolve()
        text = (root / "M8SHIFT.md").read_text(encoding="utf-8")
        read_result, _ = timed(lambda: (root / "M8SHIFT.md").read_text(encoding="utf-8"), args.runs)
        parse_result, turns = timed(lambda: engine.parse_turns(text), args.runs)
        variants = measure_status_variants(engine_path, root, args.python, args.runs)
        result["real"] = {"bytes": len(text.encode()), "turns": len(turns),
                          "read": read_result, "parse": parse_result, **variants}

    with tempfile.TemporaryDirectory(prefix="m8shift-status-scale-") as tmp:
        base = Path(tmp)
        for count in [int(value) for value in args.sizes.split(",")]:
            root = base / str(count)
            make_relay(root, count, args.body_bytes)
            production_root = base / (str(count) + "-production")
            make_relay(production_root, count, args.body_bytes)
            path = root / "M8SHIFT.md"
            text = path.read_text(encoding="utf-8")
            read_result, _ = timed(lambda: path.read_text(encoding="utf-8"), args.runs)
            parse_result, _ = timed(lambda: engine.parse_turns(text), args.runs)
            cache = TurnTailCache(engine.parse_turns, engine.TURN_RE)
            cache.refresh(path)
            hit_result, _ = timed(lambda: cache.refresh(path), args.runs)
            delta_samples = []
            for offset in range(1, args.runs + 1):
                append_turn_atomic(root, count + offset, args.body_bytes)
                started = time.perf_counter_ns()
                delta_turns = cache.refresh(path)
                delta_samples.append((time.perf_counter_ns() - started) / 1_000_000)
            delta_result = summary(delta_samples)
            full_turns = engine.parse_turns(path.read_text(encoding="utf-8"))
            if delta_turns != full_turns:
                raise AssertionError("incremental result differs from full parse at %d turns" % count)
            variants = measure_status_variants(engine_path, root, args.python, args.runs)
            production_top = measure_production_top(
                top, engine_path, production_root, count, args.body_bytes, args.runs)
            fallbacks_before_rotation = cache.fallbacks
            make_relay(root, 6, args.body_bytes)
            rotated_turns = cache.refresh(path)
            rotated_full = engine.parse_turns(path.read_text(encoding="utf-8"))
            rotation_fallback = cache.fallbacks == fallbacks_before_rotation + 1
            if not rotation_fallback or rotated_turns != rotated_full:
                raise AssertionError("rotation did not fall back to an equivalent full parse")
            rotated_text = path.read_text(encoding="utf-8").rstrip()
            complete = turn_block(7, args.body_bytes)
            partial = complete[:len(complete) // 2]
            tmp_path = root / ".M8SHIFT.md.tmp"
            tmp_path.write_text(rotated_text + "\n\n" + partial, encoding="utf-8")
            os.replace(str(tmp_path), str(path))
            partial_equivalent = cache.refresh(path) == engine.parse_turns(
                path.read_text(encoding="utf-8"))
            tmp_path.write_text(rotated_text + "\n\n" + complete, encoding="utf-8")
            os.replace(str(tmp_path), str(path))
            completed_equivalent = cache.refresh(path) == engine.parse_turns(
                path.read_text(encoding="utf-8"))
            truncated_tail_equivalent = partial_equivalent and completed_equivalent
            if not truncated_tail_equivalent:
                raise AssertionError("truncated-tail completion differs from full parse")
            result["synthetic"].append({
                "turns": count, "bytes": len(text.encode()), "read": read_result,
                "parse": parse_result,
                **variants,
                "production_top": production_top,
                "cache_hit": hit_result, "cache_one_append": delta_result,
                "cache_fallbacks": cache.fallbacks,
                "rotation_fallback_equivalent": rotation_fallback,
                "truncated_tail_equivalent": truncated_tail_equivalent,
            })

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
