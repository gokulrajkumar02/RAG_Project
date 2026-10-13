"""
Requirement 3 — how many tools did the agent discover before and after adding server
two, with names, taken from tools/list (not from anyone's notes).

    python mcp_agent/scripts/discover.py

Connects the SAME agent_core.McpHost to mcp_servers.before.json (server one only) and
mcp_servers.json (server one + two). McpHost.tools is populated only from each
server's own `tools/list` answer, so these are the servers' counts, not ours.
Writes deliverables/tool_counts.md.
"""

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)

from agent_core.host import McpHost  # noqa: E402

BEFORE = os.path.join(MCP_AGENT_DIR, "mcp_servers.before.json")
AFTER = os.path.join(MCP_AGENT_DIR, "mcp_servers.json")
OUT = os.path.join(MCP_AGENT_DIR, "deliverables", "tool_counts.md")


async def discover(config):
    with open(os.devnull, "w") as quiet:
        async with McpHost(config, errlog=quiet) as host:
            assert not host.failed, host.failed
            by_server = {}
            for t in host.tools:
                by_server.setdefault(t.server, []).append(t.name)
            return by_server, host.server_info


def section(title, config, by_server, info):
    total = sum(len(v) for v in by_server.values())
    lines = [f"### {title} — `{os.path.basename(config)}`: {total} tool(s) from {len(by_server)} server(s)", ""]
    for server, names in by_server.items():
        i = info[server]
        lines.append(f"- **{server}** ({len(names)}; initialize -> protocolVersion {i['protocolVersion']}): "
                     + ", ".join(f"`{n}`" for n in names))
    return total, "\n".join(lines)


def main():
    b_servers, b_info = asyncio.run(discover(BEFORE))
    a_servers, a_info = asyncio.run(discover(AFTER))
    b_total, b_text = section("BEFORE", BEFORE, b_servers, b_info)
    a_total, a_text = section("AFTER", AFTER, a_servers, a_info)
    before_names = {n for v in b_servers.values() for n in v}
    new = [n for v in a_servers.values() for n in v if n not in before_names]

    headline = f"**{b_total} before -> {a_total} after**"
    body = "\n".join([
        "# Tools discovered over MCP (`tools/list`)",
        "",
        headline + " — new: " + ", ".join(f"`{n}`" for n in new),
        "",
        b_text,
        "",
        a_text,
        "",
        "Counted from each server's own `tools/list` response (`McpHost.tools` is filled only "
        "from `session.list_tools()`); the agent code that did the counting is byte-identical in both runs "
        "(see agent_diff.txt).",
        "",
    ])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(body)
    print(body)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
