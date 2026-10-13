"""
Requirement 1 — run ONE query that provably calls a tool from server two, and show
the tool name in the trace. Also the bonus demo (--config mcp_servers.gateway.json).

    python mcp_agent/scripts/demo_query.py "Which amendments changed MSA-2021-0142?"
    python mcp_agent/scripts/demo_query.py --llm stub "..."          # no API key needed
    python mcp_agent/scripts/demo_query.py --config mcp_agent/mcp_servers.gateway.json --out gateway_trace.md "..."

--llm auto (default): the real Groq model if GROQ_API_KEY is set, otherwise the
deterministic STUB from offline_llm.py — and every output says which one ran.

"Provably": besides the host's trace, this captures the server's own stderr log. The
line that server two printed when it received the call is independent evidence the
tools/call crossed MCP to it.
"""

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)
sys.path.insert(0, HERE)

from agent_core.host import McpHost  # noqa: E402
from agent_core.loop import REPO_ROOT, MAX_STEPS, groq_llm, run_agent  # noqa: E402
from offline_llm import stub_llm  # noqa: E402

DEFAULT_QUESTION = "Which amendments changed MSA-2021-0142, and when did the latest one take effect?"


def pick_llm(choice):
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    except ImportError:
        pass
    key = os.environ.get("GROQ_API_KEY")
    if choice == "groq" or (choice == "auto" and key):
        if not key:
            sys.exit("--llm groq needs GROQ_API_KEY (environment or .env).")
        return groq_llm(key), "REAL MODEL: Groq openai/gpt-oss-120b"
    return stub_llm, ("STUB — deterministic rule-based stand-in, NOT a language model (no GROQ_API_KEY in this "
                      "run). The MCP traffic below is real; the choice of tool and the answer text are the stub's.")


def render_trace(result):
    out = []
    for t in result["transcript"]:
        where = f"  -> server `{t['server']}`" if t.get("server") else ""
        out.append(f"**step {t['step']}** `{t.get('tool') or '(no valid action)'}({json.dumps(t.get('args', {}))})`{where}")
        if t.get("thought"):
            out.append(f"- thought: {t['thought']}")
        for r in t.get("repairs", []):
            out.append(f"- repair: {r}")
        res = str(t.get("result", ""))
        out.append("- result:\n\n```\n" + (res if len(res) <= 900 else res[:900] + "\n... (truncated)") + "\n```")
        out.append("")
    return "\n".join(out)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    p.add_argument("--config", default=os.path.join(MCP_AGENT_DIR, "mcp_servers.json"))
    p.add_argument("--llm", choices=["auto", "stub", "groq"], default="auto")
    p.add_argument("--out", default="query_trace.md", help="file name inside deliverables/")
    args = p.parse_args()

    llm, llm_label = pick_llm(args.llm)
    out_dir = os.path.join(MCP_AGENT_DIR, "deliverables")
    os.makedirs(out_dir, exist_ok=True)
    stderr_path = os.path.join(out_dir, os.path.splitext(args.out)[0] + ".server_stderr.log")
    with open(stderr_path, "w", encoding="utf-8") as errlog:
        async with McpHost(args.config, errlog=errlog) as host:
            discovered = [(t.server, t.name) for t in host.tools]
            failed = dict(host.failed)
            result = await run_agent(args.question, host, llm)

    with open(stderr_path, encoding="utf-8") as f:
        server_lines = [ln.rstrip() for ln in f if '"tool"' in ln]

    md = [
        "# Query run — which MCP server answered",
        "",
        f"- **Model:** {llm_label}",
        f"- **Config:** `{os.path.basename(args.config)}`",
        f"- **Question:** {args.question}",
        f"- **Tools called (server.tool):** {', '.join(f'`{c}`' for c in result['tools_called']) or 'none'}",
        "",
        f"## tools/list at start-up ({len(discovered)} tools)",
        "",
        *[f"- `{n}` — server `{s}`" for s, n in discovered],
        *([f"- UNAVAILABLE server `{s}`: {why}" for s, why in failed.items()] if failed else []),
        "",
        "## Trace",
        "",
        render_trace(result),
        "## Evidence from the server's side",
        "",
        "Lines the server wrote to its own stderr when it received a call (the host did not write these):",
        "",
        "```",
        *(server_lines or ["(none — this config's servers do not log calls)"]),
        "```",
        "",
        "## Answer",
        "",
        result["answer"],
        "",
        f"({result['tool_calls']} tool call(s), {result['llm_calls']} model call(s), {result['elapsed']:.1f}s)",
        "",
    ]
    path = os.path.join(out_dir, args.out)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md))
    print(f"[wrote {path}]")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
