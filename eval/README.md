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
