"""
Judge validation: does the LLM judge (judge.py) agree with human grading,
before anything trusts its number?

Ground truth is `human_verdict` on each question in eval/questions.py,
copied over from error_analysis/open_coding_notes.md — a human reading the
actual retrieved chunks and actual generated answer for all 24 Week 5
traces (error_analysis/traces.json), one line per trace, PASS or one
honest sentence on what went wrong.

The judge is graded against those SAME traces — same retrieved context,
same generated answer the human read — not against some idealized "gold"
context, since that's the evidence the human verdict is actually based on.
Anything else would be comparing the judge to a different question than
the one the human answered.

Usage:
    python eval/validate_judge.py
"""

import os
import sys
import json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # non-interactive stdout without reconfigure (e.g. some IDE consoles)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from questions import QUESTIONS
from judge import judge_answer

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACES_PATH = os.path.join(REPO_ROOT, "error_analysis", "traces.json")
AGREEMENT_THRESHOLD = 0.80  # below this, run_evals.py should not trust the judge


def validate(api_key):
    with open(TRACES_PATH, encoding="utf-8") as f:
        traces = {t["id"]: t for t in json.load(f)}

    questions_by_id = {q["id"]: q for q in QUESTIONS}

    rows = []
    for qid, trace in traces.items():
        question = questions_by_id.get(qid)
        if question is None or "human_verdict" not in question:
            continue

        reference_context = "\n\n---\n\n".join(
            chunk["content"] for chunk in trace["retrieved"]
        )
        result = judge_answer(trace["question"], reference_context, trace["answer"], api_key)

        human = question["human_verdict"]
        judge_verdict = result["verdict"]
        rows.append({
            "id": qid,
            "problem_type": question["problem_type"],
            "human": human,
            "judge": judge_verdict,
            "match": human == judge_verdict,
            "reason": result["reason"],
        })

    n = len(rows)
    agree = sum(r["match"] for r in rows)
    rate = agree / n if n else 0.0
    return rows, agree, n, rate


def print_and_write(rows, agree, n, rate):
    print("=" * 100)
    print(f"{'id':<28}{'problem_type':<28}{'human':<8}{'judge':<8}{'match':<7}reason")
    print("=" * 100)
    for r in rows:
        print(
            f"{r['id']:<28}{r['problem_type']:<28}{r['human']:<8}{r['judge']:<8}"
            f"{str(r['match']):<7}{r['reason']}"
        )

    print("\n" + "-" * 60)
    print(f"Judge/human agreement: {agree}/{n} = {rate:.1%}")
    print("-" * 60)

    disagreements = [r for r in rows if not r["match"]]
    if disagreements:
        print(f"\nDisagreements ({len(disagreements)}): {[r['id'] for r in disagreements]}")

    if rate < AGREEMENT_THRESHOLD:
        print(f"\n!! Agreement below {AGREEMENT_THRESHOLD:.0%} — do NOT trust this judge's before/after numbers yet.")
    else:
        print(f"\nAgreement at or above {AGREEMENT_THRESHOLD:.0%} — judge is trusted for run_evals.py.")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judge_validation.md")
    lines = ["# Judge Validation — Track F (Legal Contracts)\n"]
    lines.append(
        "Judge graded against the same 24 human-labeled traces from "
        "`error_analysis/open_coding_notes.md`, using the exact retrieved "
        "context and generated answer the human read "
        "(`error_analysis/traces.json`).\n"
    )
    lines.append(f"**Agreement: {agree}/{n} = {rate:.1%}** "
                 f"(trust threshold: {AGREEMENT_THRESHOLD:.0%})\n")
    lines.append("| id | problem_type | human | judge | match | judge reason |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['problem_type']} | {r['human']} | {r['judge']} | "
            f"{r['match']} | {r['reason']} |"
        )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nFull report written to {out_path}")


def main():
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("GROQ_API_KEY is not set in .env — the judge needs it. Aborting.")
        sys.exit(1)

    rows, agree, n, rate = validate(api_key)
    print_and_write(rows, agree, n, rate)


if __name__ == "__main__":
    main()
