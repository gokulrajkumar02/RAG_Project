"""
Run the Week 9 MCP agent on one question.

    python mcp_agent/agent_core/run.py "Which amendments changed MSA-2021-0142?"
    python mcp_agent/agent_core/run.py --config mcp_agent/mcp_servers.json --json "..."

Needs GROQ_API_KEY (environment or .env). Prints what tools/list returned, then
every step of the trace with the server each tool call went to, then the answer.
"""

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)

from agent_core.host import McpHost  # noqa: E402
from agent_core.loop import REPO_ROOT, groq_llm, run_agent  # noqa: E402


def print_discovery(host):
    print(f"tools/list discovered {len(host.tools)} tool(s) from {len(host.server_info)} server(s):")
    for t in host.tools:
        print(f"  - {t.name}  [{t.server}]")
    for name, why in host.failed.items():
        print(f"  ! server '{name}' unavailable: {why}")


def print_trace(result):
    for t in result["transcript"]:
        where = f" -> server '{t['server']}'" if t.get("server") else ""
        print(f"\nstep {t['step']}: {t.get('tool') or '(no valid action)'}({json.dumps(t.get('args', {}))}){where}")
        if t.get("thought"):
            print(f"  thought: {t['thought']}")
        for r in t.get("repairs", []):
            print(f"  repair: {r}")
        out = str(t.get("result", ""))
        print("  result: " + (out if len(out) <= 600 else out[:600] + " ..."))


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--config", default=os.path.join(MCP_AGENT_DIR, "mcp_servers.json"))
    parser.add_argument("--json", action="store_true", help="print the full result as JSON instead")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    except ImportError:
        pass
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        sys.exit("GROQ_API_KEY is not set (put it in .env or the environment).")

    async with McpHost(args.config) as host:
        if not args.json:
            print_discovery(host)
        result = await run_agent(args.question, host, groq_llm(api_key))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print_trace(result)
    print(f"\nANSWER: {result['answer']}")
    print(f"\n({result['tool_calls']} tool call(s): {', '.join(result['tools_called']) or 'none'}; "
          f"{result['llm_calls']} model call(s); {result['elapsed']:.1f}s)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
