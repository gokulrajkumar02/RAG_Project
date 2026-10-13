"""
A deterministic STAND-IN for the model, for running the agent loop without a
GROQ_API_KEY. It is NOT a language model and proves nothing about how a real model
behaves — every transcript it produces is labelled STUB.

What it IS good for: proving the plumbing. The host really spawns the servers, really
runs initialize + tools/list, and every tools/call really crosses MCP to the server
named in the trace. Only the *decision* of which tool to call, and the wording of the
final answer, come from the rules below instead of a model.

Two rules matter for the demos, and both are the author's assumptions about helpful
models, not measurements: (1) error_demo.py — after a failed tool call it follows a
hint of the form "call <tool>" ONLY if that tool takes no arguments; (2) the gateway
demo — after a "Denied" result it falls back to get_contract for the same contract.
"""

import json
import re

CONTRACT_ID = re.compile(r"\b[A-Z]{3}-\d{4}-\d{4}\b")
CLAUSE_REF = re.compile(r"\bclause\s+(\d+(?:\.\d+)*)", re.I)
TOOL_LINE = re.compile(r"^([a-z_]+)\(([^)]*)\)\s+\[server: ", re.M)
RESULT = re.compile(r"<<<TOOL RESULT from ([^ ]+) [^>]*>>>\n(.*?)\n<<<END TOOL RESULT>>>", re.S)
CALL = re.compile(r"^Step \d+: called ([a-z_]+)\(", re.M)


def _act(thought, tool, **args):
    return json.dumps({"thought": f"[STUB] {thought}", "tool": tool, "args": args})


def stub_llm(prompt):
    question = re.search(r"^Question: (.*)$", prompt, re.M).group(1)
    tools = {m.group(1): m.group(2) for m in TOOL_LINE.finditer(prompt)}
    history = prompt.split("History so far", 1)[1]
    results = RESULT.findall(history)
    called = CALL.findall(history)

    cid = CONTRACT_ID.search(question)
    if not results:
        clause = CLAUSE_REF.search(question)
        q = question.lower()
        if cid and "amend" in q and "get_amendment_chain" in tools:
            return _act("question names a contract and its amendments", "get_amendment_chain", contract_id=cid.group(0))
        if cid and ("effective" in q or "date" in q) and "get_effective_date" in tools:
            return _act("question asks for an effective date", "get_effective_date", contract_id=cid.group(0))
        if cid and "get_contract" in tools:
            return _act("question names a contract id", "get_contract", contract_id=cid.group(0))
        if clause and "get_clause" in tools:
            return _act("question names a clause number", "get_clause", clause_number=clause.group(1))
        return _act("no tool matches by id; fall back to clause search", "search_clauses", query=question)

    src, last = results[-1]
    if last.startswith("[tool error] Denied") and cid and "get_contract" in tools and "get_contract" not in called:
        return _act("that tool is denied to me; the base record is still reachable", "get_contract",
                    contract_id=cid.group(0))
    if last.startswith("[tool error]"):
        for name, sig in tools.items():
            if name in last and not sig.strip() and name not in called:
                return _act(f"the error text points at {name}; follow it", name)
        first_line = last.splitlines()[0]
        return _act("the error gives me nothing to retry with", "final_answer",
                    answer=f"I could not get that. The tool said: {first_line}")
    return _act("I have a tool result; answer from it", "final_answer", answer=last.strip()[:600])
