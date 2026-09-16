"""
Week 4 task: label retrieval failures, buy back hit-rate@3 with ONE change.

Usage:
    python eval/retrieval_eval.py             # retrieval-only (no API key needed)
    python eval/retrieval_eval.py --generate   # also calls the Groq LLM to label
                                                # "right clause fetched, wrong answer"
                                                # failures (needs GROQ_API_KEY in .env)

Writes a side-by-side inspection view + before/after numbers to
eval/results.md.
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from rag_core import load_pdf_chunks, ContractIndex, generate_answer
from questions import QUESTIONS

load_dotenv()

PDF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_contract.pdf")
K = 3
RERANK_POOL = 10


def chunk_indices(docs):
    return [d.metadata["chunk_idx"] for d in docs]


def hit(retrieved, expected):
    if not expected:
        return None
    return bool(set(retrieved) & set(expected))


def keyword_match(answer, keywords):
    answer_lower = answer.lower()
    return any(kw.lower() in answer_lower for kw in keywords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="also run Groq generation to label generation failures")
    args = parser.parse_args()

    api_key = os.getenv("GROQ_API_KEY", "")
    do_generate = args.generate and bool(api_key)
    if args.generate and not api_key:
        print("!! --generate was passed but GROQ_API_KEY is not set (add it to .env) — skipping generation step.\n")

    print(f"Loading + chunking {PDF_PATH} ...")
    chunks = load_pdf_chunks(PDF_PATH)
    print(f"{len(chunks)} chunks (chunk_size=150, chunk_overlap=20)\n")

    print("Building semantic (FAISS) index + loading cross-encoder reranker ...")
    index = ContractIndex(chunks)
    _ = index.reranker  # force-load once, up front, instead of on first query
    print("Done.\n")

    rows = []
    fact_questions = [q for q in QUESTIONS if not q.get("no_answer")]
    no_answer_questions = [q for q in QUESTIONS if q.get("no_answer")]

    baseline_hits = 0
    reranked_hits = 0

    for q in fact_questions:
        baseline_docs = index.search_semantic(q["question"], k=K)
        reranked_docs = index.search_reranked(q["question"], k=K, pool=RERANK_POOL)

        baseline_idx = chunk_indices(baseline_docs)
        reranked_idx = chunk_indices(reranked_docs)

        baseline_hit = hit(baseline_idx, q["expected_chunks"])
        reranked_hit = hit(reranked_idx, q["expected_chunks"])

        baseline_hits += int(baseline_hit)
        reranked_hits += int(reranked_hit)

        row = {
            "id": q["id"],
            "question": q["question"],
            "expected_chunks": q["expected_chunks"],
            "baseline_chunks": baseline_idx,
            "baseline_hit": baseline_hit,
            "reranked_chunks": reranked_idx,
            "reranked_hit": reranked_hit,
            "label": None,
            "baseline_answer": None,
            "reranked_answer": None,
        }

        if do_generate:
            row["baseline_answer"] = generate_answer(q["question"], baseline_docs, api_key)
            if baseline_hit:
                row["label"] = (
                    "PASS"
                    if keyword_match(row["baseline_answer"], q["answer_keywords"])
                    else "GENERATION FAILURE (right chunk, wrong answer)"
                )
            else:
                row["label"] = "RETRIEVAL FAILURE (wrong chunk fetched)"

            if not baseline_hit and reranked_hit:
                row["reranked_answer"] = generate_answer(q["question"], reranked_docs, api_key)
        elif baseline_hit and reranked_hit:
            row["label"] = "HIT (both)"
        elif not baseline_hit and reranked_hit:
            row["label"] = "FIXED by reranking"
        elif baseline_hit and not reranked_hit:
            row["label"] = "REGRESSED by reranking"
        else:
            row["label"] = "RETRIEVAL FAILURE (wrong chunk fetched, both)"

        rows.append(row)

    n = len(fact_questions)
    baseline_rate = baseline_hits / n
    reranked_rate = reranked_hits / n

    print("=" * 100)
    print(f"{'ID':<28}{'expected':<12}{'baseline':<12}{'hit':<6}{'reranked':<12}{'hit':<6}{'label'}")
    print("=" * 100)
    for r in rows:
        print(
            f"{r['id']:<28}{str(r['expected_chunks']):<12}{str(r['baseline_chunks']):<12}"
            f"{str(r['baseline_hit']):<6}{str(r['reranked_chunks']):<12}{str(r['reranked_hit']):<6}{r['label']}"
        )

    print("\n" + "-" * 60)
    print(f"hit-rate@3  BEFORE (semantic-only, k=3):        {baseline_hits}/{n} = {baseline_rate:.2%}")
    print(f"hit-rate@3  AFTER  (FAISS top-10 + rerank to 3): {reranked_hits}/{n} = {reranked_rate:.2%}")
    print("-" * 60)

    fixed = [r for r in rows if not r["baseline_hit"] and r["reranked_hit"]]
    broke = [r for r in rows if r["baseline_hit"] and not r["reranked_hit"]]
    still_broken = [r for r in rows if not r["baseline_hit"] and not r["reranked_hit"]]
    gen_failures = [r for r in rows if r["label"] and "GENERATION FAILURE" in r["label"]]

    print(f"\nFixed by reranking ({len(fixed)}): {[r['id'] for r in fixed]}")
    print(f"Regressed by reranking ({len(broke)}): {[r['id'] for r in broke]}")
    print(f"Still wrong chunk after reranking ({len(still_broken)}): {[r['id'] for r in still_broken]}")
    if do_generate:
        print(f"Generation failures — reranking can't fix these ({len(gen_failures)}): {[r['id'] for r in gen_failures]}")

    # No-answer control questions (hallucination check)
    print("\n" + "=" * 60)
    print("No-answer control questions (fact not in contract):")
    print("=" * 60)
    for q in no_answer_questions:
        reranked_docs = index.search_reranked(q["question"], k=K, pool=RERANK_POOL)
        line = f"  {q['id']}: top reranked chunks = {chunk_indices(reranked_docs)}"
        if do_generate:
            answer = generate_answer(q["question"], reranked_docs, api_key)
            said_not_found = keyword_match(answer, q["answer_keywords"])
            line += f" | answer={'correctly refused' if said_not_found else 'HALLUCINATED: ' + answer[:80]}"
        print(line)

    write_report(rows, no_answer_questions, index, baseline_rate, reranked_rate, n, do_generate)


def write_report(rows, no_answer_questions, index, baseline_rate, reranked_rate, n, do_generate):
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.md")
    lines = []
    lines.append("# Retrieval Debugging Report — Legal Contract RAG\n")
    lines.append(f"Corpus: `data/sample_contract.pdf`, {len(index.chunks)} chunks "
                  f"(chunk_size=150, chunk_overlap=20)\n")
    lines.append(f"- **hit-rate@3 BEFORE (semantic-only FAISS, k=3)**: {baseline_rate:.2%}\n")
    lines.append(f"- **hit-rate@3 AFTER (FAISS top-10 -> cross-encoder rerank to top 3)**: {reranked_rate:.2%}\n")
    lines.append("\n## Inspection view (question / fetched / labeled failure)\n")
    lines.append("| id | question | expected chunks | baseline chunks | baseline hit | reranked chunks | reranked hit | label |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['question']} | {r['expected_chunks']} | {r['baseline_chunks']} | "
            f"{r['baseline_hit']} | {r['reranked_chunks']} | {r['reranked_hit']} | {r['label']} |"
        )

    if do_generate:
        lines.append("\n## Generated answers (baseline context)\n")
        for r in rows:
            if r["baseline_answer"]:
                lines.append(f"- **{r['id']}**: _{r['baseline_answer']}_")

    lines.append("\n## No-answer control questions\n")
    for q in no_answer_questions:
        reranked_docs = index.search_reranked(q["question"], k=K, pool=RERANK_POOL)
        lines.append(f"- **{q['id']}**: \"{q['question']}\" → top reranked chunks = {chunk_indices(reranked_docs)}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
