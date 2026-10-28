"""
Versioned answer prompts. Every trace records the version that answered it (prompt_version) and a sha of
the exact template text (prompt_sha), so "which prompt said this?" is a log lookup, not a guess, and a
rollback is a config change (config.json), not a deploy.

A version is the template AND the way the retrieved context is laid out for it (context_format), because
both decide what the model reads. Never edit a released version in place: add the next one, record why,
and route traffic to it through config.json.
"""

import hashlib
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from rag_core import ANSWER_PROMPT  # noqa: E402  (the prompt the app has served since Week 4)

ANSWER_V2 = """You are a legal contract assistant.
Answer the question using ONLY the contract context provided below.
If the answer is not in the context, respond with:
"This information was not found in the contract."
Be clear and concise.
Cite the clause you relied on by its number, e.g. "(Clause 4)".

Contract Context:
{context}

Question: {question}

Answer:"""

ANSWER_V3 = """You are a legal contract assistant.
Answer the question using ONLY the contract context provided below.
If the answer is not in the context, respond with:
"This information was not found in the contract."
Be clear and concise.

The context is made of whole clauses. Each clause starts with a label in square brackets, for example
[Clause 7 - TERMINATION]. Cite the clause your answer relies on as "(Clause 7 - Termination)", taking the
number ONLY from the label of the clause the supporting text sits under. If the answer relies on more than
one clause, cite each one.

Contract Context:
{context}

Question: {question}

Answer:"""

PROMPTS = {
    "answer-v1": {
        "template": ANSWER_PROMPT,
        "context_format": "plain",
        "cites": False,
        "introduced": "Week 4 (rag_core.ANSWER_PROMPT, unchanged through Week 10)",
        "change": "baseline",
    },
    "answer-v2": {
        "template": ANSWER_V2,
        "context_format": "plain",
        "cites": True,
        "introduced": "2026-10-21 11:00 IST as a 20% canary; 100% from 2026-10-22 10:00 IST",
        "change": "asks the model to cite the clause number it relied on (the legal team asked for citations)",
    },
    "answer-v3": {
        "template": ANSWER_V3,
        "context_format": "clause",
        "cites": True,
        "introduced": "2026-10-28, as a 10% canary (config.json)",
        "change": "fix for drill #1 / eval case reg_termination_cites_notice_clause. Retrieval layer: every clause "
                  "the retrieved chunks touch is served whole, labelled [Clause N - TITLE] from the ingest-time "
                  "clause map, without the next clause's trailing heading. Prompt layer: cite only from labels.",
    },
}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def get(version):
    if version not in PROMPTS:
        raise KeyError(f"unknown prompt version {version!r}; known: {sorted(PROMPTS)}")
    spec = dict(PROMPTS[version])
    spec["version"] = version
    spec["sha"] = sha(spec["template"] + "|" + spec["context_format"])
    return spec


def render_context(docs, context_format, clause_map=None):
    if context_format == "plain":
        # byte-identical to rag_core.generate_answer's context assembly
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    if context_format == "clause":
        # docs come from pipeline's retrieval.expand_clauses: whole clauses, grouped, in clause order
        ids = [doc.metadata["chunk_idx"] for doc in docs]
        _ids, order = clause_map.expand_to_clauses(ids)
        return "\n\n---\n\n".join(f"[{clause_map.label(c)}]\n{clause_map.clause_text(c, ids)}" for c in order)
    raise ValueError(f"unknown context format {context_format!r}")
