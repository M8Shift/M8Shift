# Status performance investigation

This investigation measures the live-journal cost of `m8shift.py status --json`
before proposing a production optimization.  It uses commit `b2280a9`, CPython
3.8.16, macOS 15.7.3 on arm64, and the reproducible harness in
`scripts/benchmark-status-scale.py`.

## Method and limits

The harness ran 15 fresh processes per CLI candidate.  `first_ms` is the first
fresh-process sample and `median_ms` is the repeated-process median.  The host
does not permit a kernel page-cache purge, so **first is not a claim of a true
cold-disk read**; the read column shows the observed first-versus-warm-cache
difference.  Every CLI sample still includes normal interpreter startup.

The real relay was 1,147,156 bytes with 456 turns in the living journal.  Its
LOCK turn was higher because older turns had been archived; `status` correctly
did not read the archive.  Synthetic journals used 768-byte bodies and the same
turn grammar, producing approximately 1.0, 5.0, and 10.1 MB files.

Run the benchmark from the repository root:

```console
python3.8 scripts/benchmark-status-scale.py \
  --real-root /path/to/relay --python python3.8 --runs 15
```

## End-to-end scaling

| Journal | Bytes | First status (ms) | Warm status median (ms) | First read (ms) | Warm read median (ms) | Parse median (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Real, 456 live turns | 1,147,156 | 156.453 | 156.453 | 1.557 | 0.390 | 13.652 |
| Synthetic 1k | 1,003,335 | 149.764 | 144.297 | 0.372 | 0.220 | 16.449 |
| Synthetic 5k | 5,033,335 | 218.710 | 235.047 | 3.553 | 1.169 | 87.867 |
| Synthetic 10k | 10,070,840 | 381.895 | 333.622 | 5.531 | 2.380 | 170.594 |

The parse grows linearly: 16.4 ms at 1k, 87.9 ms at 5k, and 170.6 ms at
10k.  Warm file reads remain only 0.2–2.4 ms.  At 10k, parse consumes about half
the unprofiled end-to-end latency.

`cProfile` makes the boundary clearer.  Profiling adds overhead, so these rows
are a breakdown rather than substitutes for the wall-clock table.

| Profile | Total (ms) | `parse_turns` cumulative | Relay read / validation | `_status_info` full-text scan | Time-accounting fold |
|---|---:|---:|---:|---:|---:|
| Real | 86.0 | 18.0 (20.9%) | 2.0 | 6.2 | 0.3 |
| Synthetic 10k | 314.6 | 243.2 (77.3%) | 7.2 | 6.3 | 0.2 |

`all_turns()` is not called by `status`; neither the archive nor history folding
is on this path.  Session-ledger reads and folds are sub-millisecond on the real
relay.  The dominant growing cost is regex parsing and allocation of every live
turn.  `_status_info` also performs a redundant full-text last-turn scan before
`parse_turns` constructs the same information.

## Interpreter and compilation results

`python -O` was alternated with normal invocations to avoid consistently giving
one mode the cooler/earlier samples.

| Journal | Normal median (ms) | `python -O` median (ms) | Change |
|---|---:|---:|---:|
| Real | 156.453 | 240.814 | +53.9% |
| Synthetic 1k | 144.297 | 227.938 | +58.0% |
| Synthetic 5k | 235.047 | 314.205 | +33.7% |
| Synthetic 10k | 333.622 | 417.232 | +25.1% |

The source-per-command CLI pays optimization/optimized-import setup on every
process, so `-O` hurts latency.  It does not improve throughput elsewhere:

| Full suite, Python 3.8 | Result | Wall time |
|---|---|---:|
| Normal | 1,033 tests OK, 3 skipped | 620.467 s |
| `-O` | 1,033 tests OK, 3 skipped | 618.278 s |

The 2.189-second (0.35%) suite difference is noise-scale.  A precompiled `.pyc`
isolates source compilation without changing the distribution contract:

| Candidate | Real `status --json` median | Small-relay `status` median |
|---|---:|---:|
| Source | 153.983 ms | 123.905 ms |
| `.pyc` | 118.900 ms | 79.592 ms |
| Optimized `.pyc` under `-O` | 207.943 ms | not measured |

Nuitka and PyPy were not installed on this offline measurement host
(`python3.8 -m nuitka` reports `No module named nuitka`), so no standalone-binary
number is claimed.  The existing startup harness accepts
`--candidate NAME=/path/to/executable` when a build is available.  This missing
optional tool does not support an AOT speed claim in either direction; the
measured profile, however, shows that a compiler cannot remove the linear need
to read and construct all turn dictionaries.

## Incremental prototype

The prototype caches the parsed turns, the byte length of the immutable turn
stream, and a SHA-256 anchor over the 256 bytes immediately before that
watermark.  On refresh it reads a bounded prefix to relocate the first turn,
validates the anchor, then reads and parses only bytes after the relative
watermark.

An absolute file offset or inode check is insufficient.  Production writes use
atomic replacement, so the inode normally changes, and the mutable LOCK header
can change byte length and shift every turn.  A turn-stream-relative watermark
models those facts.  Shrinkage or anchor mismatch triggers a full parse.

| Journal | Full parse median (ms) | Cache hit median (ms) | One appended turn median (ms) | Parse-stage speedup |
|---|---:|---:|---:|---:|
| Synthetic 1k | 16.449 | 0.028 | 0.106 | 155× |
| Synthetic 5k | 87.867 | 0.022 | 0.141 | 623× |
| Synthetic 10k | 170.594 | 0.024 | 0.297 | 574× |

Each size was checked after every append against a full parse.  Replacing the
journal with a rotated six-turn journal caused an anchor/size fallback, and the
fallback result was identical to the full parse.  A half-written final turn was
left beyond the watermark; after an atomic replacement completed it, both the
partial and completed snapshots remained identical to a full parse.  Because
an open descriptor continues to reference one complete inode across an atomic
replacement, a
refresh concurrent with a writer can safely observe the old snapshot and pick
up the new snapshot on the next refresh.  The production design still needs a
deterministic race test, not just that filesystem argument.

These are **parse-stage** numbers, not a claim that all status work becomes
0.1 ms.  At the current real size, eliminating the entire 13.7-ms parse can save
at most about 9% of the 156-ms CLI call.  At 5k it can remove roughly 37%; at
10k, roughly 51%.  The remaining interpreter/import/argparse and bounded status
work stays fixed.

## Recommendation

Do not adopt `python -O`, Nuitka, or another compiled distribution as the status
optimization.  The measured optimized mode is worse for CLI latency and neutral
for the suite; a `.pyc` saves startup but does not change O(N) parsing, while a
standalone build would add platform artifacts and release complexity without
addressing the scaling term.

Proceed to the incremental-fold co-design, but keep the production scope narrow:

1. Put an in-memory turn cache in the long-lived top path.  The current top
   spawns a fresh `status --json` process every refresh, so merely adding a cache
   inside that short-lived process would achieve nothing; the co-design must
   define how top owns or calls the persistent cache while preserving fallback
   behavior.
2. Do not add a sidecar cache for ordinary one-shot CLI status yet.  The current
   456-live-turn relay offers only a modest upper-bound saving, while persistence,
   invalidation, permissions, and crash recovery add risk.
3. Preserve frozen snapshot v1 byte-for-byte.  The acceptance gate is
   incremental result equals full result for no change, one/many appends,
   LOCK-length changes, archive rotation, malformed/truncated tails, and a
   deterministic concurrent atomic replacement.  Any mismatch must fall back,
   never publish a partial snapshot.
4. As a low-risk companion improvement, derive `last_turn` from the already
   parsed tail and parse the session ledger once.  This removes redundant scans
   but does not replace the incremental design at large scale.

The materiality threshold on this host is around 5k live turns, where parsing is
already about 88 ms and 37% of status latency.  The long-lived two-second top is
the earlier practical beneficiary because it can amortize one full parse across
many refreshes.  Regular archive rotation remains a valid operational bound and
reduces the urgency for one-shot CLI calls.
