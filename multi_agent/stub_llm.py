"""
A deterministic STAND-IN for the model, used only when there is no GROQ_API_KEY. It is NOT a language
model and proves nothing about how one behaves: every artefact produced with it is stamped STUB.

What it is for: exercising the real plumbing end to end - retrieval over the real index, both
workers as real HTTP services, the real injected 500, the meter, the report writers - so that the
first run with a real key is not also the first run of the code.

What it must not be used for: any claim about pass rate, latency, tokens or cost. Its "answers" are
the retrieved text copied out; its "decisions" are string rules; its token counts are tiktoken/char
estimates of the prompts this code really builds, not API-reported usage; its latency is the
latency of local string handling. Both arms get the same stub, so nothing here favours either, but
nothing here is evidence either.
"""

import json
import re

NOT_FOUND = "This information was not found in the contract."
_CHUNK = re.compile(r"\[chunk (\d+)\] (.*?)(?=\n\n\[chunk \d+\]|\n\nStep \d+:|\Z)", re.S)

# which question words make the stub's planner ask for a defined term (a guess, not a model)
_ALIASES = {
    "agreement": (" contract", " agreement"),
    "company": (" company", " employer", " firm"),
    "employee": (" i ", " my ", " me ", " employee"),
    "confidential information": ("secret", "confidential", "leak"),
}


def _act(tool, **args):
    return json.dumps({"thought": "[STUB] rule-based, not a model", "tool": tool, "args": args})


def _find(pattern, text, default=""):
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else default


def _history(prompt):
    return prompt.split("History so far", 1)[1] if "History so far" in prompt else ""


def _chunks(history):
    seen, out = set(), []
    for cid, text in _CHUNK.findall(history):
        if cid not in seen:
            seen.add(cid)
            out.append((int(cid), " ".join(text.split())))
    return out


def single(prompt):
    question = _find(r"^Question: (.*)$", prompt)
    history = _history(prompt)
    if "(none yet" in history:
        return _act("search_contract", query=question, k=3)
    chunks = _chunks(history)
    if not chunks:
        return _act("final_answer", answer=NOT_FOUND, chunk_ids=[])
    return _act("final_answer", answer=" ".join(t for _i, t in chunks)[:700], chunk_ids=[i for i, _t in chunks])


def plan(prompt):
    question = " " + _find(r"^Question: (.*)$", prompt).lower() + " "
    names = re.findall(r'"([^"]+)"', _find(r"^Defined terms on file: (.*)$", prompt))
    terms = [n for n in names if any(a in question for a in _ALIASES.get(n.lower(), (n.lower(),)))]
    return json.dumps({"clause_task": question.strip(), "terms": terms})


def clause(prompt):
    task = _find(r"^Sub-task from the manager: (.*)$", prompt)
    history = _history(prompt)
    if "(none yet" in history:
        return _act("search_clauses", query=task, k=3)
    chunks = _chunks(history)
    return _act("report", found=bool(chunks), quotes=[t[:300] for _i, t in chunks[:3]],
                chunk_ids=[i for i, _t in chunks[:3]])


def terms(prompt):
    wanted = json.loads(_find(r"^Terms to define: (.*)$", prompt, "[]"))
    history = _history(prompt)
    if "(none yet" in history:
        return _act("lookup_defined_terms", terms=wanted)
    defs = dict(re.findall(r'^"(.+?)" - (.*)$', history, re.M))
    return _act("report", definitions=defs)


def synth(prompt):
    clause_part = prompt.split("CLAUSE WORKER RESULT:\n", 1)[-1].split("\n\nDEFINED-TERMS WORKER RESULT:\n", 1)
    clause_text = clause_part[0]
    terms_text = clause_part[1].split("\n\nAnswer:", 1)[0] if len(clause_part) > 1 else ""
    if "found: no" in clause_text:
        return NOT_FOUND
    parts = re.findall(r'^- "(.*)"$', clause_text, re.M)
    if terms_text and not terms_text.startswith("NOT REQUESTED"):
        parts.append("Defined terms: " + terms_text.replace("\n", " | "))   # naive pass-through, errors included
    return " ".join(parts) or NOT_FOUND


_ROLES = {"single": single, "plan": plan, "clause": clause, "terms": terms, "synth": synth}


class StubBackend:
    mode = "stub"

    def invoke(self, prompt, role):
        return _ROLES[role](prompt), None, 0.0


def stub_judge(question, reference_context, answer):
    """The STUB judge defers to the rule check (scores PASS); the rule check still runs for both arms."""
    return {"verdict": "PASS", "reason": "STUB judge: no model available, rule check decides"}
