"""
Tools available to the hand-built contract agent (contract_agent.py).

Two real lookup tools, deliberately different in kind:

- search_contract: the exact retrieval the fixed pipeline already uses in
  production — reranked FAISS search (Week 4) + neighbor-stitch context
  expansion (Week 6). Reusing it rather than writing a second retrieval
  path means the race in race.py isolates ONE variable: whether looping
  and retrying helps, not whether the agent has a better single search.

- list_section_headings: the contract's own numbered section headings,
  read from create_sample_pdf.py's SECTIONS list — the single source of
  truth for what's actually in the indexed PDF, not a regex guess over
  chunked/re-flowed text. This is the agent's recovery tool: Week 4 found
  that a colloquially-phrased question ("how much heads-up do I need to
  give?") can miss the right chunk entirely, while the contract's own
  wording ("notice period") would not. An agent that discovers the real
  heading can retry search_contract with the contract's own words instead
  of the user's paraphrase.

final_answer is not a lookup — it's the agent's terminal action, handled
directly in contract_agent.py's loop.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def search_contract(index, query, k=3):
    query = (query or "").strip()
    if not query:
        return "search_contract needs a non-empty query."
    docs = index.search_reranked(query, k=k, pool=10)
    docs = index.expand_with_neighbors(docs)
    if not docs:
        return "No matching chunks found."
    lines = [f"[chunk {d.metadata['chunk_idx']}] {d.page_content}" for d in docs]
    return "\n\n".join(lines)


def list_section_headings():
    from create_sample_pdf import SECTIONS

    headings = [heading for heading, _body in SECTIONS if heading]
    return "\n".join(headings)
