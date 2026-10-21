"""
Week 10 - race the contract squad (manager + clause worker + defined-terms worker) against the Week 7
single agent on the SAME 10 Week-6 eval cases with the SAME judge, then inject one worker failure.

    python multi_agent/multi_race.py                 # real Groq calls if GROQ_API_KEY is set, else STUB (loud)
    python multi_agent/multi_race.py --llm groq      # real only; refuses to fall back
    python multi_agent/multi_race.py --llm stub      # plumbing check, numbers are NOT evidence

Writes to multi_agent/deliverables/: race_table.md, handoffs.log, failure_case.md, verdict.md,
run_traces.json. (agentcard.json and a2a_bonus.md are hand-written, not generated.)

Fairness, in one place:
  - same 10 cases (cases.py reads eval/questions.py unmodified), same rule check (agent/race.py's own
    rule_check) and same LLM judge (eval/judge.py) for both arms
  - same model for every role in both arms (llm.MODEL); same retrieval function behind both arms' search
  - the single agent is the Week 7 file, untouched: only its model call is swapped for a metered one
  - arm order alternates by case, so neither arm always runs first (warm-up / quota effects)
  - the race totals exclude the failure-injection run, which is a separate run of one case
"""

import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "eval"), os.path.join(REPO_ROOT, "agent"), HERE):
    sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import analysis  # noqa: E402
import cases as case_set  # noqa: E402
from contract_facts import load_facts  # noqa: E402
from llm import LLM, MODEL, Meter, GroqBackend, meter_single_agent, PRICE_IN_PER_M, PRICE_OUT_PER_M, PRICE_SOURCE  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from stub_llm import StubBackend, stub_judge  # noqa: E402
from workers import WorkerServer, make_clause_handler, make_terms_handler  # noqa: E402

PDF_PATH = os.path.join(REPO_ROOT, "data", "sample_contract.pdf")
DEFAULT_OUT = os.path.join(HERE, "deliverables")


def banner(mode):
    if mode == "stub":
        return ("MODE: STUB - no GROQ_API_KEY, so a rule-based stand-in (multi_agent/stub_llm.py) played the model. "
                "Retrieval, both workers (real HTTP), the injected 500 and the meter are real; every pass/fail, "
                "token count, latency and cost here is NOT evidence about a language model. "
                "Re-run with a key: python multi_agent/multi_race.py --llm groq")
    return f"MODE: GROQ {MODEL}, real calls. Token counts are API-reported usage, not estimates."


class Pacer:
    """Sleeps AFTER an arm finishes (outside its timer) so a free-tier tokens-per-minute cap does not
    turn into 429 waits inside the next arm's latency. 0 disables."""

    def __init__(self, tpm):
        self.rate = tpm / 60 if tpm else 0

    def after(self, tokens, elapsed):
        if self.rate:
            wait = tokens * 1.2 / self.rate - elapsed     # 1.2: the judge calls share the same quota
            if wait > 0:
                time.sleep(wait)


def score(agent_race, q, answer, ref, judge):
    """Same logic as agent/race.py:score(), but keeps the judge's reason (the failure case needs it)."""
    rule_ok = agent_race.rule_check(q, answer)
    if q.get("no_answer"):
        return rule_ok, None
    verdict = judge(q["question"], ref, answer)
    return rule_ok and verdict["verdict"] == "PASS", verdict


def week7_recorded():
    path = os.path.join(REPO_ROOT, "agent", "race_traces.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r["agent"]["passed"] for r in json.load(f)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", choices=["auto", "groq", "stub"], default="auto")
    ap.add_argument("--ids", help="comma-separated case ids (default: the 10 pinned in cases.py)")
    ap.add_argument("--tpm", type=int, default=6000, help="pace to this tokens/minute (Groq free tier ~8000); 0 = off")
    ap.add_argument("--inject", help="case id for the defined-terms 500 (default: first viable candidate)")
    ap.add_argument("--no-injection", action="store_true")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    key = os.getenv("GROQ_API_KEY", "")
    mode = args.llm if args.llm != "auto" else ("groq" if key else "stub")
    if mode == "groq" and not key:
        sys.exit("GROQ_API_KEY is not set (.env). Use --llm stub for a plumbing-only run.")

    try:
        from rag_core import load_pdf_chunks, ContractIndex
        import race as agent_race                       # agent/race.py: rule_check, reference_text
        from contract_agent import run_agent
        from judge import judge_answer
        import faiss  # noqa: F401
    except ImportError as exc:
        sys.exit(f"Missing dependency ({exc}). The race runs the real Week 4/6 retrieval: pip install -r requirements.txt")

    print(banner(mode), "\n", flush=True)
    chunks = load_pdf_chunks(PDF_PATH)
    index = ContractIndex(chunks)
    _ = index.reranker
    facts = load_facts()

    meter = Meter()
    llm = LLM(GroqBackend(key) if mode == "groq" else StubBackend(), meter)
    current = {"case": None}
    meter_single_agent(llm, current)

    judge = (lambda q, ref, a: judge_answer(q, ref, a, key)) if mode == "groq" else stub_judge
    pacer = Pacer(args.tpm if mode == "groq" else 0)

    clause_srv = WorkerServer("clause_worker", make_clause_handler(llm, index)).start()
    terms_srv = WorkerServer("terms_worker", make_terms_handler(llm, facts)).start()
    orch = Orchestrator(llm, meter, facts, clause_srv.url, terms_srv.url)

    # Warm-up, outside the meter and every timer: the first reranker pass and the first HTTPS call
    # cost seconds once. Without this, whichever arm runs case 1 first eats that cost in its p99.
    index.expand_with_neighbors(index.search_reranked("warm up", k=3, pool=10))
    if mode == "groq":
        llm.backend.invoke("Reply with the single word: ok", "warmup")

    questions = case_set.load_cases(args.ids.split(",") if args.ids else None)
    wk7 = week7_recorded()
    rows = {"single": [], "multi": []}

    try:
        for i, q in enumerate(questions):
            ref = agent_race.reference_text(q, chunks)
            order = ["single", "multi"] if i % 2 == 0 else ["multi", "single"]
            print(f"[{i + 1}/{len(questions)}] {q['id']}  (first: {order[0]})", flush=True)
            for arm in order:
                t0 = time.perf_counter()
                error = None
                try:
                    if arm == "single":
                        current["case"] = q["id"]
                        res = run_agent(q["question"], index, key or "stub")
                    else:
                        res = orch.run(q["question"], q["id"], "multi")
                except Exception as exc:                  # an API failure is a FAIL for that arm, recorded, not hidden
                    res, error = {"answer": "", "transcript": None, "trace": None}, repr(exc)
                latency = time.perf_counter() - t0
                passed, verdict = (False, None) if error else score(agent_race, q, res["answer"], ref, judge)
                arm_calls = meter.calls_for(arm, q["id"])
                rows[arm].append({
                    "case": q["id"], "problem_type": q["problem_type"], "question": q["question"],
                    "answer": res["answer"], "passed": passed, "judge": verdict, "error": error,
                    "latency_s": latency, "ran_first": order[0] == arm,
                    "llm_calls": len(arm_calls), "tokens": sum(c.total_tokens for c in arm_calls),
                    "trace": res.get("trace"), "transcript": res.get("transcript"),
                })
                print(f"    {arm:<6} {'PASS' if passed else 'FAIL'}  {latency:6.2f}s  "
                      f"{sum(c.total_tokens for c in arm_calls):>6} tok  {len(arm_calls)} calls"
                      + (f"  ERROR {error}" if error else ""), flush=True)
                pacer.after(sum(c.total_tokens for c in arm_calls), latency)

        single_sum = analysis.summarize_arm("single", rows["single"], meter.calls_for("single"))
        multi_sum = analysis.summarize_arm("multi", rows["multi"], meter.calls_for("multi"))
        shares = analysis.handoff_shares(meter.calls_for("multi"))

        failure = None
        if not args.no_injection:
            failure = run_injection(args, questions, rows, llm, meter, facts, clause_srv, index, chunks,
                                    agent_race, judge, pacer)
    finally:
        clause_srv.stop()
        terms_srv.stop()

    os.makedirs(args.out, exist_ok=True)
    write_race_table(args.out, mode, questions, rows, single_sum, multi_sum, shares, wk7, meter)
    write_handoffs_log(args.out, mode, questions, meter, single_sum, multi_sum, shares)
    write_failure_case(args.out, mode, failure)
    write_verdict(args.out, mode, single_sum, multi_sum, shares)
    write_traces(args.out, mode, rows, meter, failure)

    print("\n" + analysis.multiplier_line(single_sum, multi_sum, shares))
    print(f"single {single_sum['passed']}/{single_sum['n']}  multi {multi_sum['passed']}/{multi_sum['n']}")
    if failure:
        print(failure["classification"]["line"])
    print(f"\nDeliverables written to {args.out}")
    if mode == "stub":
        print("\n" + banner("stub"))


def run_injection(args, questions, rows, llm, meter, facts, clause_srv, index, chunks, agent_race, judge, pacer):
    """Re-run ONE case with the defined-terms worker returning a 500 on every request for it."""
    by_case = {r["case"]: r for r in rows["multi"]}
    cid = args.inject
    if not cid:
        cid = next((c for c in case_set.INJECTION_CANDIDATES
                    if c in by_case and by_case[c]["trace"] and by_case[c]["trace"]["terms_requested"]), None)
    if not cid or cid not in by_case or not by_case[cid]["trace"]:
        return {"case": None, "reason": "no candidate case delegated to the defined-terms worker in its clean "
                                        "run, so there was nothing to inject a failure into"}
    q = next(x for x in questions if x["id"] == cid)
    ref = agent_race.reference_text(q, chunks)
    print(f"\nFailure injection: defined-terms worker returns HTTP 500 on case '{cid}' ...", flush=True)

    bad = WorkerServer("terms_worker", make_terms_handler(llm, facts), fail_cases={cid}).start()
    tries, res, latency, mark = 0, None, 0.0, 0
    try:
        # The plan is model-written, so a re-run might not ask for the defined term this time. An injection that
        # never fires proves nothing, so try again (max 3) and say how many it took.
        while tries < 3:
            tries += 1
            mark = len(meter.calls)
            t0 = time.perf_counter()
            res = Orchestrator(llm, meter, facts, clause_srv.url, bad.url).run(q["question"], cid, arm="multi_fail")
            latency = time.perf_counter() - t0
            if "terms_worker" in res["trace"]["outcomes"]:
                break
        hits = list(bad.hits)
    finally:
        bad.stop()

    passed, verdict = score(agent_race, q, res["answer"], ref, judge)
    trace = res["trace"]
    calls = meter.calls[mark:]
    pacer.after(sum(c.total_tokens for c in calls), latency)
    if "terms_worker" in trace["outcomes"]:
        cls = analysis.classify_failure(res["answer"], trace["terms_requested"], trace["outcomes"]["terms_worker"],
                                        trace["clause_quotes"], facts)
    else:
        cls = {"label": "did_not_fire", "asserted": [], "unsupported": [],
               "line": f"NOT TESTED: in all {tries} tries the manager's plan did not delegate to the defined-terms worker, "
                       "so the 500 never reached it."}
    return {"case": cid, "question": q["question"], "answer": res["answer"], "passed": passed, "judge": verdict,
            "latency_s": latency, "trace": trace, "classification": cls, "server_hits": hits, "tries": tries,
            "tokens": sum(c.total_tokens for c in calls), "clean": by_case[cid]}


# ---------------------------------------------------------------------------- writers

def _x(a, b):
    if not a:
        return "n/a"
    r = b / a
    return f"{r:.1f}x" if r >= 1 else f"{r:.2f}x"


def _usd(v):
    return f"${v:.5f}"


def write_race_table(out, mode, questions, rows, S, M, shares, wk7, meter):
    sm = {r["case"]: r for r in rows["single"]}
    mm = {r["case"]: r for r in rows["multi"]}
    L = [f"# Race table - contract squad vs single agent (Task Set F, Week 10)\n", banner(mode) + "\n"]
    L.append(f"Same {S['n']} Week-6 cases (read unmodified from `eval/questions.py`), same rule check "
             "(`agent/race.py:rule_check`) and same LLM judge (`eval/judge.py`) for both arms, same model for every "
             f"role in both arms (`{MODEL}`), same retrieval function behind both arms' search. "
             "Single agent = the Week 7 `agent/contract_agent.py`, unmodified. Orchestrator = manager + clause worker "
             "+ defined-terms worker (`multi_agent/`).\n")
    gain = M["passed"] - S["passed"]
    L.append("| metric | single agent | orchestrator (manager + 2) | multi vs single |")
    L.append("|---|---|---|---|")
    L.append(f"| pass rate | {S['passed']}/{S['n']} ({S['passed'] / S['n']:.0%}) | {M['passed']}/{M['n']} "
             f"({M['passed'] / M['n']:.0%}) | {gain:+d} case{'s' if abs(gain) != 1 else ''} |")
    L.append(f"| latency p50 (s) | {S['p50_s']:.2f} | {M['p50_s']:.2f} | {_x(S['p50_s'], M['p50_s'])} |")
    L.append(f"| latency p99 (s) | {S['p99_s']:.2f} | {M['p99_s']:.2f} | {_x(S['p99_s'], M['p99_s'])} |")
    L.append(f"| total tokens (in + out) | {S['total_tokens']:,} ({S['prompt_tokens']:,} + {S['completion_tokens']:,}) | "
             f"{M['total_tokens']:,} ({M['prompt_tokens']:,} + {M['completion_tokens']:,}) | "
             f"{_x(S['total_tokens'], M['total_tokens'])} |")
    L.append(f"| cost per question (USD) | {_usd(S['cost_per_q'])} | {_usd(M['cost_per_q'])} | "
             f"{_x(S['cost_per_q'], M['cost_per_q'])} |")
    L.append(f"| model calls (total) | {S['llm_calls']} | {M['llm_calls']} | {_x(S['llm_calls'], M['llm_calls'])} |\n")
    L.append("**" + analysis.multiplier_line(S, M, shares) + "**\n")

    L.append("Reading the numbers honestly:")
    L.append(f"- p50/p99 are nearest-rank over {S['n']} per-case wall-clock latencies. With n={S['n']}, **p99 is the slowest "
             "single case**, not a smoothed tail - which is exactly what a client in a live negotiation feels.")
    L.append(f"- Cost = tokens x Groq list price (${PRICE_IN_PER_M}/M in, ${PRICE_OUT_PER_M}/M out; {PRICE_SOURCE}); "
             "cached-input discounts ignored, so an upper bound for both arms equally. Judge calls are excluded "
             "(identical for both arms). Pacing sleeps between arms are outside every timer.")
    for s in (S, M):
        if s["throttled_cases"]:
            L.append(f"- **{s['arm']}: {s['throttle_wait_s']:.1f}s of 429 quota waits inside its latencies**, cases "
                     f"{', '.join(s['throttled_cases'])}. Its p99 includes them.")
    if S["estimated_calls"] or M["estimated_calls"]:
        L.append(f"- Token counts for {S['estimated_calls'] + M['estimated_calls']} calls are tiktoken/char ESTIMATES "
                 "(no API usage available): this is a STUB run.")
    L.append(f"- Estimated share of prompt tokens that repeat the previous call's prefix in the same chain "
             f"(context re-send): single {S['resent_est'] / max(1, S['prompt_tokens']):.0%}, "
             f"multi {M['resent_est'] / max(1, M['prompt_tokens']):.0%}.")
    L.append("- The multi arm has one data structure the single arm does not: a defined-terms table parsed from the same "
             "contract text. That is the second specialist's whole premise, so it is part of what is being measured.\n")

    L.append("## The 10 cases (same for both arms)\n")
    L.append("| # | case | problem type | single | multi | single tok | multi tok | single s | multi s | Wk7 recorded agent | manager delegated to |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, q in enumerate(questions, 1):
        s, m = sm[q["id"]], mm[q["id"]]
        deleg = ", ".join(m["trace"]["delegated_to"]) if m["trace"] else "(error)"
        w = {True: "PASS", False: "FAIL", None: "-"}[wk7.get(q["id"])]
        L.append(f"| {i} | {q['id']} | {q['problem_type']} | {'PASS' if s['passed'] else 'FAIL'} | "
                 f"{'PASS' if m['passed'] else 'FAIL'} | {s['tokens']:,} | {m['tokens']:,} | "
                 f"{s['latency_s']:.2f} | {m['latency_s']:.2f} | {w} | {deleg} |")
    L.append("\n`Wk7 recorded agent` is the result the same agent got on the same case in the Week 7 run "
             "(`agent/race_traces.json`) - a reproducibility cross-check, not part of this race.")
    errs = [(a, r) for a in ("single", "multi") for r in rows[a] if r["error"]]
    if errs:
        L.append("\n**Errors (counted as FAIL):** " + "; ".join(f"{a}/{r['case']}: {r['error']}" for a, r in errs))
    excluded = ", ".join(case_set.EXCLUDED_IDS)
    L.append(f"\nSelection rule for the 10 and the {len(case_set.EXCLUDED_IDS)} left out: see `cases.py`. Left out: {excluded}.")

    L.append("\n## Where the multi arm's tokens went (all 10 cases)\n")
    L.append("| hand-off | tokens | share |")
    L.append("|---|---|---|")
    for label, tokens, share in shares:
        L.append(f"| {label} | {tokens:,} | {share:.1%} |")
    _write(out, "race_table.md", "\n".join(L) + "\n")


def write_handoffs_log(out, mode, questions, meter, S, M, shares):
    L = ["# handoffs.log - every model call and every worker hand-off, with token counts",
         "# " + banner(mode),
         "# columns: arm | case | hand-off | in | out | total | resent~ (prompt tokens identical to the previous call's prefix) | latency",
         "# HTTP lines are manager -> worker attempts: they carry no tokens themselves; the tokens a worker spends "
         "serving one are the 'manager -> <worker>' model-call lines for the same case.", ""]
    for q in questions:
        for arm in ("single", "multi", "multi_fail"):
            calls = meter.calls_for(arm, q["id"])
            events = meter.events_for(arm, q["id"])
            if not calls and not events:
                continue
            lines = [(c.t0, "call", c) for c in calls] + [(e["t0"], "event", e) for e in events]
            for _t, kind, item in sorted(lines, key=lambda t: t[0]):
                if kind == "call":
                    c = item
                    wait = f"  throttle-wait={c.throttle_wait_s:.1f}s" if c.throttle_wait_s else ""
                    L.append(f"{arm:<10} {q['id']:<28} {analysis.handoff_label(c):<84} in={c.prompt_tokens:>6} "
                             f"out={c.completion_tokens:>5} total={c.total_tokens:>6} resent~{c.resent_est:>6} "
                             f"{c.latency_s:6.2f}s [{c.usage_source}]{wait}")
                else:
                    e = item
                    status = e["status"] if e["status"] is not None else "no response"
                    note = f"  {e['error']}" if e["error"] else ""
                    L.append(f"{arm:<10} {q['id']:<28} manager -> {e['worker']} HTTP POST attempt {e['attempt']} -> "
                             f"{status} ({e['latency_s']:.2f}s){note}")
            L.append(f"{'':<10} {'':<28} = {arm} total for {q['id']}: {sum(c.total_tokens for c in calls):,} tokens\n")

    L.append("# ---- multi arm, per hand-off, all 10 cases (the failure-injection run is excluded) ----")
    for label, tokens, share in shares:
        L.append(f"{share:>6.1%}  {tokens:>7,}  {label}")
    L.append("")
    L.append(analysis.multiplier_line(S, M, shares))
    _write(out, "handoffs.log", "\n".join(L) + "\n")


def write_failure_case(out, mode, f):
    L = ["# failure_case.md - the defined-terms worker returns HTTP 500\n", banner(mode) + "\n"]
    if not f or not f.get("case"):
        L.append(f"**Not run:** {f['reason'] if f else '--no-injection was given'}.")
        _write(out, "failure_case.md", "\n".join(L) + "\n")
        return
    c, t, clean = f["classification"], f["trace"], f["clean"]
    L.append(f"**Outcome, one line:** {c['line']}\n")
    if c["label"] == "did_not_fire":
        L.append(f"- **Case:** `{f['case']}` - \"{f['question']}\"; the manager asked for terms {t['terms_requested']} and delegated to "
                 f"{t['delegated_to']} in the last of {f['tries']} tries. The service received {len(f['server_hits'])} request(s).")
        L.append("- Nothing about worker failure can be concluded from this run; re-run, or pick another case with `--inject <case_id>`.")
        _write(out, "failure_case.md", "\n".join(L) + "\n")
        return
    term_out = t["outcomes"]["terms_worker"]
    L.append(f"- **Case:** `{f['case']}` - \"{f['question']}\"")
    L.append("- **Injection:** the defined-terms worker's HTTP service answers `500 {\"error\": \"injected fault: worker crashed\"}` "
             "to EVERY request for this case (persistent, not a blip). The clause worker is untouched. This is a separate run of "
             "this one case; it is not in the race totals.")
    L.append(f"- **Did it fire?** Yes, on try {f['tries']} of max 3. The manager's plan asked for: {t['terms_requested']}; "
             f"delegated to {t['delegated_to']}; the service received {len(f['server_hits'])} request(s) over all tries, "
             f"statuses {[h['status'] for h in f['server_hits']]}.")
    L.append(f"- **Manager's client:** {term_out['attempts']} attempt(s), final HTTP {term_out['status']} "
             "(one retry on 5xx is built in - `workers.post_task`). No model tokens were spent on the failed worker.")
    L.append(f"- **What the synthesis step was told:** `{t['terms_result_text']}`")
    L.append("- **Prompt rule about unavailable workers:** none. `orchestrator.SYNTH_PROMPT` says only \"use ONLY the worker results\" and "
             "\"say not found if they do not contain the answer\", so what follows is the unprompted behaviour; a prompt rule "
             "(\"if a worker is unavailable, say so\") could change it, and that would be a new experiment.\n")
    L.append("## Final answer, failed run\n")
    L.append(f"> {f['answer']}\n")
    L.append("## Same case, clean run (for contrast)\n")
    L.append(f"> {clean['answer']}\n")
    L.append(f"- Judge on the failed run: **{'PASS' if f['passed'] else 'FAIL'}**"
             + (f" - {f['judge']['reason']}" if f['judge'] else "")
             + f". Judge on the clean run: **{'PASS' if clean['passed'] else 'FAIL'}**.")
    L.append(f"- Definitions the answer states: {c['asserted'] or 'none'}; of those, with no lookup and no clause quote behind them: "
             f"{c['unsupported'] or 'none'}.")
    L.append(f"- Failed run cost {f['tokens']:,} tokens vs {clean['tokens']:,} clean.")
    L.append("\n## How the label was decided (rules in `analysis.classify_failure`, tested in `selfcheck.py`)\n")
    L.append("`retried` = a later attempt succeeded. `degraded` = still failed and the answer discloses it. `lied` = still failed, "
             "no disclosure, and the answer states a definition that neither a lookup nor a clause-worker quote supports. "
             "`silent_omission` = still failed, no disclosure, nothing invented. The label is a regex-and-overlap heuristic: "
             "read the two answers above and overrule it if you disagree.")
    _write(out, "failure_case.md", "\n".join(L) + "\n")


def write_verdict(out, mode, S, M, shares):
    rule = (f"Rule, fixed before any run: keep multi-agent only if it wins by >= {analysis.KEEP_MIN_PASS_GAIN} of {S['n']} cases "
            f"AND costs <= {analysis.KEEP_MAX_COST_RATIO:.1f}x per question; otherwise the single agent stays.")
    sunk = ("Sunk-cost bias, named before the verdict: I built the manager and both workers and want that effort to have been "
            "worth it - effort already spent is not evidence, and %s.")
    if mode == "stub":
        L = ["# Verdict",
             sunk % "the real verdict will not weigh it",
             "NONE YET - this run used the offline STUB, not a model.",
             "The numbers in race_table.md measure plumbing (retrieval, HTTP workers, metering), not a language model, so they cannot support keep or kill.",
             rule,
             "To get the real verdict: set GROQ_API_KEY in .env, run `python multi_agent/multi_race.py --llm groq`; this file is rewritten from the real numbers."]
    else:
        d = analysis.decide(S, M)
        top_label, _t, top_share = shares[0]
        what = "the same context sent again, not new work" if "re-send" in top_label else "the largest single hand-off"
        L = ["# Verdict",
             sunk % "nothing below weighs it",
             "**KEEP the orchestrator; kill the single agent.**" if d["keep_multi"] else "**KEEP the single agent; KILL the orchestrator.**",
             f"Pass rate: single {S['passed']}/{S['n']} vs multi {M['passed']}/{M['n']} ({d['pass_gain']:+d} cases; one case of {S['n']} is one flipped judge call).",
             f"Cost: {analysis.multiplier(S['total_tokens'], M['total_tokens']):.1f}x tokens ({S['total_tokens']:,} vs {M['total_tokens']:,}); "
             f"{_usd(S['cost_per_q'])} vs {_usd(M['cost_per_q'])} per question ({d['cost_ratio']:.1f}x); p99 latency {S['p99_s']:.1f}s vs {M['p99_s']:.1f}s.",
             rule,
             f"Biggest bill: {top_label}, {top_share:.0%} of multi tokens - {what}.",
             "Worth it when: sub-tasks are truly independent (run in parallel) or need clearly different instructions/tools, and the gain is large against the cost.",
             "Not worth it when: one retrieval answers the question, hand-offs mostly re-send the same context, or p99 latency matters live.",
             f"Caveat: n={S['n']}, one run per arm, same judge; the failure test is a separate run (failure_case.md)."]
    assert len(L) <= 10, "verdict.md is capped at 10 lines"
    _write(out, "verdict.md", "\n".join(L) + "\n")


def write_traces(out, mode, rows, meter, failure):
    from llm import calls_as_rows
    payload = {
        "mode": mode, "model": MODEL,
        "rows": rows,
        "calls": calls_as_rows(meter.calls),
        "events": meter.events,
        "failure": failure,
    }
    _write(out, "run_traces.json", json.dumps(payload, indent=2, default=str))


def _write(out, name, text):
    with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


if __name__ == "__main__":
    main()
