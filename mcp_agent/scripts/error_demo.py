"""
Requirement 5 — the same failing call, old docstring/error vs new, with the model's
handling of it recorded.

    python mcp_agent/scripts/error_demo.py                 # real model if GROQ_API_KEY is set, else STUB
    python mcp_agent/scripts/error_demo.py --llm groq --runs 3

Both variants run the SAME agent_core with the SAME question and a harness-forced first
call get_clause("12.4"), so the only thing that differs is what the server says:
  before = servers/clause_search_server_v1_before.py   ("Get a clause." / "Error 3")
  after  = servers/clause_search_server.py             (docstring written as a prompt / recoverable error)

For each variant this records (a) the get_clause entry exactly as it appears in the model's
prompt, (b) the failing result exactly as the model receives it, (c) every model reply
after that, and (d) the final answer. Writes deliverables/error_before_after.md.

With the STUB, (c) and (d) come from offline_llm.stub_llm and are NOT evidence about a real
model; (a) and (b) are real in both cases. The file says which one produced it.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)
sys.path.insert(0, HERE)

from agent_core.host import McpHost  # noqa: E402
from agent_core.loop import REPO_ROOT, groq_llm, render_tool, run_agent  # noqa: E402
from offline_llm import stub_llm  # noqa: E402

QUESTION = "What does clause 12.4 of the contract say?"
FORCED = {"tool": "get_clause", "args": {"clause_number": "12.4"}}
VARIANTS = [
    ("before", "servers/clause_search_server_v1_before.py"),
    ("after", "servers/clause_search_server.py"),
]
OUT = os.path.join(MCP_AGENT_DIR, "deliverables", "error_before_after.md")


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
        return groq_llm(key), "groq", "REAL MODEL: Groq openai/gpt-oss-120b (temperature 0)"
    return stub_llm, "stub", "STUB (offline_llm.stub_llm): not a language model — see the caveat below"


async def replay(server_file, llm):
    cfg = {"mcpServers": {"clause-search": {
        "command": "${PYTHON}",
        "args": [os.path.join(MCP_AGENT_DIR, server_file)],
        "attach_resources": ["contract://sample/defined-terms"]}}}
    prompts = []

    def recording(prompt):
        reply = llm(prompt)
        prompts.append((prompt, reply))
        return reply

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with open(os.devnull, "w") as quiet:
            async with McpHost(path, errlog=quiet) as host:
                tool = next(t for t in host.tools if t.name == "get_clause")
                tool_text = render_tool(tool)
                result = await run_agent(QUESTION, host, recording, forced_first_action=FORCED)
    return tool_text, result, prompts


def fence(text):
    return "```\n" + text.rstrip() + "\n```"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--llm", choices=["auto", "stub", "groq"], default="auto")
    p.add_argument("--runs", type=int, default=1, help="repeat each variant (useful with a real model)")
    args = p.parse_args()
    llm, kind, label = pick_llm(args.llm)

    runs = {name: [asyncio.run(replay(f, llm)) for _ in range(args.runs)] for name, f in VARIANTS}

    md = [
        "# Same failing call, before vs after — `get_clause(\"12.4\")`",
        "",
        f"- **Model that handled the error:** {label}",
        f"- **Question:** {QUESTION}",
        f"- **First call (forced by the harness in both runs):** `get_clause({json.dumps(FORCED['args'])})` — "
        "the contract has clauses 1-11, so this call must fail.",
        "- Everything else is the same: agent_core, system prompt, the other two tools, the attached defined-terms.",
        "",
    ]
    if kind == "stub":
        md += [
            "> **CAVEAT — read before using this as evidence.** No `GROQ_API_KEY` was available when this file was "
            "generated, so the \"model\" below is `offline_llm.stub_llm`, a rule-based stand-in. Its only relevant rule: "
            "after a failed call it follows a hint of the form \"call <tool>\" if that tool takes no arguments. So the "
            "*difference in its behaviour* is built in and proves nothing about a real model. What IS real, and "
            "identical to what a real model would receive, is **(a) the tool description** and **(b) the failing "
            "result** in each run. To get the real transcript: "
            "`python mcp_agent/scripts/error_demo.py --llm groq --runs 3`.",
            "",
        ]
    for name, _f in VARIANTS:
        tool_text, result, prompts = runs[name][0]
        failing = result["transcript"][0]
        md += [
            f"## {name.upper()}",
            "",
            "**(a) `get_clause` exactly as it appears in the model's prompt (from `tools/list`):**",
            "",
            fence(tool_text),
            "",
            "**(b) The failing call and the result the model receives:**",
            "",
            fence(f"get_clause({json.dumps(FORCED['args'])})\n-> [tool error] {failing['result']}"),
            "",
            "**(c) What the model did next:**",
            "",
        ]
        for i, (_prompt, reply) in enumerate(prompts, 2):
            md.append(f"- model turn {i}: `{reply.strip()}`")
        for t in result["transcript"][1:]:
            if t.get("server"):
                md += ["", f"  - tool `{t['tool']}` -> `{str(t['result'])[:160].replace(chr(10), ' ')}...`"]
        md += [
            "",
            f"**(d) Final answer:** {result['answer']}",
            "",
            f"({result['llm_calls']} model call(s); tools called: "
            f"{', '.join(result['tools_called'])})",
            "",
        ]
        if args.runs > 1:
            outcomes = [r[1]["answer"] for r in runs[name]]
            md += [f"Across {args.runs} runs the final answers were:", ""] + [f"- run {i}: {a[:200]}" for i, a in enumerate(outcomes, 1)] + [""]

    md += [
        "## What changed (and only this)",
        "",
        "| | before | after |",
        "|---|---|---|",
        "| docstring (tool description) | `Get a clause.` | what it is for, when NOT to use it (topic -> `search_clauses`), the exact argument format (\"1\"-\"11\", no \"6.2\"), what an error means |",
        "| error for `12.4` | `Error 3` | `No clause 12.4 in this contract: clauses run 1-11 ... Call list_section_headings ... This server holds only the original agreement ...` |",
        "| distinguishes | nothing | not-a-number vs sub-clause of a real clause vs out-of-range; none of them looks like an outage |",
        "",
        "## Appendix — the full prompt for model turn 2",
        "",
    ]
    for name, _f in VARIANTS:
        _t, _r, prompts = runs[name][0]
        if prompts:
            md += [f"<details><summary>{name}</summary>", "", fence(prompts[0][0]), "", "</details>", ""]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md[:60]))
    print(f"\n[wrote {OUT}]")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
