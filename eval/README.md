# Week 4 — Debugging Retrieval

Task: take a set of questions the app answers about `data/sample_contract.pdf`,
label each failure as "wrong clause fetched" (retrieval) vs. "right clause
fetched, wrong answer" (generation), make **one** change, and measure
hit-rate@3 before/after.

## Why this contract, chunked this finely

The app only ships with one sample contract. To get retrieval failures worth
studying out of a single 2-page document, the chunk size used for evaluation
is smaller (150 chars, see `rag_core.CHUNK_SIZE`) than you'd use in
production — it forces ~32 short, per-clause chunks instead of ~8 large ones,
so there's real competition at k=3 instead of near-guaranteed recall.

The test questions (`questions.py`) are phrased the way a person would
actually ask, not copied from the contract's own wording — copy-paste
phrasing barely stresses semantic search since it shares almost every word
with the source clause.

## The one change

**Cross-encoder reranking**: retrieve the top 10 chunks by FAISS similarity,
then re-score all 10 against the question with
`cross-encoder/ms-marco-MiniLM-L-6-v2` and keep the best 3
(`ContractIndex.search_reranked` in `rag_core.py`). This is also what
`app.py` now uses live, not just this offline eval.

A BM25 keyword-hybrid (RRF fusion) approach was tried first and rejected:
on this corpus — short chunks, tiny vocabulary, lots of shared boilerplate
("Company", "Employee", "Agreement") — BM25 term-frequency noise from common
words displaced correct chunks about as often as it rescued them (net hit-rate
change: negative in testing). The cross-encoder consistently did not.

## Running it

```bash
# retrieval-only (no API key needed — embeddings + reranker both run locally)
python eval/retrieval_eval.py

# also label generation failures with real Groq LLM answers (needs GROQ_API_KEY in .env)
python eval/retrieval_eval.py --generate
```

Both write the full inspection view (question / expected chunks / fetched
chunks / hit or miss / failure label) plus the before/after hit-rate@3 to
`eval/results.md`.

## Result (retrieval-only pass)

hit-rate@3 over 22 fact questions: **20/22 (90.9%) → 20/22 (90.9%)**, net flat —
reranking fixed one genuine failure (`parties`) but introduced a different
one (`leave_approval`), and left a third (`notice_period`) unresolved. See
`results.md` for the full breakdown and per-question reasoning; the short
version:

- **`parties`** — fixed. Baseline FAISS ranked the correct clause 5th by
  cosine similarity; the cross-encoder scored it far above every other
  candidate (-0.2 vs. -2.3 next best) — a clean win.
- **`leave_approval`** — regressed. The correct chunk was always in the
  candidate pool, but the cross-encoder's scores across the top candidates
  were nearly tied (within ~0.2 of each other) for this question, and it
  picked wrong. The chunk itself also straddles a topic boundary — it ends
  mid-sentence on leave approval and immediately starts the next clause's
  heading — which is likely why no method scores it cleanly.
- **`notice_period`** — still broken. The correct chunk never makes it into
  FAISS's top-10 candidate pool for this phrasing at all, so reranking
  never gets a chance to promote it. This needs a retrieval-side fix (better
  embeddings, query rewriting, or fixing the chunk boundary), not reranking —
  the two kinds of "wrong" really do need different fixes.

This is why the checklist item "did you notice which failures your change
did NOT fix" matters: reranking is a real, useful, low-risk change (it never
made a *high-margin* case worse in this corpus), but it is not a universal
fix for retrieval failures, and a flat headline number here is the honest
result, not a bug in the eval.

---

# Week 6 — Evals (Track F: Legal Contracts)

Task: build a test set that runs with one command and scores the app's
answers, validate an LLM judge against human grading before trusting its
number, make one improvement, and show a before/after score **per problem
type**, not just one overall number.

This week reuses rather than restarts everything before it:

- The eval set is `questions.py` — the same 24 questions from Week 4,
  now tagged with `problem_type` (which Week 5 taxonomy group each belongs
  to) and `human_verdict` (the PASS/FAIL a human already gave it in
  `error_analysis/open_coding_notes.md`). The 7 real Week 5 failures are
  now permanent regression tests, not one-off notes.
- The one improvement is the fix Week 5 predicted and did not yet build:
  `error_analysis/error_taxonomy.md`'s "Fix target for next iteration" —
  stitch each retrieved chunk's immediate predecessor into the context
  before generation, so a clause's lead-in verb / number continuation /
  causal header that landed on the other side of a 150-char chunk
  boundary is back in view. Implemented as
  `ContractIndex.expand_with_neighbors` in `../rag_core.py`, and wired
  into `../app.py` so it's live, not just in this offline eval.

## Files

| File | What it is |
|---|---|
| `judge.py` | LLM-as-judge: given a question, reference contract text, and an answer, returns a binary PASS/FAIL + one-sentence reason. Checks *groundedness*, not just keyword presence — see the module docstring for why a keyword rule alone can't catch everything. |
| `validate_judge.py` | Runs the judge over the same 24 traces a human already graded (`error_analysis/traces.json` + `open_coding_notes.md`) and reports agreement. Below 80% agreement, `run_evals.py` falls back to rule-only scoring instead of trusting the judge. |
| `run_evals.py` | The one command. Validates the judge, then runs all 24 questions through the real pipeline twice (before/after the neighbor-stitch fix), scores each with free rule checks + the judge, and reports pass rate before/after per `problem_type`. |
| `judge_validation.md`, `eval_report.md` | Generated by the two scripts above — not checked in ahead of a run. |

## Running it

```bash
# needs GROQ_API_KEY in .env — real Groq calls throughout
python eval/run_evals.py
```

This alone does everything on the mentor checklist: runs as a single
command, includes last week's real failures as tests (they're the FAIL
rows in `questions.py`'s `human_verdict`), validates the judge against
human grading before using it, and prints/writes a before-and-after score
per problem type.

To check just the judge (e.g. after changing the judge prompt or model):

```bash
python eval/validate_judge.py
```

## Scoring design

Two layers, cheapest first:

1. **Rule checks (free, no API call)** — `rule_check()` in `run_evals.py`.
   For a no-answer control question, did it refuse? For a real question,
   does the answer contain a required keyword *and* not refuse? This alone
   catches most of Week 5's failures (a flat "not found" refusal fails
   the "must not refuse" check immediately).
2. **LLM judge (for what the rule can't see)** — grounded correctness.
   Week 5's `leave_approval` failure passed on vibes: a directionally
   plausible answer reached by inference over the *wrong* context, not by
   reading the clause that actually answers the question. A keyword rule
   can't distinguish "right answer, right reason" from "right answer,
   wrong/no reason" — that's what the judge is for. A question only
   scores PASS if it clears both layers.

## Result

Judge validation: **20/24 = 83.3%** agreement with human grading (above
the 80% trust threshold) — see `judge_validation.md` for the full
breakdown, including which 4 traces it disagrees with the human on and
why (it grades against what was *retrieved*, matching the human's basis
for grading generation quality, so a "correctly refused, given what it
saw" call from the judge can still be a "wrong, the fact exists
elsewhere in the contract" call from the human — a retrieval problem the
judge structurally can't see from inside a generation-only grading task).

Eval set, before/after the neighbor-stitch fix:

| problem_type | before | after |
|---|---|---|
| split_clause_refusal (fix target) | 0/3 (0%) | 1/3 (33%) |
| baseline_pass | 13/15 (87%) | 11/15 (73%) |
| never_retrieved_false_notfound | 0/2 (0%) | 0/2 (0%) |
| never_retrieved_lucky_pass | 0/1 (0%) | 0/1 (0%) |
| wrong_item_selected | 0/1 (0%) | 0/1 (0%) |
| no_answer_control | 2/2 (100%) | 2/2 (100%) |
| **OVERALL** | **15/24 (62.5%)** | **14/24 (58.3%)** |

**Not a clean win — net flat-to-slightly-down**, and that's the honest
result, not a bug:

- **The fix worked on the group it targeted.** `reports_to` flipped from
  a flat "not found" to the correct "Engineering Manager" — exactly the
  boundary-word failure `error_taxonomy.md` predicted, fixed the way it
  predicted. `salary` and `confidentiality_dismissal` (same group) are
  still FAIL, but not because the fix didn't reach them: `salary` still
  refuses outright (retrieval brought in the right chunks 6/7, but the
  fix only reaches *neighbors* of retrieved chunks — chunks 6/7 are
  themselves the answer, no boundary word needed, so this was never a
  neighbor-stitch problem to begin with). `confidentiality_dismissal`
  actually became substantively correct after the fix ("Yes — willful
  breach... can lead to immediate termination"), but the judge fails it
  because the gold reference for that question is deliberately narrow
  (just the one clause from Week 4's original `expected_chunks`) and
  doesn't include the termination framing the neighbor stitch correctly
  pulled in — an eval-design artifact, not a real product regression.
- **It broke two previously-passing answers.** `sick_leave` and
  `noncompete_consulting` regressed: the extra neighbor context gave the
  model more material to work with, and in both cases it added a detail
  not supported by the specific reference clause (sick_leave picked up
  an "approved in advance" condition from an adjacent leave clause;
  noncompete_consulting hallucinated a "Section 7" citation that isn't
  in either the retrieved or neighboring text). More context isn't free —
  this is the real cost side of the fix, not just the benefit side.
- **Groups 2–4 (retrieval failures) are untouched, as predicted.** The
  neighbor stitch only expands context around what retrieval already
  picked — it can't fix a chunk that never made it into the candidate
  pool in the first place (`overtime`, `notice_period`, `leave_approval`).
  `immediate_termination_fraud`'s after-answer is now substantively
  correct ("...if you are found to have stolen...") but still fails the
  free rule check, which requires the literal substring "theft" or
  "fraud" — a real limitation of a cheap keyword rule, not of the fix.

This is the same lesson Week 4's reranking result taught with hit-rate@3:
a real, targeted fix can move the number it was aimed at without being a
universal improvement, and a flat or negative headline number is
sometimes the honest result of a fix trading one failure mode for
another — worth reporting as-is rather than cherry-picking the group that
moved.
