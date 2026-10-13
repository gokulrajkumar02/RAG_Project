"""
BONUS — one front door. The agent connects to THIS server only; the gateway fans
out to the real servers listed in mcp_servers.upstream.json, and:

1. Authorizes every tools/call against the scopes of the caller's token
   (tokens.json, default-deny allow-list of "<server>.<tool>" patterns).
2. Writes exactly one audit line per tools/call — allowed or denied — with the
   caller, the tool, and the contract id. Never the token, never the result.
3. Turns a denial into an ordinary tool result (isError=true) whose text tells the
   model WHY and what it can still do, so it can recover instead of guessing.

Why a gateway: the upstream credentials (e.g. CONTRACT_REPO_TOKEN) live in the
gateway's environment, not the agent's. The agent can only do what its gateway
token allows, even if the upstream server's own token is all-powerful.

Tools are listed to every caller, including ones the token cannot call, so a denied
call reaches the model as a message it can reason about. The stricter alternative is
to filter list_tools by scope; then the model never learns the tool exists. Pick per
deployment — this file demonstrates the first.

Fan-out reuses agent_core.host.McpHost (the same client code the agent uses). That
flattens tool output to text; fine for text tools, lossy for images.

GATEWAY_TOKEN       which token this session runs as (required; unknown => refuse to start)
GATEWAY_UPSTREAMS   upstream config   (default: ../mcp_servers.upstream.json)
GATEWAY_TOKENS      token table       (default: ./tokens.json)
GATEWAY_AUDIT_LOG   audit file        (default: ../deliverables/gateway_audit.log)

stdout belongs to the JSON-RPC stream — never print() in this file.
"""

import asyncio
import datetime as dt
import fnmatch
import json
import os
import sys
from contextlib import asynccontextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)

import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from agent_core.host import McpHost  # noqa: E402

UPSTREAMS = os.environ.get("GATEWAY_UPSTREAMS", os.path.join(MCP_AGENT_DIR, "mcp_servers.upstream.json"))
TOKENS = os.environ.get("GATEWAY_TOKENS", os.path.join(HERE, "tokens.json"))
AUDIT_LOG = os.environ.get("GATEWAY_AUDIT_LOG", os.path.join(MCP_AGENT_DIR, "deliverables", "gateway_audit.log"))

STATE = {}


def _load_identity():
    with open(TOKENS, encoding="utf-8") as f:
        table = json.load(f)
    presented = os.environ.get("GATEWAY_TOKEN", "")
    entry = table.get(presented)
    if entry is None:
        sys.exit("contract-gateway: GATEWAY_TOKEN is missing or unknown; refusing to start.")
    return entry["caller"], entry["allow"]


def _allowed(patterns, tool_id):
    return any(fnmatch.fnmatchcase(tool_id, p) for p in patterns)


def _audit(caller, tool_id, contract_id, decision, outcome):
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), "caller": caller,
            "tool": tool_id, "contract_id": contract_id, "decision": decision, "outcome": outcome}
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def _denial_text(caller, tool_id, tools, patterns):
    usable = [t.name for t in tools if _allowed(patterns, f"{t.server}.{t.remote_name}")]
    return (
        f"Denied by the gateway: this session's token ({caller}) is not scoped to call {tool_id}. "
        "This is a permissions limit, NOT a missing record and NOT an outage; retrying will not change it. "
        f"Tools this session can call: {', '.join(usable)}. "
        "If the user needs this, they must ask an administrator for a token that includes it; "
        "until then, answer from what you can reach and say plainly that this check was not permitted."
    )


@asynccontextmanager
async def lifespan(_server):
    async with McpHost(UPSTREAMS, errlog=sys.stderr) as host:
        STATE["host"] = host
        yield STATE


server = Server("contract-gateway", lifespan=lifespan)


@server.list_tools()
async def list_tools():
    return [types.Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            for t in STATE["host"].tools]


@server.call_tool()
async def call_tool(name, arguments):
    host, caller, patterns = STATE["host"], STATE["caller"], STATE["patterns"]
    tool = next((t for t in host.tools if t.name == name), None)
    contract_id = (arguments or {}).get("contract_id")
    if tool is None:
        _audit(caller, name, contract_id, "deny", "unknown_tool")
        return types.CallToolResult(isError=True, content=[types.TextContent(
            type="text", text=f"Unknown tool '{name}'.")])
    tool_id = f"{tool.server}.{tool.remote_name}"
    if not _allowed(patterns, tool_id):
        _audit(caller, tool_id, contract_id, "deny", "denied")
        return types.CallToolResult(isError=True, content=[types.TextContent(
            type="text", text=_denial_text(caller, tool_id, host.tools, patterns))])
    outcome = await host.call_tool(name, arguments or {})
    _audit(caller, tool_id, contract_id, "allow", "tool_error" if outcome.is_error else "ok")
    return types.CallToolResult(isError=outcome.is_error, content=[types.TextContent(type="text", text=outcome.text)])


@server.list_resources()
async def list_resources():
    return [types.Resource(uri=a.uri, name=a.uri) for a in STATE["host"].attached]


@server.read_resource()
async def read_resource(uri):
    for a in STATE["host"].attached:
        if a.uri == str(uri):
            return a.text
    raise ValueError(f"No attached resource {uri}")


async def main():
    STATE["caller"], STATE["patterns"] = _load_identity()  # fail closed before serving anything
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
