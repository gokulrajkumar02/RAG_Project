"""
Cost per query, attributed by stage (retrieval / generation / tools) - for one request, and for the week.

    python observability/cost_report.py <trace id prefix> --out observability/deliverables/cost_by_stage.md

Attribution before optimisation: every span carries its own latency, tokens and USD, so a change in cost
can be pinned to the stage (and the prompt version) that moved it.
  retrieval   local CPU in the app process (embeddings, FAISS, cross-encoder): $0 on any bill; its cost is time
  generation  Groq tokens x list price (tracing.PRICES_PER_M)
  tools       the served app makes no tool calls - reported as 0, not left out
"""

import argparse
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from logq import LOG_DIRS, find_one  # noqa: E402
from pipeline import MODEL  # noqa: E402
from tracing import PRICE_SOURCE, PRICES_PER_M, read_logs, stage_totals  # noqa: E402

STAGES = ("retrieval", "generation", "tools")


def usd(x, digits=7):
    return f"${x:.{digits}f}"


def per_1k(x):
    return f"${x * 1000:.4f}"


def eval_runs():
    """{label: [records]} for every suite run under logs/eval."""
    root = LOG_DIRS["eval"]
    if not os.path.isdir(root):
        return {}
    return {label: read_logs(os.path.join(root, label)) for label in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, label))}


def mean(xs):
    return statistics.fmean(xs) if xs else 0.0


def before_after(runs):
    """The suite pair to compare: the real-model runs when they exist, else the stub runs."""
    for b, a in (("before-real", "after-real"), ("before", "after")):
        if runs.get(b) and runs.get(a):
            return b, a
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--logs", default="prod")
    ap.add_argument("--out")
    a = ap.parse_args()

    records = read_logs(LOG_DIRS.get(a.logs, a.logs))
    rec = find_one(records, a.trace)
    spans = rec["spans"]
    stages = stage_totals(spans)
    total_cost = rec["totals"]["cost_usd"]
    total_lat = rec["totals"]["latency_ms"]
    p_in, p_out = PRICES_PER_M[MODEL]
    L = []
    w = L.append

    w(f"# Cost per query by stage - trace `{rec['trace_id']}`\n")
    w(f"{rec['ts_local']} - {rec['user_id']} ({rec['user_role']}) - `{rec['prompt_version']}` - model `{rec['model']}` "
      f"- llm_mode `{rec['llm_mode']}`\n")
    if rec["llm_mode"] != "groq":
        w(f"> **Read the generation numbers for what they are.** This request is `llm_mode={rec['llm_mode']}`: no "
          f"model call was made for it, so its generation tokens are tiktoken estimates of the real prompt and the "
          f"logged answer (`usage_source: estimate`) - they leave out gpt-oss reasoning tokens, so real output "
          f"tokens are higher - and its generation latency is modelled, not measured. Retrieval latencies are "
          f"measured. Prices: {usd(p_in, 3)}/M input, {usd(p_out, 2)}/M output ({PRICE_SOURCE[MODEL]}).\n")

    w("## That request, by stage\n")
    w("| stage | USD | share of cost | latency (ms) | share of latency | tokens in / out |")
    w("|---|---|---|---|---|---|")
    for st in STAGES:
        t = stages[st]
        cost_share = t["cost_usd"] / total_cost if total_cost else 0
        lat_share = t["latency_ms"] / total_lat if total_lat else 0
        w(f"| **{st}** | {usd(t['cost_usd'])} | {cost_share:.0%} | {t['latency_ms']:.1f} | {lat_share:.0%} | "
          f"{t['input_tokens']} / {t['output_tokens']} |")
    gap = total_lat - sum(stages[st]["latency_ms"] for st in STAGES)
    if gap > 1.0:
        w(f"| *(covered by no span)* | $0 | - | {gap:.1f} | {gap / total_lat:.0%} | - |")
    w(f"| **total** | **{usd(total_cost)}** | 100% | **{total_lat:.1f}** | 100% | "
      f"{rec['totals']['input_tokens']} / {rec['totals']['output_tokens']} |\n")
    if gap > 5.0:
        w(f"{gap:.0f} ms of this request is covered by no span: work done inside the trace window that no stage "
          f"owns. In a synthetic trace it can only be local bookkeeping - here, loading the tokenizer in a fresh "
          f"process (a drill plant). Since 2026-10-28, traces without a model call end at their last span "
          f"(`tracing.Trace.finish`) and `Pipeline.warm()` loads the tokenizer first, so this no longer happens; "
          f"the trace is shown as it was logged.\n")
    w(f"Generation = {stages['generation']['input_tokens']} x {usd(p_in, 3)}/M + "
      f"{stages['generation']['output_tokens']} x {usd(p_out, 2)}/M = {usd(stages['generation']['cost_usd'])}. "
      f"That is **{per_1k(total_cost)} per 1,000 queries** like it. Retrieval is $0 on the bill: it runs on the "
      f"app's own CPU, and what it costs is {stages['retrieval']['latency_ms']:.0f} ms of that CPU. Tools: the "
      f"served app makes no tool calls (the Week 7-10 agents do, but they are not what lawyers use).\n")

    w("Spans (leaf spans carry the cost; `retrieval` is their parent):\n")
    w("| span | stage | start (ms) | latency (ms) | tokens in / out | USD | latency source |")
    w("|---|---|---|---|---|---|---|")
    for s in spans:
        a_ = s["attributes"]
        toks = (f"{a_.get('gen_ai.usage.input_tokens', 0)} / {a_.get('gen_ai.usage.output_tokens', 0)}"
                if "gen_ai.usage.input_tokens" in a_ else "-")
        cost = usd(a_["cost_usd"]) if "cost_usd" in a_ else "-"
        src = a_.get("latency_source", "measured")
        w(f"| `{s['name']}` | {s['stage']} | {s['start_ms']:.1f} | {s['latency_ms']:.1f} | {toks} | {cost} | {src} |")

    # ---- the week, by stage and prompt version ------------------------------------------------------
    w("\n## The logged week, by stage and prompt version\n")
    by_pv = defaultdict(list)
    for r in records:
        if r["status"] == "ok":
            by_pv[r["prompt_version"]].append(r)
    w("| prompt version | requests | mean tokens in / out | generation USD/query | retrieval USD/query | "
      "tools USD/query | USD per 1,000 | mean retrieval ms |")
    w("|---|---|---|---|---|---|---|---|")
    week_rows = {}
    for pv, rs in sorted(by_pv.items()):
        tin = mean([r["totals"]["input_tokens"] for r in rs])
        tout = mean([r["totals"]["output_tokens"] for r in rs])
        gen = mean([r["cost_by_stage_usd"]["generation"] for r in rs])
        ret = mean([r["cost_by_stage_usd"]["retrieval"] for r in rs])
        tools = mean([r["cost_by_stage_usd"]["tools"] for r in rs])
        rlat = mean([stage_totals(r["spans"])["retrieval"]["latency_ms"] for r in rs])
        week_rows[pv] = (tin, tout, gen + ret + tools)
        w(f"| `{pv}` | {len(rs)} | {tin:.0f} / {tout:.0f} | {usd(gen)} | {usd(ret)} | {usd(tools)} | "
          f"{per_1k(gen + ret + tools)} | {rlat:.0f} |")
    if "answer-v1" in week_rows and "answer-v2" in week_rows:
        d_in = week_rows["answer-v2"][0] - week_rows["answer-v1"][0]
        d_out = week_rows["answer-v2"][1] - week_rows["answer-v1"][1]
        w(f"\nThe v1 -> v2 bump moved cost through **generation only**: {d_in:+.0f} input / {d_out:+.0f} output tokens "
          f"per query on average (the citation instruction, and the clause reference in each answer). Retrieval "
          f"and tools did not move. These are different requests (v1 ran Mon-Wed, v2 Wed-Sun), so the "
          f"like-for-like comparison is the suite below.\n")

    # ---- like for like: the same 25 suite questions under two prompt versions ----------------------------
    runs = eval_runs()
    if runs:
        w("## Like for like: the same suite questions under each prompt version (eval runs)\n")
        w("| suite run | llm_mode | prompt | queries | mean tokens in / out | USD/query | USD per 1,000 | "
          "mean retrieval ms | mean generation ms |")
        w("|---|---|---|---|---|---|---|---|---|")
        summary = {}
        for label, rs in runs.items():
            if not rs:
                continue
            tin = mean([r["totals"]["input_tokens"] for r in rs])
            tout = mean([r["totals"]["output_tokens"] for r in rs])
            c = mean([r["totals"]["cost_usd"] for r in rs])
            st = [stage_totals(r["spans"]) for r in rs]
            summary[label] = (tin, tout, c, rs[0]["prompt_version"], rs[0]["llm_mode"])
            w(f"| {label} | {rs[0]['llm_mode']} | `{rs[0]['prompt_version']}` | {len(rs)} | {tin:.0f} / {tout:.0f} | "
              f"{usd(c)} | {per_1k(c)} | {mean([s['retrieval']['latency_ms'] for s in st]):.0f} | "
              f"{mean([s['generation']['latency_ms'] for s in st]):.1f} |")
        pair = before_after(runs)
        if pair:
            b, af = summary[pair[0]], summary[pair[1]]
            ctx_b = mean([len(r["retrieval"]["context_chunk_ids"]) for r in runs[pair[0]]])
            ctx_a = mean([len(r["retrieval"]["context_chunk_ids"]) for r in runs[pair[1]]])
            w(f"\nThe fix ({b[3]} -> {af[3]}) costs **{af[0] - b[0]:+.0f} input tokens per query** "
              f"({(af[0] - b[0]) / b[0]:+.0%}): whole clauses instead of fragments ({ctx_b:.1f} -> {ctx_a:.1f} "
              f"chunks per query) plus their labels. It lands in the generation stage; the retrieval stage gains "
              f"one span (`retrieval.expand_clauses`, well under 1 ms) and no cost.")
            if b[4] != "groq":
                w(f"\nStub runs: input tokens are tiktoken counts of the exact prompts each version renders, so the "
                  f"input delta is real up to tokenizer differences. The output side ({af[1] - b[1]:+.0f}) and "
                  f"the per-1,000 totals ({per_1k(b[2])} -> {per_1k(af[2])}) are not, because stub answers copy "
                  f"passages verbatim and are not a model's, and neither is the stub's 'generation ms' column "
                  f"(local string handling plus cross-encoder scoring).")
            w("")

    text = "\n".join(L) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
