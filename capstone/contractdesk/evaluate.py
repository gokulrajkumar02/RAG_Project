"""
The eval suite for the INTEGRATED system. Cases are built from truth.json (what each document says and what is in
force, computed from the generator's plan, independently of the app's parser), run through the real agent over real
MCP, and scored two ways:

  OUTCOME     did the answer say the right thing - assertions first (cheap, exact, no judge noise), a judge last
  TRAJECTORY  did the agent take a defensible path (Week 8): chain resolved before a clause was quoted, defined
              terms resolved, the right tools called, passed the guards without being sent back, trace id intact

Their gap (outcome pass, trajectory fail = right answer by a path that will not always work) is reported as a number.
A failure is classified into a named mode by which assertion failed; the taxonomy is whatever this produces.
"""

import re
from collections import Counter, defaultdict

from .corpus_gen import words
from .guards import defined_terms_in, find_characterisations, has_referral, is_referral_answer
from .registry import short_name

SUPERSEDED_PAIR = lambda slug: (f"{slug}/msa", "11.3")  # noqa: E731


def num_forms(n):
    forms = [str(n)]
    try:
        forms.append(words(n))
    except (KeyError, ValueError):
        pass
    return forms


def has_number(text, n):
    t = text.lower()
    return any(re.search(rf"(?<![\d,.]){re.escape(f.lower())}(?![\d,]|\.\d)", t) for f in num_forms(n))


def has_amount(text, usd):
    t = text.replace(" ", "")
    return f"{usd:,}" in t or str(usd) in t or f"{usd / 1e6:g}million" in t.lower()


# ----------------------------------------------------------------------------------------------------------
def build_cases(truth):
    A = truth["accounts"]
    nm = lambda s: short_name(A[s]["name"])  # noqa: E731
    P = lambda slug, doc, cl: (f"{slug}/{doc}", str(cl))  # noqa: E731
    cases = []

    def add(cid, group, slug, q, **kw):
        cases.append(dict(id=cid, group=group, slug=slug, question=q, **kw))

    amended = sorted(s for s, a in A.items() if a["amended_cap"])
    phr = ["What is the liability cap for {n}?", "What's the cap on liability in the {n} contract?",
           "We are negotiating with {n}. How much can each side be liable for under the MSA?",
           "How much is TechCorp's maximum liability to {n}?"]
    for i, s in enumerate(amended):
        cap = A[s]["in_force"]["cap"]
        add(f"cap_amended_{s}", "limitation_of_liability", s, phr[i % 4].format(n=nm(s)), live_chain=True,
            expect=dict(cites=[P(s, cap["doc"], cap["clause"])], months=cap["months"], floor=cap["usd_floor"],
                        not_cites=[SUPERSEDED_PAIR(s)], terms=["Excluded Claims"], must_call=["resolve_amendment_chain"]))
    plain = next(s for s in sorted(A) if not A[s]["has_amendment"] and not A[s]["sow_special"] and not A[s]["scan"].get("msa")
                 and A[s]["in_force"]["cap"]["months"] == 18)
    add(f"cap_plain_{plain}", "limitation_of_liability", plain, phr[0].format(n=nm(plain)),
        expect=dict(cites=[P(plain, "msa", "11.3")], months=18, terms=["Excluded Claims"], must_call=["resolve_amendment_chain"]))

    # indemnity ------------------------------------------------------------------------------------------------
    h = "halcyon-freight"
    cap_h = A[h]["in_force"]["cap"]
    q_ind = "Is TechCorp's IP indemnity to {n} subject to the liability cap?"
    add("indemnity_cap_amended", "indemnity", h, q_ind.format(n=nm(h)), live_chain=True,
        expect=dict(cites=[P(h, cap_h["doc"], cap_h["clause"])], not_cites=[SUPERSEDED_PAIR(h)], terms=["Excluded Claims"],
                    uncapped=True, must_call=["resolve_amendment_chain", "resolve_defined_term"]))
    add(f"indemnity_cap_{plain}", "indemnity", plain, q_ind.format(n=nm(plain)),
        expect=dict(cites=[P(plain, "msa", "11.3")], terms=["Excluded Claims"], uncapped=True,
                    must_call=["resolve_amendment_chain", "resolve_defined_term"]))
    scanned_plain = [s for s in sorted(A) if A[s]["scan"].get("msa") and not A[s]["has_amendment"] and not A[s]["sow_special"]]
    s_ind = scanned_plain[0]
    add(f"indemnity_scope_{s_ind}", "indemnity", s_ind, f"What does TechCorp's IP indemnity to {nm(s_ind)} cover?", scanned=True,
        expect=dict(cites=[P(s_ind, "msa", "12.1")], keywords=["third-party", "infring"], terms=["Losses"]))
    s_db = "evergreen-biotech"
    add("indemnity_databreach_amended", "indemnity", s_db, f"Does TechCorp indemnify {nm(s_db)} for a data breach, and is that capped?",
        live_chain=True, expect=dict(cites=[P(s_db, A[s_db]["in_force"]["cap"]["doc"], A[s_db]["in_force"]["cap"]["clause"])],
                                     terms=["Excluded Claims", "Losses"], uncapped=True))

    # defined terms ----------------------------------------------------------------------------------------------
    add(f"affiliate_subsidiaries_{plain}", "defined_terms", plain, f"Can {nm(plain)}'s subsidiaries use the Services under this MSA?",
        expect=dict(cites=[P(plain, "msa", "3.2")], scope="negative", terms=["Affiliate"], must_call=["resolve_defined_term"]))
    j = "jasper-creek-health"
    add("affiliate_redefined_jasper", "defined_terms", j, f"Can {nm(j)}'s subsidiaries use the Services under this MSA?", live_chain=True,
        expect=dict(cites=[P(j, "amendment-1", "1")], scope="positive", terms=["Affiliate"], must_call=["resolve_defined_term"]))
    add(f"excluded_claims_def_{plain}", "defined_terms", plain, f"How is Excluded Claims defined in the {nm(plain)} MSA?",
        expect=dict(cites=[("shared/definitions-schedule", "6")], keywords=["indemni", "fraud"], terms=["Excluded Claims"],
                    must_call=["resolve_defined_term"]))
    add("affiliate_lowercase_evergreen", "defined_terms", "evergreen-biotech",
        "Can Evergreen Biotech's affiliates log in to the platform?", live_chain=True,
        expect=dict(cites=[P("evergreen-biotech", "amendment-1", "1")], scope="positive", terms=["Affiliate"],
                    must_call=["resolve_defined_term"]))

    # termination / notice ----------------------------------------------------------------------------------------
    add("notice_amended_halcyon", "termination", h, f"How much notice does {nm(h)} have to give to terminate for convenience?",
        live_chain=True, expect=dict(cites=[P(h, A[h]["in_force"]["notice"]["doc"], A[h]["in_force"]["notice"]["clause"])],
                                     days=A[h]["in_force"]["notice"]["days"], not_cites=[(f"{h}/msa", "14.2")],
                                     must_call=["resolve_amendment_chain"]))
    w = "wexford-logistics"
    add("notice_future_wexford", "termination", w, f"What notice period applies if {nm(w)} wants to terminate for convenience?",
        live_chain=True, expect=dict(cites=[P(w, "msa", "14.2")], days=A[w]["in_force"]["notice"]["days"],
                                     keywords=["2027"], must_call=["resolve_amendment_chain"]))
    add(f"notice_plain_{plain}", "termination", plain, f"What notice does {nm(plain)} need to give to exit the MSA early?",
        expect=dict(cites=[P(plain, "msa", "14.2")], days=A[plain]["in_force"]["notice"]["days"], must_call=["resolve_amendment_chain"]))

    # governing law -----------------------------------------------------------------------------------------------
    for tag, s in (("plain", plain), ("scanned", scanned_plain[1]), ("amended", "orion-pharma")):
        law = A[s]["in_force"]["governing_law"].replace("laws of ", "")
        add(f"law_{tag}_{s}", "governing_law", s, f"Which law governs the {nm(s)} MSA, and where are disputes heard?",
            scanned=(tag == "scanned"), expect=dict(cites=[P(s, "msa", "18.1")], keywords=[law], must_call=["resolve_amendment_chain"]))

    # SOW vs MSA precedence / payment ------------------------------------------------------------------------------
    d, c = "dunmore-media", "cedarwind-insurance"
    add("payment_sow_override_dunmore", "sow_precedence", d, f"How many days does {nm(d)} have to pay an invoice?",
        expect=dict(cites=[P(d, "sow-1", "6")], days=15, not_cites=[(f"{d}/msa", "5.2")], must_call=["resolve_amendment_chain"]))
    add("cap_sow_conflict_cedarwind", "sow_precedence", c, f"{nm(c)}'s SOW mentions a liability limit. Which cap applies?",
        expect=dict(cites=[P(c, "msa", "11.3")], months=A[c]["in_force"]["cap"]["months"], keywords=["prevail"],
                    must_call=["resolve_amendment_chain"]))
    add("payment_amended_peony", "sow_precedence", "peony-retail", f"What are the payment terms for {nm('peony-retail')}?", live_chain=True,
        expect=dict(cites=[P("peony-retail", "amendment-1", "1")], days=45, not_cites=[("peony-retail/msa", "5.2")],
                    must_call=["resolve_amendment_chain"]))

    # scanned documents -------------------------------------------------------------------------------------------
    for s in scanned_plain[2:4]:
        add(f"ocr_notice_{s}", "ocr_scanned", s, f"How much notice must {nm(s)} give to terminate for convenience?", scanned=True,
            expect=dict(cites=[P(s, "msa", "14.2")], days=A[s]["in_force"]["notice"]["days"], must_call=["resolve_amendment_chain"]))

    # judgement questions: facts yes, characterisation no, counsel instead -----------------------------------------
    add("judge_cap_cedarwind", "referral_to_counsel", c, f"Is a {A[c]['in_force']['cap']['months']}-month liability cap standard for {nm(c)}?",
        expect=dict(cites=[P(c, "msa", "11.3")], months=A[c]["in_force"]["cap"]["months"], referral=True))
    add("judge_notice_halcyon", "referral_to_counsel", h, f"Is {nm(h)}'s notice period for termination acceptable?", live_chain=True,
        expect=dict(cites=[P(h, "amendment-1", "1")], days=A[h]["in_force"]["notice"]["days"], referral=True))
    add("judge_cap_orion", "referral_to_counsel", "orion-pharma", "Does Orion Pharma's liability cap look fine to you?", live_chain=True,
        scanned=True, expect=dict(cites=[P("orion-pharma", "amendment-2", "1")], months=24, floor=2_500_000, referral=True))
    add("judge_payment_dunmore", "referral_to_counsel", d, f"Is net 15 payment for {nm(d)} market?",
        expect=dict(cites=[P(d, "sow-1", "6")], days=15, referral=True))

    # scope / no answer ------------------------------------------------------------------------------------------
    add("scope_ambiguous_halcyon", "scope_and_no_answer", None, "What is the liability cap for Halcyon?",
        expect=dict(no_cites=True, mentions=["Halcyon Freight", "Halcyon Foods"]))
    add("scope_unknown_customer", "scope_and_no_answer", None, "What is the liability cap for Zenith Widgets Ltd?",
        expect=dict(no_cites=True, any_keywords=["no customer", "not on file", "no match"]))
    b = "blue-heron-energy"
    add("no_answer_mfn", "scope_and_no_answer", b, f"Does the {nm(b)} MSA include a most-favoured-customer clause?",
        expect=dict(no_cites=True, keywords=["not found"]))

    # bonus: cite every link of the chain ------------------------------------------------------------------------
    bonus = []
    for s in ("halcyon-freight", "summit-retail", "vantage-point-logistics", "mangrove-capital", "orion-pharma"):
        docs = [f"{s}/{x[0]}" if "/" not in x[0] else x[0] for x in A[s]["chains"]["11.3"]]
        if A[s]["sow_special"] == "cap_conflict":
            docs.append(f"{s}/sow-1")
        bonus.append(dict(id=f"chain_all_links_{s}", group="bonus_chain", slug=s, live_chain=True,
                          question=f"For {nm(s)}, walk me through which documents set the liability cap and which one is in force.",
                          expect=dict(chain_docs=docs, cites=[P(s, A[s]["in_force"]["cap"]["doc"], A[s]["in_force"]["cap"]["clause"])],
                                      months=A[s]["in_force"]["cap"]["months"], not_cites=[SUPERSEDED_PAIR(s)])))
    for case in cases:
        case["scanned"] = bool(case.get("scanned")) or any(A[case["slug"]]["scan"].get(k) for k in ("msa", "a1", "a2")) if case["slug"] else False
    for case in bonus:
        case["scanned"] = any(A[case["slug"]]["scan"].get(k) for k in ("msa", "a1", "a2"))
    return cases, bonus


# ----------------------------------------------------------------------------------------------------------
def score(case, res, truth):
    """-> dict(outcome=[(name, ok, detail)], trajectory=[...]). Every assertion is a plain function of the result."""
    e, text, slug = case["expect"], res["answer_text"], case["slug"]
    cited = {(c["doc_id"], c["clause"]) for c in res["citations"]}
    out, trj = [], []

    def o(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    def t(name, ok, detail=""):
        trj.append((name, bool(ok), detail))

    # A safe referral ("I could not confirm this from the documents as extracted ... referred to counsel") is NOT a wrong
    # answer and is not scored as one; it is also not an answer, so the case does not pass. Counted separately.
    referred = is_referral_answer(text) and not e.get("no_cites")
    if referred:
        o("answered", False, "declined and referred to counsel instead of answering (extraction could not support an answer)")
    if e.get("no_cites"):
        o("no_citation", not cited, f"cited {sorted(cited)}" if cited else "")
    for p in e.get("cites", []) if not referred else []:
        o("cites_in_force", p in cited, f"{p} not among {sorted(cited)}")
    for p in e.get("not_cites", []) if not referred else []:
        o("no_superseded_cited", p not in cited, f"cited superseded {p}")
    if "months" in e and not referred:
        o("value_months", has_number(text, e["months"]), f"{e['months']} months not stated")
    if e.get("floor") and not referred:
        o("value_floor", has_amount(text, e["floor"]), f"{e['floor']:,} not stated")
    if "days" in e and not referred:
        o("value_days", has_number(text, e["days"]), f"{e['days']} days not stated")
    for kw in e.get("keywords", []) if not referred else []:
        o("keyword", kw.lower() in text.lower(), f"'{kw}' missing")
    if e.get("any_keywords"):
        o("keyword", any(k.lower() in text.lower() for k in e["any_keywords"]), f"none of {e['any_keywords']} present")
    for kw in e.get("mentions", []):
        o("mentions_candidates", kw.lower() in text.lower(), f"'{kw}' missing")
    if e.get("uncapped") and not referred:
        o("says_uncapped", "excluded claims" in text.lower() and re.search(r"not subject|uncapped|not capped|outside|are not limited", text, re.I) is not None,
          "does not say the indemnity sits outside the cap via Excluded Claims")
    if e.get("scope") == "negative" and not referred:
        o("scope_negative", re.search(r"not (be )?affiliates|does not (extend|include)|not covered|are not", text, re.I)
          and not text.lower().startswith("yes"), "says subsidiaries are covered / uses the ordinary meaning")
    if e.get("scope") == "positive" and not referred:
        o("scope_positive", re.search(r"are affiliates|extends to them|are covered|may use", text, re.I)
          and not re.search(r"not affiliates", text, re.I), "says subsidiaries/affiliates are not covered")
    if e.get("chain_docs") and not referred:
        links = {c["doc_id"] for c in res["chain_links"]} | {c["doc_id"] for c in res["citations"]}
        miss = [d for d in e["chain_docs"] if d not in links]
        o("cites_every_link", not miss, f"chain links not cited: {miss}")
    if e.get("referral"):
        o("refers_to_counsel", has_referral(text), "no referral to counsel")
    o("no_characterisation", not find_characterisations(text), "; ".join(h["matched"] for h in find_characterisations(text)))
    others = [short_name(a["name"]) for s, a in truth["accounts"].items() if s != slug]
    if slug and not case.get("question", "").lower().count("halcyon") > 1:
        leak = [n for n in others if n.lower() in text.lower() and n.lower() not in case["question"].lower()]
        o("scoped_to_customer", not leak, f"mentions other customers {leak}")
    bad_cites = [c["plain"] for c in res["citations"] if not (c["doc_label"] and c["clause"] and c["effective_date"] and c["governing_law"])]
    o("citations_complete", not bad_cites, f"incomplete: {bad_cites}")
    pii = [p for a in truth["accounts"].values() for p in a["pii"] if re.sub(r"\s+", "", p).lower() in re.sub(r"\s+", "", text).lower()]
    o("no_pii_in_answer", not pii, f"{pii}")

    # trajectory -------------------------------------------------------------------------------------------------
    tool_calls = [s for s in res["transcript"] if s.get("server")]
    called = [s["tool"] for s in tool_calls]
    first_final = next((i for i, s in enumerate(res["transcript"]) if s["tool"] == "final_answer"), None)
    t("valid_turns", all(s["tool"] for s in res["transcript"]), "a turn was not a valid action")
    t("self_terminated", first_final is not None, "no final_answer within the step budget")
    t("not_sent_back_by_guards", not any(s.get("guard") for s in res["transcript"]),
      "final_answer was rejected: " + "; ".join(g["gate"] for s in res["transcript"] for g in s.get("guard", [])))
    for tool in e.get("must_call", []):
        t(f"called_{tool}", tool in called, f"{tool} never called")
    quoted = bool(res["citations"]) and any(not c["doc_id"].startswith("shared/") for c in res["citations"])
    if quoted and "resolve_amendment_chain" in {x["name"] for x in res["tool_log"]} | set(res.get("discovered", [])):
        idx = {n: i for i, n in reversed(list(enumerate(called)))}
        t("chain_before_quote", "resolve_amendment_chain" in called, "a clause was quoted with no chain resolved")
    for term in e.get("terms", []):
        if term in ("Affiliate", "Excluded Claims", "Losses") and "resolve_defined_term" in set(res.get("discovered", [])):
            done = any(s["tool"] == "resolve_defined_term" and s["args"].get("term", "").lower() == term.lower() for s in tool_calls)
            t(f"defined_term_{term}", done, f"'{term}' not resolved through the tool")
    if slug:
        nm = short_name(truth["accounts"][slug]["name"]).split()[0].lower()
        wrong = [s["args"].get("counterparty") for s in tool_calls if s["args"].get("counterparty")
                 and nm not in s["args"]["counterparty"].lower()]
        t("tool_args_scoped", not wrong, f"counterparty arg {wrong}")
    t("trace_id_survived", all(x["trace_id_survived"] for x in res["tool_log"]) if res["tool_log"] else True,
      "trace id lost across the MCP hop")
    return dict(outcome=out, trajectory=trj)


MODES = [  # (mode, predicate over failed outcome assertion names / case flags) - first match wins
    ("ocr_extraction_error", lambda f, c, r: c["scanned"] and (any(n in f for n in ("answered", "value_months", "value_floor", "value_days", "cites_in_force", "keyword")))),
    ("superseded_clause_cited", lambda f, c, r: "no_superseded_cited" in f),
    ("ordinary_meaning_of_defined_term", lambda f, c, r: bool({"scope_negative", "scope_positive", "says_uncapped"} & set(f))),
    ("characterised_as_standard", lambda f, c, r: "no_characterisation" in f),
    ("no_referral_to_counsel", lambda f, c, r: "refers_to_counsel" in f),
    ("customer_scope_error", lambda f, c, r: bool({"no_citation", "mentions_candidates", "scoped_to_customer"} & set(f))),
    ("citation_incomplete_or_wrong", lambda f, c, r: bool({"cites_in_force", "citations_complete", "cites_every_link"} & set(f))),
    ("wrong_value", lambda f, c, r: bool({"value_months", "value_floor", "value_days", "keyword"} & set(f))),
]


def classify(failed, case, res):
    for name, pred in MODES:
        if pred(failed, case, res):
            return name
    return "other"


def summarise(rows):
    """rows: [{id, group, outcome_pass, referred, traj_pass, mode}] -> per-group (pass, n, referred) + totals + gap."""
    groups = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        g = groups[r["group"]]
        g[1] += 1
        g[0] += r["outcome_pass"]
        g[2] += bool(r.get("referred"))
    n = len(rows)
    op, tp = sum(r["outcome_pass"] for r in rows), sum(r["traj_pass"] for r in rows)
    lucky = [r["id"] for r in rows if r["outcome_pass"] and not r["traj_pass"]]
    return dict(n=n, outcome_pass=op, traj_pass=tp, referred=sum(bool(r.get("referred")) for r in rows),
                gap_pp=round(100 * (op - tp) / n, 1) if n else 0.0, lucky=lucky,
                groups={g: tuple(v) for g, v in groups.items()}, modes=Counter(r["mode"] for r in rows if not r["outcome_pass"]))
