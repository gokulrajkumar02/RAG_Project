"""
Log schema w11.2: an index on the OUTPUT, computed when the trace is written.

Drill #1 showed what w11.1 was missing. It stored every answer, but only as text, so "it cited the wrong clause"
could only be answered by a person reading every termination answer of the day against the contract (76 rows).
These fields make that a filter:

  answer_cited_clauses   clauses the answer cites (citations.py - the same parser the eval suite uses)
  context_clause_ids     clauses whose TEXT the model actually read, from the logged context chunk ids and the
                         ingest-time clause map. Only possible because context ids were logged in the first
                         place: old traces are backfilled from them (reindex.py), nothing is re-run.
  citation_support       for each clause in the context, how many of the answer's content words come from it
  citation_mismatch      true when the answer cites a clause whose text was not in the context, or when its
                         wording comes clearly from a clause it did not cite (best clause has >= 3 shared words
                         and >= 2 more than any cited clause)

citation_mismatch is a heuristic flag for search, not a verdict: it ranks which answers a person reads first.
Its false positives on the logged week are measured and printed by reindex.py.
"""

import re

from citations import cited_clauses

SCHEMA = "w11.2"
STOP = {
    "this", "that", "with", "from", "shall", "which", "there", "their", "under", "have", "does", "been", "will",
    "would", "could", "should", "also", "such", "other", "into", "upon", "only", "than", "then", "them", "they",
    "what", "when", "where", "your", "yours", "about", "after", "before", "each", "every", "must", "here",
    "compa", "emplo", "agree", "claus", "contr", "secti", "techc", "smith", "john",
}
MIN_BEST, MIN_GAP = 3, 2
# a citation and the clause title that goes with it: "Clause 7 (Termination)", "Clause 7 - Termination"
CITE_SPAN = re.compile(r"\b(?:clauses?|sections?|cl\.|§)\s*\d{1,2}(?:\.\d+)*"
                       r"(?:\s*\([^)]*\)|\s*-\s*[A-Za-z][A-Za-z ]*)?", re.I)


def stems(text):
    """Content words as 5-letter prefixes ('terminate'/'termination' -> 'termi'), generic contract words dropped."""
    out = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if len(w) >= 4 and w not in STOP and w[:5] not in STOP:
            out.add(w[:5])
    return out


def derive(answer, context_chunk_ids, clause_map):
    valid = set(clause_map.numbered())
    cited = cited_clauses(answer, valid=valid)
    in_context = [c for c in clause_map.clauses_for(context_chunk_ids) if c.isdigit()]
    words = stems(CITE_SPAN.sub(" ", answer or ""))
    support = {}
    for c in in_context:
        text = clause_map.clause_text(c, context_chunk_ids)
        support[c] = len(words & stems(text))
    mismatch = False
    if cited:
        if any(c not in in_context for c in cited):
            mismatch = True
        elif support:
            best = max(support, key=lambda c: support[c])
            best_cited = max(support.get(c, 0) for c in cited)
            mismatch = best not in cited and support[best] >= MIN_BEST and support[best] - best_cited >= MIN_GAP
    return {
        "answer_cited_clauses": cited,
        "context_clause_ids": in_context,
        "citation_support": support,
        "citation_mismatch": mismatch,
    }
