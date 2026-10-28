"""
Offline checks for the Week 11 work - no API key, no network, no model. Run after any change:

    python observability/selfcheck.py

Covers: the served prompt v1 is still byte-identical to rag_core's; the instrumented retrieval returns exactly
what rag_core returns; the clause map; the citation parser; trace arithmetic (stage costs add up, every span
timed); the log CLI's slices; a drill plant lands in time order and looks like its neighbours; the regression
case still fails on its logged answer and still passes on a correct one; and the files earlier weeks pin to
git HEAD are untouched.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (REPO_ROOT, HERE, os.path.join(REPO_ROOT, "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def git_unchanged(path):
    try:
        head = subprocess.check_output(["git", "rev-parse", f"HEAD:{path}"], cwd=REPO_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
        work = subprocess.check_output(["git", "hash-object", path], cwd=REPO_ROOT, text=True).strip()
        return head == work
    except Exception:
        return None


def rec_v2_spans(pipe):
    return pipe.ask("What is the notice period?", prompt_version="answer-v2", write=False)["trace"]["spans"]


def main():
    import citations
    import prompts
    import tracing
    from clauses import ClauseMap
    from pipeline import Pipeline, classify_input, route
    from questions import QUESTIONS
    from rag_core import ANSWER_PROMPT
    from regression_cases import REGRESSION_CASES

    # ---- untouched earlier-week files --------------------------------------------------------------
    for f in ("rag_core.py", "eval/questions.py", "eval/judge.py", "eval/run_evals.py", "eval/validate_judge.py",
              "agent/contract_agent.py", "create_sample_pdf.py"):
        u = git_unchanged(f)
        check(f"{f} identical to git HEAD", u is not False, "git unavailable" if u is None else "")

    # ---- prompts --------------------------------------------------------------------------------
    check("answer-v1 is rag_core.ANSWER_PROMPT, byte for byte", prompts.PROMPTS["answer-v1"]["template"] == ANSWER_PROMPT)
    check("every prompt version renders with {context} and {question}",
          all("{context}" in p["template"] and "{question}" in p["template"] for p in prompts.PROMPTS.values()))
    shas = [prompts.get(v)["sha"] for v in prompts.PROMPTS]
    check("prompt shas are distinct per version", len(set(shas)) == len(shas))

    # ---- pipeline vs rag_core ---------------------------------------------------------------------
    pipe = Pipeline(llm="stub", log_dir=None)
    pipe.warm()
    same = True
    for q in QUESTIONS:
        t = pipe.ask(q["question"], prompt_version="answer-v1", write=False)["trace"]
        ref = pipe.index.search_reranked(q["question"], k=3, pool=10)
        ctx = pipe.index.expand_with_neighbors(ref)
        same &= t["retrieval"]["source_chunk_ids"] == [d.metadata["chunk_idx"] for d in ref]
        same &= t["retrieval"]["context_chunk_ids"] == [d.metadata["chunk_idx"] for d in ctx]
    check("instrumented retrieval == rag_core search_reranked + expand_with_neighbors (24 questions)", same)
    docs = [pipe.chunks[i] for i in (17, 18)]
    check("plain context == rag_core.generate_answer's assembly",
          prompts.render_context(docs, "plain") == "\n\n---\n\n".join(d.page_content for d in docs))

    # ---- clause map ---------------------------------------------------------------------------------
    cm = pipe.clause_map
    check("clause map: chunk 18 text is clause 7, its trailing heading is clause 8",
          cm.chunk_segments(18)[0][0] == "7" and cm.chunk_segments(18)[-1][:1] == ("8",)
          and cm.body_clauses(18) == ["7"])
    check("clause map: chunk 15 text is clause 6, its trailing heading is clause 7", cm.body_clauses(15) == ["6"])
    check("clause map: chunk 17 (page 2, no heading) is clause 7", cm.body_clauses(17) == ["7"])
    check("clause map: 11 numbered clauses found", cm.numbered() == [str(i) for i in range(1, 12)], cm.numbered())
    check("clause map: clause 7 text lives in chunks 16-18", cm.chunks_with_body("7") == [16, 17, 18])
    with open(os.path.join(REPO_ROOT, "create_sample_pdf.py"), encoding="utf-8") as f:
        src = f.read()
    for i in range(1, 12):
        title = cm.title(str(i))
        check(f"clause {i} heading '{title}' is in the PDF source text", title in src)

    # ---- the fix: answer-v3's clause context ------------------------------------------------------------
    ids, order = cm.expand_to_clauses([15, 16, 17])
    check("expand_to_clauses: chunks 15-17 -> clauses 6 and 7 served whole", order == ["6", "7"]
          and ids == [14, 15, 16, 17, 18], (ids, order))
    v3_ctx = prompts.render_context([pipe.chunks[i] for i in ids], "clause", cm)
    block7 = v3_ctx.split("[Clause 7 - TERMINATION]\n", 1)[-1]
    check("answer-v3 context: clause 7 block holds all five grounds",
          all(g in block7 for g in ("Gross misconduct", "Persistent underperformance", "Theft, fraud",
                                    "Serious or repeated breach", "Willful breach of confidentiality")))
    check("answer-v3 context: no clause block carries the next clause's heading",
          "7. TERMINATION" not in v3_ctx.split("[Clause 7")[0] and "8. CONFIDENTIALITY" not in v3_ctx)
    check("answer-v3 context: page furniture dropped", "Page 1" not in v3_ctx and "- Confidential" not in v3_ctx)
    t3 = pipe.ask("Can TechCorp terminate John Smith with immediate effect over repeated breaches of company "
                  "policy, or does it have to serve notice first?", prompt_version="answer-v3", write=False)["trace"]
    check("answer-v3 trace: retrieval.expand_clauses span logged and chunk 18 now in context",
          any(s["name"] == "retrieval.expand_clauses" for s in t3["spans"])
          and 18 in t3["retrieval"]["context_chunk_ids"])
    check("answer-v1/v2 traces have no expand_clauses span (the fix is opt-in by prompt version)",
          not any(s["name"] == "retrieval.expand_clauses" for s in rec_v2_spans(pipe)))

    # ---- the w11.2 output index ----------------------------------------------------------------------
    import index_fields
    bad = ("It can terminate with immediate effect. A serious or repeated breach of Company policies is one of the "
           "grounds on which the Company may terminate immediately and without notice, so no notice period has to "
           "be served. See Clause 6 (Notice Period).")
    d = index_fields.derive(bad, [0, 1, 15, 16, 17], cm)
    check("index: drill #1's logged answer is flagged citation_mismatch", d["citation_mismatch"]
          and d["answer_cited_clauses"] == ["6"] and d["context_clause_ids"] == ["6", "7"], d)
    good = ("Yes. The Company reserves the right to pay salary in lieu of notice and ask the Employee to leave "
            "immediately. (Clause 6 (Notice Period))")
    check("index: a correct cited answer is not flagged", not index_fields.derive(good, [14, 15, 16], cm)["citation_mismatch"])
    check("index: citing a clause the model never read is flagged",
          index_fields.derive("Yes (Clause 9).", [14, 15], cm)["citation_mismatch"])
    check("index: an answer with no citation is not flagged",
          not index_fields.derive("30 days' notice.", [14, 15], cm)["citation_mismatch"])
    check("trace: new traces are written with schema w11.2 and the index fields",
          t3["schema"] == "w11.2" and all(k in t3 for k in ("answer_cited_clauses", "context_clause_ids",
                                                             "citation_support", "citation_mismatch")))

    # ---- citations ----------------------------------------------------------------------------------
    cases = {
        "Under Clause 8 (Confidentiality), yes.": ["8"], "See clauses 6 and 7.": ["6", "7"], "(Section 7)": ["7"],
        "per cl. 7.2": ["7"], "§7 applies": ["7"], "30 (thirty) days written notice": [], "7. TERMINATION": [],
        "Clause 6 (Notice Period) and Section 9": ["6", "9"],
    }
    for text, want in cases.items():
        got = citations.cited_clauses(text)
        check(f"citation parse {text!r} -> {want}", got == want, got)
    c = citations.check("Yes (Clause 8 - Confidentiality).", ["7"], ["7", "8"])
    check("citation check: citing 8 without 7 fails (missing 7)", not c["pass"] and c["missing"] == ["7"])
    c = citations.check("Yes, under Clause 7 (Termination).", ["7"], ["7", "8"])
    check("citation check: citing 7 passes", c["pass"])
    c = citations.check("Clause 6 says so.", ["7"], ["7", "8"])
    check("citation check: citing 6 fails (missing 7, outside allowed)", not c["pass"] and c["outside"] == ["6"])

    # ---- input type + routing -------------------------------------------------------------------------
    check("input type: 'fired on the spot for leaking data' is termination",
          classify_input("Can someone be fired on the spot for leaking client data?") == "termination")
    check("input type: long pasted text is pasted_clause", classify_input("x" * 500) == "pasted_clause")
    cfg = {"stable": "a", "canary": {"version": "b", "percent": 100}, "history": [
        {"from_local": "2026-10-19T00:00", "stable": "a", "canary": None},
        {"from_local": "2026-10-21T11:00", "stable": "a", "canary": {"version": "b", "percent": 100}}]}
    from pipeline import IST
    check("routing: history before the canary -> stable",
          route(cfg, "u1", datetime(2026, 10, 21, 10, 59, tzinfo=IST)) == "a")
    check("routing: history after the canary at 100% -> canary",
          route(cfg, "u1", datetime(2026, 10, 21, 11, 0, tzinfo=IST)) == "b")
    check("routing: current config at 100% canary -> canary", route(cfg, "u1") == "b")

    # ---- trace arithmetic ---------------------------------------------------------------------------
    rec = pipe.ask("Can the company pay salary in lieu of notice?", prompt_version="answer-v2", write=False)["trace"]
    stages = tracing.stage_totals(rec["spans"])
    check("trace: cost_by_stage sums to totals.cost_usd",
          abs(sum(rec["cost_by_stage_usd"].values()) - rec["totals"]["cost_usd"]) < 1e-12)
    check("trace: retrieval, generation and tools are all reported", set(rec["cost_by_stage_usd"]) ==
          {"retrieval", "generation", "tools"})
    check("trace: every span has a latency", all(s["latency_ms"] is not None for s in rec["spans"]))
    check("trace: 4 retrieval leaf spans + 1 generation span",
          [s["name"] for s in tracing.leaf_spans(rec["spans"])] ==
          ["retrieval.embed_query", "retrieval.vector_search", "retrieval.rerank", "retrieval.expand_neighbors",
           "generation.llm"])
    check("trace: generation cost = tokens x list price",
          abs(stages["generation"]["cost_usd"] - tracing.cost_usd(
              "openai/gpt-oss-20b", stages["generation"]["input_tokens"], stages["generation"]["output_tokens"])) < 1e-12)
    for field in ("trace_id", "ts", "ts_local", "user_id", "user_role", "prompt_version", "prompt_sha", "model",
                  "input_type", "question", "answer", "retrieval", "spans", "totals", "cost_by_stage_usd"):
        check(f"trace has field {field}", field in rec)
    check("trace: context chunk ids carry a content sha",
          set(rec["retrieval"]["context_chunk_sha"]) == {str(i) for i in rec["retrieval"]["context_chunk_ids"]})

    # ---- logs: write, plant, query on a temp dir ----------------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        syn = Pipeline(llm="synthetic", index=pipe.index, contract_id=pipe.contract_id, log_dir=tmp)
        rng = random.Random(1)
        for hh in (9, 11, 15):
            syn.ask("What is the notice period?", user_id="u-lw-01", user_role="lawyer", prompt_version="answer-v2",
                    now=datetime(2026, 10, 22, hh, 0, tzinfo=IST), answer_fn=lambda *_: "30 days (Clause 6).", rng=rng)
        planted = syn.ask("Who can terminate?", user_id="u-lw-02", user_role="lawyer", prompt_version="answer-v2",
                          now=datetime(2026, 10, 22, 10, 30, tzinfo=IST), answer_fn=lambda *_: "Clause 8.",
                          write=False)["trace"]
        path, pos = tracing.JsonlSink(tmp).insert_sorted(planted)
        logs = tracing.read_logs(tmp)
        check("plant: inserted at its time position", pos == 1 and [r["trace_id"] for r in logs][1] == planted["trace_id"])
        check("plant: same keys as its neighbours", set(planted) == set(logs[0]))
        import logq
        args = types.SimpleNamespace(day="thu", t_from="10:00", t_to="16:00", user=None, role="lawyer", pv="answer-v2",
                                     type=None, status=None, q=None, a="clause 8", text=None, re=False,
                                     cost_outlier=False, mismatch=False, where=[])
        hit = logq.apply_filters(logs, args)
        check("logq: time + role + version + answer text narrows to the plant",
              [r["trace_id"] for r in hit] == [planted["trace_id"]])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- regression cases -----------------------------------------------------------------------------
    from run_suite import score
    check("at least one regression case exists", len(REGRESSION_CASES) >= 1)
    for case in REGRESSION_CASES:
        passed, why, _d = score(case, case["logged_answer"], "", None)
        check(f"[{case['id']}] logged answer FAILS the case (the test catches the real failure)", not passed, why)
        good = (f"{case['answer_keywords'][0]} - Clause {case['citation']['required'][0]} "
                f"({cm.title(case['citation']['required'][0]).title()}).")
        passed, why, _d = score(case, good, "", None)
        check(f"[{case['id']}] a correct, correctly cited answer PASSES the case", passed, why)
        check(f"[{case['id']}] expected_chunks are the required clause's chunks",
              case["expected_chunks"] == sorted({i for c in case["citation"]["required"] for i in cm.chunks_with_body(c)}))

    n_ok = sum(ok for _n, ok in RESULTS)
    print(f"\n{n_ok}/{len(RESULTS)} checks passed")
    sys.exit(0 if n_ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
