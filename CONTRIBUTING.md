# Contributing to M8Shift

M8Shift is a single self-contained file (`m8shift.py`), stdlib-only, with no build step
for normal use — clone, copy `m8shift.py` into a repo, run it. Keep it that way.

## Ground rules

- **Stdlib only.** No third-party dependencies, ever. The tool must run on a bare Python 3.8+.
- **One file.** `m8shift.py` stays self-contained and runnable as-is.
- **English is the source of truth.** The committed `m8shift.py` is **English-only**: it is the
  canonical source for every message key and every template. Other languages live as *packs*
  under `i18n/<lang>/` and are spliced in on demand (see below) — they never live in the core.
- **RFCs are English-only.** Design proposals and decision records live under
  `docs/en/rfc/NNN-rfc-*.md` only. Do not create translated RFC copies under `docs/fr/` or any
  other localized documentation tree; localized docs may link to the English RFCs.
- **Tests must stay green.** `python3 -m unittest discover -s tests`.

## Language policy

English is the canonical development language for M8Shift. Commit messages,
branch and merge-request descriptions, release notes, code identifiers, inline
comments, tests, architecture notes, and design/RFC documents should be written
in English by default.

User-facing translations are welcome, but they live in the explicit
internationalisation surfaces:

- language packs under `i18n/<lang>/`;
- localized tutorials and how-to pages under the matching `docs/<lang>/` tree;
- links from localized docs back to canonical English references when duplicating
  content would create drift.

Durable project decisions that affect code, protocol behavior, or documentation
structure must be recorded in English, or include an English summary when the
working discussion used another language. Operational relay turns may be
bilingual when useful; the permanent project record stays readable by every
contributor.

## Internationalisation (i18n)

The runtime selects a language via `--lang <code>` or `$M8SHIFT_LANG` (fallback: English).
A build only carries the languages bundled into it; `KNOWN_LANGS` lists every recognised code
so a file written by a richer build stays loadable (an unbundled language downgrades to English).

### A language pack — `i18n/<lang>/`

| file | what it is |
|------|------------|
| `messages.json` | runtime strings — **same keys as English**, values translated |
| `protocol.md`   | the protocol reference doc (also published as `docs/<lang>/`) |
| `stanza.txt`    | the per-agent stanza template (uses `{begin} {end} {me} {ME} {other} {OTHER}`) |
| `seed.txt`      | the initial `M8SHIFT.md` template (uses `__PROJECT__ __NOW__ __LANG__ __AGENTS__ __A__ __B__` and literal `M8SHIFT:` markers) |
| `bridge.txt`    | the short `AGENTS.md → CLAUDE.md` bridge note |
| `meta.json`     | `{ "code", "name", "provenance" }` |

**Preserve verbatim** in every template/value: `{placeholders}`, `__SEED_TOKENS__`, structural
`M8SHIFT:` markers, protocol state constants (`IDLE`, `WORKING_<AGENT>`, `AWAITING_<AGENT>`,
`DONE`), and all CLI commands/flags/filenames. Never introduce a triple-quote sequence.

> The non-English packs shipped here are **machine-translated, pending human review**
> (`provenance` says so). Improvements to any pack are very welcome.

### Validate and build

```bash
python3 m8shift-i18n.py --check fr                       # validate one pack
python3 m8shift-i18n.py --langs fr,es,de --into ./dist   # build EN + those languages
python3 m8shift-i18n.py --langs fr,es,it,de,pt,ja,ru,zh-cn --into ./dist   # EN + all packs
```

The builder is AST-targeted, idempotent and byte-reproducible: it compiles the result under
*warnings-as-error* and round-trips every injected constant against its pack before writing.

After editing the English protocol template **or** a pack, regenerate the docs so
`test_protocol_docs_in_sync` stays green:

```bash
python3 scripts/gen_docs.py
```

## Commits

Branch per change; keep `main` green. Don't commit relay artefacts (`M8SHIFT.md`,
`.m8shift.lock`, `CLAUDE.md`, `AGENTS.md`, …) — they are gitignored.

When dogfooding M8Shift itself, keep the relay in a dedicated directory outside the
source repo (for example `../m8shift-relais`). Do not run the live relay from inside
the repo being changed; relay state and source work must not share the same tree.
When a repo is coordinated through M8Shift, run `./m8shift.py may-i-write <agent>` (or
the alias `guard <agent>`) before scripted writes or commits. It exits 0 only while
that agent holds a non-expired `WORKING_<AGENT>` lock; any other rc means stop and
follow the printed next action.

### Pre-commit hook (enforce the pen on commit)

`hooks/pre-commit` is a POSIX-sh, stdlib-only, **local and advisory** Git hook that runs
`may-i-write` immediately before each commit, so the rule is *enforced* — not merely
documented. Install it per clone (Git does not version-control `.git/hooks/`):

```bash
cp hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Behaviour:

- `$M8SHIFT_AGENT` **unset** → the hook exits 0 (skip). Humans and unconfigured
  checkouts are never blocked.
- `$M8SHIFT_AGENT` **set** → the hook runs `m8shift.py may-i-write "$M8SHIFT_AGENT"` and,
  on any non-zero rc, prints why and **blocks the commit** (fail *closed*). The relay
  root is resolved by `m8shift.py` via `$M8SHIFT_ROOT`; the program is found via
  `$M8SHIFT_BIN`, else `m8shift.py` on `$PATH`, else `./m8shift.py` at the repo root.

**Zero-memory note.** A fresh agent needs no memorised rule: the policy lives in the
program. The `init`-generated anchors (`CLAUDE.md` / `AGENTS.md`) tell the agent to set
`$M8SHIFT_AGENT` and run `may-i-write`; the installed hook then enforces it at commit
time. Hook + `may-i-write` + anchors are self-contained.

This hook is **advisory and local** — it is not a security boundary and does not contact
the network. It narrows, but does not fully close, the check-then-commit race; see the
SEC-7 / TOCTOU note in [`docs/en/protocol-reference.md`](docs/en/protocol-reference.md).
Commits made under a M8Shift relay should also carry:

```text
Coordinated-With: M8Shift vX.Y.Z
```

`m8shift.py init` writes `.m8shift/hooks/commit-msg`, a hook template that injects this
trailer from the active relay version. For an external relay, run commits with
`M8SHIFT_ROOT=/path/to/relay`; without a configured relay the hook exits cleanly and
does not block the commit. It is a `commit-msg` hook (not `prepare-commit-msg`) on
purpose: it stamps the *final* saved message, so it never tags a commit the author
aborted by emptying the editor. Because that final buffer may be a `git commit -v`
message (body followed by a `>8` scissors line and the diff), the hook inserts the
trailer into the message body — inside the trailer block, above the scissors — so it
survives verbose commits instead of being dropped with the diff.
