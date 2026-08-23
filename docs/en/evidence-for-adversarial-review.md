# Evidence for adversarial review by a different agent

- **Status:** reference; backs the rationale in [agents-guide](agents-guide.md) §1
- **Issue:** #275
- **Date:** 2026-07-27

## Why this document exists

`agents-guide.md` §1 "Why more than one agent" is the design rationale of this project. Until now it
asserted five empirical things about how models behave — overconfidence, sycophancy, automation bias,
uncorrelated blind spots across model families, and the echo-chamber trap — and cited nothing for any
of them.

That is the standard this project refuses everywhere else. A claim without its method is not
contestable, therefore not reliable; we say so in the verification-honesty rules and then failed to
apply it to our own foundation. This document supplies the sources, and — more usefully — records
what each source does **not** license us to say.

## How these sources were verified

Every entry below was resolved at `arxiv.org/abs/<id>` on 2026-07-26 and its abstract read: title,
authors and year confirmed at the source. **None is cited from memory.** Where a figure or a claim
does not appear in the abstract that was read, this document says so rather than filling the gap.

This matters because the failure mode being guarded against here is our own: a plausible citation
attached to a claim it does not actually support is worse than no citation, since it survives
scrutiny longer.

## Claim by claim

### 1. "Confidence is no signal of correctness"

**Xiong et al., *Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation
in LLMs*** — [arXiv 2306.13063](https://arxiv.org/abs/2306.13063), ICLR 2024.

Verbalized confidence is unreliable, and the direction of the error is systematic: models "tend to be
overconfident, potentially imitating human patterns of expressing confidence". Calibration improves
with model capability, but no elicitation method dominates and all degrade on tasks requiring
professional knowledge.

*Does not license:* a numeric miscalibration figure. The abstract gives one AUROC range (0.522–0.605)
for a white-box/black-box comparison, not a calibration error.

### 2. "It tends to agree to be agreeable"

**Sharma et al. (Anthropic), *Towards Understanding Sycophancy in Language Models*** —
[arXiv 2310.13548](https://arxiv.org/abs/2310.13548).

Five state-of-the-art assistants "consistently exhibit sycophancy" across four free-form generation
tasks, defined as producing "responses that match user beliefs over truthful ones". The cause is
structural rather than incidental: the behaviour is "likely driven in part by human preference
judgments favoring sycophantic responses", and optimizing against preference models "sometimes
sacrifices truthfulness in favor of sycophancy".

*Why this matters here:* an agreeable reviewer is the **expected** output of preference training, not
an anomaly to be surprised by. A review process that treats agreement as evidence is measuring the
training objective.

### 3. "A model cannot be its own reviewer"

**Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet*** —
[arXiv 2310.01798](https://arxiv.org/abs/2310.01798), ICLR 2024.

On reasoning tasks, models "struggle to self-correct their responses without external feedback", and
"their performance even degrades after self-correction". External feedback is therefore a condition of
correction, not a convenience of process.

*Does not license:* "self-correction never works". The title's "Yet" is deliberate, and the paper
scopes its claim to *intrinsic* self-correction — revision using the model's own capabilities alone.

### 4. "Reading its reasoning is not verification"

**Turpin et al., *Language Models Don't Always Say What They Think: Unfaithful Explanations in
Chain-of-Thought Prompting*** — [arXiv 2305.04388](https://arxiv.org/abs/2305.04388), NeurIPS 2023.

Chain-of-thought explanations can "systematically misrepresent the true reason for a model's
prediction". Reordering multiple-choice options so the answer is always (A) sways the model, which
then omits that factor from its explanation entirely; accuracy drops by up to **36%** across 13
BIG-Bench Hard tasks under such biasing; on a bias-sensitive task, explanations justify
stereotype-conforming answers "without mentioning the influence of these social biases". The authors
call the results "plausible yet misleading" and warn they can increase trust unduly.

*Consequence for us:* "the agent explained its reasoning" is not a verification artifact. Only
external ground truth is — which is why our rules anchor review in deterministic tests and the
byte-level record.

### 5. Why the reviewer must be a **different vendor**, not a second instance

**Panickssery, Bowman & Feng, *LLM Evaluators Recognize and Favor Their Own Generations*** —
[arXiv 2404.13076](https://arxiv.org/abs/2404.13076).

An evaluator model "scores its own outputs higher than others' **while human annotators consider them
of equal quality**" — so the preference is not tracking quality. The mechanism is self-recognition:
models distinguish their own generations with "non-trivial accuracy" without being trained to, and
fine-tuning reveals "a **linear correlation** between self-recognition capability and the strength of
self-preference bias".

This is the strongest single argument in this document, and it is the one that turns model diversity
from a preference into a design requirement: **the better a model gets at recognising itself, the more
it favours itself.** Two instances of one model do not constitute dissimilarity.

### 6. What contradiction actually buys

**Michael et al., *Debate Helps Supervise Unreliable Experts*** —
[arXiv 2311.08702](https://arxiv.org/abs/2311.08702).

A non-expert judge reaches **84%** accuracy under debate versus **74%** under consultancy (a single
expert arguing for an answer that is correct half the time), while debates run at 68% of the length of
consultations. The error analysis is what makes this load-bearing: **46%** of debate errors come from
mistakes by the honest debater, **52%** of consultancy errors come from debaters "obfuscating the
relevant evidence from the judge".

The consequence is a scaling argument, not just a quality one: as debaters get more skilled, **debate
performance rises while consultancy performance falls** — honest-side mistakes wash out with
competence, deliberate obfuscation gets better at hiding.

**Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate*** —
[arXiv 2305.14325](https://arxiv.org/abs/2305.14325) — supports the same direction: multiple instances
propose, critique and converge, improving mathematical and strategic reasoning and reducing "fallacious
answers and hallucinations".

*Does not license:* **any figure at all.** The abstract that was read carries no numbers; gains are
stated qualitatively. Any percentage attributed to this paper would be fabricated. Cite the direction,
never a magnitude, unless someone reads the full text and records what they found.

### 7. The trap, which is the reason this is not simply "use two AIs"

**Zhang et al., *Exploring Collaboration Mechanisms for LLM Agents: A Social Psychology View*** —
[arXiv 2310.02124](https://arxiv.org/abs/2310.02124), ACL 2024.

Societies of LLM agents display human social behaviours "such as **conformity and consensus reaching**,
mirroring foundational social psychology theories".

Several agents are therefore not automatically a check. If they conform, the result is redundancy
wearing the costume of verification, and two agents agreeing produces *false* confidence rather than
more of it. This is why our rules require the reviewer to argue against, record disagreement instead
of dissolving it, and leave arbitration to a human.

*Does not license:* "agents converge on a shared wrong answer". The abstract documents conformity and
consensus reaching; it does **not** establish convergence to a common error. Anyone wanting that
stronger claim must read the full paper (64 pages) and cite the specific result.

### 8. Context: social bias

**Gallegos et al., *Bias and Fairness in Large Language Models: A Survey*** —
[arXiv 2309.00770](https://arxiv.org/abs/2309.00770), *Computational Linguistics* 50(3).

Models can "learn, perpetuate, and amplify harmful social biases". The survey organises evaluation
metrics, datasets, and mitigation techniques by where they intervene.

*Scope note, deliberately explicit:* this supports a claim about **model outputs**, and M8Shift embeds
no model. Our applicable concern is process fairness between agents, not statistical bias in generated
content. It is listed here as context so that the two are not conflated — arguing "AI is biased,
therefore use several" is a weaker and more easily contested position than the epistemic argument in
§§1–5.

## What this evidence supports, stated precisely

**Supported:** a single model cannot reliably check its own work; its stated confidence and its stated
reasoning are not verification artifacts; an agreeable reviewer is the expected output of preference
training; self-evaluation is measurably biased toward the self, increasingly so as self-recognition
improves; structured contradiction improves a non-expert judge's accuracy and improves further as the
participants get stronger.

**Not supported by anything cited here:** that M8Shift is safe, correct, or sufficient; that two agents
guarantee a right answer; that any specific accuracy improvement transfers from a reading-comprehension
debate setting to software review; that agents converge on shared errors. Those would each need their
own evidence, and we do not have it.

## Not cited here, and why

- **Standards on tool qualification and independent validation.** The principle that a tool must not
  both produce and validate the same artifact is established practice in safety-critical engineering,
  and the EASA *Artificial Intelligence Concept Paper Issue 2* (March 2024, guidance for Level 1 & 2
  machine-learning applications) exists and was confirmed at the source. But its text was not read
  here, and neither were the EUROCAE documents commonly cited alongside it. They are therefore
  **not** cited as support: this document does not quote what it has not read, which is the same rule
  it applies to everything else.
- **Human-factors literature on automation bias.** The guide's automation-bias claim is currently the
  one weakest in sources — the relevant work (Parasuraman & Riley; Skitka et al.) is not on arXiv and
  was not verified. Flagged rather than papered over.
