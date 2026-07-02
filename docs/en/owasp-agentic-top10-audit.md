# Security audit — M8Shift against the OWASP Top 10 for Agentic Applications 2026

- **Date:** 2026-06-27
- **Scope:** the **M8Shift** project (`m8shift.py` v3.41.1) and its companions, mapped
  threat-by-threat onto the OWASP Agentic Top 10 (ASI01 → ASI10).
- **Mode:** read-only source review. Every statement about the code was verified against
  the source (`file:line` citations).
- **Reference framework:** OWASP Top 10 for Agentic Applications 2026
  (OWASP GenAI Security Project — Agentic Security Initiative), <https://genai.owasp.org>.

> **Auditor's note:** this document confronts the **M8Shift** project against the ten
> threats of the OWASP Agentic Top 10. It is aligned with the existing internal audit
> [security-audit.md](./security-audit.md) (findings **SEC-1 → SEC-11**, dated 2026-06-25),
> which it **re-maps onto the ASI grid** — something the internal audit does not do.

## 1. Executive summary

M8Shift is a **multi-agent coordination relay** (Claude ↔ Codex and others): a
"degree-1" cooperative mutex around a shared relay file `M8SHIFT.md`, plus advisory
companions (degree-2 worktrees, runtime). It is a **single-file Python script, stdlib
only, with no network, no daemon, and no API key**.

> [!IMPORTANT]
> **The single most structuring security fact:** M8Shift is **not a security boundary
> against malicious agents**. It is a **cooperative coordination tool** for a **team of
> trusted agents that you run yourself**. This threat-model decision determines, for each
> ASI, what is "to be mitigated" versus "out of scope by design".

Direct consequence: M8Shift **eliminates** by construction the most frequently cited
attack surfaces of the OWASP Agentic Top 10 (no network → no MITM/downgrade/routing
spoofing; the **core** has no dependencies → near-zero supply chain and no `eval`/`shell` → no tool RCE — though the **optional v3.40+ installer/adapters add an opt-in, sha256-pinned supply-chain surface**; see ASI04/ASI05), but
**delegates to trust** the properties that OWASP recommends making cryptographic (agent
identity, message signing).

### Coverage matrix

| ASI | Threat | Relevance to M8Shift | Status | Action |
|-----|--------|----------------------|--------|--------|
| **ASI01** | Goal Hijack | Substrate (carries NL `ask`/`body`) | 🟡 Partial | Reinforce (boundary documented, not filtered) |
| **ASI02** | Tool Misuse | The tool itself (`--force`, append) | 🟢 Good | Minor hardening |
| **ASI03** | Identity & Privilege Abuse | Substrate (identity = pen) | 🟠 Out of scope by design | Document / future option |
| **ASI04** | Supply Chain | The tool (its own deps) | 🟢 Excellent | Sign releases |
| **ASI05** | RCE | The tool (git subprocess, i18n) | 🟢 Good | SEC-4 fixed + tested |
| **ASI06** | Memory & Context Poisoning | Substrate (shared memory) | 🟢 Strong integrity / 🟡 content | Optional improvements |
| **ASI07** | Insecure Inter-Agent Comm. | **This is exactly M8Shift** | 🟢 Local integrity / 🟠 no crypto | Network surface = N/A |
| **ASI08** | Cascading Failures | Substrate (serialization) | 🟢 Anti-cascade by design | Optional cap |
| **ASI09** | Human-Agent Trust | Observability for the human | 🟢 Strong traceability | Document |
| **ASI10** | Rogue Agents | Containment of a derailed agent | 🟠 Strong detection / prevention by-design | Explicit out of scope |

Legend: 🟢 covered/solid · 🟡 partial · 🟠 out of scope by design (to be owned/documented) · 🔴 gap to fix.

## 2. M8Shift's threat model (indispensable prerequisite)

Before judging "covered / not covered", we must establish **against whom** M8Shift
defends.

| Dimension | M8Shift's choice | Verified |
|-----------|------------------|----------|
| **Network** | None. No `socket`/`http`/`urllib`/`requests` import. | ✅ `grep` imports → 0 |
| **Execution** | No `eval`/`exec`/`os.system`/`shell=True`. Subprocess = `git` in argv only. | ✅ `m8shift.py:1185,1194` |
| **Dependencies** | stdlib only (`argparse, json, os, re, subprocess, tempfile, …`). No `requirements.txt`. | ✅ |
| **Identity** | **Declarative, cooperative**: one agent = one name (`claude`, `codex`) read from the roster. No auth, no signature. | ✅ `AGENTS=("claude","codex")` |
| **Confidentiality** | Local filesystem (lock `0o600`). `M8SHIFT.md` = readable plaintext. No encryption. | ✅ `m8shift.py:828` |
| **Integrity** | Mutex + atomic write + immutable append-only turns + marker neutralization + schema validation. | ✅ (detailed §3–§7) |
| **Assumed environment** | **Honest cooperative team** (agents the operator launches/controls). | ✅ declared in `docs/en/security-audit.md` |

> [!NOTE]
> **Two audit perspectives coexist**, and they must be distinguished at all times:
> - **M8Shift-as-tool:** is the Python code safe? (path traversal, injection, tool RCE) → concerns ASI02, ASI04, ASI05.
> - **M8Shift-as-substrate:** as a channel and shared memory *between* agents, does M8Shift provide the properties OWASP requires for the multi-agent layer? → concerns ASI01, ASI03, ASI06, ASI07, ASI08, ASI10.

## 3. Detailed audit by threat (ASI01 → ASI10)

### ASI01 — Agent Goal Hijack 🟡 Partial

**Relevance:** M8Shift carries natural-language fields (`ask`, `done`, `body`, `handoff`)
from one agent to another. A poisoned turn can convey instructions that a receiving LLM
will treat as orders → the classic indirect-injection vector.

**✅ What is covered (at the tool level)**
- **Fake-marker neutralization:** `clean_body()` replaces `M8SHIFT:` with `M8SHIFT​:` (zero-width) → a body **cannot forge a fake turn or a fake LOCK block** (`m8shift.py:1068-1071`).
- **Header anti-forgery:** `clean_field()` rejects any line break (LF/CR/VT/FF/FS/GS/RS/NEL/LS/PS) and the reserved markers → a field cannot inject an extra `- key: value` line (`m8shift.py:1046-1060`).
- **Documented prompt boundary (SEC-1, v3.12.0):** the STANZA and the protocol now explicitly tell agents that `ask`/`body`/`memory`/`tasks`/peer content = **"untrusted coordination data"**, and that they must refuse requests aimed at bypassing `claim`, revealing secrets, or ignoring their system instructions.

**🟡 What remains**
- The boundary is only **enforceable** if the agent honors it. As a transport, M8Shift **does not semantically filter** content (no CDR, no prompt-carrier detection). This is consistent with its role (a transport should not rewrite the payload), but it remains a residual risk carried by the LLM.

**Recommendation:** **Accept + reinforce.** Semantic injection filtering is *out of scope*
for a text relay. The structural protection (markers) is correct. Possible improvements:
an **optional hook** for content scanning on `append` (disabled by default), and keeping
the boundary stated explicitly across all i18n languages.

### ASI02 — Tool Misuse & Exploitation 🟢 Good

**Relevance:** M8Shift **is a tool** that agents invoke (self-executable CLI). Misuse =
abuse of the subcommands, in particular the `--force` overrides.

**✅ Covered**
- **Narrow scope:** the relay only writes coordination files; no costly API, no network → **no billable loop amplification** and no network exfiltration (the ASI02 "ping → DNS exfil" scenario is structurally impossible).
- **Audited `--force` override (SEC-2, v3.12.0):** `release --force` / `done --force` require `--reason`, write the event to `M8SHIFT.sessions.jsonl`, and are surfaced by `doctor --security` (`m8shift.py:3966-3995`, `2620-2629`).
- **Path denylist for `session report --write`:** `RESERVED_REPORT_OUTPUT_RELATIVE_PATHS` protects `m8shift.py`, the companions, `examples/`, `scripts/`, and `checksums.sha256` against overwrite (`m8shift.py:2056-2066, 2118-2137`).
- **Roster validation before routing:** `need_agent()` rejects any off-roster agent (`m8shift.py:1145-1148`).

**🟡 Minor gaps**
- No **rate-limiting** on `append`: an agent could spam turns (local DoS of the file). Low impact (local, detected by `doctor` for size > 1 MiB) — see **SEC-8**.

**Recommendation:** **Minor hardening.** Optional: per-session turn cap / frequency warning.
The design (narrow scope + audited force) is sound.

### ASI03 — Identity & Privilege Abuse 🟠 Out of scope by design

**Relevance:** this is where the **cooperative model** is most exposed. In M8Shift,
**identity = possession of the "pen"** (state `WORKING_<agent>`), and privilege = the
exclusive right to write a turn.

**✅ What exists**
- **Exclusive acquisition:** `claim` creates the lock via `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)` + token `pid:time_ns` (`m8shift.py:971, 978`).
- **Write right bound to state:** only `WORKING_<agent>` can append (`if st != f"WORKING_{agent.upper()}": sys.exit(...)`, `m8shift.py:3870`).
- **No silent pen theft:** `--force` is accepted only if the lock is *stale* (TTL > 30 min or mtime > 60 s) (`m8shift.py:3587-3593`); an override of an active lock requires `--reason` + leaves a trace.
- **Anti-bounce:** `release` refuses to hand back an unread incoming turn unless `--force --reason` (`m8shift.py:1498-1512, 3982-3984`).

**🟠 Owned gap**
- **No cryptographic identity.** Identity is **declarative**: any process able to run the script can `claim <any name>`. The OWASP ASI03 recommendations (per-agent scoped tokens, mTLS, **signed intent**, re-auth on context switch) **are not implemented — and should not be** in the current local model.

**Recommendation:** **Out of scope by design, to document clearly.** As long as the
environment is "a team of trusted agents launched by the operator", impersonation is a
non-problem (the attacker would already have local execution). **If the threat model
changed** (untrusted third-party agents, multi-tenant, remote execution), one would need
to add **per-agent identity** (a per-agent secret token at `claim`) — but that would
contradict the "no key, no daemon" philosophy. → See §5 "What to deliberately NOT do".

### ASI04 — Agentic Supply Chain Vulnerabilities 🟢 Excellent

**Relevance:** the supply chain **of M8Shift itself**, and M8Shift as a component of
*your* agentic supply chain.

**✅ Covered (a major strength of the project)**
- **Zero third-party dependencies (core relay):** the relay scripts are stdlib only, **no `requirements.txt`/`pyproject.toml`** → the *core*'s dependency surface is near-nil (no PyPI/npm typosquatting or poisoned package in the relay itself).
- **⚠️ Optional installer/adapter supply chain (v3.40+, post-audit — was NOT in scope at v3.26.0):** the shipped *system* is no longer zero-surface. `install.sh --with-rtk` downloads a prebuilt RTK release asset (verified against the release tag's `checksums.txt` over TLS — same-origin **TOFU**, not an independent signature) and, with `--allow-source-build`, can `cargo` build from a **tag-pinned** source; `--with-headroom` pip-installs `headroom-ai` (**unpinned**, best-effort) into `.m8shift/venvs/headroom`. At runtime the RFC 042 compression path invokes those allowlisted binaries (`rtk`/`headroom`) via the RFC 034 **identity-pinned (realpath+sha256), argv-only, output-capped** runner. So ASI04 is 🟢 for the **core** but the **installed adapters carry a real (opt-in, sha256-pinned, no-shell) supply-chain surface** — tracked in #94 (project-local opt-in), #95 (Headroom venv), #97 (this re-scope).
- **Portable single file:** `m8shift.py` is a copyable executable, Python 3.6+.
- **Self-protection of scripts:** `checksums.sha256` + denylist prevent the tool from overwriting its own scripts via `session report` (`m8shift.py:2085-2101`).

**🟡 Minor gaps**
- The scripts themselves are **not signed** (no release signature). A user who clones the repo trusts the forge.
- The worktree companion runs `git merge`/`git mv` → trusts the local git repo (legitimate).

**Recommendation:** **Sign the releases** (GPG-signed tag / published checksums) for
distribution, and keep publishing `checksums.sha256`. This is the ASI where M8Shift is
**exemplary**: the best supply-chain defense is often *to have no dependencies*, which is
exactly the choice made.

### ASI05 — Unexpected Code Execution (RCE) 🟢 Good

**Relevance:** can M8Shift be diverted to execute code?

**✅ Covered**
- **No `eval`/`exec`/`os.system`/`shell=True`** (`grep` → 0).
- **Subprocess = `git` in strict argv:** `["git","-C",HERE,"ls-files",...]` and `["git","-C",HERE,"mv","-f","--",...]` (`m8shift.py:1185, 1194`) → no shell injection.
- **Adapters = allowlisted, identity-pinned argv subprocess (v3.40+, post-audit):** since RFC 042, `m8shift-context.py` also runs `rtk`/`headroom` (allowlist `ALLOWED_ADAPTER_PROGRAMS`) via **argv-only** `subprocess.run` through the RFC 034 runner — **realpath+sha256 pin**, env-allowlisted, output-capped, **no shell / no `eval`**. So subprocess is no longer *only* `git`; it is `git` + pinned adapters. A renamed/planted/wrapped binary fails the pin (fail-closed), and a project-local `.m8shift/bin` binary needs explicit `--allow-project-local-adapters` (#94). The residual is the adapter *supply chain* (ASI04), not shell RCE.
- **Ref validation before subprocess (worktree):** `safe_branch_name()` rejects leading `-`, whitespace, control characters and runs `git check-ref-format`; `safe_id()` rejects `/`, `..`, whitespace (`m8shift-worktree.py:72-80, 91-94`).

**🟢 SEC-4 (i18n builder) — fixed**
- `m8shift-i18n.py` **generates and executes** code, so its `--name` option is the **only RCE-adjacent surface** in the project. It is hardened in depth: `safe_output_name()` rejects any `--name` that is not a plain basename (no `/`, no `..`, no absolute path, no `os.altsep`), and the output path is then re-validated with `os.path.realpath` + `os.path.commonpath` ("output path escapes --into"). A `--name ../x` is refused and nothing is ever written outside `--into` (`m8shift-i18n.py:44-49, 247-252`).
- Regression test: `tests/test_m8shift.py::TestInjector::test_name_rejects_path_escape` drives the builder with `../evil.py`, `foo/bar.py`, `/etc/passwd`, `a/../../../b`, `..` and asserts each is rejected with no file escaping `--into`.

**Status:** closed (was the P1 action of this audit) — verified empirically and locked by a regression test.

### ASI06 — Memory & Context Poisoning 🟢 Strong integrity / 🟡 content

**Relevance:** **M8Shift IS the shared memory** of the agents — `M8SHIFT.md` (turn
journal), `M8SHIFT.memory.md`, `M8SHIFT.tasks.md`, `M8SHIFT.sessions.jsonl`. ASI06 is
directly applicable.

**✅ Covered (integrity)**
- **Append-only + immutable closed turns:** a closed turn (END marker) is read-only, with no retroactive rewrite (`parse_turns`, `m8shift.py:1476-1495`).
- **Atomic write:** `mkstemp` + `os.replace` preserving the mode → no partial write / corruption (`m8shift.py:822-840`, verified).
- **Anti-forgery of memory entries:** `M8SHIFT:` neutralization + line-break rejection → one cannot inject a fake note/turn/LOCK into memory.
- **LOCK schema validation** before any routing (agents, state, turn, holder, lang, session, integrating) (`m8shift.py:1016-1041`).
- **Bounded archiving:** `archive --keep N` moves old turns to `M8SHIFT.archive.md` (retention).

**🟡 Gap vs OWASP ASI06 recommendations**
- No **signed provenance**, no per-entry **trust score**, no **decay/expiry** of unverified entries, no **content scan** on memory writes (ASI06 §2,5,7,9). But: these are recommendations for **multi-tenant RAG/vector stores**; M8Shift is a single-context text journal. "Bootstrap poisoning" (auto re-ingestion of outputs) **does not exist**: M8Shift ingests nothing automatically — it is the agents who read.

**Recommendation:** **Optional improvements.** Integrity (impossible to forge/rewrite) is
**solid**. On the content side: optional — an extended `doctor` could flag memory notes
with abnormal volume/frequency (light anomaly detection). No per-tenant namespaces needed
(single-context assumed).

### ASI07 — Insecure Inter-Agent Communication 🟢 Local integrity / 🟠 no crypto

**Relevance:** **M8Shift is, literally, the inter-agent communication channel.** This is
the most directly applicable ASI. Let us confront the OWASP recommendations point by
point:

| ASI07 recommendation | M8Shift state | Verdict |
|----------------------|---------------|---------|
| E2E encrypted channels, mTLS, PKI, pinning | **N/A** — local file, no network | MITM surface **eliminated** |
| Message integrity & signing | No crypto signature; integrity = append-only + atomic write + marker neutralization + lock | 🟢 local / 🟠 no signature |
| Anti-replay (nonces, timestamps) | Monotonic integer `turn` + `session` id; immutable closed turns → intra-file replay impossible | 🟢 |
| Protocol & version pinning | `doctor` verifies the sync of `protocol.md`; VERSION lockstep across the 7 scripts | 🟢 |
| Schema validation / typed contracts | LOCK schema validated, turn structure parsed, field-injection guards | 🟢 |
| Attested registry / agent verification | **Declarative** roster, no attestation | 🟠 by-design |
| Limit metadata inference | N/A (no network traffic to analyze) | N/A |

> [!IMPORTANT]
> **The key insight:** the majority of ASI07 vectors (MITM on unencrypted channels,
> protocol downgrade, A2A registration spoofing, routing attacks, traffic-metadata
> analysis) **presuppose a network**. By being **local-file-only**, M8Shift **removes this
> entire class of threats** rather than mitigating it. What remains (integrity, ordering,
> anti-replay, schema) is ensured locally by the mutex + immutability + validation.

**🟠 What remains owned:** no **encrypted confidentiality** (relies on FS permissions) and
no **signing** of turns (relies on git + conventional immutability).

**Recommendation:** **Document the transport model.** As long as it is local, the absence
of crypto is correct. **If M8Shift were ever networked** (shared server, remote agents),
one would need to add mTLS + message signing + roster attestation — at which point it
would be a **different product**.

### ASI08 — Cascading Failures 🟢 Anti-cascade by design

**Relevance:** does a fault (poisoned turn, looping agent) propagate in cascade through
M8Shift?

**✅ Covered (intrinsically anti-cascade architecture)**
- **Degree-1 mutex = a single writer at a time:** no fan-out, no self-propagated parallel action. This is the strongest **structural guarantee** against ASI08 (OWASP specifically recommends "separate planning/execution" and "circuit breakers" — degree-1 serialization does this natively).
- **Advisory companions:** runtime and worktree **never touch** the pen / `M8SHIFT.md` / network / auto-force; they observe and freeze, they do not propagate (advisory boundary, verified).
- **Integration sentinel:** `integrating:<id>@<sha>` refuses any public `--force` operation during a degree-2 merge (`m8shift.py:3560-3571`).
- **No auto-deploy / auto-force:** no automatic action triggered by a turn.
- **Livelock detection:** `doctor` detects the "ack-bounce" pattern (recent turns all "ack" with no file touched) and "WORKING with parked note" (`m8shift.py:2749-2761, 2737-2747`).
- **Bounded polling:** `wait` polls ~60 s (configurable), no tight loop; the headless runner has a bounded child timeout (RFC 020).

**🟡 Minor gap**
- The livelock is **detected** (`doctor`) but not **auto-stopped**: no hard circuit-breaker on a session's turn counter. Low impact (cooperative, local).

**Recommendation:** **Optional cap.** A per-session `--max-turns` or an automatic stop on
repeated ack-bounce (instead of a mere warning) would reinforce the blast-radius cap
recommended by ASI08 §7. Overall, M8Shift is **well aligned** with this threat.

### ASI09 — Human-Agent Trust Exploitation 🟢 Strong traceability

**Relevance:** M8Shift is agent↔agent infrastructure; the human is the operator/reader.
The risk: the human reads `M8SHIFT.md` and **trusts** potentially fabricated turn content.

**✅ Covered (observability = support for oversight)**
- **Rich inspection surfaces:** `status`, `recap`, `log`, `history`, `watch`, `peek` → the human sees *who holds the pen, what the state is, the turn/session history* (cf. ASI09 "provide plain-language risk summary").
- **Immutable logs + audit trail of `--force`:** `M8SHIFT.sessions.jsonl` is append-only, `force` events timestamped with `reason` → non-repudiation of administrative operations (ASI09 §2 "immutable logs").
- **Structural anti-forgery:** an agent cannot fabricate a fake turn header (`clean_field`) or a fake coordination block (`clean_body`).

**🟡 To keep in mind**
- The **content** of the `done:`/`ask:` fields is **written by the agents**: a human must not treat a `done: "tests OK"` claim as **verified** (it is an agent statement, not proof). This is inherent to any journal written by agents (ASI09 "fake explainability").

**Recommendation:** **Document.** Add a line to the protocol/README: *"turn content is
declarative, not verified; independently verify high-impact claims"*. Observability (the
true ASI09 defense) is already **strong**.

### ASI10 — Rogue Agents 🟠 Strong detection / prevention by-design

**Relevance:** can a derailed (rogue) agent using M8Shift be contained?

**✅ Detection / forensics (strong)**
- **Append-only, signed-by-convention ledger:** all actions (turns, force, pause/resume, done) are traced → **attribution** possible *a posteriori* (ASI10 §1 "governance & logging").
- **Light behavioral detection:** `doctor` spots ack-bounce, parked sessions, overlapping session identities.
- **Degree-2 containment:** isolated worktrees + integration sentinel limit the blast radius of an agent in integration.

**🟠 Prevention (weak — owned)**
- M8Shift **detects and traces** but does not **prevent** a determined rogue agent: declarative identity → an agent can usurp a name, `force-release` (with audit), or spam. The ASI10 recommendations (signed behavioral manifests, per-agent cryptographic attestation, kill-switch, orchestrator-mediated HSM/KMS keys) **are not implemented**.

**Recommendation:** **Explicit out of scope.** This is the clearest case: M8Shift is a
**cooperative tool**, not a **containment mechanism for adversarial agents**. Its real
contribution to ASI10 is **traceability** (you *see* what an agent did), not prevention.
If you need to contain untrusted agents, you need an external layer (per-agent auth +
access-controlled server) — explicitly **not to be done** inside M8Shift (§5).

## 4. Prioritized action plan (improvements in the code)

### 🔴 P1 — To fix (real gaps)

| # | Finding | ASI | Concrete action | File |
|---|---------|-----|-----------------|------|
| 1 | ~~**SEC-4**: the i18n builder's `--name` can write outside the directory (RCE-adjacent)~~ | ASI05 | ✅ **FIXED** — `safe_output_name()` enforces a plain basename (no `/`, `..`, absolute, `altsep`) + `realpath`/`commonpath` "escapes --into" check; locked by `test_name_rejects_path_escape` | `m8shift-i18n.py:44-49, 247-252` |
| 2 | ~~**SEC-7**: stale-lock takeover can `unlink` another process's fresh lock (TOCTOU)~~ | ASI03/07 | ✅ **ADDRESSED** — the `.m8shift.lock` reclaim is serialized + multi-re-checked (`_lock_unlink_guard`, `_reclaim_stale_lock`: same-inode + staleness re-checks before `unlink`), and `guard.require_owned()` is **generalized to every LOCK write** (8/8 `write(set_lock())` sites re-check token ownership before writing → a stolen-mid-flight transition is refused). Locked by `test_file_lock_token_ownership` + `test_stale_internal_lock_reclaimed` | `m8shift.py:1055-1069, 1104-1171` |

### 🟡 P2 — Useful hardening

| # | Finding | ASI | Action |
|---|---------|-----|--------|
| 3 | **SEC-9**: worktree branch/ref names validated by git but not by *policy* | ASI05 | Stricter rejection of control characters / whitespace before `git check-ref-format` |
| 4 | **SEC-8**: unbounded bodies/ledgers (local DoS) | ASI02/08 | Confirm the caps (256 KiB body / 64 KiB field exist) + per-session `--max-turns` option; auto-stop on repeated ack-bounce (not just a warning) |
| 5 | **SEC-11**: lock-file hardening | ASI03 | `O_NOFOLLOW`, `lstat` for staleness, mode `0o600` confirmed |
| 6 | Release signing | ASI04 | GPG-signed tag + checksum publication for distribution |

### 🟢 P3 — Observability / documentation

| # | Action | ASI |
|---|--------|-----|
| 7 | Explicitly document in README/protocol: *"turn content = declarative, unverified"* | ASI09 |
| 8 | Document the local transport model and the "if networked → mTLS+signing" condition | ASI07 |
| 9 | Extend `doctor --security`: volume/frequency anomalies in memory writes | ASI06 |
| 10 | Optional hook (disabled by default) for content scanning on `append` | ASI01 |

## 5. What to deliberately **NOT do** (out of scope by design)

> [!CAUTION]
> These controls, recommended by OWASP for **adversarial / multi-tenant production**
> deployments, **would contradict M8Shift's model** (local, stdlib-only, no key, no daemon,
> no network, cooperative). Adding them would bring major complexity for a threat model
> M8Shift does not target. **Recommendation: do not implement them** — unless there is an
> explicit threat-model switch.

| OWASP control | ASI | Why NOT to do it in M8Shift |
|---------------|-----|-----------------------------|
| **Per-agent cryptographic identity / signed-intent OAuth** | ASI03, ASI10 | Breaks "no key, no daemon"; in a local trusted context, an attacker able to impersonate an agent already has local execution (the defense would be illusory). |
| **mTLS / PKI / E2E channel encryption** | ASI07 | No network → no MITM surface. Adding transport crypto to a local file is security theater. |
| **Semantic prompt-injection filtering inside the relay** | ASI01, ASI06 | A transport must not rewrite the payload; reliable NL injection filtering is unsolved and would introduce false positives. The documented boundary + structural neutralization are sufficient for the role. |
| **Signed behavioral manifests / HSM-KMS attestation / agent watchdog** | ASI10 | Heavy orchestrator architecture, antithetical to the stdlib single file. Reserved for an agentic platform, not a cooperative relay. |
| **Sandboxing/containerization of agents by M8Shift** | ASI05, ASI08 | M8Shift coordinates; it does not execute the agents. Sandboxing belongs to the host environment, not the relay. |

## 6. Conclusion

**Strengths (intrinsic OWASP alignment)**
- **ASI04 / ASI05 / ASI07(network):** excellent — *by absence of surface* (zero dependencies, zero `eval`/`shell`, zero network). The best mitigation is often surface elimination, and M8Shift embodies it.
- **ASI06 / ASI08 / ASI09:** solid on **integrity, anti-cascade serialization, and traceability** (immutable append-only, atomic write, degree-1 mutex, audited ledger, `doctor`).
- **ASI02:** narrow scope + audited `--force`.

**Residual risks (all documented, consistent with the model)**
- **ASI01:** anti-injection ultimately relies on the agent (boundary documented, not filtered).
- **ASI03 / ASI10:** declarative identity → **weak prevention against a malicious agent**; M8Shift offers *detection/attribution*, not *prevention*.
- **No P1 gap remaining.** SEC-4 (i18n path footgun) is **fixed + tested**. SEC-7 (stale-lock takeover TOCTOU) is **addressed**: the `.m8shift.lock` reclaim is serialized and multi-re-checked (`_lock_unlink_guard` / `_reclaim_stale_lock`), and `guard.require_owned()` is generalized to **every** LOCK write (re-checks token ownership before writing, so a transition whose lock was stolen mid-flight is refused) — locked by regression tests. The pre-commit pen guard (issue #39) adds a complementary *commit-time* narrowing for scripted writes.

**Verdict:**

> M8Shift is **well aligned** with the OWASP Agentic Top 10 *for its declared threat model*
> (local cooperative coordination of trusted agents). It **is not, and does not claim to
> be**, a security boundary against adversarial agents or untrusted content. Within that
> scope: **2 P1 fixes**, a few P2 hardenings, P3 documentation — and an **explicit list of
> controls NOT to add** in order to preserve its philosophy. For use in a hostile /
> multi-tenant environment, it is not M8Shift that should be hardened, but an external
> orchestration layer.

---

*Cross-references: OWASP Top 10 for Agentic Applications 2026 (OWASP GenAI Security Project
— Agentic Security Initiative), <https://genai.owasp.org> (threat grid) ·
[security-audit.md](./security-audit.md) (internal audit SEC-1→SEC-11) · verified code
`m8shift.py` v3.41.1.*
