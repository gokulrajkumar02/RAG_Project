"""
STAND-IN for the knowledge team's contract-repository MCP server.

The real server was not available when this exercise was built (no URL, no
credentials, no source), so this file imitates its documented surface — lookup by
contract id, effective date, and amendment chain — over SYNTHETIC records. Nothing
in CONTRACTS is real contract data. It exists so the host can be proven against a
server it has no code for. When the real server is reachable, replace this entry in
mcp_servers.json with its command or url; no agent code changes, which is the claim
this exercise tests.

Behaviours chosen to match what the brief says about the real one:
- It is someone else's code, run inside our trust boundary with one shared token.
- That token reads EVERY record, including ones marked NDA (see NDA-2023-0077). The
  server does not scope reads by caller; nothing below the token check does.
- It logs every call (tool + arguments) to stderr as JSON lines. A host that
  inherits stderr — ours does — therefore writes contract ids into its own logs.

Run it:  python contract_repo_server.py                      (stdio, what the agent uses)
         python contract_repo_server.py --transport http     (127.0.0.1:8765, bearer token)

stdout belongs to the JSON-RPC stream on stdio — never print() in this file.
"""

import argparse
import datetime as dt
import hmac
import json
import os
import sys
import time

from mcp.server.fastmcp import FastMCP

EXPECTED_TOKEN = os.environ.get("CONTRACT_REPO_EXPECTED_TOKEN", "demo-token-not-a-secret")

mcp = FastMCP("contract-repository", host="127.0.0.1", port=8765)

CONTRACTS = {
    "MSA-2021-0142": {
        "title": "Master Services Agreement",
        "parties": ["TechCorp Pvt. Ltd.", "Meridian Logistics Ltd."],
        "status": "executed",
        "executed_on": "2021-03-15",
        "confidentiality": "standard",
        "versions": [
            {"label": "Original", "effective_date": "2021-04-01", "clauses": "1-9",
             "summary": "Base agreement."},
            {"label": "Amendment 1", "effective_date": "2022-01-01", "clauses": "1-9",
             "summary": "Clause 4 (fees): annual uplift raised from 4% to 6%."},
            {"label": "Amendment 2", "effective_date": "2023-06-01", "clauses": "1-11",
             "summary": "Adds clause 10 (data protection) and clause 11 (subcontracting)."},
        ],
    },
    "EMP-2024-0001": {
        "title": "Employment Agreement",
        "parties": ["TechCorp Pvt. Ltd.", "John Smith"],
        "status": "executed",
        "executed_on": "2023-12-20",
        "confidentiality": "standard",
        "versions": [
            {"label": "Original", "effective_date": "2024-01-01", "clauses": "1-11",
             "summary": "Base agreement. No amendments on file."},
        ],
    },
    "NDA-2023-0077": {
        "title": "Mutual Non-Disclosure Agreement (Project Falcon)",
        "parties": ["TechCorp Pvt. Ltd.", "Falcon Holdings (counterparty name restricted)"],
        "status": "executed",
        "executed_on": "2023-09-08",
        "confidentiality": "NDA",
        "versions": [
            {"label": "Original", "effective_date": "2023-09-12", "clauses": "1-7",
             "summary": "Covers pre-acquisition diligence; terms restricted to named signatories."},
        ],
    },
}


def _log(tool, args):
    print(json.dumps({"ts": round(time.time(), 3), "server": "contract-repository",
                      "tool": tool, "args": args}), file=sys.stderr, flush=True)


def _find(contract_id):
    record = CONTRACTS.get(contract_id)
    if record is None:
        raise ValueError(f"No contract with id '{contract_id}'. Ids look like 'MSA-2021-0142'.")
    return record


@mcp.tool()
def get_contract(contract_id: str) -> str:
    """Look up a contract by id and return its record: title, parties, status, execution date,
    confidentiality class, original effective date, and how many amendments are on file."""
    _log("get_contract", {"contract_id": contract_id})
    r = _find(contract_id)
    return json.dumps({
        "contract_id": contract_id,
        "title": r["title"],
        "parties": r["parties"],
        "status": r["status"],
        "executed_on": r["executed_on"],
        "confidentiality": r["confidentiality"],
        "original_effective_date": r["versions"][0]["effective_date"],
        "amendments_on_file": len(r["versions"]) - 1,
        "latest_version": r["versions"][-1]["label"],
    }, indent=2)


@mcp.tool()
def get_effective_date(contract_id: str, as_of: str | None = None) -> str:
    """Return the effective date of a contract. With no `as_of`, returns the original effective
    date and the latest version's. With `as_of` (YYYY-MM-DD), returns the version in force on
    that date."""
    _log("get_effective_date", {"contract_id": contract_id, "as_of": as_of})
    r = _find(contract_id)
    original = r["versions"][0]["effective_date"]
    if as_of is None:
        return json.dumps({"contract_id": contract_id, "original_effective_date": original,
                           "latest_version": r["versions"][-1]}, indent=2)
    try:
        day = dt.date.fromisoformat(as_of)
    except ValueError:
        raise ValueError(f"as_of must be a date in YYYY-MM-DD form, got '{as_of}'.")
    if day < dt.date.fromisoformat(original):
        raise ValueError(f"No version of {contract_id} was in force on {as_of}: the original took "
                         f"effect on {original}, so that date predates the contract.")
    in_force = [v for v in r["versions"] if dt.date.fromisoformat(v["effective_date"]) <= day][-1]
    return json.dumps({"contract_id": contract_id, "as_of": as_of, "version_in_force": in_force}, indent=2)


@mcp.tool()
def get_amendment_chain(contract_id: str) -> str:
    """Return a contract's amendment chain in order: the original, then each amendment with its
    effective date, the clause range after it, and a one-line summary of what it changed."""
    _log("get_amendment_chain", {"contract_id": contract_id})
    r = _find(contract_id)
    return json.dumps({"contract_id": contract_id, "chain": r["versions"]}, indent=2)


class _BearerAuth:
    """Pure-ASGI bearer check for the HTTP transport (stdio has no per-request credentials)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope["headers"]).get(b"authorization", b"").decode()
            if not hmac.compare_digest(supplied, f"Bearer {EXPECTED_TOKEN}"):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"missing or invalid bearer token"})
                return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    supplied = os.environ.get("CONTRACT_REPO_TOKEN", "")
    if args.transport == "stdio":
        if not hmac.compare_digest(supplied, EXPECTED_TOKEN):
            sys.exit("contract-repository: CONTRACT_REPO_TOKEN missing or wrong; refusing to start.")
        mcp.run()
    else:
        import uvicorn

        app = mcp.streamable_http_app()
        app.add_middleware(_BearerAuth)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
