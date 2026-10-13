# FROZEN COPY of the first-cut clause-search server (Week 9 "before"). Kept only so
# scripts/error_demo.py can replay the SAME failing call against the old docstring and
# error text. Do not edit; the live server is clause_search_server.py.
"""
Week 9 — server one: OUR OWN MCP server. It puts the clause-lookup capability the
Week 7 agent already had (agent/tools.py) behind the standard MCP socket, so any
host — not just our agent — can call it.

Tools   (model-invoked):  search_clauses, get_clause, list_section_headings
Resource (app-attached):  contract://sample/defined-terms

Defined terms are a RESOURCE on purpose. They are context the app should hand the
model alongside every clause, not a lookup the model should have to decide to make;
as a tool the model would spend a step (and sometimes not bother) fetching what it
should simply have been given. See mcp_servers.json -> attach_resources.

There is NO model call in this file. A server exposes a capability; the host runs
the model. If you find yourself importing an LLM client here, the capability is
in the wrong place.

Retrieval here is plain lexical scoring over the contract's clauses, not the
Week 4 FAISS + cross-encoder pipeline: this week tests the protocol, not
retrieval quality, and the MCP surface (tool names, arguments, output shape) is
identical whichever ranker sits behind _rank(). Swap it in there.

stdout belongs to the JSON-RPC stream on stdio — never print() in this file.
"""

import math
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from create_sample_pdf import SECTIONS  # noqa: E402  (single source of truth for the indexed PDF)

mcp = FastMCP("clause-search")

# {1: ("1. POSITION AND DUTIES", "The Employee is hired ..."), ...} — the numbered clauses only.
CLAUSES = {}
for _heading, _body in SECTIONS:
    _m = re.match(r"^(\d+)\.\s", _heading or "")
    if _m:
        CLAUSES[int(_m.group(1))] = (_heading, " ".join(_body.split()))

_STOP = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its my of on or our "
    "that the their there this to was what when where which who will with you your".split()
)


def _terms(text):
    # crude prefix stem so termination / terminate / terminated meet at "termi"
    return [t[:5] for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


_DOCS = {n: (_terms(h), _terms(b)) for n, (h, b) in CLAUSES.items()}
_DF = {}
for _head_terms, _body_terms in _DOCS.values():
    for _t in set(_head_terms) | set(_body_terms):
        _DF[_t] = _DF.get(_t, 0) + 1


def _rank(query, k):
    q = set(_terms(query))
    scored = []
    for n, (head_terms, body_terms) in _DOCS.items():
        score = 0.0
        for t in q:
            idf = math.log((len(_DOCS) + 1) / (_DF.get(t, 0) + 1)) + 1
            score += idf * (3 * head_terms.count(t) + body_terms.count(t))
        if score > 0:
            scored.append((score, n))
    scored.sort(reverse=True)
    return [n for _score, n in scored[:k]]


@mcp.tool()
def search_clauses(query: str, k: int = 3) -> str:
    """Search the contract."""
    hits = _rank(query, max(1, min(5, k)))
    if not hits:
        return "No matching clauses."
    return "\n\n".join(f"[clause {n}] {CLAUSES[n][0]}\n{CLAUSES[n][1]}" for n in hits)


@mcp.tool()
def get_clause(clause_number: str) -> str:
    """Get a clause."""
    try:
        heading, body = CLAUSES[int(clause_number)]
    except (KeyError, ValueError):
        raise ValueError("Error 3")
    return f"{heading}\n{body}"


@mcp.tool()
def list_section_headings() -> str:
    """List the section headings."""
    return "\n".join(h for h, _b in CLAUSES.values())


@mcp.resource("contract://sample/defined-terms")
def defined_terms() -> str:
    """Defined terms of the sample employment agreement (the app attaches this to every prompt)."""
    return (
        '"Agreement" - this Employment Agreement, entered into as of January 1, 2024.\n'
        '"Company" - TechCorp Pvt. Ltd.\n'
        '"Employee" - John Smith.\n'
        '"Confidential Information" - as used in clause 8: business plans, client lists, '
        "financial data, technical documentation, and trade secrets."
    )


if __name__ == "__main__":
    mcp.run()
