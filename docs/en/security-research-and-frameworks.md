# Security research & external frameworks — applicability to M8Shift

- **Date:** 2026-06-27
- **Scope:** external security research (arXiv agentic-security defenses), MITRE ATLAS,
  and the IBM AI Risk Atlas, each judged against M8Shift's declared threat model
  (`m8shift.py` v3.42.0 and its companions).
- **Mode:** external-source review + verification. Every external citation was fetched
  (`arxiv.org/abs/<id>`, the ATLAS canonical YAML, the IBM Atlas Nexus mirror / AIUC-1
  crosswalk) and fact-checked against the source before being used here.
- **Companion to:** [owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md)
  (the OWASP Agentic Top 10 audit) and the internal
  [security-audit.md](./security-audit.md) (findings **SEC-1 → SEC-11**).

> [!NOTE]
> **Auditor's note:** this document complements
> [owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md); every external citation
> was fetched and fact-checked. arXiv ids were resolved at `arxiv.org/abs/<id>` to confirm
> exact title, authors, and date; ATLAS facts are grounded on the canonical
> `mitre-atlas/atlas-data` YAML (the `atlas.mitre.org` HTML is JS-rendered and 404s a
> fetcher); IBM risk titles come from the Atlas Nexus mirror and the AIUC-1 crosswalk
> (the `dataplatform.cloud.ibm.com` pages are JS-rendered / 403 to a fetcher).

## 1. Executive summary

The throughline of this review is simple and structural: **M8Shift has no model, runs
local files only, depends on the standard library only, and assumes a cooperative team of
trusted agents.** That charter — `no model / local / stdlib / cooperative` — makes the
**model-centric mass** of the external frameworks **NOT-APPLICABLE by construction**:

- **MITRE ATLAS** is overwhelmingly a *model-attack* taxonomy (evasion, inversion,
  extraction, training/data poisoning, inference-API abuse). With **no model and no
  inference API**, roughly **~90 % of ATLAS has no surface in M8Shift-the-tool**.
- The **IBM AI Risk Atlas** Training-Data, Inference, and Output categories — **including
  every classic bias/fairness risk** — are **structurally inapplicable**: there is no
  training data to skew, no inference to attack, no generated output to be biased.
- Several leading **arXiv defenses** are correctly NOT-APPLICABLE (activation-based drift
  needs model internals; RAG-poisoning needs a knowledge store; MCP defenses need a
  protocol surface).

> [!IMPORTANT]
> M8Shift's minimalism is itself a **threat-model reduction**: whole attack classes have
> no locus in the relay. The "no surface here" verdicts are a *feature*, not a gap.

What **is** APPLICABLE or already-present is a small, sharply-focused set of
**agentic / coordination** defenses:

- **verify-before-commit** (VIGIL) ↔ M8Shift's atomic-write + LOCK-validation, formalizable
  into a two-phase stage→validate→append pen handoff;
- **immutable audit / runtime-trace analysis** (AgentArmor) ↔ the append-only ledger;
- **structural drift detection** (goal-drift metrics) without ML;
- **message integrity / information-flow labels** (Fides) as plain-string lane tags;
- **declarative-identity hardening** (per-lane capability lists, honest mismatch framing).

These map onto the audit's open items — notably **SEC-4** (i18n path footgun, P1) and
**SEC-7** (stale-lock TOCTOU, P1) — and onto **ASI06/ASI07** (message integrity),
**ASI08/ASI09** (cascade / traceability), and **ASI01/ASI10** (drift / rogue detection).

The same structural verdict holds for the **government & standards frameworks** (§5):
NIST's **MEASURE** function (model metrics, bias measurement, adversarial-robustness eval)
and ANSSI's model- and training-poisoning recommendations (the *infection / empoisonnement*
family) are **NOT-APPLICABLE to a model-less relay** — there is no model to measure or
poison. What maps directly to M8Shift's strengths (zero third-party deps, immutable audit
ledger) is the **secure-by-design lifecycle** (CISA's four lifecycle stages, esp.
supply-chain hygiene and continuous monitoring), **phase isolation / cloisonnement** (ANSSI
R12/R28 ↔ degree-2 worktree isolation), and **GOVERN/MANAGE accountability + monitoring**
(NIST's charter-as-governance, ledger-as-traceability). Where they press is the same two
open gaps the audit already names: **SEC-4** and **SEC-7**, both surfacing under CISA's
"harden the deployment environment / configuration" and ANSSI's access-control axis.

### 1.1 Framework applicability at a glance

One-screen map across every framework reviewed; each row is detailed in the section noted,
and the per-item applies/N-A verdicts (ATLAS tactic-by-tactic §3.2, IBM risk-by-risk §4.2)
live in those sections.

| Framework | What it targets | Applies to M8Shift | Where it presses |
|-----------|-----------------|--------------------|------------------|
| [OWASP Agentic Top 10](https://genai.owasp.org/) (ASI01–10) | agentic-application threats | **Audited threat-by-threat** — see the [OWASP audit](owasp-agentic-top10-audit.md) coverage matrix | ASI01/ASI06/ASI07 reinforcement; identity & network out of scope by design |
| [MITRE ATLAS](https://atlas.mitre.org/) | adversarial ML (model attacks) | **~10 % applies** — ~90 % is model-attack with no surface here (§3) | supply chain + the ecosystem of agents *using* M8Shift |
| [IBM AI Risk Atlas](https://www.ibm.com/think/topics/ai-risk-management) | AI risks incl. bias & fairness | **N/A by design** — Training-Data / Inference / Output, incl. all bias, structurally inapplicable (§4) | none on the model axis; process fairness is the only analogue (§4.3) |
| [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) (100-1 + 600-1) | AI risk-management functions | **Partial** — GOVERN / MAP / MANAGE apply; MEASURE (model metrics, bias) N/A (§5.1) | SEC-4 / SEC-7 under MANAGE |
| [CISA Secure AI](https://www.cisa.gov/ai) | secure-by-design AI lifecycle | **Applies** — supply chain, config hardening, monitoring (§5.2) | SEC-4 / SEC-7 (harden deployment / configuration) |
| [ANSSI-PA-102](https://cyber.gouv.fr/) | securing a generative-AI system | **Partial** — phase isolation / access control apply; model / training poisoning N/A (§5.3) | SEC-7 (access-control axis) |
| [arXiv defenses](https://arxiv.org/) | agentic attacks & defenses | **Mixed** — activation / model-drift defenses N/A; verify-before-commit maps to review/validation (§2) | reinforce the documented injection boundary |

## 2. arXiv — agentic-security research & defenses

All 19 papers below were verified by fetching `arxiv.org/abs/<id>` and confirming exact
title, authors, and date. The **ASI** column maps to a generic Agentic-Security-Issue
taxonomy (ASI01 prompt/instruction injection; ASI02 tool/plugin exploitation; ASI03
memory/knowledge poisoning; ASI04 goal/task drift; ASI05 rogue/compromised-agent behavior;
ASI06 inter-agent message integrity & trust; ASI07 identity/authorization mismatch &
privilege escalation; ASI08 supply-chain / MCP-A2A; ASI09 information-flow / data
isolation; ASI10 auditability/monitoring). **⚠️ Numbering note:** this generic taxonomy is *this document's own* and does **not** match the canonical **OWASP Agentic Top-10** grid used in [owasp-agentic-top10-audit.md](owasp-agentic-top10-audit.md) (there ASI04=Supply Chain, ASI05=RCE, ASI08=Cascading Failures). Do not cross-map the two docs by ASI number — use the threat names. The M8Shift charter recap is applied per row:
stdlib-only local CLI, no ML, no network, cooperative trusted agents, declarative identity,
degree-1 mutex, immutable ledger.

| arXiv id (link) | Title | Authors (short) | Year | Defense idea (one line) | ASI | Applicability | Implementation lead (charter-respecting) |
|---|---|---|---|---|---|---|---|
| [2510.06445](https://arxiv.org/abs/2510.06445) | A Survey on Agentic Security: Applications, Threats and Defenses | Shahriar, Rahman, Ahmed, Sadeque, Parvez | 2025 | Lifecycle-spanning defense taxonomy over 260+ papers | ASI01-10 | INSPIRATION-ONLY | Use its defense taxonomy as the section scaffold for the M8Shift threat-model doc; map each charter invariant to a named lifecycle stage. |
| [2601.05755](https://arxiv.org/abs/2601.05755) | VIGIL: Defending LLM Agents Against Tool Stream Injection via Verify-Before-Commit | Lin, Zhou, Zheng, Liu, Xu, Chen, Chen | 2026 | Verify-before-commit gate between proposing an action and committing it | ASI01,ASI02 | APPLICABLE | Add a "stage-then-commit" pen handoff: a write is staged to a temp turn record, schema/marker-validated, and only atomically appended to the ledger after a `verify` pass (already half-present via LOCK validation + atomic writes — formalize the two-phase commit). |
| [2502.05174](https://arxiv.org/abs/2502.05174) | MELON: Provable Defense Against Indirect Prompt Injection Attacks in AI Agents | Zhu, Yang, Wang, Guo, Wang | 2025 | Re-run trajectory with masked prompt; flag if actions invariant to user intent | ASI01 | INSPIRATION-ONLY | No model in M8Shift to re-execute; conceptual lead only — a "did this turn's effect depend on the declared task?" sanity check could be surfaced to the operator, but masking/replay needs an LLM. |
| [2406.00799](https://arxiv.org/abs/2406.00799) | Get my drift? Catching LLM Task Drift with Activation Deltas | Abdelnabi, Fay, Cherubin, Salem, Fritz, Paverd | 2024 | Detect injection via activation deltas before/after external data | ASI04,ASI01 | NOT-APPLICABLE | Requires model internals/activations; M8Shift has no model. Drift must be caught structurally (see 2505.02709 / 2502.05986), not via activations. |
| [2505.02709](https://arxiv.org/abs/2505.02709) | Technical Report: Evaluating Goal Drift in Language Model Agents | Arike, Donoway, Bartsch, Hobbhahn | 2025 | Metrics for goal drift (commission vs omission) as context grows | ASI04 | PARTIAL | M8Shift can compute a cheap structural proxy: compare each turn's declared `task/intent` field against the session's original objective string and emit a drift warning in `doctor` when the lane's stated goal mutates across turns (text-diff over the immutable ledger; no ML). |
| [2502.05986](https://arxiv.org/abs/2502.05986) | Preventing Rogue Agents Improves Multi-Agent Collaboration | Barbi, Yoran, Geva | 2025 | Monitor for "critical points of confusion" and intervene before failure cascades | ASI05 | PARTIAL | Advisory companion (already in charter) that flags rogue signals from the ledger — e.g., an agent re-claiming the pen after a `done`, repeated no-progress turns, or contradicting a prior committed turn — and surfaces to operator; never auto-revokes (stays advisory). |
| [2407.12784](https://arxiv.org/abs/2407.12784) | AgentPoison: Red-teaming LLM Agents via Poisoning Memory or Knowledge Bases | Chen, Xiang, Xiao, Song, Li | 2024 | Attack: backdoor via poisoned memory/RAG triggers | ASI03 | NOT-APPLICABLE (attack) | M8Shift has no RAG/vector memory; the "memory" is the append-only immutable ledger, which already resists post-hoc poisoning by design. Useful as a red-team checklist for the audit. |
| [2402.07867](https://arxiv.org/abs/2402.07867) | PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models | Zou, Geng, Wang, Jia | 2024 | Attack: inject malicious texts into RAG knowledge base | ASI03 | NOT-APPLICABLE (attack) | No knowledge base in M8Shift. Confirms the design choice to keep the ledger append-only/immutable rather than a mutable knowledge store. |
| [2503.12188](https://arxiv.org/abs/2503.12188) | Multi-Agent Systems Execute Arbitrary Malicious Code | Triedman, Jha, Shmatikov | 2025 | Attack: adversarial content hijacks MAS to run arbitrary code (58-100% ASR) | ASI02,ASI05 | INSPIRATION-ONLY | Charter explicitly states M8Shift is not a boundary against malicious agents; this motivates documenting that companions must never execute content from M8SHIFT.md and the runner stays headless/immutable (already a charter rule — cite as rationale). |
| [2508.15310](https://arxiv.org/abs/2508.15310) | IPIGuard: A Novel Tool Dependency Graph-Based Defense Against Indirect Prompt Injection in LLM Agents | An, Zhang, Du, Zhou, Li, Lin, Ji | 2025 | Pre-plan a tool dependency graph; enforce strict topological execution | ASI01,ASI02 | INSPIRATION-ONLY | M8Shift orchestrates turns not tool calls, but the "declare the plan first, then execute only within it" pattern maps to a per-session immutable `run-plan` (which the runtime companion already enforces) — cite as prior art for plan-lock. |
| [2508.01249](https://arxiv.org/abs/2508.01249) | AgentArmor: Enforcing Program Analysis on Agent Runtime Trace to Defend Against Prompt Injection | Wang, Liu, Lu, Cai, Chen, Yang, Zhang, Hong, Wu | 2025 | Turn runtime trace into a graph IR; apply program analysis + type system | ASI01,ASI10 | PARTIAL | M8Shift's ledger IS a runtime trace — add a stdlib `doctor --analyze` that parses the jsonl ledger into a turn graph and runs static invariant checks (one writer at a time, no orphan claims, monotonic turn ids, marker-clean), purely local. |
| [2505.23643](https://arxiv.org/abs/2505.23643) | Securing AI Agents with Information-Flow Control | Costa, Köpf, Kolluri, Paverd, Russinovich, Salem, Tople, Wutschitz, Zanella-Béguelin | 2025 | Track confidentiality/integrity labels and deterministically enforce IFC policies (system: Fides) | ASI09 | PARTIAL | Add lightweight integrity labels to ledger entries: tag each turn's source lane and whether content originated from a trusted-roster agent vs external paste; companions can refuse to act on lower-integrity entries. Labels are plain strings — stdlib-only. |
| [2602.07398](https://arxiv.org/abs/2602.07398) | AgentSys: Secure and Dynamic LLM Agents Through Explicit Hierarchical Memory Management | Wen, Li, Xiao, Zhang | 2026 | OS-process-like memory isolation; only schema-validated returns reach main agent | ASI03,ASI09 | APPLICABLE | Strengthen the existing LOCK/turn schema: require every cross-lane handoff payload to pass strict schema validation before it is accepted into the shared M8SHIFT.md, so a malformed/oversized field can't leak across lanes. Pure `json`/regex validation. |
| [2509.14956](https://arxiv.org/abs/2509.14956) | Sentinel Agents for Secure and Trustworthy Agentic AI in Multi-Agent Systems | Gosmar, Dahl | 2025 | Distributed sentinels monitor comms + coordinators enforce policy/audit | ASI06,ASI10 | PARTIAL | Maps directly to the advisory-companion role: a read-only "sentinel" companion that tails the ledger, keeps the audit record, and emits anomaly notes — but stays advisory (never holds the pen/enforces), per charter. |
| [2603.15408](https://arxiv.org/abs/2603.15408) | TrinityGuard: A Unified Framework for Safeguarding Multi-Agent Systems | Wang, Zeng, Wei, Jin, Zhou, Li, Yang, Qu, Xu, Hu | 2026 | 3-tier risk taxonomy (single-agent / inter-agent / system) + runtime monitoring | ASI05,ASI06,ASI10 | INSPIRATION-ONLY | Use the 3-tier taxonomy to structure the audit's risk register; M8Shift's surface is mostly the inter-agent and system tiers (single-agent tier is out of charter since M8Shift hosts no agent). |
| [2601.11893](https://arxiv.org/abs/2601.11893) | Taming Various Privilege Escalation in LLM-Based Agent Systems: A Mandatory Access Control Framework | Ji, Wu, Jiang, Ma, Li, Gao, Wang, Li | 2026 | MAC/ABAC over agent-tool interactions via information-flow graph (system: SEAgent) | ASI07 | PARTIAL | Charter has degree-1 mutex (one writer) — extend with a declarative per-lane capability list (which fields/files a lane may touch) checked at append time; a lane can't write outside its declared scope. Static policy file, stdlib-enforced. |
| [2512.06914](https://arxiv.org/abs/2512.06914) | SoK: Trust-Authorization Mismatch in LLM Agent Interactions | Shi, Du, Wang, Liang, Liu, Bian, Guan | 2025 | Belief-Intention-Permission: static perms decoupled from runtime trust | ASI06,ASI07 | INSPIRATION-ONLY | Frames M8Shift's known limitation honestly: declarative identity = static permission with no runtime trust signal. Lead: document the mismatch explicitly and let operators downgrade a lane's scope mid-session via the roster. |
| [2603.19469](https://arxiv.org/abs/2603.19469) | A Framework for Formalizing LLM Agent Security | Siu, He, Montgomery, Wang, Gong, Wang, Song | 2026 | 4 properties: task alignment, action alignment, source authorization, data isolation | ASI01,ASI07,ASI09 | APPLICABLE | Adopt these 4 properties as named, testable invariants in the M8Shift test suite: task/action alignment (turn matches claimed task), source-authorization (writer is in roster), data-isolation (lane scope), each assertable over the ledger with stdlib. |
| [2604.05969](https://arxiv.org/abs/2604.05969) | A Formal Security Framework for MCP-Based AI Agents: Threat Taxonomy, Verification Models, and Defense Mechanisms | Acharya, Gupta | 2026 | Defense-in-depth: capability ACL, tool attestation, IFC, runtime policy (framework: MCPSHIELD) | ASI08,ASI02 | NOT-APPLICABLE | M8Shift speaks no MCP/A2A and exposes no tools/network. Relevant only if M8Shift ever adds a protocol surface; today there is no attack surface here. |

> [!NOTE]
> **Dropped/adjusted from the seed list:** none dropped — all seeds resolved. Two
> supplementary catalogs kept *out* of the headline table:
> **[2505.18156](https://arxiv.org/abs/2505.18156) (InjectLab — Austin Howard, "InjectLab:
> A Tactical Framework for Adversarial Threat Modeling Against Large Language Models")** has
> its v1 dated **April 16, 2025** despite the 2505 id, so it is a 2025 paper;
> **[2503.05780](https://arxiv.org/abs/2503.05780) (AI Risk Atlas — Bagehorn et al., "AI
> Risk Atlas: Taxonomy and Tooling for Navigating AI Risks and Resources")** is 2025. Both
> were omitted from the headline table only because they are framework/taxonomy catalogs
> rather than implementable defenses, but both are confirmed real and usable as audit
> scaffolding (InjectLab = MITRE ATT&CK-inspired technique matrix, 25+ techniques across
> six tactics, for the red-team checklist; AI Risk Atlas = consolidated AI-risk taxonomy
> plus the open-source "Risk Atlas Nexus" tooling for the risk register).

### Key takeaways for M8Shift

- **Verify-before-commit is the single most charter-aligned defense pattern**
  ([VIGIL 2601.05755](https://arxiv.org/abs/2601.05755),
  [IPIGuard 2508.15310](https://arxiv.org/abs/2508.15310)). M8Shift already does atomic
  writes + LOCK validation; formalizing it into an explicit two-phase
  "stage → validate → atomic-append" pen handoff is a small, stdlib-only hardening with
  strong literature backing.
- **The append-only immutable ledger is M8Shift's biggest pre-existing strength.** It
  neutralizes the entire memory/knowledge-poisoning attack class
  ([AgentPoison 2407.12784](https://arxiv.org/abs/2407.12784),
  [PoisonedRAG 2402.07867](https://arxiv.org/abs/2402.07867)) by construction, and doubles
  as the "runtime trace" that [AgentArmor 2508.01249](https://arxiv.org/abs/2508.01249) and
  program-analysis defenses operate on — so a `doctor --analyze` that runs static invariant
  checks over the ledger graph is low-cost and high-value.
- **Drift detection is feasible without a model** (contra activation-based
  [2406.00799](https://arxiv.org/abs/2406.00799)). Following the goal-drift metrics of
  [2505.02709](https://arxiv.org/abs/2505.02709), M8Shift can text-diff each turn's declared
  task against the session's original objective and warn on mutation — a structural, stdlib
  proxy rather than ML inference, staying strictly inside charter (no model, no inference).
- **Adopt the four formal security properties of
  [2603.19469](https://arxiv.org/abs/2603.19469) (task alignment, action alignment, source
  authorization, data isolation) as named, asserted test invariants.** They map cleanly onto
  M8Shift's roster (source authorization), turn schema (task/action alignment), and lane
  scoping (data isolation), and turn fuzzy "is it secure?" questions into concrete unit
  tests.
- **Honestly frame the declarative-identity limitation rather than over-engineer it.**
  [SoK 2512.06914](https://arxiv.org/abs/2512.06914) and
  [SEAgent 2601.11893](https://arxiv.org/abs/2601.11893) show the field is converging on
  dynamic trust + capability/MAC scoping; the charter-respecting middle ground is a
  *declarative per-lane capability list* checked at append time, plus operator-driven
  mid-session scope downgrade — never crypto auth, which is out of charter.
- **Several leading defenses are correctly NOT-APPLICABLE and that is a feature, not a
  gap.** No model (MELON, activation-drift), no RAG/memory store (AgentPoison, PoisonedRAG),
  no tools/network/MCP ([MCPSHIELD 2604.05969](https://arxiv.org/abs/2604.05969)) means whole
  attack classes have no surface in M8Shift. The audit should state this affirmatively:
  M8Shift's minimalism (stdlib-local-cooperative) is itself a threat-model reduction, and
  the residual surface is concentrated in inter-agent message integrity (ASI06) and
  auditability (ASI10), where the advisory-sentinel companion pattern
  ([2509.14956](https://arxiv.org/abs/2509.14956)) applies.

## 3. MITRE ATLAS — applicability

> [!NOTE]
> **Sources verified:** ATLAS taxonomy and technique descriptions from the official data
> repo `raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml` (16 tactics,
> full technique tree, GenAI descriptions quoted faithfully). All technique IDs and tactic
> associations below were checked against that canonical YAML by direct grep of the raw
> file. M8Shift controls verified against [security-audit.md](./security-audit.md)
> (SEC-1→SEC-11) and [owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md). Note:
> `atlas.mitre.org/techniques/<ID>` HTML pages 404 on direct fetch — the JS site does not
> render server-side — so all ATLAS facts here are grounded on the structured YAML, which
> is the canonical data backing <https://atlas.mitre.org>.

### 3.1 What ATLAS is, and why most of it does not touch M8Shift-the-tool

MITRE ATLAS (Adversarial Threat Landscape for Artificial-Intelligence Systems) is a
knowledge base of adversary tactics and techniques against AI/ML systems, deliberately
modeled on MITRE ATT&CK. The live data repo defines **16 tactics** (the brief named 14; the
current dataset has since added **Lateral Movement** `AML.TA0015` and **Command and
Control** `AML.TA0014`) spanning Reconnaissance → Impact, and a technique tree whose center
of gravity is the **ML model itself**: crafting adversarial data (`AML.T0043`), creating a
proxy AI model (`AML.T0005`), poisoning training data (`AML.T0020`) or manipulating the
model (`AML.T0018`), model inversion / extraction / membership inference via the inference
API (`AML.T0024.000/.001/.002`, parent *Exfiltration via AI Inference API*), evading a
deployed model (`AML.T0015`), and discovering model ontology/family/outputs
(`AML.T0013/T0014/T0063`). The GenAI additions (LLM Prompt Injection `AML.T0051`, LLM
Jailbreak `AML.T0054`, RAG Poisoning `AML.T0070`, Publish Hallucinated Entities
`AML.T0060`, LLM Data Leakage `AML.T0057`, LLM Prompt Self-Replication `AML.T0061`, etc.)
extend the same logic to LLM behavior.

**The structuring fact:** *M8Shift has no model.* It does no training, inference,
classification, generation, embedding, or retrieval. It is a single-file stdlib-only Python
CLI that serializes a cooperative degree-1 mutex around a local plaintext relay file
(`M8SHIFT.md`) — local files only, no network, no daemon, no API key, no ML. Therefore the
**entire model-centric mass of ATLAS is NOT-APPLICABLE to M8Shift-the-tool**: there is no
model to evade, invert, extract, poison, or query; no inference API to abuse; no training
pipeline to corrupt; no class scores to discover. Those techniques map only to **the
agents/LLMs that *use* M8Shift**, which are separate products under their own threat models.
The only place ATLAS genuinely touches the *coordination substrate* is a thin band of
techniques where M8Shift is either (a) a **carrier of untrusted natural-language content**
between agents (indirect prompt injection, hallucinated-entity / self-replicating
payloads), or (b) **a piece of supply chain / a tool an agent invokes** (AI supply chain
compromise, malicious package, tool invocation). That thin band — not the model attacks — is
where M8Shift has real surface and real mitigations.

### 3.2 Tactic-by-tactic mapping

Legend for "applies": **N/A** = no surface in M8Shift; **PARTIAL** = limited/structural
surface; **APPL** = applicable, M8Shift can/does act in-charter; **INSPIRATION** =
conceptual lead only, not implementable within the stdlib-local-cooperative charter. "Tool"
= the relay code; "Ecosystem" = the agents/LLMs running on top of it.

| ATLAS tactic | Representative technique(s) (verified IDs) | M8Shift-the-tool? | Agent ecosystem using M8Shift? | Rationale |
|---|---|---|---|---|
| **Reconnaissance** `TA0002` | Search Open AI Vulnerability Analysis `T0001`, Gather RAG-Indexed Targets `T0064`, Active Scanning `T0006` | **N/A** | PARTIAL | Recon targets a victim *model/service*. M8Shift exposes no service, no network, no scannable endpoint. Reconnaissance of the agents themselves is outside the relay. |
| **Resource Development** `TA0003` | LLM Prompt Crafting `T0065`, Retrieval Content Crafting `T0066`, Publish Hallucinated Entities `T0060`, Publish Poisoned Models `T0058` / Publish Poisoned Datasets `T0019` | **N/A** | APPL (ecosystem) | Attacker-side staging. M8Shift builds none of this. But a *crafted payload* `T0065`/`T0060` can later transit a turn body — mitigation lives at Execution, below. |
| **Initial Access** `TA0004` | **AI Supply Chain Compromise `T0010`** (.001 AI Software, .002 Data, .003 Model); Valid Accounts `T0012` | **PARTIAL** | PARTIAL | `T0010` is the *one* Initial-Access technique with real tool surface: `m8shift.py` is itself a script in someone's agentic supply chain. M8Shift's answer is **zero third-party deps (stdlib-only, no `requirements.txt`)** → near-nil dependency surface, plus `checksums.sha256` + a script-overwrite denylist. Gap: releases are not signed. `T0012` Valid Accounts = N/A (no accounts). |
| **AI Model Access** `TA0000` | AI Model Inference API Access `T0040`, Full AI Model Access `T0044`, AI-Enabled Product or Service `T0047` | **N/A** | N/A (for relay) | Pure model-access tactic. M8Shift has no model and mediates no model API. |
| **Execution** `TA0005` | **LLM Prompt Injection `T0051` (.000 Direct, .001 Indirect)**; **AI Agent Tool Invocation `T0053`**; User Execution → Malicious Package `T0011.001`; Command and Scripting Interpreter `T0050` | **PARTIAL** | **APPL** | **This is the crux.** Indirect prompt injection `T0051.001` — *"inject prompts indirectly via a separate data channel ingested by the LLM such as … text or multimedia pulled from databases or websites"* — is exactly what a poisoned `ask`/`body`/`memory`/`tasks` field is: M8Shift is the data channel. M8Shift cannot stop an LLM from obeying, but as the *carrier* it does: **marker neutralization** (`clean_body` zero-widths `M8SHIFT:` so a body can't forge a turn/LOCK), **header anti-forgery** (`clean_field` rejects line breaks/reserved markers), and an **explicit "untrusted coordination data" prompt boundary** in the stanza/protocol (SEC-1). `T0053` Tool Invocation maps to misuse of M8Shift's own subcommands → audited `--force` (`--reason` + ledger). `T0011.001` Malicious Package overlaps `T0010` above. `T0050` = N/A (no `eval`/`shell`/`os.system`; subprocess is `git` argv-only). |
| **Persistence** `TA0006` | **LLM Prompt Self-Replication `T0061`**; Poison Training Data `T0020`; Manipulate AI Model `T0018` | **PARTIAL** | **APPL** | `T0020`/`T0018` (model/training persistence) = N/A, no model. `T0061` self-replication — causing the LLM to replicate the prompt as part of its output — is the realistic persistence vector on a **shared append-only journal**: a self-replicating payload could re-emit itself into successive turns/memory. M8Shift's append-only immutability *preserves* the audit trail but does not block re-emission; structural marker neutralization limits it to inert text, not a forged control block. |
| **Privilege Escalation** `TA0012` | LLM Jailbreak `T0054`; AI Agent Tool Invocation `T0053`; Valid Accounts `T0012` | **N/A** (tool) | APPL (ecosystem) | Jailbreak `T0054` is a model-behavior attack — N/A to the relay. In M8Shift "privilege" = holding the pen; that is governed by the degree-1 mutex (`O_EXCL` lock, write-right bound to `WORKING_<agent>` state), but it is **declarative/cooperative, not a security boundary** — see Identity below. |
| **Defense Evasion** `TA0007` | LLM Trusted Output Components Manipulation `T0067`; LLM Prompt Obfuscation `T0068`; Evade AI Model `T0015` | **PARTIAL** | APPL | `T0015`/`T0068` = model/detector evasion → N/A. `T0067` (making a response *look* trustworthy) has a faint analog: an agent can write a convincing but false `done: "tests OK"` into the journal. M8Shift's answer is **observability, not verification** — content is declarative; the human must independently verify high-impact claims (documented gap, ASI09). |
| **Credential Access** `TA0013` | Unsecured Credentials `T0055` | **PARTIAL** | PARTIAL | M8Shift stores **no** credentials (no API key, no daemon) → minimal surface. Residual: an agent could *paste a secret into a turn body/memory*, making the relay an incidental credential store. Mitigation lead: the stanza already forbids writing secrets into relay files; an optional `doctor --security` secret-scan is noted as future work (deferred as too noisy). |
| **Discovery** `TA0008` | Discover AI Model Outputs `T0063`, Discover AI Model Ontology `T0013`, Discover AI Model Family `T0014`, Discover LLM System Information `T0069` | **N/A** | PARTIAL | All probe a *model's* internals/outputs. M8Shift exposes no model surface to discover. |
| **Lateral Movement** `TA0015` | Phishing `T0052` | **N/A** | N/A | No network, no cross-host movement; the relay is a single local file. (`T0052` is verified as a Lateral Movement technique, also tagged Initial Access.) |
| **Collection** `TA0009` | Data from Local System `T0037`, Data from Information Repositories `T0036`, AI Artifact Collection `T0035` | **PARTIAL** | PARTIAL | `T0037`/`T0036` have a thin analog: `M8SHIFT.md` + `M8SHIFT.memory.md` + `M8SHIFT.sessions.jsonl` are a local repository an agent with FS access can read. M8Shift sets the lock `0o600` but the relay files are intentionally **plaintext, unencrypted** — confidentiality relies on FS permissions, by charter. |
| **AI Attack Staging** `TA0001` | Create Proxy AI Model `T0005`, Craft Adversarial Data `T0043`, Verify Attack `T0042` | **N/A** | APPL (ecosystem) | Entirely model-staging (surrogate models, adversarial-example optimization). No surface in a text relay. |
| **Command and Control** `TA0014` | AI Agent `T0108` | **N/A** | INSPIRATION | M8Shift is local-file-only with no network beacon. A poisoned shared journal could *conceptually* act as a dead-drop between agents — but with no network and append-only audit, this is inspiration-only, not a relay-implementable concern. (`T0108` "AI Agent" is verified as the Command and Control technique; its canonical description is precisely about abusing an agent's tool access as a C2 channel.) |
| **Exfiltration** `TA0010` | **LLM Data Leakage `T0057`**; Exfiltration via Cyber Means `T0025`; Exfiltration via AI Inference API `T0024`; Extract LLM System Prompt `T0056` | **PARTIAL** | **APPL** | `T0024`/`T0056` (model inversion / system-prompt extraction) = N/A. The real lead is `T0057`/`T0025`: a compromised agent could **use M8Shift as the exfil channel** — write leaked data into a turn body, or (worse) push it via `git`. M8Shift itself has **no network egress** (structurally blocks the network exfil path *through the tool*), but it cannot stop an agent writing secrets into a plaintext journal that is then committed/pushed by other tooling. |
| **Impact** `TA0011` | RAG Poisoning `T0070`; Denial of AI Service `T0029`; Cost Harvesting `T0034` (.002 Agentic Resource Consumption); LLM Data Leakage `T0057`; Erode AI Model Integrity `T0031` | **PARTIAL** | APPL | `T0070` RAG poisoning / `T0031` model-integrity = N/A (no retrieval index, no model). `T0034.002` Agentic Resource Consumption / a local-DoS variant of `T0029` *do* have a tool analog: unbounded turn bodies/ledgers (SEC-8) → M8Shift caps bodies at 256 KiB (`--allow-large-body`) and single-line fields at 64 KiB, and `doctor` warns on oversized files. The **degree-1 mutex (one writer at a time)** is structurally **anti-cascade / anti-fan-out**, capping blast radius. |

### 3.3 Verdict — what M8Shift should care about, what it should ignore by design

**Ignore by design (NOT-APPLICABLE — no surface in a no-model relay).** The dominant mass
of ATLAS — everything in **AI Model Access** `TA0000`, **AI Attack Staging** `TA0001`,
model-centric Persistence/Privilege-Escalation/Defense-Evasion (`T0020`, `T0018`, `T0054`,
`T0015`, `T0068`), **Discovery** of model internals (`T0013/T0014/T0063/T0069`),
inference-API Exfiltration (`T0024`, `T0056`), RAG poisoning (`T0070`, `T0064`, `T0066`),
and most of Impact (`T0070`, `T0031`, `T0046` *Spamming AI System with Chaff Data*) —
targets an ML model or retrieval store M8Shift does not have. These belong to the
**agents/LLMs** in the ecosystem, under their own threat models, not to the relay. Adding
mitigations for them inside M8Shift would be category error.

**Care about (the thin genuinely-relevant band — and M8Shift already covers most of it):**

| Technique class (verified IDs) | Why it touches the substrate | Existing M8Shift control | Residual gap |
|---|---|---|---|
| **Indirect Prompt Injection** `T0051.001` + carrier of crafted/hallucinated payloads `T0065`/`T0060` | M8Shift is the *data channel ingested by the LLM* | `clean_body` marker neutralization; `clean_field` header anti-forgery; LOCK schema validation; explicit "untrusted coordination data" stanza/protocol boundary (SEC-1) | Cannot semantically filter NL — by charter a transport must not rewrite payload. Optional disabled-by-default `append` content-scan hook. |
| **AI Supply Chain Compromise** `T0010` / Malicious Package `T0011.001` | `m8shift.py` is a component in the operator's agentic supply chain | **Zero third-party deps** (stdlib-only) → near-nil surface; `checksums.sha256`; script-overwrite denylist | **Releases unsigned** → sign tags / publish signed checksums (the one concrete supply-chain lead). |
| **AI Agent Tool Invocation / Tool Misuse** `T0053` | Agents invoke the M8Shift CLI itself | Audited `--force` (`--reason` + `M8SHIFT.sessions.jsonl` + `doctor --security`); roster validation; append requires prior claim | Lock takeover TOCTOU (SEC-7) and i18n `--name` path footgun (SEC-4) are the two open P1 code fixes. |
| **Prompt Self-Replication** `T0061` | Self-propagating payload on a shared append-only journal | Append-only immutability (audit preserved); marker neutralization keeps replicants inert text | Re-emission into future turns not blocked; degree-1 serialization caps spread. |
| **Local DoS / Agentic Resource Consumption** `T0034.002`/`T0029` analog | Unbounded bodies/ledgers (SEC-8) | 256 KiB body cap, 64 KiB field cap, `doctor` size warnings; **degree-1 mutex = anti-cascade by construction** | No hard per-session turn circuit-breaker (warning only). |
| **Exfiltration channel** `T0057`/`T0025` | A rogue agent could route leaked data through the relay/git | M8Shift has **no network egress** (blocks the in-tool network exfil path); stanza forbids writing secrets to relay files | Plaintext journal + external `git push` remain outside the relay's control. |

**Inspiration-only (conceptual leads that the stdlib-local-cooperative charter deliberately
declines):** cryptographic agent identity / signed-intent attestation against **Valid
Accounts `T0012`** and **rogue-agent** scenarios (`T0053` privilege abuse) — M8Shift
identity is declarative by design; per-agent crypto would break "no key, no daemon" and, in
a *trusted-team* model, an attacker who could impersonate an agent already has local
execution, so the defense would be illusory. Likewise a shared journal as a `TA0014` Command
and Control dead-drop (the `T0108` "AI Agent" technique describes exactly this agent-as-C2
pattern) is conceptually interesting but moot without network.

> [!IMPORTANT]
> **Bottom line.** ATLAS is overwhelmingly a *model-attack* taxonomy; against
> M8Shift-the-tool it is ~90 % NOT-APPLICABLE by construction (no model = no attack surface
> for evasion/extraction/inversion/poisoning/inference). The genuinely relevant residue is a
> handful of techniques where M8Shift acts as **untrusted-content carrier** (`T0051.001`,
> `T0061`, `T0060`/`T0065`), **supply-chain component** (`T0010`/`T0011.001`), or **invoked
> tool / exfil path** (`T0053`, `T0057`) — and M8Shift's existing controls (stdlib-only
> zero-dep surface, marker/field neutralization + schema validation, the explicit
> untrusted-coordination-data boundary, audited `--force`, no network egress, degree-1
> anti-cascade mutex, size caps) already address the in-charter portion. The only net-new
> ATLAS-motivated actions consistent with the charter are: **sign releases** (`T0010`),
> close the **two open P1 code fixes SEC-4/SEC-7** (`T0011.001`/`T0053`), and optionally add
> a **disabled-by-default `append` content-scan hook** and a **`doctor` secret-scan /
> turn-rate cap** — everything else ATLAS lists belongs to the agents, not the relay.

**Sources (§3):**

- <https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml> (canonical
  ATLAS tactics/techniques + GenAI descriptions — all IDs, names, and tactic associations in
  this section verified by direct grep of the raw file: 16 tactics; `T0108` "AI Agent"
  confirmed real under `TA0014`; `T0052` confirmed under `TA0015`); reference site
  <https://atlas.mitre.org>.
- [security-audit.md](./security-audit.md) (SEC-1→SEC-11, code-level controls with
  `file:line` evidence).
- [owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md) (M8Shift threat model +
  verified controls).
- `CLAUDE.md` (prompt-security boundary / cooperative invariants).

## 4. IBM AI Risk Atlas — applicability (incl. the explicit BIAS verdict)

> [!NOTE]
> **Sources verified:** all risk names and categories below are grounded in live sources
> fetched this session: the IBM Atlas Nexus mirror, the AIUC-1 × IBM AI Risk Atlas crosswalk
> (which enumerates the Atlas risks IBM 1–99 with exact titles), the arXiv taxonomy paper
> [2503.05780](https://arxiv.org/abs/2503.05780), and IBM watsonx docs search excerpts. The
> canonical `dataplatform.cloud.ibm.com` pages are JS-rendered and return navigation-only /
> 403 to a fetcher — so the verbatim definitions below come from IBM's own doc search
> excerpts and the crosswalk's exact risk titles.

### 4.1 The IBM AI Risk Atlas taxonomy

IBM groups every risk by **where it originates** into four technical categories plus a newer
**Agentic** family, and cross-tags each risk with a **risk dimension** (accuracy, fairness,
robustness, explainability, transparency, privacy, value alignment, misuse, harmful output,
societal impact). Risks are also tagged by applicability: *traditional/broad*,
*generative-AI-specific*, or *agentic-AI-specific*.

> Note on naming: the table below uses the **exact Atlas risk titles** (as enumerated IBM
> 1–99 in the crosswalk). Where a row groups several Atlas risks, each is the real Atlas
> name.

| Category | Origin | Representative named risks (exact Atlas titles) |
|---|---|---|
| **Training Data** (input) | Risk from the data used to train/tune the model | **Data bias** (IBM 26); **Unrepresentative data** (23); **Data poisoning** (29); **Data contamination** (24); **Personal information in data** (30); **Lack of training data transparency** (33); **Uncertain data provenance** (34) |
| **Inference** (input-time / attacks) | Risk arising as the model processes a query | **Poor model accuracy** (40); **Evasion attack** (41) / **Extraction attack** (42); **Jailbreaking** (43); **Prompt injection attack** (46) / **Prompt leaking** (47) / **Prompt priming** (48); **Membership inference attack** (57) / **Attribute inference attack** (56); **Confidential data in prompt** (45) |
| **Output** | Risk in what the model produces | **Output bias** (59, misrepresents groups); **Decision bias** (58, unfairly advantages groups); **Hallucination** (71); **Harmful output** (60) / **Toxic output** (62); **Spreading disinformation** (66); **Copyright infringement** (73); **Exposing personal information** (72) / **Revealing confidential information** (74); **Untraceable attribution** (77); **Unexplainable output** (75) |
| **Non-Technical** (governance / societal / legal) | Risk from governance, law, society — not a model property | **Lack of system transparency** (81) / **Lack of model transparency** (80) / **Lack of domain expertise** (82); **Legal accountability** (89); **Unrepresentative risk testing** (84) / **Incorrect risk testing** (85); **Lack of testing diversity** (86); **Impact on the environment** (91) / **Impact on affected communities** (92); **Impact on human agency** (95); **Generated content ownership and IP** (90) |
| **Agentic** (agentic-AI-specific) | Risk from autonomous agents calling tools/other agents | **Unexplainable and untraceable actions** (IBM 1); **Over- or under-reliance on AI agents** (4); **Misaligned actions** (5, value alignment); **Redundant actions** (10); **Function calling hallucination** (9); **Attack on AI agents' external resources** (6); **Incomplete AI agent evaluation** (11); **Lack of AI agent transparency** (13); **Reproducibility** (14); **Accountability of AI agent actions** (15); **Discriminatory actions** (17) / **Introduce data bias** (18) |

### 4.2 Applicability table

| IBM risk (exact Atlas title) | Category / dimension | Applies to M8Shift? | Rationale |
|---|---|---|---|
| Data bias (26) | Training Data / fairness | **NOT-APPLICABLE** | M8Shift has no training data and no model. No surface. |
| Unrepresentative data (23) / Data poisoning (29) / Data contamination (24) | Training Data / accuracy-robustness | **NOT-APPLICABLE** | No dataset is ingested or learned from. |
| Personal information in data (30) / Confidential information in data (38) / Lack of training data transparency (33) | Training Data / privacy | **NOT-APPLICABLE** | Nothing is trained; the only files are local turn ledgers the operator owns. |
| Poor model accuracy (40) | Inference / accuracy | **NOT-APPLICABLE** | No inference; M8Shift makes no predictions. |
| Evasion attack (41) / Extraction attack (42) / Jailbreaking (43) / Prompt injection attack (46) / inference attacks (56,57) | Inference / robustness-privacy | **NOT-APPLICABLE** | No model to attack; no prompt processing. Charter is explicitly *not* a security boundary against malicious agents (trusted-team threat model). |
| Output bias (59) / Decision bias (58) | Output / fairness | **NOT-APPLICABLE (model sense)** — see §4.3 | M8Shift generates no content and makes no decisions about people. No statistical/representational output. |
| Hallucination (71) / Harmful output (60) / Toxic output (62) / Spreading disinformation (66) | Output / harmful-output-accuracy | **NOT-APPLICABLE** | M8Shift emits no generated content — only structured coordination state. |
| Copyright infringement (73) / Exposing personal information (72) | Output / misuse-privacy | **NOT-APPLICABLE** | No generative output channel. |
| **Untraceable attribution (77) / Unexplainable output (75)** | Output / transparency-explainability | **INSPIRATION → already addressed** | M8Shift's append-only immutable turn ledger + per-turn agent attribution is exactly the *opposite* (full traceability). Adopt its spirit as a positive invariant. |
| Lack of system transparency (81) / Lack of AI agent transparency (13) | Non-Technical + Agentic / transparency | **APPLICABLE** | M8Shift *is* the documentation surface for a multi-agent run. Lead: keep `docs/en/agents-guide.md` + LOCK schema + session history authoritative; doctor lint should flag undocumented roster roles. |
| **Legal accountability (89) / Accountability of AI agent actions (15)** | Non-Technical + Agentic / transparency | **APPLICABLE** | "Who did what" is the core question. Lead: ledger already records `agent + turn + timestamp`; ensure every pen-acquisition and M8SHIFT.md write is attributed and never anonymous. |
| **Over- or under-reliance on AI agents (4)** | Agentic / trust-calibration (human oversight) | **PARTIAL (operator-facing)** | M8Shift can't calibrate operator trust, but it *can* surface signals (no-progress detector, run counts, idle/stale lanes) so the operator neither over-trusts a stuck agent nor under-trusts a healthy one. Per IBM's definition this risk is about *calibrating trust in agent behavior*, not value alignment. Lead: `status`/`doctor` already expose progress/no-progress + run-plan; keep these advisory and visible. |
| **Redundant actions (10)** | Agentic / robustness | **PARTIAL → see §4.3** | Direct analogue exists: relay livelock / no-progress (M8Shift's interpretation of "redundant actions" as cyclical churn without progress). M8Shift's `no-progress` companion + loop guards (`next`, `append --wait`, `status --for`) already target this. |
| Misaligned actions (5) | Agentic / value-alignment | **INSPIRATION-ONLY** | M8Shift coordinates but doesn't judge agent intent; advisory companions explicitly never touch the pen/network. Conceptual lead only. |
| Function calling hallucination (9) / Attack on AI agents' external resources (6) | Agentic / robustness-security | **NOT-APPLICABLE** | M8Shift calls no tools and makes no network/API calls (stdlib-local invariant). |
| Reproducibility (14) | Agentic / robustness | **PARTIAL** | M8Shift itself is deterministic (local files, no network), so the relay is reproducible by construction; the *agents'* outputs aren't its concern. Lead: keep VERSION lockstep + run-plan immutability so a run can be replayed/audited. |
| Incomplete AI agent evaluation (11) / Lack of testing diversity (86) | Agentic + Non-Technical / robustness | **APPLICABLE (to M8Shift's own dev)** | Applies to M8Shift-as-software, not as a model. Lead: the existing 388-test suite (as of v3.42.0 — regenerate on release; a test *count* is not evidence of coverage or diversity, so risk 86 is addressed by adversarial + invariant/property tests, not a headline number) plus adversarial dogfooding (Codex implements / Claude reviews) is the mitigation. |
| Discriminatory actions (17) / Introduce data bias (18) | Agentic / fairness | **NOT-APPLICABLE (model sense) / see §4.3** | M8Shift takes no actions toward people and writes no dataset. |
| Impact on the environment (91) / Impact on Jobs (94) / Impact on human agency (95) | Non-Technical / societal-impact | **NOT-APPLICABLE** | A single-file local CLI mutex has no societal-scale footprint; no inference compute. |

### 4.3 BIAS verdict (explicit)

> [!IMPORTANT]
> **Classic ML bias/fairness risks are STRUCTURALLY NOT-APPLICABLE to M8Shift.** The IBM
> bias risks — **Data bias** (IBM 26, Training Data / fairness), **Output bias** (IBM 59)
> and **Decision bias** (IBM 58, Output / fairness), and the agentic **Discriminatory
> actions** (IBM 17) / **Introduce data bias** (IBM 18, Agentic / fairness) — every one
> presupposes a system that *learns from data*, *makes inferences*, and *produces
> predictions, classifications, or content about people or groups*. M8Shift has **no model,
> no training data, no inference step, and emits no generated content or decisions**. There
> is no representation to skew, no distribution to under-sample, no protected-attribute
> output to audit. So statistical bias, representational bias, and output/decision bias have
> **no surface whatsoever** in M8Shift. This is not "low risk" — it is *no locus*: the
> mechanism that produces ML bias does not exist in the relay.

**But the question deserves a harder look for a NON-model "fairness" notion** — *process
fairness between coordinated agents*. A coordination relay can be unfair even with zero ML.
The honest analysis:

- **Structural favoritism / holder-bias?** M8Shift's degree-1 mutex is *one writer at a
  time, serialized*. The pen is not auto-assigned by the relay to any privileged agent —
  acquisition is cooperative and operator/agent-driven. There is **no built-in scheduler
  that prefers a given roster name**, so no systemic favoritism by construction. **Verdict:
  no holder-bias in the core.** The one caveat worth naming: **default roster ordering** —
  if any listing/`next` logic iterates the roster in declaration order, an agent declared
  first could get a *de facto* first-look advantage. This is the closest thing to a
  "default-ordering bias" and is worth an explicit check (round-robin or last-served ordering
  rather than static declaration order).
- **Starvation / livelock (the real fairness risk)?** This is the genuine process-fairness
  concern, and it maps directly to the IBM Agentic risk **"Redundant actions" (IBM 10)** —
  interpreted as cyclical churn without forward progress. A serialized mutex *can* starve an
  agent that never wins the pen, or livelock the team if two agents bounce it. **Verdict:
  this fairness notion DOES apply** — and M8Shift already mitigates it with the **no-progress
  detector**, **loop guards** (`next`, `append --wait`, `status --for`), TTL/force-bounce
  handling, and the runtime companion's lane-ownership/no-progress signals. The honest
  residual: because the mutex is *cooperative* and advisory companions "never touch the
  pen," M8Shift **detects and surfaces** starvation/livelock but does not *forcibly*
  arbitrate fairness — preventing starvation ultimately relies on the trusted operator
  acting on the signal. That's a deliberate charter choice, not a gap to silently fix.
- **Identity fairness?** Identity is declarative (an agent is a name in the roster), with no
  crypto auth. So "fairness" can't be undermined by spoofed identity in the threat model's
  terms — but equally, M8Shift can't *enforce* that two distinct agents aren't the same
  operator gaming turn order. Within the trusted-team model this is acceptable; outside it,
  it's explicitly out of scope.

> [!NOTE]
> **Bottom line on bias:** ML/statistical/representational/output bias →
> **NOT-APPLICABLE (no model surface)**. The *only* defensible "fairness" lens is **process
> fairness between agents** (starvation/livelock/default-ordering), which **IS relevant**, is
> largely already addressed by M8Shift's no-progress + loop-guard machinery, and whose one
> concrete to-check is **default roster ordering** (avoid static declaration-order
> advantage).

#### A second bias axis — trusting the AI, not the AI's output

The risks above concern *model* bias (the AI's output). A different, and for a multi-agent
relay more relevant, axis is **trust calibration** — the biases of relying on AI at all:

- **automation bias** — the human deferring to the machine ("it's the AI");
- **overconfidence** — an LLM stating wrong answers as fluently as right ones, so confidence
  is no signal of correctness;
- **sycophancy** — an LLM agreeing to be agreeable rather than to be correct.

These are exactly what M8Shift's **structured contradiction** targets: an independent reviewer
required to refute rather than rubber-stamp, ideally from a **different model family** (less
correlated blind spots), with the verdict **anchored in deterministic ground truth** (tests,
builds, byte-level diffs) and a **human arbiter**. The honest caveat — and the reason this is
not automatic — is the **echo-chamber / correlated-error** failure: two agents that merely
agree, especially the same model, manufacture *false* confidence. The advantage is the
contradiction being real, not the redundancy itself. This is an operating rule in
[agents-guide.md](../agents-guide.md) §1 (*Why more than one agent*) and §2 (reviewer
neutrality, verification honesty).

### 4.4 Category-level verdict

**Wholesale NOT-APPLICABLE to M8Shift** (no surface — the originating mechanism doesn't
exist in a stdlib-local cooperative relay with no model):

- **Training Data** — entire category. No data is trained on.
- **Inference** — entire category. No inference, no prompts, no model to attack.
- **Output** — almost entirely. Bias, hallucination, harmful/toxic output, disinformation,
  copyright, privacy leakage all require generated content M8Shift never produces. (Only the
  *transparency/traceability* sub-theme — Untraceable attribution (77), Unexplainable output
  (75) — is relevant, and as inspiration M8Shift already over-satisfies it.)
- Most **Agentic security/tool risks** (Function calling hallucination (9), Attack on AI
  agents' external resources (6)) and all **societal-scale** Non-Technical risks.

**RELEVANT to M8Shift** — the governance/observability and agentic-coordination risks, which
M8Shift's design already engages:

- **Untraceable attribution (77) / Unexplainable and untraceable actions (1)** → fully
  addressed by the **append-only immutable turn ledger + atomic writes + per-turn agent
  attribution + session history (`history` + jsonl ledger)**. M8Shift is, by charter, the
  *traceability layer* for a multi-agent run.
- **Accountability of AI agent actions (15) / Legal accountability (89)** → addressed by
  attributed pen-acquisition and M8SHIFT.md writes; "who held the pen at turn N" is always
  answerable.
- **Over- or under-reliance on AI agents (4)** → *partially* addressed: M8Shift surfaces
  progress/no-progress, run counts, and stale/idle lanes so the operator can calibrate trust;
  it advises but does not decide. (IBM frames this as a trust-calibration risk, not value
  alignment.)
- **Redundant actions (10)** (livelock/no-progress) → addressed by the no-progress detector +
  loop guards + TTL/force-bounce.
- **Incomplete AI agent evaluation (11) / Lack of testing diversity (86) / Lack of system
  transparency (81)** → addressed for M8Shift-as-software by `docs/en/agents-guide.md`, LOCK
  schema validation, the 388-test suite (count ≠ coverage), and adversarial dogfooding.
- **Reproducibility (14)** → addressed by construction: no network, deterministic local
  files, VERSION lockstep, immutable run-plans.

**One-line synthesis:** M8Shift sits almost entirely *outside* the technical half of the
Atlas (Training Data / Inference / Output) because it has no model — including all classic
bias/fairness risks, which are structurally inapplicable. It intersects the Atlas only on the
**Non-Technical governance and Agentic coordination** axes — traceability, accountability,
reliance calibration, and redundant-action/no-progress livelock — and its audit-trail-first
design (immutable ledger, attribution, no-progress signals) already constitutes the
mitigation for those. The single genuinely-applicable "fairness" item is **inter-agent
process fairness** (starvation/default-ordering), not ML bias.

**Sources (§4)** (fetched/verified this session):

- [IBM AI Risk Atlas — AI Atlas Nexus mirror](https://ibm.github.io/ai-atlas-nexus/concepts/IBM_AI_Risk_Atlas/)
  (confirms the 5 categories: Training Data, Inference, Output, Non-Technical, Agentic).
- [AIUC-1 × IBM AI Risk Atlas crosswalk](https://www.aiuc-1.com/crosswalks/ibm-ai-risk-atlas)
  (full enumerated risk list IBM 1–99 with exact titles).
- [AI Risk Atlas: Taxonomy and Tooling (arXiv 2503.05780)](https://arxiv.org/abs/2503.05780).
- IBM watsonx docs (search excerpts):
  [Over- or under-reliance on AI agents](https://dataplatform.cloud.ibm.com/docs/content/wsj/ai-risk-atlas/over-or-under-reliance-on-ai-agents-agentic.html?context=wx),
  [Accountability of AI agent actions](https://dataplatform.cloud.ibm.com/docs/content/wsj/ai-risk-atlas/accountability-agentic.html?context=wx),
  [Untraceable attribution](https://dataplatform.cloud.ibm.com/docs/content/wsj/ai-risk-atlas/untraceable-attribution.html?context=wx),
  [Lack of training data transparency](https://dataplatform.cloud.ibm.com/docs/content/wsj/ai-risk-atlas/data-transparency.html?context=wx).

> [!NOTE]
> The canonical `dataplatform.cloud.ibm.com` risk pages are JS-rendered and returned
> navigation-only content / 403 to the fetcher (as expected); the verbatim over/under-reliance
> and accountability definitions above come from IBM's own search-result excerpts, and the
> full risk enumeration with exact titles from the AIUC-1 crosswalk (cross-checked against
> arXiv 2503.05780).

## 5. Government & standards frameworks (NIST · CISA · ANSSI)

> [!NOTE]
> **Sources verified:** NIST cited by document number (**NIST.AI.100-1**, 26 Jan 2023;
> **NIST.AI.600-1**, 26 Jul 2024) against nist.gov / airc.nist.gov / nvlpubs.nist.gov; CISA
> cited by document title (*Guidelines for Secure AI System Development*, 26 Nov 2023 —
> verified verbatim against the NCSC/CISA PDF; *Deploying AI Systems Securely*, 15 Apr 2024;
> *AI Data Security*, 22 May 2025); ANSSI cited as **ANSSI-PA-102** (*Recommandations de
> sécurité pour un système d'IA générative*, 29/04/2024 — R1–R35 extracted from the official
> PDF). The same structural filter as §§2–4 applies: **M8Shift hosts no model** (no training,
> inference, weights, prompts, network), so every model-centric control is NOT-APPLICABLE by
> construction; what transfers is the secure-by-design lifecycle, phase isolation, integrity
> verification, supply-chain hygiene, and governance/accountability that apply to *any*
> software tool.

### 5.1 NIST AI Risk Management Framework

The **NIST AI Risk Management Framework 1.0** (**NIST.AI.100-1**, 26 January 2023) is a
voluntary, outcome-based framework organized into four **functions** — **GOVERN** (policies,
accountability, roles, culture), **MAP** (context and risk framing), **MEASURE** (analyze,
benchmark, track risks), **MANAGE** (prioritize, treat, respond) — targeting seven
characteristics of trustworthy AI (valid & reliable; safe; secure & resilient; accountable &
transparent; explainable & interpretable; privacy-enhanced; fair – with harmful bias
managed). The companion **Generative AI Profile** (**NIST.AI.600-1**, 26 July 2024)
enumerates 12 GenAI risk categories mapped back to those four functions.

> [!IMPORTANT]
> The AI RMF presumes a system that *is* an AI/ML model. M8Shift has **no model** — so
> **all of MEASURE** (model metrics, bias measurement, robustness eval) and the *fair / safe
> / explainable / privacy / valid* characteristics in their AI sense are **NOT-APPLICABLE**.
> Where M8Shift maps, it maps as the **governance + audit-trail substrate** around the
> agents, not as an AI system itself.

| RMF function / characteristic | What it asks | Applies to M8Shift? | Rationale / control |
|---|---|---|---|
| **GOVERN** | Policies, accountability, roles, documented processes | **APPLICABLE — largely satisfied** | The charter *is* a governance policy; degree-1 cooperative mutex = accountability/role structure; advisory-companion boundary = documented separation of duties. Lead: surface as an explicit charter/`GOVERNANCE.md` (roles, trust assumption, out-of-charter list). |
| **MAP** | Frame context, intended use, actors, risks before building | **PARTIAL — partially satisfied** | No model context, but a stated threat model (trusted cooperative agents; explicitly *not* a boundary against malicious agents) + classified gaps (SEC-4/SEC-7, ASI03/ASI10) = the "frame context & known limits" outcome. Keep the threat-model + gaps register versioned with the code. |
| **MEASURE** | Quantitative/qualitative *model* eval: metrics, bias, robustness, drift | **NOT-APPLICABLE (largely)** | No model ⇒ no accuracy/bias/robustness metrics. Inspiration-only carve-out: `doctor` diagnostics + the 388-test suite are *software-quality* measurement, not "AI measurement." Do **not** invent model metrics. |
| **MANAGE** | Prioritize/treat risks, monitor, incident response, traceability, residual risk | **APPLICABLE — largely satisfied** | Append-only immutable ledger + atomic writes = traceability; force-ops audited in `sessions.jsonl` = incident record; LOCK validation + marker neutralization = risk treatment; `doctor` = monitoring. Lead: document SEC-7/SEC-4 as accepted/open residual risks tied to ledger evidence. |
| *Char.:* **secure & resilient** | Withstand misuse, recover gracefully | **PARTIAL** | Resilience real (atomic writes, immutable ledger, LOCK validation, force-op audit, `doctor`); security bounded by charter (declarative identity, no crypto auth). Lead: close SEC-7 / SEC-4 (resilience hardening, not a threat-model change). |
| *Char.:* **accountable & transparent** | Who did what, when; traceable | **APPLICABLE — satisfied** | Core strength: append-only ledger (transparency), `sessions.jsonl` force-op audit (accountability), declarative identity attributes every entry. Lead: `doctor`/`history` render a human-readable provenance view. |
| *Char.:* **valid & reliable / safe / explainable / privacy / fair** | Model validity, safety, interpretability, PII, bias | **NOT-APPLICABLE (AI sense)** | Software reliability applies (atomic writes, schema validation, tests) but the *model* senses have no surface; no PII pipeline (local-only, no network); no training data ⇒ no algorithmic-bias surface. |

**NIST.AI.600-1 GenAI risks:** of the 12 categories (§2.1–§2.12), 10 are model-output /
model-data risks with **no surface** (CBRN, Confabulation, Dangerous/Hateful content, Data
Privacy, Environmental, Harmful Bias, Human-AI Configuration, Information Integrity, IP,
Obscene content). Only two touch M8Shift: **§2.9 Information Security** — **PARTIAL**, mapping
to integrity/robustness posture (LOCK validation, marker neutralization, atomic writes,
force-op audit, immutable ledger; SEC-4/SEC-7 are §2.9-class hardening, in-charter); and
**§2.12 Value Chain and Component Integration** — **already satisfied** by construction
(stdlib-only, zero third-party deps, single file). The declarative-identity items
(ASI03/ASI10) are **design-owned**, not gaps to "fix."

### 5.2 CISA AI security guidance

The anchor document is the **Guidelines for Secure AI System Development** (CISA + UK NCSC +
21 partner agencies, 26 November 2023), a *secure-by-design / secure-by-default* framework
structured around four AI-lifecycle stages — **(1) Secure design, (2) Secure development,
(3) Secure deployment, (4) Secure operation and maintenance** — each with named
sub-guidelines (quoted verbatim below). Two later joint products extend it operationally:
**Deploying AI Systems Securely** (NSA AISC with CISA/FBI/Five-Eyes, 15 April 2024) and
**AI Data Security: Best Practices for Securing Data Used to Train & Operate AI Systems**
(CISA/NSA/FBI/Five-Eyes, 22 May 2025). M8Shift hosts no model, so every practice about
models, training data, inference, weights, or network/API hardening is **NOT-APPLICABLE for
lack of surface**; what transfers is the secure-by-design spine for *any* software:
supply-chain hygiene, environment/config hardening, logging/monitoring, incident handling,
least-privilege, and secure updates.

| CISA stage / practice | What it asks | Applies to M8Shift? | How M8Shift does / doesn't satisfy it |
|---|---|---|---|
| **1. Secure design** — "Model the threats to your system" | Threat-model before building | **APPLICABLE — already satisfied** | Stated threat model (cooperative *trusted* agents; explicitly **not** a malicious-agent boundary) + formal audit `security-audit.md` (SEC-1→SEC-11) + OWASP-agentic mapping. |
| **1. Secure design** — "Design your system for security as well as functionality and performance" | Security as first-class design goal | **APPLICABLE — already satisfied** | Degree-1 mutex (one writer), append-only immutable ledger, atomic writes, marker neutralization, LOCK schema validation. |
| **1. Secure design** — "Consider security benefits and trade-offs when selecting your AI model" | Model-selection trade-offs | **NOT-APPLICABLE** | M8Shift selects/hosts no model. |
| **2. Secure development** — "Secure your supply chain" | Vet/secure dependencies and build inputs | **APPLICABLE — strongly satisfied** | The **core** is stdlib-only, zero third-party deps = minimal surface by construction (single file; the m8shift scripts are verified against `checksums.sha256`). **Post-v3.40 the optional adapter installers are a real supply-chain input**: RTK is verified against the release tag's `checksums.txt` over TLS (same-origin **TOFU**, not an independent signature), and Headroom is an **unpinned** `pip` install — a strength *for the core*, a tracked opt-in surface for the installed system (ATLAS T0010/T0011.001; #97). |
| **2. Secure development** — "Manage your technical debt" | Track/pay down tech debt | **APPLICABLE — partially satisfied** | **SEC-4** (`--name` path footgun) and **SEC-7** (stale-lock TOCTOU) tracked as documented P1 debt, not hidden. |
| **3. Secure deployment** — "Secure your infrastructure" *(+ harden the deployment environment, Apr 2024)* | Harden the environment/config that runs the system | **PARTIAL — the key gap area** | Charter limits surface (no network/daemon/API/credentials; `git` argv-only, no shell/`eval`). **But this is where the open gaps live:** SEC-4 (`--name`/`--into` path escape) and SEC-7 (stale-lock TOCTOU). Leads: separator-free basename + `commonpath` containment (SEC-4); post-`O_EXCL` ownership token re-checked via `still_owned()` or rename-based takeover (SEC-7); require git-root/`M8SHIFT.md` for `M8SHIFT_ROOT` (SEC-3). |
| **3. Secure deployment** — "Develop incident management procedures" | Have IR playbooks ready | **PARTIAL** | `doctor` + audited `--force` (`--reason` + `sessions.jsonl`) give IR raw material. Lead: add a short documented IR/recovery runbook (detect stale/forged lock, recover from `sessions.jsonl`, restore single-writer). |
| **4. Secure operation & maintenance** — "Monitor your system's behaviour" | Continuous runtime monitoring | **APPLICABLE — already satisfied** | `sessions.jsonl` ledger + `doctor` (lint/JSON read-only) + runtime sidecars + advisory sentinel companions (always advisory, never auto-revoke). |
| **4. Secure operation & maintenance** — "Follow a secure by design approach to updates" | Patch/update securely | **APPLICABLE — satisfied** | Single-file checksum-verified updates, VERSION lockstep across the 7 scripts; no auto-update daemon. |
| **4. Secure operation & maintenance** — "Collect and share lessons learned" | Feed incidents back into design | **APPLICABLE — already satisfied** | Append-only `sessions.jsonl` + `history`/ledger + this living security-research doc. |
| *(Deploying AI Securely, Apr 2024)* — robust logging / audits & pentest | Tamper-evident logs; periodic audits | **APPLICABLE — largely satisfied** | Immutable ledger + audited force-ops + `doctor`; recurring adversarial audits (`security-audit.md`). |
| *(Deploying AI Securely, Apr 2024)* — strict access controls (RBAC/MFA) | Least-privilege access | **PARTIAL (design-owned limit)** | Declarative/cooperative identity, no crypto auth (ASI03/ASI07/ASI10); degree-1 mutex *is* a "one writer" control, but real authN is out of scope by design. |
| *(AI Data Security, May 2025)* — 10 data-security best practices | Protect training/operational data | **MOSTLY NOT-APPLICABLE; 1 INSPIRATION-ONLY** | No training/operational dataset ⇒ 9 of 10 have no surface. The exception (integrity checks / provenance) is conceptual: M8Shift already ships an immutable ledger + `checksums.sha256`; optional ledger/release *signing* is inspiration-only (crypto identity is outside the declarative-identity charter). |

**CISA verdict:** M8Shift *already embodies* the secure-by-design core — supply-chain
security (stdlib-only, checksum-verified install — its standout alignment), continuous
logging/monitoring + lessons-learned, tamper-evident audit, threat-modeled secure-by-default
design, and local-only minimized surface (no network/daemon/API key/shell). The few real
gaps all fall under "secure deployment environment / harden configuration": **SEC-4**,
**SEC-7**, plus **SEC-3** containment and a short **incident-response runbook**. Out of scope
by design: anything touching models/training/inference/weights/bias, network/API hardening,
and *cryptographic* identity/data-signing/secure-deletion.

### 5.3 ANSSI — recommendations for generative-AI systems

**ANSSI-PA-102, *Recommandations de sécurité pour un système d'IA générative*** (French
national cyber agency ANSSI, 29/04/2024) gives **35 numbered recommendations (R1–R35)** for
securing LLM-based generative-AI systems. It frames AI-specific threats as three attack
categories — **manipulation** (malicious requests), **infection** (training-data poisoning /
backdoor), and **exfiltration** (theft of training data, user data, or model weights) — and
organizes the lifecycle into three phases (**entraînement / déploiement / production**) that
"*peuvent être réalisées dans des environnements distincts*" and must each be treated as a
separate environment. Its cross-cutting controls are **cloisonnement** (R12/R28),
**contrôle d'accès / moindre privilège** (R9/R10/R35), and **vérification d'intégrité**
(R19/R20). The 2026 follow-up **CERTFR-2026-CTI-001** is a threat-landscape report
(contextual only; it issues no controls for a tool like M8Shift).

> [!IMPORTANT]
> M8Shift has **no model, no training, no inference, no weights**. The entire
> **infection / empoisonnement** family (training-data poisoning), model-file protection,
> retraining, GPU isolation, model I/O filtering, side-channels, and **exfiltration of
> weights/parameters** are **NOT-APPLICABLE by construction**. What transfers is the
> architectural skeleton: phase isolation (cloisonnement), access/privilege control,
> integrity verification, and supply-chain hygiene.

| ANSSI rec / theme | What it asks | Applies to M8Shift? | Mapping & lead |
|---|---|---|---|
| **R3** Évaluer la confiance des bibliothèques / modules externes | Map & assess third-party libs (supply chain) | **APPLICABLE — already satisfied** | **Stdlib-only, zero third-party deps** — the strongest possible answer to R3. Lead: keep the no-deps invariant enforced (CI/`doctor` check). |
| **R9** Proscrire l'usage automatisé d'IA pour des actions critiques | No autonomous critical actions | **APPLICABLE — already satisfied** | M8Shift has **no ML and takes no autonomous action**; it only coordinates agents the operator runs; companions are advisory-only. |
| **R10** Sécuriser les accès à privilèges | Restrict privileged access | **PARTIAL** | No OS-level authN (declarative identity, design-owned ASI03/ASI10). Lead: exactly **SEC-4** (`--name` footgun, ASI05) territory; document that M8Shift is **not** a boundary against malicious agents. |
| **R12** **Cloisonner chaque phase dans un environnement dédié** | Isolate each lifecycle phase | **APPLICABLE — strong map, partially satisfied** | **Best transfer.** Maps to **degree-2 worktree isolation** (`m8shift-worktree.py`: claim/integrate/drop, merge `--no-ff --no-commit` + `integrating:` sentinel) and **per-session sandboxes**. Lead: document worktrees explicitly as M8Shift's cloisonnement; keep handoff non-stranding so isolation can't deadlock. |
| **R19 / R20** Protéger en intégrité les données / fichiers du système d'IA | Integrity verification (signature/hash) | **NOT-APPLICABLE (model)** but **principle satisfied** | The model/training objects are N/A, but the **vérification d'intégrité** principle is realised by M8Shift's **immutable append-only ledger + atomic writes + LOCK schema validation + marker neutralization + `doctor`** over its own data. |
| **R23** Audits de sécurité avant déploiement | Audit before deploy | **APPLICABLE — already practised** | Mirrors M8Shift's adversarial-review dogfooding (Codex implements / Claude reviews adversarially before APPROVE). |
| **R24** Tests fonctionnels avant déploiement | Functional tests | **APPLICABLE — already satisfied** | **388 tests** (v3.42.0, regenerate on release), VERSION lockstep across 7 scripts. |
| **R28** **Cloisonner dans des zones logiques dédiées** ("limiter les risques de latéralisation") | Isolate in dedicated logical zones | **APPLICABLE — strong map** | Reinforces R12: worktree / per-session isolation limits "latéralisation." Same lead as R12. |
| **R29** Journaliser l'ensemble des traitements | Comprehensive logging | **APPLICABLE — already satisfied** | Session history (`history` + ledger jsonl), force-ops audited in `sessions.jsonl`, immutable turn ledger. |
| **R35** **Revue régulière de la configuration des droits** | Periodic access-rights review | **PARTIAL** | Touches the declarative-identity design-owned gap (ASI03/ASI10): M8Shift can't enforce access rights cryptographically. Lead: surface lane-ownership / identity declarations via `doctor`/`status` for periodic operator review. |
| *Model/training half* (R2/R6/R7/R11/R13/R14/R16/R17/R18/R21/R25/R26/R33/R34) | Training, model files, GPU, I/O filtering, public AI services, weights | **NOT-APPLICABLE** | No model, training, inference, weights, network, or public service surface. |
| **Cross-cutting: cloisonnement par phase** | Each phase = distinct environment | **APPLICABLE — strongest map** | → degree-2 **worktree isolation** + per-session sandboxes (R12/R28). |
| **Cross-cutting: contrôle d'accès & privilèges** | Access control + least privilege | **PARTIAL — design-owned gap** | → declarative/cooperative identity, degree-1 mutex, advisory companions. Enforcement gap = **ASI03/ASI10** (by design) + **SEC-4** (ASI05) and **SEC-7** TOCTOU (ASI03/07). |
| **Cross-cutting: vérification d'intégrité** | Integrity verification | **APPLICABLE — already satisfied** | → atomic writes + immutable turn ledger + LOCK schema validation + marker neutralization + `doctor`. |
| **Cross-cutting: supply-chain hygiene (R3/R5)** | Trusted libraries, secure CI | **APPLICABLE — already satisfied** | → **stdlib-only, zero third-party deps** is M8Shift's structural supply-chain answer. |

**ANSSI verdict:** the transferable core is the three cross-cutting principles —
**cloisonnement** (R12/R28 ↔ degree-2 worktree isolation + per-session sandboxes, its single
strongest alignment), **vérification d'intégrité** (R19/R20's principle ↔ atomic writes +
immutable ledger + LOCK validation + `doctor`, already satisfied), and **supply-chain
hygiene** (R3/R5 ↔ the stdlib-only, zero-dependency invariant, already satisfied). The
**access-control / privilege** axis (R10/R35) presses on M8Shift's acknowledged design-owned
gap (declarative identity, ASI03/ASI10) with the same open items **SEC-4** and **SEC-7**. The
entire model/training/inference half of the standard is **NOT-APPLICABLE by construction**.

**Sources (§5):**

- NIST AI Risk Management Framework — **NIST.AI.100-1** (26 Jan 2023; functions
  Govern/Map/Measure/Manage) — <https://www.nist.gov/itl/ai-risk-management-framework>;
  seven trustworthy characteristics — <https://airc.nist.gov/airmf-resources/airmf/3-sec-characteristics/>;
  Generative AI Profile **NIST.AI.600-1** (26 Jul 2024) —
  <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf>.
- CISA — **Guidelines for Secure AI System Development** (CISA + UK NCSC + partners,
  26 Nov 2023; four stages + 17 sub-guidelines verified verbatim);
  **Deploying AI Systems Securely** (NSA AISC / CISA / FBI / Five Eyes, 15 Apr 2024);
  **AI Data Security: Best Practices for Securing Data Used to Train & Operate AI Systems**
  (CISA / NSA / FBI / Five Eyes, 22 May 2025).
- ANSSI — **ANSSI-PA-102**, *Recommandations de sécurité pour un système d'IA générative*
  (29/04/2024; R1–R35, the 3 attack categories, the 3 phases, and R12/R19/R20/R28/R35 wording
  verified verbatim against the official PDF); contextual follow-up **CERTFR-2026-CTI-001**
  (4 Feb 2026).
- [security-audit.md](./security-audit.md) (SEC-1→SEC-11; SEC-3/SEC-4/SEC-7),
  [owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md) (ASI taxonomy), and the
  M8Shift charter invariants in `M8SHIFT.protocol.md` / `README.md`.

## 6. Synthesis: what to adopt vs ignore

This table consolidates the strongest external leads and maps each to M8Shift's open items,
cross-referencing the audit's SEC findings and its P1/P2/P3 plan.

| External lead (source) | M8Shift hook | Verdict | One-line reason |
|---|---|---|---|
| **Verify-before-commit** ([VIGIL 2601.05755](https://arxiv.org/abs/2601.05755)) | integration sentinel + atomic write + LOCK validation; audit P1 | **APPLICABLE** | Formalize the half-present two-phase pen handoff (stage → validate → atomic append); stdlib-only. |
| **Runtime-trace program analysis** ([AgentArmor 2508.01249](https://arxiv.org/abs/2508.01249)) | the append-only ledger (ASI08/ASI09) | **APPLICABLE** | The ledger *is* the trace; add `doctor --analyze` static invariant checks (one writer, monotonic turns, marker-clean). |
| **Four formal security properties** ([2603.19469](https://arxiv.org/abs/2603.19469)) | roster + turn schema + lane scope; 388-test suite | **APPLICABLE** | Encode task/action alignment, source-authorization, data-isolation as asserted unit-test invariants. |
| **Schema-validated cross-lane handoff** ([AgentSys 2602.07398](https://arxiv.org/abs/2602.07398)) | LOCK/turn schema validation (ASI06) | **APPLICABLE** | Require strict schema validation on every handoff payload before it enters M8SHIFT.md. |
| **Structural goal-drift detection** ([2505.02709](https://arxiv.org/abs/2505.02709)) | declared-task field vs original objective (ASI01/ASI10) | **APPLICABLE (PARTIAL)** | Text-diff the lane's stated goal across the immutable ledger; warn in `doctor` — no ML. |
| **Rogue-signal / sentinel monitoring** ([2502.05986](https://arxiv.org/abs/2502.05986), [2509.14956](https://arxiv.org/abs/2509.14956)) | advisory companion (ASI06/ASI10) | **APPLICABLE (PARTIAL)** | Read-only companion flags re-claim-after-done, no-progress, contradictions; never auto-revokes. |
| **Information-flow integrity labels** ([Fides 2505.23643](https://arxiv.org/abs/2505.23643)) | per-turn source-lane tag (ASI09) | **APPLICABLE (PARTIAL)** | Plain-string trusted-vs-external labels; companions refuse lower-integrity entries. |
| **Per-lane capability/MAC scoping** ([SEAgent 2601.11893](https://arxiv.org/abs/2601.11893)) | degree-1 mutex; declarative identity (ASI03/ASI07) | **APPLICABLE (PARTIAL)** | Declarative per-lane capability list checked at append time; static policy, stdlib-enforced. |
| **Release signing** (ATLAS `T0010` / audit ASI04) | `checksums.sha256` + denylist | **APPLICABLE** | The one concrete supply-chain lead: sign tags / publish signed checksums. |
| **Plan-lock** ([IPIGuard 2508.15310](https://arxiv.org/abs/2508.15310)) | runtime companion run-plan immutability | **INSPIRATION** | "Declare plan first, execute within it" — already enforced; cite as prior art. |
| **Defense taxonomy / risk-register scaffolding** ([2510.06445](https://arxiv.org/abs/2510.06445), [TrinityGuard 2603.15408](https://arxiv.org/abs/2603.15408), InjectLab, [2503.05780](https://arxiv.org/abs/2503.05780)) | threat-model doc structure | **INSPIRATION** | Use as section scaffolding / red-team checklist; not implementable defenses. |
| **Trust-authorization mismatch framing** ([SoK 2512.06914](https://arxiv.org/abs/2512.06914)) | declarative-identity limitation (audit §5) | **INSPIRATION** | Document the static-perms-vs-runtime-trust gap honestly; offer operator scope downgrade. |
| **Harden deployment config / secure environment** (CISA *Guidelines for Secure AI System Development* "Secure your infrastructure" + *Deploying AI Systems Securely*) | env/config hardening; SEC-4 / SEC-7 (§5.2) | **APPLICABLE** | The named gap area: `--name`/`--into` path containment (SEC-4) + stale-lock TOCTOU (SEC-7) are exactly "harden the deployment environment." |
| **Cloisonnement par phase** (ANSSI-PA-102 R12/R28) | degree-2 worktree isolation + per-session sandboxes (§5.3) | **APPLICABLE** | M8Shift's strongest ANSSI alignment: worktrees *are* the cloisonnement; document them explicitly and keep handoff non-stranding. |
| **GOVERN / MANAGE accountability + monitoring** (NIST.AI.100-1, §5.1) | charter-as-governance; immutable ledger + `doctor` + audited `--force` | **APPLICABLE** | Charter = GOVERN policy/roles; ledger + `sessions.jsonl` + `doctor` = MANAGE traceability/incident-record/monitoring (already largely satisfied). |
| **MEASURE (model metrics/bias) / ANSSI infection (training poisoning)** (NIST.AI.100-1; ANSSI-PA-102) | — | **NOT-APPLICABLE** | No model to measure or train ⇒ no metrics/bias surface and no training-data poisoning surface (§§5.1, 5.3). |
| **Activation-based drift** ([2406.00799](https://arxiv.org/abs/2406.00799)), **masked-replay** ([MELON 2502.05174](https://arxiv.org/abs/2502.05174)) | — | **NOT-APPLICABLE** | Need model internals/inference; M8Shift has no model. |
| **Memory/RAG poisoning** ([AgentPoison 2407.12784](https://arxiv.org/abs/2407.12784), [PoisonedRAG 2402.07867](https://arxiv.org/abs/2402.07867)) | append-only immutable ledger | **NOT-APPLICABLE** | No RAG/vector store; immutable ledger resists poisoning by construction. |
| **MCP/A2A defense-in-depth** ([MCPSHIELD 2604.05969](https://arxiv.org/abs/2604.05969)), **MAS arbitrary-code** ([2503.12188](https://arxiv.org/abs/2503.12188)) | — | **NOT-APPLICABLE** | No MCP/tools/network surface; charter is not a boundary against malicious agents. |
| **Classic ML bias/fairness** (IBM 26/58/59/17/18) | — | **NOT-APPLICABLE** | No model/training/inference/output — no locus for statistical bias (see §4.3). |

> [!NOTE]
> The strongest leads cluster on the audit's existing axes: **verify-before-commit ↔ the
> integration sentinel** (ASI02/ASI07/SEC-7), **immutable logs ↔ ASI08/ASI09**, **drift
> detection ↔ ASI01/ASI10**, and **schema/IFC integrity ↔ ASI06**. None require leaving the
> stdlib-local-cooperative charter; the two code-level P1 items remain **SEC-4** (i18n path
> footgun) and **SEC-7** (stale-lock TOCTOU).

## 7. Bottom line

Across three independent external frameworks the verdict converges. **MITRE ATLAS** is
~90 % NOT-APPLICABLE because it is a model-attack taxonomy and M8Shift has no model. The
**IBM AI Risk Atlas** Training-Data / Inference / Output categories — **all classic
bias/fairness risks included** — are structurally inapplicable for the same reason; M8Shift
intersects the Atlas only on the **governance/traceability and agentic-coordination** axes,
which its audit-trail-first design already mitigates. The **arXiv** literature contributes a
small, high-value set of charter-aligned hardenings: formalize **verify-before-commit**, add
a stdlib **`doctor --analyze`** over the ledger-as-runtime-trace, encode the **four formal
security properties** and a **structural goal-drift check** as tests, and add **per-lane
integrity labels / capability scoping** — all stdlib-only, all local. The honest residuals
are the same two the OWASP audit already names (**SEC-4**, **SEC-7**, both P1) plus
**release signing** (ATLAS `T0010`). Everything else the frameworks list belongs to the
*agents that use* M8Shift, not to the relay: M8Shift's minimalism is its security posture.

---

*Cross-references:
[owasp-agentic-top10-audit.md](./owasp-agentic-top10-audit.md) (ASI01→ASI10 grid) ·
[security-audit.md](./security-audit.md) (SEC-1→SEC-11) · MITRE ATLAS
<https://atlas.mitre.org> (canonical YAML) · IBM AI Risk Atlas (Atlas Nexus / AIUC-1
crosswalk / arXiv [2503.05780](https://arxiv.org/abs/2503.05780)) · 19 verified arXiv
defense papers. Verified code `m8shift.py` v3.42.0.*
