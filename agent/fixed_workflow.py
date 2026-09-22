"""
The "plain fixed sequence" side of the Week 7 race.

This is exactly the pipeline app.py already runs live: one reranked
search (Week 4), one neighbor-stitch context expansion (Week 6), one
generation call. Nothing new is built here on purpose - the point of a
fixed-workflow comparison is to race the agent against what's actually
shipping today, not a strawman rebuilt from scratch.
"""

import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from rag_core import generate_answer


def run_fixed(question, index, api_key):
    start = time.time()
    docs = index.search_reranked(question, k=3, pool=10)
    context_docs = index.expand_with_neighbors(docs)
    answer = generate_answer(question, context_docs, api_key)
    elapsed = time.time() - start

    return {
        "answer": answer,
        "chunk_ids": [d.metadata["chunk_idx"] for d in docs],
        "llm_calls": 1,
        "tool_calls": 1,
        "elapsed": elapsed,
        "transcript": [
            {"step": 1, "tool": "search_contract", "args": {"query": question, "k": 3},
             "result": f"{len(docs)} chunks retrieved: {[d.metadata['chunk_idx'] for d in docs]}"},
            {"step": 2, "tool": "final_answer", "args": {"answer": answer}},
        ],
        "stopped_early": False,
    }
