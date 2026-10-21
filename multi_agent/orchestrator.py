"""
The manager: split the question, hand pieces to the two specialists, synthesise.

    user question
        |  (1) PLAN    one model call: which sub-task for the clause worker, which defined terms (if any)
        v
    manager ---- HTTP ----> clause worker          } fanned out in parallel: the two jobs are independent,
            \--- HTTP ----> defined-terms worker   } which is the one thing a team genuinely buys you
        |  (2) both results come back (or fail)
        v  (3) SYNTHESIS one model call over the worker results only -> the answer

Context discipline (the brief's "you tested your context strategy, not the pattern" trap, avoided):
a worker's brief is the sub-task + the user's wording + the governing-agreement line (effective date,
amendments). Not the contract, not the other worker's output. A worker answers with a compact report
(quotes + ids / definitions), not the raw chunks it read. If the plan names no defined term the
defined-terms worker is not called at all - skipping a hand-off is the cheapest hand-off.

Model-turn recovery: a blank or unparsable PLAN, and a blank SYNTHESIS, get one retry. The Week 7 README
documents that gpt-oss occasionally returns an empty turn; the single agent recovers by looping, so the
manager gets the same courtesy - and pays for it, because the retry is metered like any other call.

Failure handling is deliberately plain: one retry on 5xx/connection error (workers.post_task), then the
result is marked UNAVAILABLE and the synthesis call still runs. The synthesis prompt has NO special rule
about unavailable workers - whether the model discloses the gap, hides it, or invents around it is the
thing failure_case.md exists to record, so it is not engineered either way.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from workers import post_task

PLAN_PROMPT = """You are the MANAGER of a contract-research team answering questions about ONE employment agreement. You do not read the contract yourself. You split the question and hand pieces to two specialists:
- clause worker: finds the clause text that answers a sub-task.
- defined-terms worker: reports how the agreement defines capitalised terms.

Governing agreement: {governing}
Defined terms on file: {term_names}

Reply with ONLY one JSON object, no other text, no markdown fencing:
{{"clause_task": "<what the clause worker should find, in the contract's own wording>", "terms": ["<defined term>", ...]}}
List a term ONLY if the answer depends on how the agreement defines it; otherwise use an empty list.

Question: {question}"""

SYNTH_PROMPT = """You are the MANAGER of a contract-research team. Answer the user's question using ONLY the worker results below. If the results do not contain the answer, reply exactly: "This information was not found in the contract." Be clear and concise.

Governing agreement: {governing}

Question: {question}

CLAUSE WORKER RESULT:
{clause_result}

DEFINED-TERMS WORKER RESULT:
{terms_result}

Answer:"""

NOT_REQUESTED = "NOT REQUESTED - the manager judged the answer does not depend on a defined term."


def parse_plan(raw, question):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        obj = json.loads(cleaned)
        task = str(obj.get("clause_task") or "").strip() or question
        terms = obj.get("terms") or []
        terms = [str(t).strip() for t in terms if str(t).strip()] if isinstance(terms, list) else []
        return {"clause_task": task, "terms": terms[:4], "parse_error": None}
    except (json.JSONDecodeError, AttributeError, TypeError):
        # visible fallback, never silent: the trace carries parse_error
        return {"clause_task": question, "terms": [], "parse_error": raw[:200]}


def format_clause_result(res):
    found = {True: "yes", False: "no", None: "unknown"}[res.get("found")]
    lines = [f"found: {found}"]
    if res.get("chunk_ids"):
        lines.append(f"chunks: {', '.join(str(c) for c in res['chunk_ids'])}")
    if res.get("quotes"):
        lines.append("quotes:")
        lines += [f'- "{q}"' for q in res["quotes"]]
    if res.get("note"):
        lines.append(f"note: {res['note']}")
    return "\n".join(lines)


def format_terms_result(res):
    defs = res.get("definitions") or {}
    if not defs:
        return f"(the worker returned no definitions{': ' + res['raw'] if res.get('raw') else ''})"
    return "\n".join(f'"{t}" - {d}' for t, d in defs.items())


def unavailable(worker, outcome):
    return (f"UNAVAILABLE - the {worker} returned HTTP {outcome['status']} after {outcome['attempts']} attempts "
            f"(no result retrieved).")


class Orchestrator:
    def __init__(self, llm, meter, facts, clause_url, terms_url):
        self.llm, self.meter, self.facts = llm, meter, facts
        self.urls = {"clause_worker": clause_url, "terms_worker": terms_url}

    def _ask(self, prompt, *, role, hand_off, case, arm, valid):
        text = self.llm(prompt, role=role, hand_off=hand_off, case=case, arm=arm)
        if not valid(text):
            text = self.llm(prompt, role=role, hand_off=hand_off, case=case, arm=arm)
        return text

    def run(self, question, case, arm="multi"):
        t0 = time.perf_counter()
        governing = self.facts.governing_line()
        term_names = ", ".join(f'"{t}"' for t in self.facts.defined_terms)

        plan_raw = self._ask(PLAN_PROMPT.format(governing=governing, term_names=term_names, question=question),
                             role="plan", hand_off="user -> manager", case=case, arm=arm,
                             valid=lambda t: parse_plan(t, question)["parse_error"] is None)
        plan = parse_plan(plan_raw, question)

        base = {"case": case, "arm": arm, "question": question, "governing": governing}
        jobs = {"clause_worker": {**base, "task": plan["clause_task"]}}
        if plan["terms"]:
            jobs["terms_worker"] = {**base, "terms": plan["terms"]}

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(post_task, self.urls[name], payload, meter=self.meter, arm=arm,
                                         case=case, worker=name) for name, payload in jobs.items()}
            outcomes = {name: f.result() for name, f in futures.items()}

        clause = outcomes["clause_worker"]
        clause_text = (format_clause_result(clause["out"]["result"]) if clause["ok"]
                       else unavailable("clause worker", clause))
        if "terms_worker" not in outcomes:
            terms_text = NOT_REQUESTED
        elif outcomes["terms_worker"]["ok"]:
            terms_text = format_terms_result(outcomes["terms_worker"]["out"]["result"])
        else:
            terms_text = unavailable("defined-terms worker", outcomes["terms_worker"])

        answer = self._ask(SYNTH_PROMPT.format(governing=governing, question=question,
                                               clause_result=clause_text, terms_result=terms_text),
                           role="synth", hand_off="workers -> manager", case=case, arm=arm,
                           valid=lambda t: bool(t.strip())).strip()

        return {
            "answer": answer,
            "elapsed": time.perf_counter() - t0,
            "trace": {
                "plan_raw": plan_raw,
                "plan": plan,
                "terms_requested": plan["terms"],
                "delegated_to": list(jobs),
                "outcomes": {n: {k: v for k, v in o.items() if k != "out"} for n, o in outcomes.items()},
                "worker_transcripts": {n: o["out"].get("transcript") for n, o in outcomes.items() if o["ok"]},
                "clause_result_text": clause_text,
                "terms_result_text": terms_text,
                "clause_quotes": (clause["out"]["result"].get("quotes") or []) if clause["ok"] else [],
            },
        }
