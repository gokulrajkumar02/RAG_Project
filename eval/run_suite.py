"""
Week 11 - the regression suite: the 24 Week-6 questions (questions.py) + every production failure turned into
a case (regression_cases.py), run through the SERVED pipeline (observability/pipeline.py: the app's retrieval,
neighbour stitch and model) under one named prompt version, and scored with Week 6's own checks.

    python eval/run_suite.py --pv answer-v2 --label before
    python eval/run_suite.py --pv answer-v3 --label after --compare before

Scoring, per case - all must hold:
  * Week 6 rule check (run_evals.rule_check): required keyword present, no wrong refusal / missing refusal
  * citation check, for cases that carry one (observability/citations.py): cites every required clause,
    nothing outside the allowed ones
  * the Week 6 LLM judge (judge.py, openai/gpt-oss-120b), validated against the human labels first exactly
    as run_evals.py does; with --llm stub it is a stand-in that defers to the checks above
Also printed, every run:
  * REPLAY: each regression case's logged bad answer through the same checks. It must FAIL - that is the
    proof the test catches the failure that happened, independent of what the model says today.
  * citation accuracy over the Week-6 questions (answers that cite a clause vs the clause their gold chunks
    belong to). Not part of pass/fail - the Week-6 cases predate citations - but a fix that only repairs
    the one reported question shows up here.
  * with --compare: every case whose result changed since that run, PASS->FAIL first.

Output goes to the console and to observability/deliverables/suite_<label>.txt / .json.
"""

import argparse
import io
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
OBS_DIR = os.path.join(REPO_ROOT, "observability")
for _p in (REPO_ROOT, EVAL_DIR, OBS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

import citations  # noqa: E402
import prompts  # noqa: E402
import validate_judge  # noqa: E402
from judge import JUDGE_MODEL, judge_answer  # noqa: E402
from pipeline import EVAL_LOG_DIR, MODEL, Pipeline  # noqa: E402
from questions import QUESTIONS  # noqa: E402
from regression_cases import REGRESSION_CASES  # noqa: E402
from run_evals import reference_text, rule_check  # noqa: E402
from tracing import JsonlSink  # noqa: E402

load_dotenv()
OUT_DIR = os.path.join(OBS_DIR, "deliverables")
MAX_429_RETRIES = 6


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def with_429_retry(fn, *args):
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            return fn(*args)
        except Exception as exc:
            limited = exc.__class__.__name__ == "RateLimitError" or getattr(exc, "status_code", None) == 429
            if not limited or attempt == MAX_429_RETRIES:
                raise
            time.sleep(min(2 ** attempt * 2, 30))


def score(case, answer, ref, judge):
    """(passed, why, detail) with the same checks for live answers and replays."""
    rule = rule_check(case, answer)
    cit = None
    if case.get("citation"):
        cit = citations.check(answer, case["citation"]["required"], case["citation"].get("allowed"))
    verdict = None
    if judge and not case.get("no_answer"):
        verdict = judge(case["question"], ref, answer)
    why = []
    if not rule:
        why.append("refused" if "not found" in answer.lower() else "keyword missing" if not case.get("no_answer")
                   else "did not refuse")
    if cit and not cit["pass"]:
        bits = []
        if cit["missing"]:
            bits.append(f"missing {cit['missing']}")
        if cit["outside"]:
            bits.append(f"cited {cit['outside']} (allowed {cit['allowed']})")
        why.append("citation: " + ", ".join(bits) if bits else "citation")
    if verdict and verdict["verdict"] != "PASS":
        why.append(f"judge: {verdict['reason']}")
    passed = rule and (cit is None or cit["pass"]) and (verdict is None or verdict["verdict"] == "PASS")
    return passed, "; ".join(why), {"rule": rule, "citation": cit, "judge": verdict}


def citation_accuracy(rows, clause_map):
    tally = {"correct": 0, "wrong": 0, "uncited": 0, "scored": 0, "wrong_ids": []}
    for r in rows:
        if r["kind"] != "week6" or r["no_answer"]:
            continue
        gold = [c for c in clause_map.clauses_for(r["expected_chunks"]) if c.isdigit()]
        if not gold or "not found" in r["answer"].lower():
            continue
        tally["scored"] += 1
        cited = citations.cited_clauses(r["answer"])
        if not cited:
            tally["uncited"] += 1
        elif set(cited) <= set(gold):
            tally["correct"] += 1
        else:
            tally["wrong"] += 1
            tally["wrong_ids"].append(f"{r['id']} (cited {cited}, clause {gold})")
    return tally


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pv", required=True, help="prompt version to run, e.g. answer-v2")
    ap.add_argument("--label", required=True, help="output name: suite_<label>.txt/.json")
    ap.add_argument("--llm", choices=["auto", "groq", "stub"], default="auto")
    ap.add_argument("--compare", help="label of an earlier run to diff against")
    ap.add_argument("--skip-judge-validation", action="store_true")
    ap.add_argument("--pace", type=float, default=None, help="seconds between cases (default 3 with groq)")
    a = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    txt_path = os.path.join(OUT_DIR, f"suite_{a.label}.txt")
    log_file = open(txt_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)

    spec = prompts.get(a.pv)
    pipe = Pipeline(llm=a.llm, log_dir=None)
    pipe.warm()
    real = pipe.llm_mode == "groq"
    api_key = os.getenv("GROQ_API_KEY", "")
    pace = a.pace if a.pace is not None else (3.0 if real else 0.0)

    print("=" * 112)
    print(f"REGRESSION SUITE  label={a.label}  prompt={a.pv} (sha {spec['sha']}, context {spec['context_format']})")
    if real:
        print(f"MODE: GROQ - answers from {MODEL}, judge {JUDGE_MODEL}")
    else:
        print("MODE: STUB - no GROQ_API_KEY. Answers come from observability/stub_llm.py, a rule-based stand-in, "
              "NOT a model;\n      the judge defers to the rule + citation checks. Shows the plumbing and the "
              "test working, not model behaviour.")
    print(f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 112)

    judge = None
    if real:
        if a.skip_judge_validation:
            judge_ok = True
            print("judge validation skipped (--skip-judge-validation); last recorded result: eval/judge_validation.md")
        else:
            print("validating the judge against the human labels (eval/validate_judge.py) ...")
            # same validation as run_evals.py; only its judge calls are routed through the 429 retry
            validate_judge.judge_answer = lambda *args: with_429_retry(judge_answer, *args)
            _rows, agree, n, rate = validate_judge.validate(api_key)
            judge_ok = rate >= validate_judge.AGREEMENT_THRESHOLD
            print(f"judge/human agreement {agree}/{n} = {rate:.1%} -> "
                  f"{'judge used' if judge_ok else 'BELOW threshold: rule + citation checks only'}")
        if judge_ok:
            judge = lambda q, ref, ans: with_429_retry(judge_answer, q, ref, ans, api_key)  # noqa: E731
    else:
        from stub_llm import stub_judge
        judge = stub_judge

    sink = JsonlSink(os.path.join(EVAL_LOG_DIR, a.label))
    for name in os.listdir(sink.log_dir):          # one run per label: start the label's trace log fresh
        if name.startswith("traces-"):
            os.remove(os.path.join(sink.log_dir, name))
    cases = [dict(q, kind="week6") for q in QUESTIONS] + [dict(c, kind="regression") for c in REGRESSION_CASES]
    rows = []
    print(f"\n{'id':<38}{'problem_type':<32}{'result':<8}why")
    print("-" * 112)
    for case in cases:
        res = pipe.ask(case["question"], user_id="eval-suite", user_role="eval", prompt_version=a.pv, sink=sink)
        ref = reference_text(case, pipe.chunks)
        passed, why, detail = score(case, res["answer"], ref, judge)
        rows.append({"id": case["id"], "kind": case["kind"], "problem_type": case["problem_type"],
                     "passed": passed, "why": why, "answer": res["answer"], "detail": detail,
                     "no_answer": bool(case.get("no_answer")), "expected_chunks": case["expected_chunks"],
                     "trace_id": res["trace"]["trace_id"],
                     "context_chunk_ids": res["trace"]["retrieval"]["context_chunk_ids"]})
        print(f"{case['id']:<38}{case['problem_type']:<32}{'PASS' if passed else 'FAIL':<8}{why}")
        if pace:
            time.sleep(pace)

    n = len(rows)
    total = sum(r["passed"] for r in rows)
    w6 = [r for r in rows if r["kind"] == "week6"]
    reg = [r for r in rows if r["kind"] == "regression"]
    print("-" * 112)
    print(f"SUITE: {total}/{n} passed   (Week-6 questions {sum(r['passed'] for r in w6)}/{len(w6)}, "
          f"regression cases {sum(r['passed'] for r in reg)}/{len(reg)})")

    for r in reg:
        print(f"\n[{r['id']}] live answer under {a.pv}: {'PASS (GREEN)' if r['passed'] else 'FAIL (RED)'}")
        print(f"    answer: {r['answer']}")
        cit = r["detail"]["citation"]
        if cit:
            print(f"    cited {cit['cited']}  required {cit['required']}  allowed {cit['allowed']}")
        print(f"    context chunk ids: {r['context_chunk_ids']}  trace {r['trace_id']}")

    replays = []
    for case in REGRESSION_CASES:
        passed, why, _d = score(case, case["logged_answer"], reference_text(case, pipe.chunks), judge)
        replays.append({"id": case["id"], "passed": passed, "why": why})
        verdict = "FAIL - the test catches the logged failure" if not passed else \
            "PASS - WARNING: this test does not catch the failure it was written for"
        print(f"\nREPLAY [{case['id']}] logged answer ({case['source']['prompt_version']}, "
              f"trace {case['source']['trace_id'][:8]}): {verdict}")
        print(f"    {why}")

    acc = citation_accuracy(rows, pipe.clause_map)
    print(f"\nCitation accuracy over Week-6 questions answered (not refused) with a gold clause: "
          f"{acc['correct']} right / {acc['wrong']} wrong / {acc['uncited']} uncited  (of {acc['scored']})")
    for w in acc["wrong_ids"]:
        print(f"    wrong: {w}")

    if a.compare:
        with open(os.path.join(OUT_DIR, f"suite_{a.compare}.json"), encoding="utf-8") as f:
            before = {r["id"]: r for r in json.load(f)["rows"]}
        print(f"\nCHANGES vs '{a.compare}':")
        flips = [(r["id"], before[r["id"]]["passed"], r["passed"]) for r in rows
                 if r["id"] in before and before[r["id"]]["passed"] != r["passed"]]
        new = [r["id"] for r in rows if r["id"] not in before]
        regressions = [f for f in flips if f[1] and not f[2]]
        for cid, _b, _a in regressions:
            print(f"    REGRESSION  {cid}: PASS -> FAIL")
        for cid, b, aft in flips:
            if not (b and not aft):
                print(f"    fixed       {cid}: FAIL -> PASS")
        for cid in new:
            print(f"    new case    {cid}")
        if not flips and not new:
            print("    none")
        print(f"    => {len(regressions)} regression(s); before {sum(r['passed'] for r in before.values())}/"
              f"{len(before)}, now {total}/{n}")

    with open(os.path.join(OUT_DIR, f"suite_{a.label}.json"), "w", encoding="utf-8") as f:
        json.dump({"label": a.label, "prompt_version": a.pv, "prompt_sha": spec["sha"], "llm_mode": pipe.llm_mode,
                   "passed": total, "n": n, "rows": rows, "replays": replays, "citation_accuracy": acc},
                  f, indent=2, ensure_ascii=False)
    print(f"\nwritten: {os.path.relpath(txt_path, REPO_ROOT)} (+ .json); traces: "
          f"{os.path.relpath(sink.log_dir, REPO_ROOT)}")
    sys.stdout = sys.__stdout__
    log_file.close()


if __name__ == "__main__":
    main()
