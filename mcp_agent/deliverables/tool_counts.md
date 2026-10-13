# Tools discovered over MCP (`tools/list`)

**3 before -> 6 after** — new: `get_contract`, `get_effective_date`, `get_amendment_chain`

### BEFORE — `mcp_servers.before.json`: 3 tool(s) from 1 server(s)

- **clause-search** (3; initialize -> protocolVersion 2025-11-25): `search_clauses`, `get_clause`, `list_section_headings`

### AFTER — `mcp_servers.json`: 6 tool(s) from 2 server(s)

- **clause-search** (3; initialize -> protocolVersion 2025-11-25): `search_clauses`, `get_clause`, `list_section_headings`
- **contract-repository** (3; initialize -> protocolVersion 2025-11-25): `get_contract`, `get_effective_date`, `get_amendment_chain`

Counted from each server's own `tools/list` response (`McpHost.tools` is filled only from `session.list_tools()`); the agent code that did the counting is byte-identical in both runs (see agent_diff.txt).
