"""
Week 8 — one command: score the contract agent's PATH, not just its answer.

Runs both agents over all 24 questions in eval/questions.py:

  baseline = agent/contract_agent.py   (Week 7's loop, unmodified)
  guarded  = agent_eval/guarded_agent.py (Week 8's fix + defenses)

and grades every run twice, independently:

  OUTCOME    — Week 7's scoring, reused unchanged from agent/race.py: the
               free keyword rule check + the LLM judge validated in Week 6.
  TRAJECTORY — agent_eval/trajectory.py: six free checks on the path
               (tool-choice accuracy, expected tool sequence, self-termination,
               fabricated citations, looping, arg bounds). No LLM involved.

The report is built around the gap between them: runs that PASS the outcome
while FAILING the trajectory are the "right answer, wrong path" cases the
brief is about — a lucky path that will break on the next input. It also
reports cost per task (mean / median / p95 / p99 seconds and LLM calls) for
each agent, because a fix that saves steps but moves the p99 tail is a fix
you want to see before shipping.

Usage:
    python agent_eval/traj_eval.py                 # full run, ~10-15 min
    python agent_eval/traj_eval.py --resume        # continue an interrupted run
                                                    # (per-question checkpoint +
                                                    # 429 backoff inside)
    python agent_eval/traj_eval.py --report-only   # rebuild traj_report.md from
                                                    # saved traj_traces.json,
                                                    # zero API calls
"""

import json
import math
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(REPO_ROOT, "eval")
AGENT_DIR = os.path.join(REPO_ROOT, "agent")
for p in (REPO_ROOT, EVAL_DIR, AGENT_DIR, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from rag_core import load_pdf_chunks, ContractIndex  # noqa: E402
from questions import QUESTIONS  # noqa: E402
from race import reference_text, rule_check  # noqa: E402
from judge import judge_answer  # noqa: E402
from contract_agent import run_agent  # noqa: E402
from guarded_agent import run_guarded_agent  # noqa: E402
from trajectory import CHECKS, score_run  # noqa: E402

PDF_PATH = os.path.join(REPO_ROOT, "data", "sample_contract.pdf")
AGENTS = {"baseline": run_agent, "guarded": run_guarded_agent}


def percentile(values, p):
    """Nearest-rank percentile (p in 0..1) — honest for small n, no interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(p * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def cost_stats(values):
    if not values:
        return {}
    n = len(values)
    return {
        "n": n,
        "mean": sum(values) / n,
        "median": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def grade(q, answer, ref, api_key):
    """Week 7's grading, unchanged (agent/race.py `score`), but recorded as its
    two parts so the report can say *why* an outcome moved: the free keyword
    rule check, then the Week 6 LLM judge on top of it.

    The judge is only called when the rule check passes — outcome is
    `rule AND judge`, so a rule miss already settles the outcome, and skipping
    the call there keeps this harness inside one day's Groq token budget."""
    rule_pass = rule_check(q, answer)
    if q.get("no_answer") or not rule_pass:
        return {"outcome_pass": False, "rule_pass": rule_pass, "judge_verdict": None}
    verdict = judge_answer(q["question"], ref, answer, api_key)["verdict"]
    return {"outcome_pass": verdict == "PASS",
            "rule_pass": rule_pass, "judge_verdict": verdict}


def _with_backoff(fn, tries=6, base_sleep=45):
    """Run fn; on Groq 429 (daily token budget) wait and retry instead of
    dying mid-run — paired with the per-question checkpoint in run_all, so an
    interrupted run can also be continued with --resume."""
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - re-raised if it isn't a rate limit
            if "429" not in str(e) and "rate_limit" not in str(e).lower():
                raise
            last = e
            wait = base_sleep * (attempt + 1)
            print(f"    rate limited — waiting {wait}s then retrying "
                  f"({attempt + 1}/{tries}) ...", flush=True)
            time.sleep(wait)
    raise last


def run_all(api_key, index, chunks, resume=False):
    checkpoint = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traj_checkpoint.json")
    done = {}
    if resume and os.path.exists(checkpoint):
        with open(checkpoint, encoding="utf-8") as f:
            done = json.load(f)
        print(f"resuming: {len(done)}/{len(QUESTIONS)} questions already scored")

    rows = []
    for i, q in enumerate(QUESTIONS, 1):
        if q["id"] in done:
            rows.append(done[q["id"]])
            continue
        print(f"[{i}/{len(QUESTIONS)}] {q['id']} ...", flush=True)
        ref = reference_text(q, chunks)
        row = {"id": q["id"], "problem_type": q["problem_type"], "question": q["question"]}
        for agent_name, agent_fn in AGENTS.items():
            print(f"  {agent_name} ...", flush=True)
            t0 = time.time()
            result = _with_backoff(lambda: agent_fn(q["question"], index, api_key))
            graded = _with_backoff(lambda: grade(q, result["answer"], ref, api_key))
            traj = score_run(result)
            row[agent_name] = {
                "answer": result["answer"],
                **graded,
                "trajectory_pass": traj["trajectory_pass"],
                "failed_checks": traj["failed_checks"],
                "checks": {k: v["pass"] for k, v in traj["checks"].items()},
                "n_model_turns": traj["n_model_turns"],
                "llm_calls": result["llm_calls"],
                "tool_calls": result["tool_calls"],
                "elapsed": result["elapsed"],
                "stopped_early": result["stopped_early"],
                "repairs": result.get("repairs", 0),
                "dropped_citations": result.get("dropped_citations", []),
                "quarantined_chunks": result.get("quarantined_chunks", []),
                "harness_seconds": round(time.time() - t0, 2),
                "transcript": result["transcript"],
            }
        rows.append(row)
        done[q["id"]] = row
        with open(checkpoint, "w", encoding="utf-8") as f:
            json.dump(done, f, indent=2)
    if os.path.exists(checkpoint) and len(done) >= len(QUESTIONS):
        os.remove(checkpoint)
    return rows


def agent_summary(rows, agent_name):
    runs = [r[agent_name] for r in rows]
    n = len(runs)
    outcome_pass = sum(r["outcome_pass"] for r in runs)
    traj_pass = sum(r["trajectory_pass"] for r in runs)
    both = sum(r["outcome_pass"] and r["trajectory_pass"] for r in runs)
    lucky = [r["id"] for r in rows if r[agent_name]["outcome_pass"] and not r[agent_name]["trajectory_pass"]]
    honest_fail = [r["id"] for r in rows if not r[agent_name]["outcome_pass"] and r[agent_name]["trajectory_pass"]]
    double_fail = [r["id"] for r in rows if not r[agent_name]["outcome_pass"] and not r[agent_name]["trajectory_pass"]]
    check_fails = {name: sum(1 for r in runs if not r["checks"][name]) for name in CHECKS}
    tool_choice_turns_ok = sum(
        1 for r in runs
        for t in r["transcript"]
        if not str(t.get("tool", "")).startswith("final_answer (forced")
        and str(t.get("tool", "")).strip() in {"search_contract", "list_section_headings", "final_answer"}
        and not t.get("parse_error")
    )
    model_turns = sum(
        1 for r in runs
        for t in r["transcript"]
        if not str(t.get("tool", "")).startswith("final_answer (forced")
    )
    return {
        "n": n,
        "outcome_pass": outcome_pass,
        "outcome_rate": outcome_pass / n,
        "trajectory_pass": traj_pass,
        "trajectory_rate": traj_pass / n,
        "both_pass": both,
        "lucky_path": lucky,
        "honest_fail": honest_fail,
        "double_fail": double_fail,
        "check_fails": check_fails,
        "tool_choice_accuracy": (tool_choice_turns_ok / model_turns) if model_turns else 1.0,
        "model_turns": model_turns,
        "forced_answers": sum(r["stopped_early"] for r in runs),
        "repairs": sum(r["repairs"] for r in runs),
        "dropped_citations": sum(len(r["dropped_citations"]) for r in runs),
        "quarantined": sum(len(r["quarantined_chunks"]) for r in runs),
        "cost": {
            "seconds": cost_stats([r["elapsed"] for r in runs]),
            "llm_calls": cost_stats([float(r["llm_calls"]) for r in runs]),
            "tool_calls": cost_stats([float(r["tool_calls"]) for r in runs]),
        },
    }


def fmt_cost(c):
    if not c:
        return "-"
    return (f"mean {c['mean']:.2f} · median {c['median']:.2f} · "
            f"p95 {c['p95']:.2f} · p99 {c['p99']:.2f} · max {c['max']:.2f}")


def write_report(rows, summaries, fp_flagged=None, n_chunks=None):
    base, guard = summaries["baseline"], summaries["guarded"]
    lines = ["# Week 8 Trajectory Eval Report — Track F (Legal Contracts)\n"]
    lines.append(
        "One command (`python agent_eval/traj_eval.py`): runs the Week 7 baseline agent and "
        "the Week 8 guarded agent over all 24 questions, grades each run on the OUTCOME "
        "(Week 7's rule check + Week 6's validated judge, unchanged) and independently on the "
        "PATH (six free trajectory checks in `trajectory.py`), then reports the gap between "
        "them plus cost per task.\n"
    )

    lines.append("## Headline\n")
    lines.append("| metric | baseline | guarded |")
    lines.append("|---|---|---|")
    lines.append(f"| outcome pass rate | {base['outcome_pass']}/{base['n']} ({base['outcome_rate']:.1%}) | "
                 f"{guard['outcome_pass']}/{guard['n']} ({guard['outcome_rate']:.1%}) |")
    lines.append(f"| trajectory pass rate | {base['trajectory_pass']}/{base['n']} ({base['trajectory_rate']:.1%}) | "
                 f"{guard['trajectory_pass']}/{guard['n']} ({guard['trajectory_rate']:.1%}) |")
    lines.append(f"| **outcome PASS + trajectory FAIL (right answer, wrong path)** | "
                 f"**{len(base['lucky_path'])}** | **{len(guard['lucky_path'])}** |")
    lines.append(f"| tool-choice accuracy (valid turns) | {base['tool_choice_accuracy']:.1%} | "
                 f"{guard['tool_choice_accuracy']:.1%} |")
    lines.append(f"| answers forced by budget fallback | {base['forced_answers']} | {guard['forced_answers']} |")
    lines.append(f"| turn repairs (invalid replies re-asked) | 0 (n/a) | {guard['repairs']} |")
    lines.append(f"| citations dropped by output validation | 0 (n/a) | {guard['dropped_citations']} |")
    lines.append(f"| chunks quarantined by the injection screen | 0 (n/a) | {guard['quarantined']} |\n")
    if fp_flagged is not None:
        lines.append(
            f"False-positive scan of the injection screen against the {n_chunks} legitimate contract "
            f"chunks: **{len(fp_flagged)}/{n_chunks} flagged** "
            f"({', '.join(map(str, fp_flagged)) if fp_flagged else 'none'}) — a screen that withholds "
            "real clauses would show up here as lost evidence.\n"
        )

    lines.append("## Outcome vs trajectory (the gap)\n")
    lines.append("| quadrant | baseline | guarded |")
    lines.append("|---|---|---|")
    lines.append(f"| outcome PASS · trajectory PASS (right answer, right path) | {base['both_pass']} | {guard['both_pass']} |")
    lines.append(f"| outcome PASS · trajectory FAIL (**lucky path**) | {len(base['lucky_path'])} | {len(guard['lucky_path'])} |")
    lines.append(f"| outcome FAIL · trajectory PASS (honest failure) | {len(base['honest_fail'])} | {len(guard['honest_fail'])} |")
    lines.append(f"| outcome FAIL · trajectory FAIL (double failure) | {len(base['double_fail'])} | {len(guard['double_fail'])} |")
    lines.append(f"\n- baseline lucky-path runs: {', '.join(base['lucky_path']) or 'none'}")
    lines.append(f"- guarded lucky-path runs: {', '.join(guard['lucky_path']) or 'none'}")
    lines.append(f"- baseline double-fail runs: {', '.join(base['double_fail']) or 'none'}")
    lines.append(f"- guarded double-fail runs: {', '.join(guard['double_fail']) or 'none'}\n")

    lines.append("## Where the outcome numbers moved\n")
    lines.append(
        "Outcome is graded the same way as Week 7 (keyword rule AND the Week 6 judge), "
        "recorded here as its two parts so a changed score can be attributed instead of "
        "hand-waved. A `-` judge cell means the judge verdict wasn't needed for that "
        "run (it isn't stored): the rule check already settled the outcome, since "
        "outcome = rule AND judge.\n"
    )
    moved = [r for r in rows if r["baseline"]["outcome_pass"] != r["guarded"]["outcome_pass"]]
    if not moved:
        lines.append("No outcome differences between the two agents on this run.\n")
    else:
        lines.append("| id | baseline rule | baseline judge | guarded rule | guarded judge | direction |")
        lines.append("|---|---|---|---|---|---|")
        for r in moved:
            b, g = r["baseline"], r["guarded"]
            direction = "baseline only" if b["outcome_pass"] else "guarded only"
            lines.append(
                f"| {r['id']} | {'ok' if b['rule_pass'] else 'miss'} | {b['judge_verdict'] or '-'} | "
                f"{'ok' if g['rule_pass'] else 'miss'} | {g['judge_verdict'] or '-'} | {direction} |"
            )
        lines.append("")
        for r in moved:
            b, g = r["baseline"], r["guarded"]
            winner, loser = (g, b) if g["outcome_pass"] else (b, g)
            who = "guarded" if g["outcome_pass"] else "baseline"
            lines.append(
                f"- **{r['id']}** → {who} only. Passing answer ({who}): "
                f"\"{(winner['answer'] or '')[:220]}\" · Other answer: "
                f"\"{(loser['answer'] or '')[:220]}\""
            )
        lines.append("")

    lines.append("## Failures by trajectory check (n = 24 runs each)\n")
    lines.append("| check | what it means | baseline fails | guarded fails |")
    lines.append("|---|---|---|---|")
    meaning = {
        "valid_turns": "tool-choice accuracy: every turn parsed to a known tool",
        "expected_order": "expected tool sequence: lookup first, search before answering",
        "self_terminated": "agent chose to finish instead of running out of budget",
        "citations_retrieved": "no fabricated evidence: cited chunks were actually retrieved",
        "no_repeat_search": "no looping: never re-ran an identical query",
        "args_in_bounds": "tool argument sanity: non-empty query, k within limits",
    }
    for name in CHECKS:
        lines.append(f"| `{name}` | {meaning[name]} | {base['check_fails'][name]} | {guard['check_fails'][name]} |")

    lines.append("\n## Cost per task\n")
    lines.append("| metric | baseline | guarded |")
    lines.append("|---|---|---|")
    lines.append(f"| seconds/question | {fmt_cost(base['cost']['seconds'])} | {fmt_cost(guard['cost']['seconds'])} |")
    lines.append(f"| LLM calls/question | {fmt_cost(base['cost']['llm_calls'])} | {fmt_cost(guard['cost']['llm_calls'])} |")
    lines.append(f"| tool calls/question | {fmt_cost(base['cost']['tool_calls'])} | {fmt_cost(guard['cost']['tool_calls'])} |")

    lines.append("\n## Per-question detail\n")
    lines.append("| id | baseline outcome | baseline trajectory | baseline failed checks | guarded outcome | guarded trajectory | guarded failed checks | base_s | guard_s |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        b, g = r["baseline"], r["guarded"]
        lines.append(
            f"| {r['id']} | {'PASS' if b['outcome_pass'] else 'FAIL'} | "
            f"{'PASS' if b['trajectory_pass'] else 'FAIL'} | {', '.join(b['failed_checks']) or '-'} | "
            f"{'PASS' if g['outcome_pass'] else 'FAIL'} | {'PASS' if g['trajectory_pass'] else 'FAIL'} | "
            f"{', '.join(g['failed_checks']) or '-'} | {b['elapsed']:.2f} | {g['elapsed']:.2f} |"
        )

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traj_report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSummary report written to {out}")

    traces_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traj_traces.json")
    with open(traces_path, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "summaries": summaries}, f, indent=2)
    print(f"Full per-run transcripts written to {traces_path}")


def finalize(rows, chunks):
    summaries = {name: agent_summary(rows, name) for name in AGENTS}
    for name, s in summaries.items():
        print(f"\n{name}: outcome {s['outcome_pass']}/{s['n']}, "
              f"trajectory {s['trajectory_pass']}/{s['n']}, "
              f"lucky-path {len(s['lucky_path'])}")
    from guarded_agent import screen_untrusted
    fp_flagged = [i for i, c in enumerate(chunks) if screen_untrusted(c.page_content)[1]]
    print(f"injection-screen false positives on legitimate chunks: {len(fp_flagged)}/{len(chunks)}")
    write_report(rows, summaries, fp_flagged, len(chunks))


def report_only():
    """Rebuild traj_report.md from saved traj_traces.json — no API calls.

    Used when the traces were produced by an earlier run of this harness: the
    rule check is recomputed offline (it's free), and the judge verdict is
    derived as `outcome = rule AND judge` for runs where the rule passed.
    A '-' judge cell therefore means "not run / irrelevant: the rule check
    already settled the outcome"."""
    from questions import QUESTIONS as QS

    traces_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traj_traces.json")
    with open(traces_path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data["rows"]
    for r in rows:
        q = next(x for x in QS if x["id"] == r["id"])
        for agent_name in AGENTS:
            cell = r[agent_name]
            if "rule_pass" in cell:
                continue
            rule_pass = rule_check(q, cell["answer"])
            cell["rule_pass"] = rule_pass
            cell["judge_verdict"] = ("PASS" if cell["outcome_pass"] else "FAIL") if rule_pass else None
    chunks = load_pdf_chunks(PDF_PATH)
    finalize(rows, chunks)


def main():
    args = sys.argv[1:]
    if "--report-only" in args:
        report_only()
        return

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("GROQ_API_KEY is not set in .env — this harness needs it. Aborting.")
        sys.exit(1)

    print(f"Loading + chunking {PDF_PATH} ...")
    chunks = load_pdf_chunks(PDF_PATH)
    index = ContractIndex(chunks)
    _ = index.reranker
    print(f"{len(chunks)} chunks. Index ready.\n")

    rows = run_all(api_key, index, chunks, resume="--resume" in args)
    finalize(rows, chunks)


if __name__ == "__main__":
    main()
