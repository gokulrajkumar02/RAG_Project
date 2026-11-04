"""
OUR MCP server: the amendment-aware contract lookup. One server, used two ways:
  * CONSUMED by our own agent (agent discovers its tools from tools/list at runtime; mcp_servers.json)
  * EXPOSED to any outside MCP client:      python capstone/server.py        (stdio)

What a client we do not control gets (the privilege line):
  * every call names ONE customer; there is no cross-customer search
  * text comes from the REDACTED registry (no signatory names, e-mails, phones, addresses), clipped
  * every clause hit carries its amendment-chain status, and a superseded hit carries `in_force_now`, so a client with
    no chain logic of its own still cannot quote clause 11.3 when Amendment No.2 replaced it
  * the privileged fallback playbook is not a tool here
  * the trace id sent in the request's _meta is echoed back with this call's spans, and logged to logs/servers/
    (tool, argument NAMES, counterparty, sizes, spans - never text)

Which tools exist depends on the variant (config.json): v0-naive has 3, v1-guarded has 6. No model call lives here.
stdout belongs to the JSON-RPC stream on stdio - never print() in this file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contractdesk  # noqa: E402,F401  (puts the repo root and capstone/ on sys.path)

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.types import CallToolResult  # noqa: E402

from contractdesk.index import CorpusIndex  # noqa: E402
from contractdesk.toolkit import Toolkit, dumps  # noqa: E402
from contractdesk.tracex import ServerCall  # noqa: E402

SERVER = "contract-desk"


def build():
    kit = Toolkit(index=CorpusIndex.load())
    kit.index.warm()          # load the cross-encoder now, so no caller's first request pays for it
    mcp = FastMCP(SERVER, instructions="Executed customer contracts. Every call names one customer. Quote only what is IN_FORCE.")
    tools = kit.vcfg["tools"]

    def run(tool, ctx, args, fn):
        call = ServerCall(SERVER, tool, ctx, args, variant=kit.variant)
        with call.handler():
            out = fn(call)
        if not call.counterparty and isinstance(out, dict):
            call.counterparty = out.get("counterparty")
        return call.finish(dumps(out), ok="error" not in out)

    if "lookup_contract" in tools:
        @mcp.tool()
        def lookup_contract(counterparty: str, ctx: Context) -> CallToolResult:
            """List the documents on file for ONE customer: MSA, each SOW, each amendment, with effective dates and how
            each was read (text layer, or scanned and read by OCR). counterparty is the customer's name ("Halcyon
            Freight"). If it matches two customers the call fails with the candidates: ask which one. Call this first."""
            return run("lookup_contract", ctx, dict(counterparty=counterparty), lambda c: kit.lookup_contract(counterparty))

    if "resolve_amendment_chain" in tools:
        @mcp.tool()
        def resolve_amendment_chain(counterparty: str, clause: str, ctx: Context) -> CallToolResult:
            """Find which document's version of a clause is IN FORCE for one customer today: walks MSA -> SOWs ->
            amendments by the MSA's precedence clause (1.4) and returns every link with its status.
            clause: an MSA clause number ("11.3" liability cap, "14.2" termination for convenience, "5.2" payment,
            "18.1" governing law), "def:Affiliate" for a defined term, or a short subject ("liability cap").
            ALWAYS call this before quoting a clause: the base MSA is frequently NOT the operative text.
            Statuses: IN_FORCE, SUPERSEDED, NOT_YET_IN_FORCE, NOT_PREVAILING (an SOW term that loses to the MSA),
            UNAPPLIED. If resolution is `uncertain`, do not state the clause as in force; refer to counsel."""
            return run("resolve_amendment_chain", ctx, dict(counterparty=counterparty, clause=clause),
                       lambda c: kit.resolve_amendment_chain(counterparty, clause))

    if "resolve_defined_term" in tools:
        @mcp.tool()
        def resolve_defined_term(counterparty: str, term: str, ctx: Context) -> CallToolResult:
            """What a capitalised term means in THIS customer's contract (Definitions Schedule plus any amendment that
            redefined it). A defined term means what its definition says, not its ordinary meaning: "Affiliate" here is
            not "any related company". Call it for every defined term the question or the clause you quote depends on
            (Affiliate, Excluded Claims, Confidential Information, Losses, Business Day, Control, Authorised Users)."""
            return run("resolve_defined_term", ctx, dict(counterparty=counterparty, term=term),
                       lambda c: kit.resolve_defined_term(counterparty, term))

    if "get_governing_law" in tools:
        @mcp.tool()
        def get_governing_law(counterparty: str, ctx: Context) -> CallToolResult:
            """Governing law and venue for one customer (Legal Operations table) plus the text of MSA clause 18.1."""
            return run("get_governing_law", ctx, dict(counterparty=counterparty), lambda c: kit.get_governing_law(counterparty))

    if "search_clauses" in tools:
        @mcp.tool()
        def search_clauses(counterparty: str, query: str, ctx: Context, k: int = 4, document_type: str = "any") -> CallToolResult:
            """Search ONE customer's executed documents (MSA, SOWs, amendments) for the clauses best matching a query.
            counterparty is required (no cross-customer search). query: a short contract-style phrase. document_type:
            "any" (default), "msa", "sow" or "amendment". Results are whole clauses with document, clause number,
            effective date and page. When status marks are on, each is IN_FORCE / SUPERSEDED / NOT_YET_IN_FORCE /
            NOT_PREVAILING, and a SUPERSEDED hit carries `in_force_now`: quote that one."""
            return run("search_clauses", ctx, dict(counterparty=counterparty, query=query, k=k, document_type=document_type),
                       lambda c: kit.search_clauses(counterparty, query, k, document_type, call=c))

    if "get_clause" in tools:
        @mcp.tool()
        def get_clause(counterparty: str, document: str, clause: str, ctx: Context) -> CallToolResult:
            """Exact text of ONE clause of ONE document of ONE customer. document: "msa", "sow-1", "amendment-2" (or a
            full doc id from a result). clause: the number as printed ("11.3"; amendments and SOWs number paragraphs
            "1", "2", ...)."""
            return run("get_clause", ctx, dict(counterparty=counterparty, document=document, clause=clause),
                       lambda c: kit.get_clause(counterparty, document, clause, call=c))

    return mcp


if __name__ == "__main__":
    build().run("stdio")
