"""
Week 5 task: collect complete traces from the app's real pipeline, to be
read by hand for error analysis (see error_analysis/README.md).

A trace here means the same thing app.py produces for a live user question:
    question -> ContractIndex.search_reranked(k=3, pool=10) -> generate_answer()
run against the real Groq LLM (needs GROQ_API_KEY in .env) — not the
retrieval-only hit/miss check from eval/retrieval_eval.py (Week 4). That
harness only asks "was the right chunk retrieved"; this one captures the
full question -> context -> answer record so it can be read like a real
user would read it, including answers that retrieved the right chunk but
are still wrong, badly worded, or incomplete.

The question set is eval/questions.py, reused as-is rather than written
fresh for this exercise: it was authored in Week 4, before this error-
analysis pass existed, phrased the way a real employee would ask
(paraphrased, not copied from the contract's wording), and deliberately
includes two "no_answer" controls where the honest answer is "not in the
contract". Reusing it means this sample wasn't cherry-picked after the
fact to make the results look a particular way.

Usage:
    python error_analysis/collect_traces.py

Writes:
    error_analysis/traces.json  — complete structured traces (replayable)
    error_analysis/traces.md    — the same traces, human-readable
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval"))

from dotenv import load_dotenv

from rag_core import load_pdf_chunks, ContractIndex, generate_answer
from questions import QUESTIONS

load_dotenv()

PDF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_contract.pdf")
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces.json")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces.md")
K = 3
RERANK_POOL = 10


def build_trace(q, index, api_key):
    docs = index.search_reranked(q["question"], k=K, pool=RERANK_POOL)
    answer = generate_answer(q["question"], docs, api_key)

    retrieved = [
        {
            "chunk_idx": doc.metadata["chunk_idx"],
            "page": doc.metadata.get("page", 0) + 1,
            "content": doc.page_content,
        }
        for doc in docs
    ]

    return {
        "id": q["id"],
        "question": q["question"],
        "no_answer_expected": bool(q.get("no_answer")),
        "expected_chunks": q.get("expected_chunks", []),
        "answer_keywords": q.get("answer_keywords", []),
        "retrieved": retrieved,
        "answer": answer,
    }


def main():
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("GROQ_API_KEY is not set (add it to .env) — cannot generate real answers.")
        sys.exit(1)

    print(f"Loading + chunking {PDF_PATH} ...")
    chunks = load_pdf_chunks(PDF_PATH)
    print(f"{len(chunks)} chunks (chunk_size=150, chunk_overlap=20)\n")

    print("Building semantic (FAISS) index + loading cross-encoder reranker ...")
    index = ContractIndex(chunks)
    _ = index.reranker
    print("Done.\n")

    traces = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"[{i}/{len(QUESTIONS)}] {q['id']}: {q['question']}")
        traces.append(build_trace(q, index, api_key))

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(traces, f, indent=2, ensure_ascii=False)
    print(f"\n{len(traces)} traces written to {OUT_JSON}")

    write_markdown(traces)
    print(f"Human-readable view written to {OUT_MD}")


def write_markdown(traces):
    lines = ["# Collected Traces — Legal Contract RAG\n"]
    lines.append(
        f"{len(traces)} traces. Each is a real run of the app's live pipeline "
        "(FAISS top-10 -> cross-encoder rerank to top 3 -> Groq `openai/gpt-oss-20b`) "
        "against `data/sample_contract.pdf`, using the question set from `eval/questions.py`.\n"
    )
    for t in traces:
        lines.append(f"## {t['id']}\n")
        lines.append(f"**Question:** {t['question']}\n")
        if t["no_answer_expected"]:
            lines.append("_Control question — the contract does not contain this fact; correct behavior is refusal._\n")
        else:
            lines.append(f"**Expected chunks:** {t['expected_chunks']}  |  **Answer must contain one of:** {t['answer_keywords']}\n")
        lines.append("**Retrieved context:**\n")
        for r in t["retrieved"]:
            lines.append(f"- chunk {r['chunk_idx']} (page {r['page']}): {r['content']!r}")
        lines.append(f"\n**Answer:**\n> {t['answer']}\n")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
