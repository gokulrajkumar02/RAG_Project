"""
Week 6 — Evals & Error Analysis (Track F: Legal Contracts).

ONE command, does everything the brief asks for:
  1. Validates the LLM judge against human grading (eval/validate_judge.py)
     — before its number gets used for anything below.
  2. Runs the eval set (eval/questions.py, all 24 questions — the same set
     Week 5 turned into permanent regression tests) through the app's real
     retrieval + generation pipeline, TWICE:
       BEFORE - current context assembly (reranked chunks only)
       AFTER  - + the neighbor-stitch fix predicted in
                error_analysis/error_taxonomy.md ("Fix target for next
                iteration"): stitch in each retrieved chunk's immediate
                predecessor so a clause's lead-in/verb/number-continuation
                that fell on the other side of a 150-char chunk boundary is
                back in view.
  3. Scores every answer two ways:
       - free rule checks first (did it refuse when it shouldn't have /
         fail to refuse when it should / contain the required keyword)
       - the (now-validated) LLM judge for groundedness a keyword can't
         check (an answer that happens to contain/avoid the right words
         without actually being read off the right clause)
  4. Reports pass rate BEFORE vs AFTER, broken down by the Week 5 problem
     type (`problem_type` in questions.py), not just one overall number.

Usage:
    python eval/run_evals.py
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # non-interactive stdout without reconfigure (e.g. some IDE consoles)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from rag_core import load_pdf_chunks, ContractIndex, generate_answer
from questions import QUESTIONS
from judge import judge_answer
import validate_judge

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(REPO_ROOT, "data", "sample_contract.pdf")
K = 3
RERANK_POOL = 10


def says_not_found(answer):
    return "not found" in answer.lower()


def keyword_match(answer, keywords):
    answer_lower = answer.lower()
    return any(kw.lower() in answer_lower for kw in keywords)


def rule_check(question, answer):
    """
    Free, deterministic pass/fail — no API call. Catches most of the
    failures Week 5 found on its own: a "not found" refusal on a question
    that has an answer, a missing refusal on a no-answer control, or a
    generated answer that just doesn't contain the fact.
    """
    if question.get("no_answer"):
        return says_not_found(answer)
    return keyword_match(answer, question["answer_keywords"]) and not says_not_found(answer)


def reference_text(question, chunks):
    """Gold reference for the judge: the actual expected clause(s), independent
    of what retrieval happened to fetch — used for BEFORE/AFTER scoring
    (contrast with validate_judge.py, which judges against what was
    actually retrieved, to match the human's basis for grading)."""
    if not question["expected_chunks"]:
        return ""
    return "\n\n---\n\n".join(chunks[i].page_content for i in question["expected_chunks"])


def score_variant(question, answer, ref_text, api_key, run_judge):
    passed_rule = rule_check(question, answer)
    judge_result = None
    if run_judge and not question.get("no_answer"):
        judge_result = judge_answer(question["question"], ref_text, answer, api_key)
        passed = passed_rule and judge_result["verdict"] == "PASS"
    else:
        passed = passed_rule
    return {
        "answer": answer,
        "rule_pass": passed_rule,
        "judge_verdict": judge_result["verdict"] if judge_result else None,
        "judge_reason": judge_result["reason"] if judge_result else None,
        "passed": passed,
    }


def run_eval_set(index, chunks, api_key, run_judge):
    rows = []
    for q in QUESTIONS:
        reranked_docs = index.search_reranked(q["question"], k=K, pool=RERANK_POOL)
        expanded_docs = index.expand_with_neighbors(reranked_docs)

        before_answer = generate_answer(q["question"], reranked_docs, api_key)
        after_answer = generate_answer(q["question"], expanded_docs, api_key)

        ref = reference_text(q, chunks)
        before = score_variant(q, before_answer, ref, api_key, run_judge)
        after = score_variant(q, after_answer, ref, api_key, run_judge)

        rows.append({
            "id": q["id"],
            "problem_type": q["problem_type"],
            "question": q["question"],
            "before": before,
            "after": after,
        })
    return rows


def aggregate_by_problem_type(rows):
    groups = {}
    for r in rows:
        g = groups.setdefault(r["problem_type"], {"n": 0, "before": 0, "after": 0})
        g["n"] += 1
        g["before"] += int(r["before"]["passed"])
        g["after"] += int(r["after"]["passed"])
    return groups


def print_report(rows, groups, judge_rate, run_judge):
    n = len(rows)
    before_total = sum(r["before"]["passed"] for r in rows)
    after_total = sum(r["after"]["passed"] for r in rows)

    print("\n" + "=" * 100)
    print(f"{'id':<28}{'problem_type':<28}{'before':<8}{'after':<8}")
    print("=" * 100)
    for r in rows:
        before_mark = "PASS" if r["before"]["passed"] else "FAIL"
        after_mark = "PASS" if r["after"]["passed"] else "FAIL"
        print(f"{r['id']:<28}{r['problem_type']:<28}{before_mark:<8}{after_mark:<8}")

    print("\n" + "-" * 60)
    print("Score by problem type (Week 5 taxonomy)")
    print("-" * 60)
    print(f"{'problem_type':<32}{'before':<14}{'after'}")
    for name, g in sorted(groups.items()):
        b = f"{g['before']}/{g['n']} ({g['before']/g['n']:.0%})"
        a = f"{g['after']}/{g['n']} ({g['after']/g['n']:.0%})"
        print(f"{name:<32}{b:<14}{a}")

    print("\n" + "-" * 60)
    print(f"OVERALL  BEFORE: {before_total}/{n} = {before_total/n:.1%}")
    print(f"OVERALL  AFTER:  {after_total}/{n} = {after_total/n:.1%}")
    print("-" * 60)

    if run_judge and judge_rate < validate_judge.AGREEMENT_THRESHOLD:
        print(
            f"\n!! Judge/human agreement was only {judge_rate:.1%} (below "
            f"{validate_judge.AGREEMENT_THRESHOLD:.0%}) — treat the rule-only "
            f"signal (keyword + refusal checks) as the trustworthy number "
            f"here, not the judge-gated pass/fail above."
        )


def write_report(rows, groups, judge_rows, judge_agree, judge_n, judge_rate, run_judge):
    n = len(rows)
    before_total = sum(r["before"]["passed"] for r in rows)
    after_total = sum(r["after"]["passed"] for r in rows)

    lines = ["# Week 6 Eval Report — Track F (Legal Contracts)\n"]
    lines.append(
        "One command (`python eval/run_evals.py`): validates the judge, "
        "runs all 24 questions before/after the neighbor-stitch fix "
        "(`ContractIndex.expand_with_neighbors`, `rag_core.py`), scores "
        "each with free rule checks + the validated LLM judge, and reports "
        "before/after per Week 5 problem type.\n"
    )

    lines.append("## Judge validation\n")
    lines.append(f"Agreement with human grading (`error_analysis/open_coding_notes.md`): "
                 f"**{judge_agree}/{judge_n} = {judge_rate:.1%}** "
                 f"(trust threshold: {validate_judge.AGREEMENT_THRESHOLD:.0%}). "
                 f"Full breakdown: [`judge_validation.md`](judge_validation.md).\n")

    lines.append("## Score by problem type\n")
    lines.append("| problem_type | before | after |")
    lines.append("|---|---|---|")
    for name, g in sorted(groups.items()):
        lines.append(
            f"| {name} | {g['before']}/{g['n']} ({g['before']/g['n']:.0%}) | "
            f"{g['after']}/{g['n']} ({g['after']/g['n']:.0%}) |"
        )
    lines.append(f"\n**OVERALL — before: {before_total}/{n} = {before_total/n:.1%}, "
                 f"after: {after_total}/{n} = {after_total/n:.1%}**\n")

    lines.append("## Per-question detail\n")
    lines.append("| id | problem_type | before | after | before answer | after answer | judge reason (after) |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        b = "PASS" if r["before"]["passed"] else "FAIL"
        a = "PASS" if r["after"]["passed"] else "FAIL"
        reason = r["after"]["judge_reason"] or ""
        lines.append(
            f"| {r['id']} | {r['problem_type']} | {b} | {a} | "
            f"{r['before']['answer']} | {r['after']['answer']} | {reason} |"
        )

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nFull report written to {out_path}")


def main():
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("GROQ_API_KEY is not set in .env — this harness needs it for both "
              "answer generation and the LLM judge. Aborting.")
        sys.exit(1)

    print("Step 1/3 — Validating the LLM judge against human grading ...")
    judge_rows, judge_agree, judge_n, judge_rate = validate_judge.validate(api_key)
    validate_judge.print_and_write(judge_rows, judge_agree, judge_n, judge_rate)
    run_judge = judge_rate >= validate_judge.AGREEMENT_THRESHOLD
    if not run_judge:
        print(
            "\nJudge did not clear the trust threshold — run_evals.py will still "
            "run, but scoring below falls back to rule checks only (no judge gate)."
        )

    print(f"\nStep 2/3 — Loading + chunking {PDF_PATH} ...")
    chunks = load_pdf_chunks(PDF_PATH)
    print(f"{len(chunks)} chunks (chunk_size=150, chunk_overlap=20)")
    print("Building semantic (FAISS) index + loading cross-encoder reranker ...")
    index = ContractIndex(chunks)
    _ = index.reranker  # force-load once, up front
    print("Done.")

    print("\nStep 3/3 — Running eval set before/after the neighbor-stitch fix "
          f"({len(QUESTIONS)} questions, 2 generations + up to 2 judge calls each) ...")
    rows = run_eval_set(index, chunks, api_key, run_judge)
    groups = aggregate_by_problem_type(rows)

    print_report(rows, groups, judge_rate, run_judge)
    write_report(rows, groups, judge_rows, judge_agree, judge_n, judge_rate, run_judge)


if __name__ == "__main__":
    main()
