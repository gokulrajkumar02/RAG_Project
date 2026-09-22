"""
Week 7 - race the hand-built contract agent (contract_agent.py) against
the existing fixed pipeline (fixed_workflow.py). Same 24 questions
(eval/questions.py), same scoring (the rule check + LLM judge already
validated in Week 6 - eval/judge.py, eval/validate_judge.py - not
revalidated here since nothing about the judge changed).

Reports, per approach: pass rate (overall + per Week 5 problem_type),
total/average wall-clock seconds, and total/average LLM calls per
question (a cost proxy for call *volume* - see contract_agent.py's
AGENT_MODEL comment for why the fixed workflow's generation model
(openai/gpt-oss-20b) and the agent's decision model (openai/gpt-oss-120b)
ended up different, and agent/README.md for what that means for reading
the $ side of "cost" here, not just the call count).

This specifically tests whether the agent's retry/reformulate loop can
rescue the never_retrieved_* questions (`notice_period`, `overtime`,
`leave_approval`) that neither Week 4's reranker nor Week 6's
neighbor-stitch fix could touch, since both of those only ever look at
ONE search result - they can't try again with different words.

Usage:
    python agent/race.py
"""

import os
import sys
import json
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(REPO_ROOT, "eval")
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, EVAL_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from rag_core import load_pdf_chunks, ContractIndex
from questions import QUESTIONS
from judge import judge_answer

from contract_agent import run_agent
from fixed_workflow import run_fixed

PDF_PATH = os.path.join(REPO_ROOT, "data", "sample_contract.pdf")


def says_not_found(answer):
    return "not found" in answer.lower()


def keyword_match(answer, keywords):
    answer_lower = answer.lower()
    return any(kw.lower() in answer_lower for kw in keywords)


def rule_check(question, answer):
    if question.get("no_answer"):
        return says_not_found(answer)
    return keyword_match(answer, question["answer_keywords"]) and not says_not_found(answer)


def reference_text(question, chunks):
    if not question["expected_chunks"]:
        return ""
    return "\n\n---\n\n".join(chunks[i].page_content for i in question["expected_chunks"])


def score(question, answer, ref_text, api_key):
    passed_rule = rule_check(question, answer)
    if question.get("no_answer"):
        return passed_rule
    judge_result = judge_answer(question["question"], ref_text, answer, api_key)
    return passed_rule and judge_result["verdict"] == "PASS"


def run_race(api_key, index, chunks):
    rows = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"[{i}/{len(QUESTIONS)}] {q['id']} ...", flush=True)
        ref = reference_text(q, chunks)

        fixed = run_fixed(q["question"], index, api_key)
        fixed["passed"] = score(q, fixed["answer"], ref, api_key)

        agent = run_agent(q["question"], index, api_key)
        agent["passed"] = score(q, agent["answer"], ref, api_key)

        rows.append({
            "id": q["id"],
            "problem_type": q["problem_type"],
            "question": q["question"],
            "fixed": fixed,
            "agent": agent,
        })
    return rows


def _totals(rows, key):
    n = len(rows)
    passed = sum(r[key]["passed"] for r in rows)
    total_time = sum(r[key]["elapsed"] for r in rows)
    total_calls = sum(r[key]["llm_calls"] for r in rows)
    return {
        "n": n,
        "passed": passed,
        "pass_rate": passed / n if n else 0.0,
        "avg_seconds": total_time / n if n else 0.0,
        "total_seconds": total_time,
        "avg_llm_calls": total_calls / n if n else 0.0,
        "total_llm_calls": total_calls,
    }


def _by_problem_type(rows, key):
    groups = {}
    for r in rows:
        g = groups.setdefault(r["problem_type"], {"n": 0, "passed": 0})
        g["n"] += 1
        g["passed"] += int(r[key]["passed"])
    return groups


def print_report(rows):
    fixed_totals = _totals(rows, "fixed")
    agent_totals = _totals(rows, "agent")
    fixed_groups = _by_problem_type(rows, "fixed")
    agent_groups = _by_problem_type(rows, "agent")

    print("\n" + "=" * 100)
    print(f"{'id':<28}{'problem_type':<28}{'fixed':<8}{'agent':<8}{'fixed_s':<9}{'agent_s':<9}{'fixed_calls':<12}agent_calls")
    print("=" * 100)
    for r in rows:
        f, a = r["fixed"], r["agent"]
        print(
            f"{r['id']:<28}{r['problem_type']:<28}"
            f"{'PASS' if f['passed'] else 'FAIL':<8}{'PASS' if a['passed'] else 'FAIL':<8}"
            f"{f['elapsed']:<9.2f}{a['elapsed']:<9.2f}{f['llm_calls']:<12}{a['llm_calls']}"
        )

    print("\n" + "-" * 70)
    print("Score by problem type (Week 5 taxonomy)")
    print("-" * 70)
    print(f"{'problem_type':<32}{'fixed':<14}{'agent'}")
    for name in sorted(fixed_groups):
        fg, ag = fixed_groups[name], agent_groups[name]
        fixed_str = f"{fg['passed']}/{fg['n']}"
        agent_str = f"{ag['passed']}/{ag['n']}"
        print(f"{name:<32}{fixed_str:<14}{agent_str}")

    print("\n" + "-" * 70)
    print(f"{'metric':<28}{'fixed':<20}{'agent'}")
    print("-" * 70)
    fixed_pass_str = f"{fixed_totals['passed']}/{fixed_totals['n']} ({fixed_totals['pass_rate']:.1%})"
    agent_pass_str = f"{agent_totals['passed']}/{agent_totals['n']} ({agent_totals['pass_rate']:.1%})"
    print(f"{'pass rate':<28}{fixed_pass_str:<20}{agent_pass_str}")
    print(f"{'avg seconds/question':<28}{fixed_totals['avg_seconds']:<20.2f}{agent_totals['avg_seconds']:.2f}")
    print(f"{'total seconds':<28}{fixed_totals['total_seconds']:<20.1f}{agent_totals['total_seconds']:.1f}")
    print(f"{'avg LLM calls/question':<28}{fixed_totals['avg_llm_calls']:<20.2f}{agent_totals['avg_llm_calls']:.2f}")
    print(f"{'total LLM calls':<28}{fixed_totals['total_llm_calls']:<20}{agent_totals['total_llm_calls']}")
    print("-" * 70)

    return fixed_totals, agent_totals, fixed_groups, agent_groups


def write_report(rows, fixed_totals, agent_totals, fixed_groups, agent_groups):
    lines = ["# Week 7 Agent Race Report — Track F (Legal Contracts)\n"]
    lines.append(
        "One command (`python agent/race.py`): races the hand-built retry/reformulate "
        "agent (`contract_agent.py`) against the existing fixed pipeline "
        "(`fixed_workflow.py` — the same search_reranked + expand_with_neighbors + "
        "generate_answer app.py runs live) on the same 24 questions, scored with the "
        "Week 6 rule check + validated LLM judge.\n"
    )

    lines.append("## Overall\n")
    lines.append("| metric | fixed | agent |")
    lines.append("|---|---|---|")
    lines.append(f"| pass rate | {fixed_totals['passed']}/{fixed_totals['n']} ({fixed_totals['pass_rate']:.1%}) | "
                 f"{agent_totals['passed']}/{agent_totals['n']} ({agent_totals['pass_rate']:.1%}) |")
    lines.append(f"| avg seconds/question | {fixed_totals['avg_seconds']:.2f} | {agent_totals['avg_seconds']:.2f} |")
    lines.append(f"| total seconds | {fixed_totals['total_seconds']:.1f} | {agent_totals['total_seconds']:.1f} |")
    lines.append(f"| avg LLM calls/question | {fixed_totals['avg_llm_calls']:.2f} | {agent_totals['avg_llm_calls']:.2f} |")
    lines.append(f"| total LLM calls | {fixed_totals['total_llm_calls']} | {agent_totals['total_llm_calls']} |\n")

    lines.append("## Score by problem type\n")
    lines.append("| problem_type | fixed | agent |")
    lines.append("|---|---|---|")
    for name in sorted(fixed_groups):
        fg, ag = fixed_groups[name], agent_groups[name]
        lines.append(f"| {name} | {fg['passed']}/{fg['n']} | {ag['passed']}/{ag['n']} |")

    lines.append("\n## Per-question detail\n")
    lines.append("| id | problem_type | fixed | agent | fixed_s | agent_s | fixed_calls | agent_calls | agent tool calls |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        f, a = r["fixed"], r["agent"]
        lines.append(
            f"| {r['id']} | {r['problem_type']} | {'PASS' if f['passed'] else 'FAIL'} | "
            f"{'PASS' if a['passed'] else 'FAIL'} | {f['elapsed']:.2f} | {a['elapsed']:.2f} | "
            f"{f['llm_calls']} | {a['llm_calls']} | {a['tool_calls']} |"
        )

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "race_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSummary report written to {out_path}")

    traces_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "race_traces.json")
    with open(traces_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"Full per-question transcripts (every agent step) written to {traces_path}")


def main():
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("GROQ_API_KEY is not set in .env — this harness needs it. Aborting.")
        sys.exit(1)

    print(f"Loading + chunking {PDF_PATH} ...")
    chunks = load_pdf_chunks(PDF_PATH)
    index = ContractIndex(chunks)
    _ = index.reranker
    print(f"{len(chunks)} chunks. Index ready.\n")

    rows = run_race(api_key, index, chunks)
    fixed_totals, agent_totals, fixed_groups, agent_groups = print_report(rows)
    write_report(rows, fixed_totals, agent_totals, fixed_groups, agent_groups)


if __name__ == "__main__":
    main()
