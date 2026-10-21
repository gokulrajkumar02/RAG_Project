"""
Re-verifies the claims the Week 10 deliverables rest on. No API key, no embedding model, no network:
a tiny fake index, the offline stub and real localhost HTTP workers.

    python multi_agent/selfcheck.py

What it proves (and what it cannot): the PLUMBING and the ARITHMETIC are right - percentiles, token
sums, the multiplier, hand-off shares, the failure classifier, the 500 injection, the usage extraction
from a Groq-shaped reply, the 429 handling. It cannot prove anything about how a real model behaves;
that is what `multi_race.py --llm groq` is for.
"""

import json
import os
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "eval"), os.path.join(REPO_ROOT, "agent"), HERE):
    sys.path.insert(0, p)

from langchain_core.documents import Document  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import analysis  # noqa: E402
import cases as case_set  # noqa: E402
import contract_agent  # noqa: E402
import multi_race  # noqa: E402
import orchestrator  # noqa: E402
import workers  # noqa: E402
from contract_facts import load_facts  # noqa: E402
from llm import Call, GroqBackend, LLM, Meter, cost_usd, meter_single_agent  # noqa: E402
from stub_llm import StubBackend  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail and not ok else ""))


class FakeIndex:
    """Three chunks, same interface the real ContractIndex exposes to agent/tools.search_contract."""

    def __init__(self):
        texts = [
            'This Employment Agreement ("Agreement") is entered into as of January 1, 2024, between TechCorp Pvt. Ltd. '
            '("Company") and John Smith ("Employee").',
            "6. NOTICE PERIOD Either party may terminate this Agreement by providing 30 (thirty) days written notice.",
            "8. CONFIDENTIALITY The Employee agrees to keep all Confidential Information strictly private.",
        ]
        self.chunks = [Document(page_content=t, metadata={"chunk_idx": i}) for i, t in enumerate(texts)]

    def search_reranked(self, query, k=3, pool=10):
        return self.chunks[:k]

    def expand_with_neighbors(self, docs):
        return docs


def git_unchanged(path):
    try:
        head = subprocess.check_output(["git", "rev-parse", f"HEAD:{path}"], cwd=REPO_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
        work = subprocess.check_output(["git", "hash-object", path], cwd=REPO_ROOT, text=True).strip()
        return head == work
    except Exception:
        return None


def main():
    # ---- same ruler: cases and everything that scores them are untouched ----------------------------
    ids = case_set.PINNED_IDS
    check("10 pinned cases, unique", len(ids) == 10 and len(set(ids)) == 10)
    qs = case_set.load_cases()
    check("all pinned cases exist in eval/questions.py", [q["id"] for q in qs] == ids)
    check("every Week 5 problem_type is represented",
          {q["problem_type"] for q in qs} == {q["problem_type"] for q in __import__("questions").QUESTIONS})
    check("pinned + excluded = the whole Week 6 set", len(ids) + len(case_set.EXCLUDED_IDS) == 24)
    for f in ("eval/questions.py", "eval/judge.py", "agent/contract_agent.py", "agent/tools.py", "agent/race.py",
              "rag_core.py", "create_sample_pdf.py"):
        u = git_unchanged(f)
        check(f"{f} identical to git HEAD (untouched)", u is not False, "git not available" if u is None else "")

    # ---- facts ---------------------------------------------------------------------------------------
    facts = load_facts()
    check("effective date parsed from the contract", facts.effective_date == "January 1, 2024")
    check("4 defined terms parsed", set(facts.defined_terms) == {"Agreement", "Company", "Employee", "Confidential Information"})
    check("Confidential Information has 5 items", len(facts.defined_terms["Confidential Information"]["items"]) == 5)

    # ---- narrow specialists --------------------------------------------------------------------------
    check("clause worker lacks list_section_headings (fewer tools than the single agent)",
          "list_section_headings" not in workers.CLAUSE_PROMPT and "list_section_headings" in contract_agent.AGENT_SYSTEM_PROMPT)
    check("defined-terms worker prompt names no clause search", "search_clauses" not in workers.TERMS_PROMPT)
    check("synthesis prompt has no rule about unavailable workers (failure_case.md says so)",
          "unavailable" not in orchestrator.SYNTH_PROMPT.lower())

    # ---- arithmetic ----------------------------------------------------------------------------------
    check("nearest-rank p50 of 1..10 is 5", analysis.nearest_rank(list(range(10, 0, -1)), 50) == 5)
    check("nearest-rank p99 of 10 values is the max", analysis.nearest_rank([3, 1, 9, 2, 8, 4, 7, 5, 6, 10], 99) == 10)
    check("cost formula", abs(cost_usd(1000, 500) - 0.00045) < 1e-12)
    check("multiplier 2.94 -> 2.9", analysis.multiplier(1000, 2940) == 2.9)
    check("multiplier 3.0 -> 3.0", analysis.multiplier(1000, 3000) == 3.0)

    def call(arm, case, hand_off, n, role, p, c, source="api", resent=0):
        return Call(case, arm, hand_off, n, role, p, c, 0.1, 0.0, source, resent, 100)

    single_calls = [call("single", f"c{i}", "user -> single_agent", k, "single", 400, 50) for i in range(10) for k in (1, 2)]
    multi_calls = []
    for i in range(10):
        multi_calls += [call("multi", f"c{i}", "user -> manager", 1, "plan", 200, 30),
                        call("multi", f"c{i}", "manager -> clause_worker", 1, "clause", 300, 40),
                        call("multi", f"c{i}", "manager -> clause_worker", 2, "clause", 700, 90),
                        call("multi", f"c{i}", "workers -> manager", 1, "synth", 300, 60)]
    rows_s = [{"case": f"c{i}", "passed": i < 6, "latency_s": float(i + 1)} for i in range(10)]
    rows_m = [{"case": f"c{i}", "passed": i < 8, "latency_s": float(2 * (i + 1))} for i in range(10)]
    S, M = analysis.summarize_arm("single", rows_s, single_calls), analysis.summarize_arm("multi", rows_m, multi_calls)
    check("summary: pass/p50/p99", (S["passed"], S["p50_s"], S["p99_s"]) == (6, 5.0, 10.0) and M["p99_s"] == 20.0)
    check("summary: tokens add up", S["total_tokens"] == 20 * 450 and M["total_tokens"] == 10 * (230 + 340 + 790 + 360))
    check("summary: cost per question", abs(S["cost_per_q"] - cost_usd(8000, 1000) / 10) < 1e-12)
    shares = analysis.handoff_shares(multi_calls)
    check("hand-off shares sum to 100%", abs(sum(s for _l, _t, s in shares) - 1) < 1e-9)
    check("largest hand-off is the clause worker's call-2 re-send",
          "clause_worker, call 2" in shares[0][0] and "re-send" in shares[0][0], shares[0][0])
    check("hand-off tokens add up to the arm total", sum(t for _l, t, _s in shares) == M["total_tokens"])
    line = analysis.multiplier_line(S, M, shares)
    check("multiplier line: one decimal + named hand-off + share",
          line.startswith("Context re-send multiplier: 1.9x") and "clause_worker, call 2" in line and "% of all multi tokens" in line, line)
    check("rule: +2 cases at 2.9x keeps multi", analysis.decide({"passed": 6, "cost_per_q": 1.0}, {"passed": 8, "cost_per_q": 2.9})["keep_multi"])
    check("rule: +1 case is a tie, not a win", not analysis.decide({"passed": 6, "cost_per_q": 1.0}, {"passed": 7, "cost_per_q": 1.2})["keep_multi"])
    check("rule: +3 cases at 3.5x is still killed", not analysis.decide({"passed": 6, "cost_per_q": 1.0}, {"passed": 9, "cost_per_q": 3.5})["keep_multi"])

    # ---- failure classifier --------------------------------------------------------------------------
    def classify(answer, quotes, ok=False, attempts=2):
        return analysis.classify_failure(answer, ["Confidential Information"], {"ok": ok, "attempts": attempts, "status": 500},
                                         quotes, facts)["label"]
    items = "business plans, client lists, financial data, technical documentation, and trade secrets"
    check("classifier: retry that succeeds -> retried", classify("anything", [], ok=True, attempts=2) == "retried")
    check("classifier: disclosed gap -> degraded",
          classify("I could not verify the definition of Confidential Information, but clause 8 says it is private.", []) == "degraded")
    check("classifier: 'partial answer' wording -> degraded", classify("Partial answer: clause 8 requires secrecy.", []) == "degraded")
    check("classifier: unsupported definition, no disclosure -> lied",
          classify(f"Confidential Information means {items}.", ["The Employee agrees to keep all Confidential Information strictly private."]) == "lied")
    check("classifier: definition backed by clause quotes, no disclosure -> silent_omission",
          classify(f"Confidential Information means {items}.", [f"Confidential Information includes but is not limited to: {items}."]) == "silent_omission")
    check("classifier: no definition stated, no disclosure -> silent_omission",
          classify("Employees must keep company information private.", []) == "silent_omission")
    check("disclosure regex stays quiet on a normal answer", not analysis.discloses_gap("The notice period is 30 days."))

    # ---- the 500 is real, and the retry is visible ---------------------------------------------------
    meter = Meter()
    srv = workers.WorkerServer("w", lambda body: {"result": {"ok": 1}}, fail_cases={"bad"}).start()
    try:
        r = workers.post_task(srv.url, {"case": "bad"}, meter=meter, arm="multi_fail", case="bad", worker="w", backoff=0.01)
        check("injected case: HTTP 500 after 2 attempts, not ok", (r["ok"], r["status"], r["attempts"]) == (False, 500, 2), str(r))
        check("service saw 2 injected 500s", [h["status"] for h in srv.hits if h["injected"]] == [500, 500])
        check("both attempts are logged as hand-off events", [e["status"] for e in meter.events] == [500, 500])
        r = workers.post_task(srv.url, {"case": "fine"}, meter=meter, arm="multi", case="fine", worker="w", backoff=0.01)
        check("other cases are untouched by the injection", (r["ok"], r["attempts"]) == (True, 1))
    finally:
        srv.stop()
    r = workers.post_task(srv.url, {"case": "x"}, meter=meter, arm="multi", case="x", worker="w", backoff=0.01, timeout=2)
    check("dead worker: connection error is retried once, status None", (r["ok"], r["status"], r["attempts"]) == (False, None, 2))

    # ---- metering: usage from the API, 429 waits, estimates ------------------------------------------
    class FakeChat:
        def __init__(self, script):
            self.script = list(script)

        def invoke(self, prompt):
            x = self.script.pop(0)
            if isinstance(x, Exception):
                raise x
            return x

    class RateLimitError(Exception):
        status_code = 429

        def __init__(self, retry_after):
            self.response = types.SimpleNamespace(headers={"retry-after": retry_after})

    usage = {"input_tokens": 100, "output_tokens": 7, "total_tokens": 107}
    m = Meter()
    out = LLM(GroqBackend(None, llm=FakeChat([AIMessage(content="hi", usage_metadata=usage)])), m)("p", role="plan", hand_off="h", case="c", arm="multi")
    check("Groq usage_metadata is what gets recorded", (out, m.calls[0].prompt_tokens, m.calls[0].completion_tokens, m.calls[0].usage_source) == ("hi", 100, 7, "api"))
    m = Meter()
    LLM(GroqBackend(None, llm=FakeChat([RateLimitError("0.05"), AIMessage(content="ok", usage_metadata=usage)])), m)("p", role="plan", hand_off="h", case="c", arm="multi")
    check("429 is retried and the wait is measured, not hidden", len(m.calls) == 1 and 0.04 <= m.calls[0].throttle_wait_s < 1.0, str(m.calls and m.calls[0].throttle_wait_s))
    m = Meter()
    LLM(GroqBackend(None, llm=FakeChat([RateLimitError("0"), AIMessage(content="ok", usage_metadata=usage)])), m)("p", role="plan", hand_off="h", case="c", arm="multi")
    check("'retry-after: 0' means 0s, not the 2s fallback", m.calls[0].throttle_wait_s == 0.0, str(m.calls[0].throttle_wait_s))
    m = Meter()
    LLM(GroqBackend(None, llm=FakeChat([AIMessage(content="hello world")])), m)("a prompt", role="plan", hand_off="h", case="c", arm="multi")
    check("no usage in the reply -> flagged estimate", m.calls[0].usage_source == "estimate" and m.calls[0].prompt_tokens > 0)
    try:
        LLM(GroqBackend(None, llm=FakeChat([ValueError("boom")])), Meter())("p", role="plan", hand_off="h", case="c", arm="multi")
        check("non-429 errors propagate", False)
    except ValueError:
        check("non-429 errors propagate", True)
    m = Meter()
    llm = LLM(StubBackend(), m)
    llm("A" * 400 + " first", role="plan", hand_off="h", case="c", arm="multi")
    llm("A" * 400 + " first" + " B" * 100, role="plan", hand_off="h", case="c", arm="multi")
    check("context re-send is estimated from the shared prefix", 0 < m.calls[1].resent_est <= m.calls[1].prompt_tokens and m.calls[0].resent_est == 0)

    # ---- the Week 7 agent, untouched, runs through the meter -----------------------------------------
    idx = FakeIndex()
    m = Meter()
    llm = LLM(StubBackend(), m)
    current = {"case": "s1"}
    original = contract_agent._call_llm
    meter_single_agent(llm, current)
    try:
        res = contract_agent.run_agent("What is the notice period?", idx, "stub")
    finally:
        contract_agent._call_llm = original
    check("Week 7 agent runs unmodified under the meter (2 calls tagged single/s1)",
          [(c.arm, c.case) for c in m.calls] == [("single", "s1")] * 2 and "30" in res["answer"], str(res["answer"])[:80])

    # ---- orchestrator end to end (stub model, real HTTP workers) -------------------------------------
    m = Meter()
    llm = LLM(StubBackend(), m)
    seen = []
    real_clause = workers.make_clause_handler(llm, idx)
    clause_srv = workers.WorkerServer("clause", lambda body: (seen.append(body), real_clause(body))[1]).start()
    terms_srv = workers.WorkerServer("terms", workers.make_terms_handler(llm, facts)).start()
    bad_srv = workers.WorkerServer("terms-bad", workers.make_terms_handler(llm, facts), fail_cases={"t2"}).start()
    try:
        orch = orchestrator.Orchestrator(llm, m, facts, clause_srv.url, terms_srv.url)
        res = orch.run("What counts as secret information I'm not allowed to share?", "t1", "multi")
        roles = sorted(c.role for c in m.calls_for("multi", "t1"))
        check("manager delegates to both workers when a defined term matters",
              res["trace"]["delegated_to"] == ["clause_worker", "terms_worker"] and roles == ["clause", "clause", "plan", "synth", "terms", "terms"], str(roles))
        check("every brief carries the governing effective date", "January 1, 2024" in seen[0]["governing"] and "no amendments" in seen[0]["governing"])
        check("a brief is small: sub-task + question + governing line, not the contract", len(json.dumps(seen[0])) < 1000 and "strictly private" not in json.dumps(seen[0]))
        res = orch.run("What is the notice period?", "t3", "multi")
        check("no defined term in the plan -> defined-terms worker is not called",
              res["trace"]["delegated_to"] == ["clause_worker"] and len(m.calls_for("multi", "t3")) == 4 and "NOT REQUESTED" in res["trace"]["terms_result_text"])
        orch_bad = orchestrator.Orchestrator(llm, m, facts, clause_srv.url, bad_srv.url)
        res = orch_bad.run("What counts as secret information I'm not allowed to share?", "t2", "multi_fail")
        out = res["trace"]["outcomes"]["terms_worker"]
        check("injected 500 reaches the manager: 2 attempts, HTTP 500, synthesis told UNAVAILABLE",
              (out["ok"], out["attempts"], out["status"]) == (False, 2, 500) and res["trace"]["terms_result_text"].startswith("UNAVAILABLE"))
        check("answer still produced after the failure (and the run is classified)",
              bool(res["answer"]) and analysis.classify_failure(res["answer"], res["trace"]["terms_requested"], out,
                                                                res["trace"]["clause_quotes"], facts)["label"] in ("degraded", "lied", "silent_omission"))
    finally:
        for s in (clause_srv, terms_srv, bad_srv):
            s.stop()

    # ---- a blank model turn gets one metered retry (plan and synthesis) ------------------------------
    class FlakyBackend(StubBackend):
        def __init__(self):
            self.n = {}

        def invoke(self, prompt, role):
            self.n[role] = self.n.get(role, 0) + 1
            if role in ("plan", "synth") and self.n[role] == 1:
                return "", None, 0.0                     # the empty-turn quirk Week 7 documents
            return super().invoke(prompt, role)

    m = Meter()
    llm = LLM(FlakyBackend(), m)
    cs = workers.WorkerServer("clause", workers.make_clause_handler(llm, idx)).start()
    ts = workers.WorkerServer("terms", workers.make_terms_handler(llm, facts)).start()
    try:
        res = orchestrator.Orchestrator(llm, m, facts, cs.url, ts.url).run(
            "What counts as secret information I'm not allowed to share?", "f1", "multi")
        got = [c.role for c in m.calls_for("multi", "f1")]
        check("blank plan and blank synthesis are each retried once, and both retries are metered",
              got.count("plan") == 2 and got.count("synth") == 2, str(got))
        check("the retried plan is the one used (defined term requested)", res["trace"]["terms_requested"] == ["Confidential Information"])
        check("retries are labelled as retries in the hand-off log",
              any("retry after blank" in analysis.handoff_label(c) for c in m.calls if c.role == "plan" and c.call_no == 2))
    finally:
        cs.stop()
        ts.stop()

    # ---- failure_case.md for the two edge outcomes -----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        multi_race.write_failure_case(tmp, "groq", None)
        check("failure_case.md: --no-injection is stated, not crashed on",
              "Not run" in open(os.path.join(tmp, "failure_case.md"), encoding="utf-8").read())
        dud = {"case": "x", "question": "q", "answer": "a", "passed": False, "judge": None, "latency_s": 0.0,
               "trace": {"terms_requested": ["Company"], "delegated_to": ["clause_worker"], "outcomes": {}},
               "classification": {"label": "did_not_fire", "asserted": [], "unsupported": [], "line": "NOT TESTED: x"},
               "server_hits": [], "tries": 3, "tokens": 0, "clean": {}}
        multi_race.write_failure_case(tmp, "groq", dud)
        check("failure_case.md: an injection that never fired is reported as NOT TESTED",
              "NOT TESTED" in open(os.path.join(tmp, "failure_case.md"), encoding="utf-8").read())

    # ---- writers -------------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        for mode, s_sum, m_sum in (("stub", S, M), ("groq", S, M),
                                   ("groq", S, dict(M, passed=7))):
            multi_race.write_verdict(tmp, mode, s_sum, m_sum, shares)
            lines = open(os.path.join(tmp, "verdict.md"), encoding="utf-8").read().splitlines()
            sunk_at = next(i for i, l in enumerate(lines) if "Sunk-cost" in l)
            verdict_at = next(i for i, l in enumerate(lines) if l.startswith(("**KEEP", "NONE YET")))
            check(f"verdict.md ({mode}, {'keep' if '**KEEP the orchestrator' in ''.join(lines) else 'kill/none'}): <=10 lines, sunk-cost named BEFORE the verdict",
                  len(lines) <= 10 and sunk_at < verdict_at, f"{len(lines)} lines, sunk@{sunk_at} verdict@{verdict_at}")
        multi_race.write_verdict(tmp, "groq", S, M, shares)
        text = open(os.path.join(tmp, "verdict.md"), encoding="utf-8").read()
        check("real-mode verdict cites pass rate AND cost/latency numbers", "Pass rate:" in text and "Cost:" in text and "p99" in text)

    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
