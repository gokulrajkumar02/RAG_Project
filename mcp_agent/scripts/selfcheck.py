"""
One command that re-verifies the claims this exercise makes, each against the brief's
"common mistakes" list:

    python mcp_agent/scripts/selfcheck.py

 1. discovery is real        - tool counts come back 3 -> 6 from tools/list
 2. no hard-coded tools      - no discovered tool name appears in agent_core/ source
 3. agent unchanged          - agent_core/ hashes equal the ones recorded before server two was added
 4. no model in a server     - no LLM client imported by any server or the gateway
 5. defined terms = resource - served via resources/list, and no tool is named for it
 6. errors tell causes apart - predates-the-contract vs bad id vs infrastructure failure read differently
 7. risk note                - exactly 5 non-empty lines

Exits non-zero if anything fails. Needs no API key.
"""

import asyncio
import hashlib
import os
import re
import sys
import tempfile
import json

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)

from agent_core.host import McpHost  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def read(path):
    with open(os.path.join(MCP_AGENT_DIR, path), encoding="utf-8") as f:
        return f.read()


async def quiet_host(config):
    return McpHost(config, errlog=open(os.devnull, "w"))


async def main():
    before_cfg = os.path.join(MCP_AGENT_DIR, "mcp_servers.before.json")
    after_cfg = os.path.join(MCP_AGENT_DIR, "mcp_servers.json")

    async with await quiet_host(before_cfg) as h1:
        n_before = len(h1.tools)
    async with await quiet_host(after_cfg) as h2:
        names = [t.name for t in h2.tools]
        check("1. discovery is real (tools/list)", (n_before, len(names)) == (3, 6) and not h2.failed,
              f"{n_before} before -> {len(names)} after: {', '.join(names)}")

        src = "\n".join(read(f"agent_core/{f}") for f in os.listdir(os.path.join(MCP_AGENT_DIR, "agent_core"))
                       if f.endswith(".py"))
        leaked = [n for n in names if re.search(rf"\b{re.escape(n)}\b", src)]
        check("2. no discovered tool name hard-coded in agent_core/", not leaked, f"found: {leaked}" if leaked else "")

        outcome = await h2.call_tool("get_effective_date", {"contract_id": "MSA-2021-0142", "as_of": "2020-12-31"})
        bad_id = await h2.call_tool("get_contract", {"contract_id": "MSA-2021-142"})
        check("6a. 'date predates the contract' vs 'no such id' read differently",
              "predates the contract" in outcome.text and "No contract with id" in bad_id.text
              and "predates" not in bad_id.text)

    manifest = {}
    for line in read("deliverables/agent_core.sha256.before").splitlines():
        digest, fname = line.split(None, 1)
        manifest[fname.strip().lstrip("*")] = digest
    now = {f: hashlib.sha256(open(os.path.join(MCP_AGENT_DIR, "agent_core", f), "rb").read()).hexdigest()
           for f in manifest}
    check("3. agent_core/ unchanged since before server two", now == manifest,
          f"{len(manifest)} files hashed")

    offenders = []
    for folder in ("servers", "third_party", "gateway"):
        for f in os.listdir(os.path.join(MCP_AGENT_DIR, folder)):
            if f.endswith(".py"):
                body = read(f"{folder}/{f}")
                if re.search(r"^\s*(from|import)\s+(langchain\w*|groq|openai|anthropic)\b", body, re.M):
                    offenders.append(f"{folder}/{f}")
    check("4. no LLM client imported by any server or the gateway", not offenders, str(offenders) if offenders else "")

    async with await quiet_host(before_cfg) as h:
        uris = [a.uri for a in h.attached]
        terms_tools = [t.name for t in h.tools if "term" in t.name or "defin" in t.name]
        check("5. defined terms are an app-attached resource, not a tool",
              uris == ["contract://sample/defined-terms"] and not terms_tools,
              f"attached: {uris}; tools named for it: {terms_tools}")

    # 6b: an infrastructure failure must not read like a missing record
    with tempfile.TemporaryDirectory() as tmp:
        srv = os.path.join(tmp, "dies.py")
        with open(srv, "w") as f:
            f.write("import os\nfrom mcp.server.fastmcp import FastMCP\nm = FastMCP('d')\n"
                    "@m.tool()\ndef boom() -> str:\n    '''die'''\n    os._exit(1)\nm.run()\n")
        cfg = os.path.join(tmp, "c.json")
        with open(cfg, "w") as f:
            json.dump({"mcpServers": {"d": {"command": "${PYTHON}", "args": [srv]}}}, f)
        async with await quiet_host(cfg) as h:
            o = await h.call_tool("boom", {})
        check("6b. a dead server is reported as infrastructure, not as 'not found'",
              o.is_error and "infrastructure failure" in o.text and "not found" not in o.text.lower())

    lines = read("deliverables/risk_note.md").split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    check("7. risk_note.md is exactly 5 non-empty lines", len(nonempty) == 5 and len(lines) in (5, 6),
          f"{len(nonempty)} lines")

    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    if not all(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
