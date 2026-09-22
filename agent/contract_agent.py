"""
Week 7 — hand-built contract agent. No agent framework: this file IS the
loop. Ask the model for one JSON action, run the tool it picked, feed the
result back in as history, repeat — until it calls final_answer or a stop
condition fires.

Two real tools (tools.py) plus the terminal final_answer action. Every
step (thought, tool, args, result) is appended to a transcript that's
returned alongside the answer, so nothing the agent did is hidden —
race.py prints and saves it.

Stop conditions, so this can never run forever:
- MAX_STEPS tool calls (default 4). After that, one last LLM call is
  forced to commit to a final answer from whatever's been gathered so
  far, rather than looping indefinitely.
- MAX_SECONDS wall-clock budget (default 45s), checked before every
  step — fires the same forced-answer fallback if the model is just slow.
"""

import json
import time

from tools import search_contract, list_section_headings

MAX_STEPS = 5  # observed: the model occasionally returns an empty first turn (see
# README) which burns one step recovering — 5 leaves real search/retry headroom
# after that instead of 4, while still being a small, clearly-bounded budget.
MAX_SECONDS = 45
# NOT the same model the fixed workflow uses (openai/gpt-oss-20b): that model is
# tuned for native tool-calling and Groq rejects its output as a malformed tool
# call whenever the prompt describes tools, even with no `tools=` registered on
# the API request. openai/gpt-oss-120b (also used by eval/judge.py for structured
# JSON output) doesn't have this problem, so the agent uses it for the decision
# step. This does mean the two approaches no longer use an identical model - see
# agent/README.md for how that's accounted for when reading the cost numbers.
AGENT_MODEL = "openai/gpt-oss-120b"

AGENT_SYSTEM_PROMPT = """You are a legal-contract research agent. You answer questions about one employment contract using tools that look up real clause text — never from memory, never a guess.

Tools you can call, ONE per turn:

1. search_contract(query, k) - semantic search over the contract's clauses. Returns the top k matching chunks, each labeled "[chunk N]". A short, contract-style phrase works better than a full colloquial question (e.g. "notice period" beats "how much heads-up do I need to give?").
2. list_section_headings() - returns every numbered section heading in the contract (no arguments). Use this when search_contract isn't finding the right clause - it shows you the contract's own wording for each section, so a follow-up search_contract is much more likely to succeed.
3. final_answer(answer, chunk_ids) - ends the task. `answer` is your final answer to the user's question, in plain text (or exactly "This information was not found in the contract." if it genuinely isn't in the contract after you've tried). `chunk_ids` is the list of chunk numbers (integers) your answer is grounded in.

Rules:
- Call search_contract at least once before answering.
- If your first search doesn't clearly contain the answer, try list_section_headings and/or a reformulated search_contract before giving up - but don't keep searching once you already have what you need.
- Call final_answer exactly once, when you're done.
- Respond with ONLY one JSON object per turn, no other text, no markdown fencing:
{{"thought": "one short sentence on what you're doing and why", "tool": "<tool name>", "args": {{...}}}}

Question: {question}

History so far (your previous tool calls and their results this turn):
{history}

What do you do next? Respond with exactly one JSON object."""


def _call_llm(prompt, api_key, model=AGENT_MODEL):
    from langchain_groq import ChatGroq
    from langchain_core.output_parsers import StrOutputParser

    llm = ChatGroq(groq_api_key=api_key, model_name=model, temperature=0)
    chain = llm | StrOutputParser()
    return chain.invoke(prompt)


def _parse_action(raw):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        obj = json.loads(cleaned)
        return {
            "thought": str(obj.get("thought", "")).strip(),
            "tool": str(obj.get("tool", "")).strip(),
            "args": obj.get("args", {}) or {},
        }
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"thought": "", "tool": "", "args": {}, "parse_error": raw[:200]}


def _format_history(history):
    if not history:
        return "(none yet - this is your first move)"
    blocks = []
    for i, h in enumerate(history, 1):
        blocks.append(f"Step {i}: called {h['tool']}({h['args']})\nResult:\n{h['result']}")
    return "\n\n".join(blocks)


def _dispatch(tool, args, index):
    if tool == "search_contract":
        return search_contract(index, args.get("query", ""), int(args.get("k", 3) or 3))
    if tool == "list_section_headings":
        return list_section_headings()
    return f"Unknown tool '{tool}'. Available tools: search_contract, list_section_headings, final_answer."


def _build_result(answer, chunk_ids, transcript, llm_calls, elapsed, stopped_early):
    return {
        "answer": answer,
        "chunk_ids": chunk_ids,
        "llm_calls": llm_calls,
        "tool_calls": sum(1 for t in transcript if t.get("tool") in ("search_contract", "list_section_headings")),
        "elapsed": elapsed,
        "transcript": transcript,
        "stopped_early": stopped_early,
    }


def run_agent(question, index, api_key, max_steps=MAX_STEPS, max_seconds=MAX_SECONDS):
    start = time.time()
    history = []
    transcript = []
    llm_calls = 0

    for step in range(1, max_steps + 1):
        if time.time() - start > max_seconds:
            break

        prompt = AGENT_SYSTEM_PROMPT.format(question=question, history=_format_history(history))
        raw = _call_llm(prompt, api_key)
        llm_calls += 1
        action = _parse_action(raw)
        transcript.append({"step": step, **action})

        if action["tool"] == "final_answer":
            answer = str(action["args"].get("answer", "")).strip()
            answer = answer or "This information was not found in the contract."
            chunk_ids = action["args"].get("chunk_ids", [])
            return _build_result(answer, chunk_ids, transcript, llm_calls, time.time() - start, stopped_early=False)

        result = _dispatch(action["tool"], action["args"], index)
        history.append({"tool": action["tool"] or "(unparsed)", "args": action["args"], "result": result})
        transcript[-1]["result"] = result

    # Budget exhausted before the agent called final_answer on its own -
    # force one last call so the task still ends with an answer, not silence.
    forced_prompt = (
        f"You have used your full search budget for this question: {question}\n\n"
        f"Everything you found:\n{_format_history(history)}\n\n"
        'Answer now using ONLY the above. If it does not contain the answer, say '
        '"This information was not found in the contract." Respond with plain text - '
        "just the answer, no JSON."
    )
    answer = _call_llm(forced_prompt, api_key).strip()
    llm_calls += 1
    transcript.append({"step": max_steps + 1, "tool": "final_answer (forced by budget)", "args": {}, "result": answer})

    return _build_result(answer, [], transcript, llm_calls, time.time() - start, stopped_early=True)
