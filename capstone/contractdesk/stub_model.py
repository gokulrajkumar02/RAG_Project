"""
A deterministic STAND-IN for the agent's model, used only when there is no GROQ_API_KEY. It is NOT a language
model and proves nothing about how gpt-oss-120b behaves: every number produced with it is stamped STUB.

What it IS for: running the real agent loop, the real MCP hop, the real guards and the real eval, end to end.
Everything except the *decision* of which tool to call next and the wording of the answer is real.

Its habits are my hypotheses about how an unguarded model goes wrong; each one is what one of the guards exists to
catch, and each is listed so nobody mistakes them for measurements:

  H1  resolves the amendment chain only for liability / indemnity / termination / payment questions, not for governing
      law or definitions ("they can't have been amended")                       -> chain gate, trajectory gap
  H2  resolves a defined term only if the term is typed capitalised in the question; never for lower-case
      "subsidiaries", and never for "Excluded Claims" unprompted               -> defined-term gate
  H3  on a question that asks for a judgement it appends "This is a standard position."   -> characterisation guard
  H4  takes the first search hit without reading its status, unless the hit carries `in_force_now`
  H5  copies the customer name as written in the question (so "Halcyon" reaches the tool as "Halcyon")
  H6  when a tool says `uncertain` it says so and refers to counsel (it follows the tool's instruction line)

When the loop sends it a "GUARD: ... Required next call: tool(k="v")" message it makes that call.
"""

import json
import re

_REG = None


def _names():
    global _REG
    if _REG is None:
        from .registry import Registry, short_name
        reg = Registry.load()
        _REG = [short_name(n) for n in reg._names.values()]
    return _REG


def _act(thought, tool, **args):
    return json.dumps({"thought": f"[STUB] {thought}", "tool": tool, "args": args})


def _final(answer, cites=()):
    return _act("answer from the results above", "final_answer", answer=answer,
                citations=[{"doc": d, "clause": c} for d, c in dict.fromkeys(cites)])


def _customer(q):
    names = sorted(_names(), key=len, reverse=True)
    for n in names:
        if n.lower() in q.lower():
            return n
    for n in names:
        first = n.split()[0]
        if re.search(rf"\b{re.escape(first)}\b", q):
            return first
    return ""


def _topic(q):
    l = q.lower()
    if re.search(r"playbook|fallback", l):
        return "playbook"
    if re.search(r"how is .*defined|definition of|what (does|do) .* mean|what are (the )?excluded claims", l):
        return "definition"
    if re.search(r"affiliate|subsidiar|sister|group compan", l):
        return "affiliate_scope"
    if "indemn" in l:
        return "indemnity"
    if re.search(r"liab(?:ility|le)|\bcap\b", l):
        return "cap"
    if re.search(r"terminat|notice|convenience|walk away|exit", l):
        return "termination"
    if re.search(r"payment|invoice|\bpay\b|net \d", l):
        return "payment"
    if re.search(r"governing law|jurisdiction|venue|court|which law", l):
        return "law"
    return "generic"


CALL = re.compile(r"Step \d+: called (\w+)\((\{.*?\})\)\nResult:\n<<<TOOL RESULT from [^>]*>>>\n(.*?)\n<<<END TOOL RESULT>>>", re.S)


def _history(prompt):
    hist = prompt.split("History so far", 1)[1].split("What do you do next?", 1)[0]
    calls = []
    for m in CALL.finditer(hist):
        body = m.group(3)
        err = body.startswith("[tool error] ")
        try:
            obj = json.loads(body[len("[tool error] "):] if err else body)
        except ValueError:
            obj = {"raw": body}
        calls.append(dict(tool=m.group(1), args=json.loads(m.group(2)), res=obj, err=err))
    feedback = hist[hist.rfind("GUARD:"):] if "GUARD:" in hist else ""
    return calls, feedback


def _used(c):
    return [x for x in c if x["tool"] in ("search_clauses", "get_clause", "resolve_amendment_chain")]


def decide(prompt):
    q = re.search(r"^Question: (.*)$", prompt, re.M).group(1)
    tools = set(re.findall(r"^(\w+)\(.*\)\s+\[server: ", prompt, re.M))
    calls, feedback = _history(prompt)
    called = lambda t: [c for c in calls if c["tool"] == t]  # noqa: E731
    name, topic = _customer(q), _topic(q)
    v1 = "resolve_amendment_chain" in tools

    m = re.search(r'Required next call: (\w+)\((.*?)\)\s*$', feedback, re.M)
    if m and m.group(1) in tools:
        args = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
        if not any(c["tool"] == m.group(1) and c["args"] == args for c in calls):
            return _act("the guard says this call is required", m.group(1), **args)

    if not called("lookup_contract"):
        return _act("start by looking the customer up", "lookup_contract", counterparty=name or q[:60])
    first = called("lookup_contract")[0]
    if first["err"]:
        r = first["res"]
        if r.get("error") == "ambiguous_counterparty":
            opts = " or ".join(c["name"] for c in r["candidates"])
            return _final(f"More than one customer matches '{name}': {opts}. Which one do you mean?")
        return _final("No customer by the name in the question is on file, so I cannot answer from any contract.")
    cust = first["res"]["name"]

    if topic == "playbook":
        return _final("The fallback playbook is privileged and is not available through this tool; please ask counsel.")

    def need_chain(target):
        return v1 and not [c for c in called("resolve_amendment_chain") if c["args"].get("clause") == target]

    def chain(target):
        return next((c["res"] for c in called("resolve_amendment_chain") if c["args"].get("clause") == target), None)

    def clause_text(res):
        if res.get("in_force"):
            it = res["in_force"]
        elif res.get("results"):
            it = res["results"][0]
            it = it.get("in_force_now") or it
        else:
            it = res
        return it

    def quote(it):
        return f'{it.get("doc", "")} cl. {it["clause"]} (effective {it["effective_date"]}): "{it["text"]}"'

    def uncertain_answer(res, what):
        why = "; ".join(res.get("uncertain", []))
        cites = [(i["doc_id"], i["clause"]) for i in res.get("chain", [])]
        return _final(f"I could not confirm the {what} for {cust} from the documents as extracted: {why}. I am not "
                      f"stating it as in force; this is referred to counsel.", cites)

    judge = " This is a standard position." if re.search(r"standard|acceptable|\bfine\b|\bok\b|market|normal|reasonable", q, re.I) else ""

    # ---- topics that read one clause (cap, termination, payment, indemnity scope) -----------------------------
    targets = {"cap": ("11.3", "liability cap"), "indemnity": ("11.3" if re.search(r"cap|limit|uncapped|liab", q, re.I) else "12.1",
               "indemnity"), "termination": ("14.2", "termination for convenience notice"), "payment": ("5.2", "payment terms")}
    if topic in targets:
        tgt, phrase = targets[topic]
        if v1:
            if need_chain(tgt):
                return _act(f"resolve the chain for clause {tgt} before quoting it", "resolve_amendment_chain", counterparty=cust, clause=tgt)
            res = chain(tgt)
            if res.get("error") or res.get("resolution") == "not_found" or not res.get("in_force"):
                return _final(f"I could not find the {phrase} clause (MSA clause {tgt}) for {cust} in the documents as "
                              f"extracted (the MSA may be a scan whose clause was not recovered). I am not stating anything "
                              f"about it; this is referred to counsel for the source PDF.")
            if res.get("resolution") == "uncertain":
                return uncertain_answer(res, phrase)
            it = res["in_force"]
            extra = ""
            for link in res["chain"]:
                if link["status"] == "NOT_PREVAILING":
                    extra += f' The {link["doc"]} term ("{link["text"][:90]}...") does not prevail under MSA clause 1.4.'
                if link["status"] == "NOT_YET_IN_FORCE":
                    extra += f' {link["doc"]} takes effect {link["effective_date"]} and is not yet in force.'
            cites = [(it["doc_id"], it["clause"])]
            if topic == "indemnity" and tgt == "11.3":
                d = [c for c in called("resolve_defined_term") if c["args"].get("term", "").lower() == "excluded claims"]
                if d and d[0]["res"].get("defined"):
                    defn = d[0]["res"]["definition"]
                    cites.append((defn["doc_id"], defn["clause"]))
                    return _final(f"Indemnification obligations under clauses 12.1 to 12.3 are Excluded Claims "
                                  f'("{defn["text"][:160]}"), so they are not subject to the cap in {quote(it)}.{extra}{judge}', cites)
            return _final(f"{cust}: {quote(it)}.{extra}{judge}", cites)
        if not called("search_clauses"):
            return _act(f"search the {phrase} clause", "search_clauses", counterparty=cust, query=phrase)
        it = clause_text(called("search_clauses")[0]["res"])
        if topic == "indemnity" and tgt == "11.3":
            return _final(f"The indemnities are part of the liability limitation: {quote(it)}.{judge}", [(it["doc_id"], it["clause"])])
        return _final(f"{cust}: {quote(it)}.{judge}", [(it["doc_id"], it["clause"])])

    # ---- governing law (H1: no chain call) ------------------------------------------------------------------
    if topic == "law":
        if "get_governing_law" in tools:
            if not called("get_governing_law"):
                return _act("the law table has this", "get_governing_law", counterparty=cust)
            r = called("get_governing_law")[0]["res"]
            return _final(f"{cust}: governed by {r['governing_law']}; venue {r['venue']}. MSA clause 18.1: \"{r['msa_clause_18_1']}\"",
                          [(f"{r['counterparty']}/msa", "18.1")])
        if not called("search_clauses"):
            return _act("search the governing law clause", "search_clauses", counterparty=cust, query="governing law")
        it = clause_text(called("search_clauses")[0]["res"])
        return _final(f"{cust}: {quote(it)}", [(it["doc_id"], it["clause"])])

    # ---- defined terms ---------------------------------------------------------------------------------------
    term = next((t for t in ("Affiliate", "Excluded Claims", "Confidential Information", "Losses", "Business Day", "Control")
                 if re.search(rf"\b{t}(s|es)?\b", q, re.I)), None)
    if topic == "definition":
        if "resolve_defined_term" in tools and term:
            if not called("resolve_defined_term"):
                return _act("look up the definition", "resolve_defined_term", counterparty=cust, term=term)
            r = called("resolve_defined_term")[0]["res"]
            return _final(f"In {cust}'s contract, \"{r['term']}\": \"{r['definition']['text']}\"", [(r["definition"]["doc_id"], r["definition"]["clause"])])
        if not called("search_clauses"):
            return _act("search for the definition", "search_clauses", counterparty=cust, query=f"{term or 'definition'} means")
        words = [w for w in re.findall(r"[a-z]{5,}", (term or q).lower())]
        for r in called("search_clauses")[0]["res"].get("results", []):
            if any(w in r["text"].lower() for w in words):
                return _final(f'{cust}: {quote(r)}', [(r["doc_id"], r["clause"])])
        return _final("This information was not found in the contract.")

    if topic == "affiliate_scope":
        if "resolve_defined_term" in tools and re.search(r"\bAffiliates?\b", q) and not called("resolve_defined_term"):
            return _act("the question names a defined term", "resolve_defined_term", counterparty=cust, term="Affiliate")
        if not called("get_clause") and not called("search_clauses"):
            return _act("read the Authorised Users clause", "get_clause", counterparty=cust, document="msa", clause="3.2")
        got = called("get_clause")
        it = clause_text(got[0]["res"]) if got else clause_text(called("search_clauses")[0]["res"])
        d = called("resolve_defined_term")
        if d and d[0]["res"].get("defined"):
            defn = d[0]["res"]["definition"]
            covered = "Controlled by" in defn["text"] or "common Control" in defn["text"]
            verdict = ("Customer's subsidiaries ARE Affiliates under the definition, so clause 3.2 extends to them"
                       if covered else "Customer's subsidiaries are NOT Affiliates under the definition (it does not include "
                       "subsidiaries or sister companies), so clause 3.2 does not extend to them")
            return _final(f'{verdict}. Definition: "{defn["text"]}" Clause: {quote(it)}',
                          [(defn["doc_id"], defn["clause"]), (it["doc_id"], it["clause"])])
        return _final(f"Yes: clause 3.2 lets Customer's affiliates, including its subsidiaries, use the Services. {quote(it)}",
                      [(it["doc_id"], it["clause"])])

    # ---- anything else: search and answer only if the hit actually mentions the subject ----------------------
    if not called("search_clauses"):
        return _act("search the customer's clauses", "search_clauses", counterparty=cust, query=q)
    skip = {"contract", "clause", "customer", "agreement", "msa", "does", "include", "contain", "there", "have", "with", "this", "that"}
    words = [w for w in re.findall(r"[a-z]{5,}", q.lower()) if w not in skip and w != cust.lower()]
    for r in called("search_clauses")[0]["res"].get("results", []):
        if any(w in (r["text"] + r.get("title", "")).lower() for w in words):
            it = r.get("in_force_now") or r
            return _final(f"{cust}: {quote(it)}", [(it["doc_id"], it["clause"])])
    return _final("This information was not found in the contract.")
