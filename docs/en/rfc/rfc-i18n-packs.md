# RFC — M8Shift i18n: English-only core + injectable language packs

- **Status:** Proposed
- **Companion to:** the single-file / stdlib / passive identity (no runtime change).

## 1. Summary

Today both English and French are baked inline into `m8shift.py` (`MESSAGES = {"en", "fr"}`
plus four template families for protocol, stanza, seed, and bridge content, each `{"en", "fr"}`).
Adding a 3rd language means editing the monolith in ~5 places. This RFC externalizes i18n:

- the **committed `m8shift.py` is English-only** — the canonical source and a runnable,
  cp-and-go single file;
- each non-English language is an **external pack** (`i18n/<lang>/…`), tracked as data;
- a **stdlib injector** (`m8shift-i18n.py`) produces a *self-contained* `m8shift.py` carrying
  English + the chosen languages, for anyone who wants a localized build.

The runtime stays unchanged (`--lang` / `$M8SHIFT_LANG` select among the *available* languages,
fallback English). **There are no current FR users**, so the cutover is clean (no continuity
burden). This formalizes and replaces the existing local `build/assemble.py`.

## 2. Status quo (what exists)

- Inline `MESSAGES`, and the English/French protocol, stanza, seed, and bridge constants, joined
  into the runtime template dictionaries in `m8shift.py`.
- `build/` already holds the **EN sources** (`protocol.en.md`, `stanza.en.txt`, `seed.en.txt`,
  `bridge.en.txt`) + `assemble.py`, but is **gitignored / local** and the committed file is the
  assembled artifact.
- `scripts/gen_docs.py` writes `docs/{en,fr}/protocol*.md` from `PROTOCOL[lang]`;
  `test_protocol_docs_in_sync` byte-compares them. A few tests assert FR runtime output
  (`--lang fr`, `$M8SHIFT_LANG=fr`) or `BRIDGE["en"]`.

## 3. Decision

**EN-only committed core + per-language packs + a build-time injector.**

- **Core = English, inline.** `m8shift.py` keeps `MESSAGES = {"en": {…}}` and the EN template
  constants only, joined as `PROTOCOL = {"en": PROTOCOL_EN}` etc. The bare committed file runs in
  English with zero build step (cp-and-go preserved). English is the source of truth for *keys*
  and *structure*.
- **Non-EN = packs.** `i18n/fr/`, `i18n/it/`, … hold the translations as data. EN is NOT a pack
  (it stays inline so the bare file is runnable).
- **Injector = build/deploy tool**, not part of the passive relay core (same tier as
  `gen_docs.py`). stdlib only; produces a single self-contained file.

## 4. Pack format

One **directory per language** (markdown templates stay markdown — far better to translate than
escaped JSON):

```
i18n/fr/
  messages.json     # {key: "value"} — the MESSAGES["fr"] dict, flat JSON (stdlib)
  protocol.md       # PROTOCOL_FR body
  stanza.txt        # STANZA_FR body
  seed.txt          # M8SHIFT.md seed body
  bridge.txt        # BRIDGE_FR body
```

- `messages.json` keys MUST be a subset of the EN keys (the injector errors on an unknown key and
  warns on a missing one → that key falls back to EN at runtime).
- The template files are verbatim bodies, exactly like the existing `build/*.en.*` EN sources.
- A `i18n/<lang>/meta.json` (optional) may carry the language label.

## 5. Injector CLI

```bash
m8shift-i18n.py --langs it,ru --into /work/dir/        # build with EN + it + ru
m8shift-i18n.py --langs fr --into . --name m8shift.py  # default output name
m8shift-i18n.py --check i18n/it                         # validate a pack vs the EN keys
```

Mechanism (mirrors `assemble.py`, generalized + from external packs):
1. Read the EN core `m8shift.py`.
2. For each requested `<lang>`: read its pack; insert a `<LANG>` template constant per family and
   add a `"<lang>": <LANG>_TPL` entry into each protocol/stanza/seed/bridge template dict, and a
   `"<lang>": {…}` entry into `MESSAGES`, targeting the existing dict literals via stable anchors
   (e.g. `PROTOCOL = {"en": PROTOCOL_EN}` → add `, "fr": PROTOCOL_FR`).
3. `ast.parse` the result (syntax gate, as assemble.py already does), write the self-contained file.

Constraints: stdlib only; deterministic output (sorted/ordered) so a rebuild is reproducible;
never network; refuses an unknown/foreign key in a pack (no silent drift).

## 6. Runtime (unchanged)

`--lang xx` / `$M8SHIFT_LANG=xx` selects among the languages **present in this build**; an absent
language falls back to `DEFAULT_LANG = "en"`. `resolve_lang` and `LANGS` are unchanged in shape —
`LANGS` is computed from the keys actually injected (so a bare EN build has `LANGS = ("en",)`).

## 7. Release plan

- The **canonical, committed** artifact is the **EN-only `m8shift.py`** (the source). The injector
  + `i18n/` packs are tracked (replacing the local `build/assemble.py`).
- **Release assets** (forge + GitHub) ship pre-built bundles for non-builders: at least `m8shift.py`
  (EN) and a `m8shift.py` built with all packs (`en+fr+…`), so a localized user can grab a file
  without running the injector.

## 8. Tests / docs impact

- `scripts/gen_docs.py` generates `docs/<lang>/…` from the **packs** (and EN from the core), rather
  than from `PROTOCOL["fr"]` in the bare core.
- `test_protocol_docs_in_sync` compares `docs/<lang>/…` to the **pack body** (or to an injected
  build), not to a `PROTOCOL["fr"]` that no longer exists in the bare core.
- FR-asserting tests (`--lang fr`, `$M8SHIFT_LANG=fr`, `PROTOCOL["fr"]`) run against an **injected
  `en+fr` build** produced once by a test fixture (the harness already copies `SCRIPT` into a temp
  dir — it injects first). EN-only assertions (`BRIDGE["en"]`, all relay/mutex tests) run against
  the bare core unchanged.
- A new **pack-validation test**: every `i18n/<lang>/messages.json` key ∈ EN keys; each pack has the
  four template files; an injected build `ast.parse`s and passes a smoke relay.

## 9. Migration steps

1. Extract the inline FR into `i18n/fr/` (messages.json + the four template bodies); make the core
   EN-only (`MESSAGES = {"en"…}`, `PROTOCOL = {"en": PROTOCOL_EN}`, …).
2. Write `m8shift-i18n.py` (stdlib injector) + `--check`.
3. Rewire `gen_docs.py` to read packs; update `test_protocol_docs_in_sync` accordingly.
4. Add the injected-build test fixture for FR-asserting tests; add the pack-validation test.
5. Track `i18n/` + the injector; retire `build/assemble.py` (document the new flow in CONTRIBUTING).
6. CI/release: build the bundle assets.

## 10. Non-goals

- **No runtime dependency / no YAML / no auto-translation.** The injector is a build step; the
  injected file is plain stdlib Python.
- The injector is **not** part of the passive relay core (it is tooling, like `gen_docs.py`).
- Not a plugin/loader that reads packs at runtime — that would make `m8shift.py` non-self-contained.

## 11. Resolved decisions

1. **Committed artifact:** EN-only `m8shift.py` is canonical; a built `en+fr` ships as a release asset.
2. **Pack shape:** directory with `messages.json` + markdown template bodies.
3. **Injector name:** `m8shift-i18n.py`.
4. **FR tests:** a session fixture injects an `en+fr` build once (`InjectedFRBase`); FR-asserting
   tests run against it, all other tests stay on the bare EN core.

## 12. Review outcome (validation panel) — required changes, now the build contract

GO-with-additions. Three blockers were reproduced end-to-end; this is the corrected contract:

- **(blocker) Cross-build `lang` validation.** `load_or_die` must validate the LOCK `lang` against a
  **curated `KNOWN_LANGS` superset**, NOT the build-local `LANGS`, and NOT a bare `[a-z]{2}` regex
  (which wrongly accepts the `lang:xx` malformed-value test). A well-formed lang **absent from this
  build is accepted and downgraded to `DEFAULT_LANG`** (`resolve_lang` already does this) — **never
  `lock_invalid`**. So an `en+fr` build's `M8SHIFT.md` (with `lang: fr`) is loadable by a bare-EN
  build, in English. This MUST land *before* the core goes EN-only.
- **(blocker) Injector raw-string safety.** Each template family is emitted with the **same prefix
  its EN constant uses** (raw `r"""` for protocol+seed, plain `"""` for stanza+bridge) — never
  uniform. The gate is **not** `ast.parse` alone: compile under `warnings.simplefilter("error")`
  **and** a **round-trip byte assertion** (re-import each constant == the pack body). `--check`
  rejects a body containing the triple-quote sequence or a trailing odd backslash run.
- **(blocker→moot) migrate-brand on a French legacy file** — dissolved by v3.0.0 (§15 removes
  migrate-brand). The `KNOWN_LANGS` fix above still stands for any `lang:fr` file.
- **Three lang sources, distinct:** CLI `--lang` = **hard** (`argparse choices=LANGS`; an absent lang
  is a usage error rc 2 — by design); `$M8SHIFT_LANG` = **soft** (→ `DEFAULT_LANG`); LOCK field =
  **soft** (after the fix). The earlier blanket "`--lang fr` falls back to English" was wrong.
- **No "mirror assemble.py".** It is FR-primary with 100%-stale anchors; the injector is a
  from-scratch **AST-targeted** rewrite: find the `Assign` whose target is
  the protocol/stanza/seed/bridge/message dictionaries with a `Dict` value, splice by source offset, assert
  one anchor each. `LANGS = tuple(PROTOCOL)` (single source of truth). The injector **sorts+dedupes**
  langs, builds in one pass, orders each `MESSAGES` sub-dict's keys to the EN order (EN fallback on
  miss), and **refuses a core already carrying a target lang** (idempotent, byte-reproducible).
- **Pack invariants (§4 amended):** all four template bodies are **required + non-empty** (no runtime
  per-family fallback for stanza/seed/bridge templates — only `messages.json` keys fall back to EN);
  bodies are `str.format` inputs (translator escapes braces; `{begin}`/`{end}` are injected, not
  inlined); `--check` dry-renders each `stanza.txt`/`seed.txt` and rejects literal reserved relay
  markers or missing `{begin}`/`{end}`.
- **gen_docs / doc-sync, pack-direct.** `gen_docs.py` writes `docs/en` from the core and
  `docs/<lang>` from `i18n/<lang>/protocol.md` **directly** (never `PROTOCOL[lang]`).
  `test_protocol_docs_in_sync` compares `docs/en` to the core and `docs/<lang>` to the pack body
  (skip when absent). This rewire lands in the **same commit** as the core strip (else CI goes red).
- **Provenance for the FR pack:** regenerate `i18n/fr/` from the **committed** constants (the
  gitignored `build/` has drifted — its `seed.en.txt` lacks the `agents:`/`__AGENTS__` fields).
- **Tooling:** `CONTRIBUTING.md` does not exist (create); CI runs the injector with all packs under
  warnings-as-error + a smoke relay, and attaches the EN and `en+fr` builds as release assets.

## 13. Tests (injector + migration)

`--check` rejects unknown key / missing template / brace-unsafe stanza; `en→en+fr` compiles
warnings-as-error and passes a smoke relay; injected `PROTOCOL["fr"]` is byte-identical to
`i18n/fr/protocol.md` and to today's inline FR; two lang orderings → identical bytes; double-inject
errors. A bare-EN build reading a `lang:fr` fixture → `status`/`claim` rc 0, English output; bare-EN
`--lang fr` exits 2 ("invalid choice"). `test_lang_field_in_schema` (`lang:xx` rejected) stays green
via `KNOWN_LANGS` membership.

## 14. Target languages

`en` is the core; the **8 packs** mirror the Publisher X site: `fr`, `es`, `it`, `de`, `pt`,
`ja`, `ru`, `zh-cn`. First pass is **machine-translated**, each pack stamped
`provenance: machine-translated, review pending` (especially `ja`/`zh-cn`/`ru`).

## 15. Versioning — this lands as v3.0.0

The EN-only cutover is breaking, so it ships as **v3.0.0** (major). v3.0.0 makes the
public surface **M8Shift-only** and removes deprecated migration shims and fallback paths. The
committed `m8shift.py` remains the canonical single-file relay; localized builds are produced by
the injector.

---

*The relay core stays a single passive English file you can cp and run; languages become tracked
data a build-time injector folds in, on demand, into a still-single self-contained file.*
