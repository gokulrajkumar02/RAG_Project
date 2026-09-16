# Error Taxonomy — Legal Contract RAG (Track F: Legal Contracts)

Built by grouping the 7 failure notes in [`open_coding_notes.md`](open_coding_notes.md)
(written first, before any category existed) into named problem types, then
ranking by frequency × severity.

## Problem groups

### 1. Over-cautious refusal on split clauses
**Frequency: 3/24 (12.5%) — `reports_to`, `salary`, `confidentiality_dismissal`**

The correct fact is physically present in the retrieved context, but split
across a chunk boundary from the word or heading that would let the model
confidently connect it to the question — a verb ("shall report to the"), a
number's second half ("Rupees)" separated from "Rs. 80,000"), or a causal
header ("may terminate immediately for:"). Instead of inferring across the
fragment it *does* have, the model defaults to "This information was not
found in the contract."

**Severity: HIGH.** This is the worst version of a RAG failure: it looks
identical to a correct "not in the contract" refusal, so the user has no
way to tell it apart from a real absence — and it happened on `salary`,
arguably the single most important fact an employee asks a contract
assistant about.

### 2. Clause never retrieved — false "not found"
**Frequency: 2/24 (8.3%) — `notice_period`, `overtime`**

The correct chunk (notice period's "30 days," overtime's compensation
clause) never enters the top-10 FAISS candidate pool at all for these
phrasings, so reranking never gets a chance — this matches the
`notice_period` retrieval gap already identified in the Week 4 report
(`eval/results.md`), now confirmed to produce a wrong end-to-end answer,
not just a bad hit-rate number.

**Severity: HIGH.** Same user-facing symptom as Group 1 (a flat, wrong
"not found"), on equally ordinary questions.

### 3. Wrong item selected from a similar list
**Frequency: 1/24 (4.2%) — `immediate_termination_fraud`**

The right chunk was retrieved and contains the exact answer ("Theft,
fraud, or dishonesty"), but the model picked a different bullet from the
same list ("Gross misconduct or negligence") and stated it as fact.

**Severity: HIGH per occurrence.** Unlike Groups 1–2, this fails silently
as a *confident, plausible-sounding wrong answer* with no refusal to tip
the user off — in a legal-contract context, misattributing which clause
applies to a disciplinary question is a meaningfully worse failure mode
than a visible "not found," it's just rarer so far.

### 4. Clause never retrieved — but the answer got lucky
**Frequency: 1/24 (4.2%) — `leave_approval`**

Same root cause as Group 2 (correct chunk never retrieved), but here the
model produced a directionally correct answer by inference from adjacent
context (the leave-days list) rather than the real "must be approved in
advance" clause. It reads fine today; nothing here guarantees it will next
time a differently-worded question hits the same gap.

**Severity: MEDIUM.** No visible harm in this instance, but it's an
unforced, ungrounded answer — a near-miss, not a genuine pass.

## Ranked (frequency × severity, high→low)

| rank | group | freq | severity | score |
|---|---|---|---|---|
| 1 | Over-cautious refusal on split clauses | 3 | high (3) | 9 |
| 2 | Clause never retrieved → false "not found" | 2 | high (3) | 6 |
| 3 | Wrong item selected from a similar list | 1 | high (3) | 3 |
| 4 | Clause never retrieved → lucky ungrounded answer | 1 | medium (2) | 2 |

Benchmark comparison for scale: MMLU/HumanEval-style leaderboard numbers
describe the base model's general knowledge or code-generation ability in
isolation. None of the 7 failures above are model-knowledge gaps — every
one is this specific app's retrieval pipeline or prompt failing to get a
fact that's sitting right there in a 2-page PDF in front of the model. A
strong MMLU score for `openai/gpt-oss-20b` would not have predicted any of
this; only reading this app's own traces surfaced it.

## Fix target for next iteration

**Target: Group 1 — Over-cautious refusal on split clauses** (rank 1, and
the only group with a fix that doesn't require improving retrieval itself).

**Planned change:** when assembling context for generation, stitch in each
retrieved chunk's immediate neighbor (`chunk_idx - 1`) alongside it, so a
clause header or lead-in phrase that got separated from its content by the
150-char chunk boundary is back in view. This is a generation-context fix,
not a retrieval fix — it doesn't change which chunks FAISS/the reranker
pick, only what's shown to the LLM once they're picked.

**Prediction:** this should fix `reports_to`, `salary`, and
`confidentiality_dismissal` (all three currently fail because the
retrieved chunk's neighbor holds the missing lead-in) without changing
`notice_period` or `overtime` at all, since those fail earlier, in
retrieval — the correct chunk (and therefore its neighbor) is never
selected in the first place. Expect the pass rate to move from 17/24
(70.8%) to 20/24 (83.3%) with this one change, and expect it to leave
Groups 2–4 exactly as broken as they are now, the same way Week 4's
reranker fix improved one problem without touching the others.
