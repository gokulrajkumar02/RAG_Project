"""
THE single entry point for the Contract Review Assistant.

    python capstone/run.py              # = all: build (if needed) -> eval both systems -> results/RESULTS.txt
    python capstone/run.py build        # generate corpus, extract (OCR the scans), parse, redact, index
    python capstone/run.py ask "What is the liability cap for Halcyon Freight?"
    python capstone/run.py eval         # the suite on v0-naive and v1-guarded, trajectory, taxonomy, cost
    python capstone/run.py case cap_amended_halcyon-freight   # one eval case on BOTH systems: RED before, GREEN after
    python capstone/run.py trace <trace id prefix>   # span tree: latency + cost per span, id across agent and MCP hops
    python capstone/run.py serve        # expose the MCP server (stdio) to an outside client

Options: --llm auto|stub|groq   (auto = groq if GROQ_API_KEY is set, else the offline STUB)
         --variant v0-naive|v1-guarded
"""

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contractdesk  # noqa: E402,F401
from contractdesk import paths  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(paths.REPO_ROOT, ".env"))
except ImportError:
    pass


def say(msg):
    print(msg, flush=True)


def build(force=False):
    """corpus -> extraction (pypdf / OCR) -> registry -> index. Each stage is skipped if its output exists."""
    from contractdesk import corpus_gen, extract, ingest
    t0 = time.time()
    manifest, _truth = corpus_gen.generate(force=force)
    say(f"corpus: {len(manifest['documents'])} documents, {len(manifest['counterparties'])} customers (synthetic, seed {corpus_gen.SEED})")
    extract.extract_all(manifest, progress=say)
    if force or not os.path.exists(paths.REGISTRY):
        ingest.build_registry(manifest, progress=say)
    if force or not os.path.exists(os.path.join(paths.INDEX_DIR, "index.faiss")):
        reg = json.load(open(paths.REGISTRY, encoding="utf-8"))
        ingest.build_index(reg, progress=say)
    say(f"build done in {time.time() - t0:.0f}s")


@contextlib.asynccontextmanager
async def open_desk(variant, llm_kind="auto", log_dir=None, log_content=False, keep_prompts=False):
    from contractdesk.agent import Desk, TracedHost
    from contractdesk.llm import make_llm
    from contractdesk.toolkit import load_config
    os.environ["CONTRACT_DESK_VARIANT"] = variant
    os.makedirs(paths.LOGS, exist_ok=True)
    cfg = load_config()
    with open(os.path.join(paths.LOGS, "server_stderr.log"), "a", encoding="utf-8") as errlog:
        async with TracedHost(paths.MCP_CONFIG, errlog=errlog) as host:
            if host.failed:
                raise SystemExit(f"MCP server failed to start: {host.failed}  (see capstone/logs/server_stderr.log)")
            yield Desk(host, make_llm(llm_kind, cfg["model"]), variant, log_dir=log_dir, log_content=log_content,
                       keep_prompts=keep_prompts), host


async def ask(question, variant, llm_kind):
    async with open_desk(variant, llm_kind) as (desk, host):
        say(f"[{variant} | llm={desk.llm.mode}{' (STUB: not a language model)' if desk.llm.mode == 'stub' else ''}] "
            f"tools discovered over MCP: {', '.join(t.name for t in host.tools)}")
        res = await desk.ask(question)
    for s in res["transcript"]:
        if s["tool"] != "final_answer":
            say(f"  step {s['step']}: {s['tool']}({json.dumps(s['args'])}) -> {s.get('server', '')}")
        else:
            say(f"  step {s['step']}: final_answer{'  [REJECTED by guards: ' + '; '.join(g['gate'] for g in s['guard']) + ']' if s.get('guard') else ''}")
    say("\n" + res["answer"])
    for ev in res["guard_events"]:
        say(f"  guard: {ev['gate']} - {ev.get('action', '')} {ev.get('detail', '')}")
    t = res["trace"]
    say(f"\ntrace {t['trace_id']}  {t['totals']['latency_ms']:.0f} ms  ${t['totals']['cost_usd']:.5f}  "
        f"trace id survived every MCP call: {t['trace_id_survived_all']}")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="all", choices=["all", "build", "ask", "eval", "serve", "case", "trace"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--llm", default="auto", choices=["auto", "stub", "groq"])
    ap.add_argument("--variant", default="v1-guarded", choices=["v0-naive", "v1-guarded"])
    ap.add_argument("--rebuild", action="store_true", help="regenerate corpus and rebuild everything")
    a = ap.parse_args()
    if a.command == "serve":
        os.execv(sys.executable, [sys.executable, os.path.join(paths.CAPSTONE_DIR, "server.py")])
    if a.command == "trace":
        from contractdesk import report
        report.show_trace(a.question)
        return
    if a.command in ("all", "build", "eval", "ask", "case"):
        build(force=a.rebuild)
    if a.command == "build":
        return
    if a.command == "case":
        from contractdesk import report
        asyncio.run(report.run_case(a.question, a.llm))
        return
    if a.command == "ask":
        if not a.question:
            ap.error("ask needs a question")
        asyncio.run(ask(a.question, a.variant, a.llm))
        return
    from contractdesk import report
    asyncio.run(report.run_all(a.llm))


if __name__ == "__main__":
    main()
