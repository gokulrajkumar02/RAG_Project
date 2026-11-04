"""
`python capstone/run.py eval`: run the suite on v0-naive and v1-guarded (same stand-in/model, same cases, same corpus;
the ONLY difference is config.json), then write results/RESULTS.txt + results/results.json.

Every model-dependent number is stamped with the mode. With no GROQ_API_KEY the model is the rule-based STUB
(contractdesk/stub_model.py): the numbers then measure the system's code and guards, not a language model.
"""

import json
import os
import re
import statistics
import time
from collections import Counter, defaultdict

from . import evaluate as E
from . import extract, paths, redact
from . import parse as P
from .registry import Registry

RESULTS_DIR = os.path.join(paths.CAPSTONE_DIR, "results")
SEVERITY = {"superseded_clause_cited": "critical", "ordinary_meaning_of_defined_term": "critical",
            "ocr_extraction_error": "high", "characterised_as_standard": "high", "customer_scope_error": "high",
            "wrong_value": "high", "guard_fail_closed": "medium", "citation_incomplete_or_wrong": "medium",
            "no_referral_to_counsel": "medium", "trace_id_lost": "medium", "other": "low"}
INTEGRATION_MODES = {"guard_fail_closed", "trace_id_lost", "customer_scope_error"}


def rss_mb(pid):
    """Resident memory of a process in MB (tasklist on Windows, ps elsewhere); None if it cannot be read."""
    import subprocess
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
            mem = out.strip().split('","')[-1]
            return round(int(re.sub(r"\D", "", mem)) / 1024, 0)
        return round(int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout) / 1024, 0)
    except Exception:
        return None


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - m) / d, (c + m) / d)


def quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


async def run_variant(variant, cases, truth, llm_kind):
    from run import open_desk
    rows = []
    async with open_desk(variant, llm_kind, log_dir=os.path.join(paths.LOGS, "eval", variant), log_content=True,
                         keep_prompts=True) as (desk, host):
        mode = desk.llm.mode
        discovered = [t.name for t in host.tools]
        for case in cases:
            try:
                res = await desk.ask(case["question"], user_id="eval-suite", user_role="eval")
            except Exception as exc:       # an agent crash is a failure of the integrated system, not a reason to stop
                print(f"  AGENT CRASH on {case['id']}: {exc.__class__.__name__}: {exc}", flush=True)
                res = dict(answer_text=f"[agent crashed: {exc.__class__.__name__}]", answer="", citations=[], chain_links=[],
                           guard_events=[dict(gate="agent_crash", detail=str(exc)[:120])], transcript=[], tools_called=[],
                           tool_log=[], prompts=[], trace=dict(trace_id="-", totals=dict(latency_ms=0, cost_usd=0, input_tokens=0,
                                                                                            output_tokens=0), spans=[], steps=0))
            res["discovered"] = discovered
            sc = E.score(case, res, truth)
            failed = [n for n, ok, _ in sc["outcome"] if not ok]
            tfailed = [n for n, ok, _ in sc["trajectory"] if not ok]
            gates = [g["gate"] for g in res["guard_events"]]
            res["uncertain_flag"] = any("could not confirm" in res["answer_text"] or "could not read" in res["answer_text"] for _ in [0])
            mode_name = E.classify(failed, case, res) if failed else None
            if failed and "fail_closed" in gates:
                mode_name = "guard_fail_closed"
            if "trace_id_survived" in tfailed:
                mode_name = mode_name or "trace_id_lost"
            rows.append(dict(id=case["id"], group=case["group"], slug=case["slug"], question=case["question"],
                             live_chain=bool(case.get("live_chain")), scanned=case["scanned"],
                             outcome_pass=not failed, referred="answered" in failed, traj_pass=not tfailed, failed=failed, traj_failed=tfailed,
                             detail=[(n, d) for n, ok, d in sc["outcome"] + sc["trajectory"] if not ok], mode=mode_name,
                             answer=res["answer_text"], citations=[(c["doc_id"], c["clause"]) for c in res["citations"]],
                             tools=res["tools_called"], guard_events=res["guard_events"], trace_id=res["trace"]["trace_id"],
                             latency_ms=res["trace"]["totals"]["latency_ms"], cost_usd=res["trace"]["totals"]["cost_usd"],
                             tokens_in=res["trace"]["totals"]["input_tokens"], tokens_out=res["trace"]["totals"]["output_tokens"],
                             spans=[(s["name"], s["latency_ms"]) for s in res["trace"]["spans"]],
                             prompts=res["prompts"], steps=res["trace"]["steps"]))
        pids = []
        sdir = os.path.join(paths.LOGS, "servers")
        for f in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
            for ln in open(os.path.join(sdir, f), encoding="utf-8"):
                pids.append(json.loads(ln).get("pid"))
        rows[0]["server_rss_mb"] = rss_mb(pids[-1]) if pids else None
    return mode, rows


def ocr_report(truth, reg):
    tiers = defaultdict(lambda: dict(docs=0, cer=[], crit_total=0, crit_found=0, clauses_true=0, clauses_got=0,
                                     edits_true=0, edits_got=0, numeric_flags=0))
    digital = []
    for doc_id, t in truth["docs"].items():
        rec = reg["documents"][doc_id]
        ex = extract.load_extracted(doc_id)
        text = "\n".join(p["text"] for p in ex["pages"])
        if not t["scanned"]:
            if len(digital) < 10:
                digital.append(extract.ocr_metrics(t["text"], re.sub(r"Page \d+\n?", "", text), t["critical"])["cer"])
            continue
        m = extract.ocr_metrics(t["text"], text, t["critical"])
        tier = tiers[t["tier"]]
        tier["docs"] += 1
        tier["cer"].append(m["cer"])
        tier["crit_total"] += m["critical_total"]
        tier["crit_found"] += m["critical_found"]
        true_cl = {c["no"] for c in P.parse_clauses([{"n": 1, "text": t["text"]}], rec["type"]) if c["no"] not in ("0", "sig")}
        got_cl = {c["no"] for c in reg["clauses"][doc_id] if c["no"] not in ("0", "sig")}
        tier["clauses_true"] += len(true_cl)
        tier["clauses_got"] += len(true_cl & got_cl)
        if rec["type"] == "AMENDMENT":
            te, _ = P.parse_edits(P.parse_clauses([{"n": 1, "text": t["text"]}], "AMENDMENT"))
            tier["edits_true"] += len(te)
            tier["edits_got"] += rec["edits_parsed"]
        tier["numeric_flags"] += len(rec.get("numeric_flags", []))
    return tiers, digital


def pii_report(rows, truth):
    pii = [p for a in truth["accounts"].values() for p in a["pii"]]
    prompts = [p for r in rows for p in r["prompts"]]
    leaks_prompts = sum(1 for p in prompts if redact.find_leaks(p, pii))
    log_hits, files = 0, 0
    for root, _d, fs in os.walk(os.path.join(paths.LOGS)):
        for f in fs:
            if f.endswith(".jsonl"):
                files += 1
                log_hits += len(redact.find_leaks(open(os.path.join(root, f), encoding="utf-8").read(), pii))
    return dict(prompts_scanned=len(prompts), prompts_with_pii=leaks_prompts, log_files=files, pii_strings_in_logs=log_hits,
                pii_strings_checked=len(pii))


def show_trace(prefix):
    """Print one request's span tree (latency and cost per span) from the request/eval logs, plus the server-side log
    lines that carry the same trace id - the proof the id survived the agent hop and the MCP hop."""
    rec = None
    for root, _d, fs in os.walk(os.path.join(paths.LOGS, "eval")):
        for f in fs:
            if f.endswith(".jsonl"):
                for ln in open(os.path.join(root, f), encoding="utf-8"):
                    r = json.loads(ln)
                    if r["trace_id"].startswith(prefix):
                        rec = r
    for f in (os.listdir(os.path.join(paths.LOGS, "requests")) if os.path.isdir(os.path.join(paths.LOGS, "requests")) else []):
        for ln in open(os.path.join(paths.LOGS, "requests", f), encoding="utf-8"):
            r = json.loads(ln)
            if r["trace_id"].startswith(prefix):
                rec = r
    if rec is None:
        raise SystemExit(f"no trace starting with {prefix!r} in capstone/logs")
    spans = rec["spans"]
    kids = defaultdict(list)
    for sp in spans:
        kids[sp["parent_id"]].append(sp)

    def walk(sp, depth):
        a = sp["attributes"]
        extra = []
        if "gen_ai.usage.input_tokens" in a:
            extra.append(f"{a['gen_ai.usage.input_tokens']} in / {a['gen_ai.usage.output_tokens']} out tok  ${a['cost_usd']:.6f}")
        if "trace_id_survived" in a:
            extra.append(f"trace id survived: {a['trace_id_survived']}")
        print(f"  {'  ' * depth}{sp['name']:<{34 - 2 * depth}} {sp['stage']:<10}{sp['latency_ms']:>9.1f} ms  {'  '.join(extra)}")
        for c in sorted(kids.get(sp["span_id"], []), key=lambda s: s["start_ms"]):
            walk(c, depth + 1)

    print(f"trace {rec['trace_id']}  variant={rec['variant']}  llm={rec['llm_mode']}  customer={rec['counterparty']}")
    print(f"total {rec['totals']['latency_ms']:.0f} ms, {rec['totals']['input_tokens']} in / {rec['totals']['output_tokens']} out tokens, "
          f"${rec['totals']['cost_usd']:.5f}; cost by stage {rec['cost_by_stage_usd']}")
    print(f"content logged: {rec['content_logged']}  question sha {rec['question_sha']}")
    walk(spans[0], 0)
    n = 0
    for f in os.listdir(os.path.join(paths.LOGS, "servers")):
        for ln in open(os.path.join(paths.LOGS, "servers", f), encoding="utf-8"):
            r = json.loads(ln)
            if r["trace_id"] == rec["trace_id"]:
                n += 1
                print(f"  server log: {r['server']}.{r['tool']}  pid {r['pid']}  args {r['argument_names']}  {r['result_chars']} chars  "
                      f"(same trace id, propagated={r['propagated']})")
    print(f"{n} server-side log line(s) carry this trace id")


async def run_case(case_id, llm_kind="auto"):
    """The closed loop, live: one eval case (a failure that became a permanent test) on both systems."""
    truth = json.load(open(paths.TRUTH, encoding="utf-8"))
    cases, bonus = E.build_cases(truth)
    case = next((c for c in cases + bonus if c["id"] == case_id), None)
    if case is None:
        raise SystemExit("unknown case id; e.g. " + ", ".join(c["id"] for c in (cases + bonus)[:5]))
    print(f"CASE {case_id}: {case['question']}\n")
    for variant in ("v0-naive", "v1-guarded"):
        _m, rows = await run_variant(variant, [case], truth, llm_kind)
        r = rows[0]
        verdict = "GREEN (pass)" if r["outcome_pass"] else ("RED (referred to counsel)" if r["referred"] else "RED (fail)")
        print(f"--- {variant}: {verdict}   trace {r['trace_id'][:12]}")
        print("    answer:", r["answer"][:300].replace("\n", " "))
        for n, d in r["detail"]:
            print(f"    failed: {n}: {d}")


async def run_all(llm_kind):
    t0 = time.time()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    truth = json.load(open(paths.TRUTH, encoding="utf-8"))
    regd = json.load(open(paths.REGISTRY, encoding="utf-8"))
    cases, bonus = E.build_cases(truth)
    allc = cases + bonus
    runs = {}
    for variant in ("v0-naive", "v1-guarded"):
        print(f"running {len(allc)} cases on {variant} ...", flush=True)
        runs[variant] = await run_variant(variant, allc, truth, llm_kind)
    mode = runs["v1-guarded"][0]
    lines = write_report(runs, cases, bonus, truth, regd, mode)
    with open(os.path.join(RESULTS_DIR, "RESULTS.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    slim = {v: [{k: r[k] for k in r if k != "prompts"} for r in rows] for v, (_m, rows) in runs.items()}
    json.dump(dict(mode=mode, runs=slim), open(os.path.join(RESULTS_DIR, "results.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("\n".join(lines))
    print(f"\nwritten: capstone/results/RESULTS.txt, results.json   ({time.time() - t0:.0f}s)")


def write_report(runs, cases, bonus, truth, regd, mode):
    L = []
    w = L.append
    bonus_ids = {c["id"] for c in bonus}
    banner = ("MODE: GROQ - answers from openai/gpt-oss-120b" if mode == "groq" else
              "MODE: STUB - no GROQ_API_KEY. The 'model' is the rule-based stand-in in contractdesk/stub_model.py, NOT a language\n"
              "      model. Numbers below measure this system's code, tools and guards; they are NOT evidence about gpt-oss-120b.")
    w("=" * 110)
    w("WEEK 12 CAPSTONE - Contract Review Assistant: integrated eval")
    w(banner)
    w("CORPUS: synthetic (seed 12): 60 customers, 191 documents. Numbers about this corpus are about the generator as much as the system.")
    w("=" * 110)
    v0, v1 = runs["v0-naive"][1], runs["v1-guarded"][1]
    main1 = [r for r in v1 if r["id"] not in bonus_ids]
    main0 = [r for r in v0 if r["id"] not in bonus_ids]

    # -- 1. headline per group ---------------------------------------------------------------------------------
    s0, s1 = E.summarise(main0), E.summarise(main1)
    w(f"\n1. SUITE ({len(main1)} cases, outcome = every assertion passes; judge not used: see section 8)")
    w(f"   pass = every assertion holds. referred = the system declined and referred to counsel (not a wrong answer, not a pass).")
    w(f"   {'group':<28}{'n':>3}   {'v0-naive':>9}  {'v0 refd':>7}   {'v1-guarded':>10}  {'v1 refd':>7}")
    for g in sorted(s1["groups"], key=lambda g: (g != "limitation_of_liability", g != "indemnity", g)):
        p1, n, r1 = s1["groups"][g]
        p0, _n0, r0 = s0["groups"][g]
        w(f"   {g:<28}{n:>3}   {p0:>3}/{n:<3} {pct(p0, n):>4}  {r0:>7}   {p1:>3}/{n:<3} {pct(p1, n):>4}  {r1:>7}")
    w(f"   {'ALL':<28}{s1['n']:>3}   {s0['outcome_pass']:>3}/{s1['n']:<3} {pct(s0['outcome_pass'], s1['n']):>4}  {s0['referred']:>7}   {s1['outcome_pass']:>3}/{s1['n']:<3} {pct(s1['outcome_pass'], s1['n']):>4}  {s1['referred']:>7}")
    w(f"   wrong (neither pass nor referral): v0 {s0['n'] - s0['outcome_pass'] - s0['referred']}  v1 {s1['n'] - s1['outcome_pass'] - s1['referred']}")
    w("   Limitation-of-liability and indemnity are broken out above on purpose: a blended average would hide them.")

    # -- 2. the number that moved -----------------------------------------------------------------------------
    amended = [r for r in v1 if r["id"].startswith("cap_amended_")]
    amended0 = [r for r in v0 if r["id"].startswith("cap_amended_")]
    sup = lambda r: (not r["referred"]) and any(c == (f"{r['slug']}/msa", "11.3") for c in r["citations"])  # noqa: E731
    k0, k1 = sum(sup(r) for r in amended0), sum(sup(r) for r in amended)
    lo0, hi0 = wilson(k0, len(amended0))
    lo1, hi1 = wilson(k1, len(amended))
    w(f"\n2. THE NUMBER THAT MOVED - superseded-clause citation rate on the {len(amended)} accounts whose Amendment No.2 replaced the cap")
    w(f"   v0-naive   {k0}/{len(amended0)} answers relied on MSA clause 11.3 (superseded)   95% CI {lo0:.0%}-{hi0:.0%}   referred: {sum(r['referred'] for r in amended0)}")
    w(f"   v1-guarded {k1}/{len(amended)} answers relied on MSA clause 11.3 (superseded)   95% CI {lo1:.0%}-{hi1:.0%}   referred: {sum(r['referred'] for r in amended)}")
    w(f"   n = {len(amended)} (one question per amended account). 'After' differs from 'before' by config.json only: the chain + definition")
    w("   tools, status on search hits, and the guards. Under STUB, 'before' is what an agent that takes the first search hit does.")
    ok_amended = sum(r["outcome_pass"] for r in amended)
    w(f"   Whole-answer correct on those {len(amended)}: v0 {sum(r['outcome_pass'] for r in amended0)}/{len(amended0)} -> v1 {ok_amended}/{len(amended)}")
    unc = [r for r in amended if not r["outcome_pass"]]
    for r in unc:
        w(f"     still failing: {r['id']} mode={r['mode']} {r['detail'][:2]}")
    sc1 = [r for r in v1 if r["scanned"] and r["group"] != "bonus_chain"]
    w(f"   (of the v1 failures, scanned-document accounts account for {sum(1 for r in sc1 if not r['outcome_pass'])} of {sum(1 for r in main1 if not r['outcome_pass'])})")

    # -- 3. bonus -----------------------------------------------------------------------------------------------
    b0, b1 = [r for r in v0 if r["id"] in bonus_ids], [r for r in v1 if r["id"] in bonus_ids]
    w(f"\n3. BONUS - cite every link of the chain ({len(b1)} cases on amended accounts)")
    w(f"   red before (v0): {sum(not r['outcome_pass'] for r in b0)}/{len(b0)}   green after (v1): {sum(r['outcome_pass'] for r in b1)}/{len(b1)}")
    for r in b1:
        w(f"     {r['id']:<44} v0 {'PASS' if next(x for x in b0 if x['id'] == r['id'])['outcome_pass'] else 'FAIL'}  v1 {'PASS' if r['outcome_pass'] else 'FAIL'} {r['detail'][:1] if not r['outcome_pass'] else ''}")
    chain_ms = [ms for r in v1 for n, ms in r["spans"] if n == "mcp.resolve_amendment_chain"]
    w(f"   cost of chain resolution: p50 {statistics.median(chain_ms):.0f} ms per resolve_amendment_chain call (client-side, incl. MCP hop); "
      f"per question p50 latency v0 {statistics.median(r['latency_ms'] for r in main0):.0f} ms -> v1 {statistics.median(r['latency_ms'] for r in main1):.0f} ms" if chain_ms else "")

    # -- 4. trajectory -------------------------------------------------------------------------------------------
    w(f"\n4. TRAJECTORY (Week 8 checks on the integrated agent, v1-guarded, n={len(main1)})")
    turns = sum(r["steps"] for r in main1)
    bad_turns = sum(1 for r in main1 if "valid_turns" in r["traj_failed"])
    must = [r for r in main1]
    tool_acc = sum(1 for r in must if not any(f.startswith(("called_", "chain_before", "defined_term_")) for f in r["traj_failed"]))
    w(f"   tool-choice accuracy (right tools called for the case): {tool_acc}/{len(must)} = {pct(tool_acc, len(must))}")
    w(f"   outcome pass {s1['outcome_pass']}/{s1['n']}   trajectory pass {s1['traj_pass']}/{s1['n']}   gap {s1['gap_pp']} points")
    w(f"   right answer, wrong path (outcome PASS, trajectory FAIL): {len(s1['lucky'])} runs")
    cnt = Counter(f for r in main1 if r["outcome_pass"] and not r["traj_pass"] for f in r["traj_failed"])
    for k, v in cnt.most_common():
        w(f"       {k:<34}{v}")
    gate_runs = sum(1 for r in main1 if any(g["gate"] in ("chain_not_resolved", "defined_term", "fabricated_citation", "superseded_citation", "no_citations")
                                           for g in r["guard_events"]))
    w(f"   runs where a guard sent the model's final_answer back at least once: {gate_runs}/{len(main1)} (this hidden work is what the gap measures)")

    # -- 5. taxonomy ----------------------------------------------------------------------------------------------
    guard_hits = Counter(g["gate"] for r in main1 for g in r["guard_events"] if g.get("action") in ("final_answer rejected", "sentence removed"))
    w(f"\n5. ERROR TAXONOMY re-scored on the integrated system (n={len(main1)} cases; each mode: cases failing it, unguarded v0 vs guarded v1)")
    w(f"   {'mode':<36}{'v0':>4}{'v1':>4}{'(v1 refd)':>10}  {'v0 %':>5}{'v1 %':>5}  severity   example trace (v0 / v1)")
    m0 = defaultdict(list)
    m1 = defaultdict(list)
    for r in main0:
        if not r["outcome_pass"]:
            m0[r["mode"]].append(r)
    for r in main1:
        if not r["outcome_pass"]:
            m1[r["mode"]].append(r)
    for m in sorted(set(m0) | set(m1), key=lambda m: (-len(m0[m]) - len(m1[m]))):
        t0 = m0[m][0]["trace_id"][:10] if m0[m] else "-"
        t1 = m1[m][0]["trace_id"][:10] if m1[m] else "-"
        w(f"   {m:<36}{len(m0[m]):>4}{len(m1[m]):>4}{sum(r['referred'] for r in m1[m]):>10}  {pct(len(m0[m]), len(main0)):>5}{pct(len(m1[m]), len(main1)):>5}  {SEVERITY.get(m, 'low'):<9}  {t0} / {t1}")
    w("   v1 = 'safe': a referral is not a wrong answer. Guard actions that fired on the v1 runs (each is a model-side failure that did NOT ship): "
      + (", ".join(f"{k} x{v}" for k, v in guard_hits.most_common()) or "none"))
    w("   Integration-created modes found while building (each fixed; counts are as measured on that run, not re-measured here): see README, 'Seams'.")

    # -- 6. OCR ----------------------------------------------------------------------------------------------------
    tiers, digital = ocr_report(truth, regd)
    w("\n6. EXTRACTION ERROR - measured against the text the generator drew (real OCR: " + regd["ocr_engine"] + ")")
    w(f"   {'scan quality':<14}{'docs':>5} {'char error rate':>16} {'figure/date tokens read':>24} {'clauses recovered':>18} {'amendment edits parsed':>24}")
    tot = dict(d=0, ct=0, cf=0, kt=0, kg=0, et=0, eg=0)
    for tier in ("mild", "moderate", "poor"):
        t = tiers.get(tier)
        if not t:
            continue
        w(f"   {tier:<14}{t['docs']:>5} {statistics.fmean(t['cer']):>15.1%} {t['crit_found']:>12}/{t['crit_total']:<6} {pct(t['crit_found'], t['crit_total']):>4} "
          f"{t['clauses_got']:>8}/{t['clauses_true']:<5} {pct(t['clauses_got'], t['clauses_true']):>4} {t['edits_got']:>10}/{t['edits_true']:<4}")
        tot["d"] += t["docs"]; tot["ct"] += t["crit_total"]; tot["cf"] += t["crit_found"]; tot["kt"] += t["clauses_true"]; tot["kg"] += t["clauses_got"]
        tot["et"] += t["edits_true"]; tot["eg"] += t["edits_got"]
    w(f"   ALL SCANNED   {tot['d']:>5}   figure/date tokens misread: {tot['ct'] - tot['cf']}/{tot['ct']} = {pct(tot['ct'] - tot['cf'], tot['ct'])};  "
      f"clauses lost: {tot['kt'] - tot['kg']}/{tot['kt']};  amendment edits not parsed: {tot['et'] - tot['eg']}/{tot['et']}")
    w(f"   digital (text-layer) PDFs, 10 sampled: char error rate {statistics.fmean(digital):.2%}")
    n_sc = sum(1 for d in regd["documents"].values() if d["source"] == "ocr")
    w(f"   {n_sc} of {len(regd['documents'])} documents are scans. Handling: figures written as words AND digits are cross-checked; an amendment")
    w("   paragraph that cannot be read, or an edit that cannot be applied, makes the chain `uncertain` and the answer a referral, not a guess.")

    # -- 7. privacy ----------------------------------------------------------------------------------------------
    pr = pii_report(v1 + v0, truth)
    w(f"\n7. PII / PRIVILEGE LINE: {pr['prompts_with_pii']}/{pr['prompts_scanned']} prompts sent to the model contained a known personal-data string; "
      f"{pr['pii_strings_in_logs']} occurrences of {pr['pii_strings_checked']} known strings across {pr['log_files']} log files")
    w("   (searched against truth.json's list of signatory names, e-mails, phones, addresses). Eval logs hold question/answer text because the")
    w("   questions are synthetic; the default for `ask` is content_logged=false.")

    # -- 8. judge --------------------------------------------------------------------------------------------------
    w("\n8. JUDGE: " + ("the Week 6 LLM judge was not run (no GROQ_API_KEY). Every pass above is assertions only. The >=85% agreement gate against hand labels "
                        "has NOT been cleared or measured; see README 'Still open'." if mode != "groq" else "see judge_check output"))

    # -- 9. cost / latency -----------------------------------------------------------------------------------------
    lat = [r["latency_ms"] for r in main1]
    cost = [r["cost_usd"] for r in main1]
    tok = [r["tokens_in"] + r["tokens_out"] for r in main1]
    stage = defaultdict(list)
    for r in main1:
        s = defaultdict(float)
        for n, ms in r["spans"]:
            if n == "llm.call":
                s["generation"] += ms
            elif n.startswith("retrieval."):
                s["retrieval"] += ms
            elif n.startswith("server.") and n not in ("server.search_clauses",):
                s["tools"] += ms
            elif n == "mcp.transport":
                s["transport"] += ms
        for k in ("generation", "retrieval", "tools", "transport"):
            stage[k].append(s[k])
    w(f"\n9. COST AND LATENCY per contract question (v1-guarded, n={len(main1)}; {'tokens measured' if mode == 'groq' else 'tokens ESTIMATED: tiktoken(real prompt) + assumed 250 reasoning tokens/step'})")
    w(f"   cost: mean ${statistics.fmean(cost):.5f}  p95 ${quantile(cost, .95):.5f}   tokens/question mean {statistics.fmean(tok):.0f}   LLM calls/question mean {statistics.fmean(r['steps'] for r in main1):.1f}")
    w(f"   latency: p50 {statistics.median(lat):.0f} ms  p99 {quantile(lat, .99):.0f} ms   " + "  ".join(f"{k} p50 {statistics.median(v):.0f} ms" for k, v in stage.items()))
    w("   cost by stage: retrieval and tools run on local CPU ($0 on any bill; their cost is time); generation is the whole bill.")

    # -- 10. what breaks first at 10x -------------------------------------------------------------------------------
    T, C = statistics.fmean(tok), statistics.fmean(r["steps"] for r in main1)
    rss = v1[0].get("server_rss_mb")
    lim = dict(RPM=30, TPM=8000, TPD=200_000)      # Groq free-tier figures as Week 11 recorded them (gpt-oss-20b); check your org's page
    peak_q_min, q_day = 3, 5                        # ASSUMPTIONS, stated: 4 lawyers, ~60 deals/quarter x ~5 lookups = ~300/quarter
    wrong_hi = wilson(sum(1 for r in main1 if not r["outcome_pass"] and not r["referred"]), len(main1))[1]
    refd = sum(r["referred"] for r in main1) / len(main1)
    w("\n10. COST PER QUESTION AND THE 10x PLAN (opening to the whole sales org, not four lawyers)")
    w(f"   cost per contract question: ${statistics.fmean(cost):.4f} mean (${quantile(cost, .95):.4f} p95); {T:.0f} tokens and {C:.1f} model calls per question")
    w("   ASSUMED load today: ~5 questions/day, peak 3 in one minute (4 lawyers, ~60 deals/quarter x ~5 lookups). 10x = 50/day, peak 30/min.")
    w(f"   {'resource':<44}{'needed today':>14}{'limit':>10}{'headroom':>10}   at 10x")
    rows10 = [("Groq tokens per minute (TPM)", peak_q_min * T, lim["TPM"]),
              ("Groq requests per minute (RPM)", peak_q_min * C, lim["RPM"]),
              ("Groq tokens per day (TPD)", q_day * T, lim["TPD"])]
    for name, need, limit in rows10:
        w(f"   {name:<44}{need:>14,.0f}{limit:>10,}{limit / need:>9.1f}x   {'BREAKS' if limit / need < 10 else 'ok'}")
    if rss:
        sess = peak_q_min / 60 * 15 * 10      # concurrent sessions at 10x if a real question takes ~15 s (assumption)
        w(f"   MCP server process memory (one per agent session): {rss:.0f} MB measured; at 10x ~{sess:.1f} concurrent sessions "
          f"(assuming 15 s per real question) = ~{sess * rss / 1024:.1f} GB")
    w(f"   answers the system declined (referred to counsel): {pct(sum(r['referred'] for r in main1), len(main1))} of the suite -> at 10x about "
      f"{refd * q_day * 10:.0f} referrals/day for counsel to clear")
    w(f"   wrong answers: 0 observed in {len(main1)}, but the 95% upper bound on that is {wrong_hi:.0%}: at 10x volume ({q_day * 10 * 63:.0f} questions/quarter) "
      f"that bound is up to ~{wrong_hi * q_day * 10 * 63:.0f} wrong answers a quarter that nobody has measured.")
    first = min(rows10, key=lambda x: x[2] / x[1])
    w(f"   WHAT BREAKS FIRST: {first[0]} - headroom {first[2] / first[1]:.1f}x of today's peak on the free-tier limits, i.e. it breaks BEFORE 10x (one")
    w(f"   question already needs ~{T:.0f} tokens of an 8,000-token minute). On a paid tier the first thing to break is human: the referral load and the")
    w("   unmeasured wrong-answer rate above, not the servers. Numbers marked ASSUMED are mine; the token/latency/memory figures come from this run.")
    return L
