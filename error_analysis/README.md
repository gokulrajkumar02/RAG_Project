# Week 5 — Error Analysis (Track F: Legal Contracts)

Task: collect ~20 real traces from the app, read every one, write an honest
note on each failure, group the notes into named problem types, and rank
them so there's a clear next thing to fix.

This is a different question from Week 4's retrieval eval (`eval/`). Week 4
asked "was the right chunk retrieved" (hit-rate@3). This asks "what does the
*whole* answer look like to a real user" — including cases where the right
chunk was retrieved but the answer is still wrong.

## Files

| File | What it is |
|---|---|
| `collect_traces.py` | Runs the app's real pipeline (`ContractIndex.search_reranked` → `generate_answer`, live Groq call) over every question in `eval/questions.py` and writes complete traces. |
| `traces.json` | The 24 traces in structured form — question, retrieved chunk indices/pages/content, full generated answer. Complete enough to replay any one of them. |
| `traces.md` | The same traces, human-readable — this is what was actually read for the analysis below. |
| `open_coding_notes.md` | One line per trace, written while reading `traces.md` top to bottom, **before** any category existed: PASS, or one honest sentence on what went wrong. |
| `error_taxonomy.md` | The failure notes grouped into named problem types, ranked by frequency × severity, with the chosen fix target and a written prediction. |

## Sample: why 24 questions, and why not cherry-picked

The brief asks for "around 20" real answers, taken as a fair sample rather
than hand-picked good (or bad) examples. This run reused all 24 questions
from `eval/questions.py` as-is, unchanged, rather than writing a fresh set
for this exercise, for one reason: that question set was authored in
**Week 4**, before this error-analysis pass existed, specifically to be
paraphrased the way a real employee would ask ("how much heads-up do I
need to give?" instead of "what is the notice period?") rather than
copied from the contract's own wording. Reusing a pre-existing set means
nothing here was selected after the fact to make the results look better
or worse than they are — every question the app has a labeled test for
got read, including the two `no_answer` controls that test for
hallucination rather than correctness.

The one thing this sample can't cover: real free-text phrasing variance
from actual users, since there's no live traffic yet for this project —
only one sample contract and a fixed test set. That's the honest
limitation, not glossed over.

## Reproducing

```bash
# needs GROQ_API_KEY in .env — real Groq calls, ~24 requests
python error_analysis/collect_traces.py
```

## Result

17/24 traces pass. 7 fail, falling into 4 named problem groups; full
breakdown, ranking, and the chosen fix target with a prediction are in
[`error_taxonomy.md`](error_taxonomy.md).
