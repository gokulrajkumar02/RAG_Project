"""
The two specialists, and the HTTP shell they sit behind.

Narrow on purpose (the whole case for a team is "narrow prompt, fewer tools"):
  clause worker         ONE tool, search_clauses - the same reranked + neighbour-stitched search the single
                        agent's search_contract is (it calls that very function), minus list_section_headings.
                        Its prompt says what it must NOT do (interpret defined terms, write the final answer).
  defined-terms worker  ONE tool, lookup_defined_terms - whole definitions from contract_facts, not 150-char
                        chunks. It never sees a clause.

Both run the same JSON-action loop mechanics as the Week 7 agent (parser and history format are imported
from it, not re-written), each with a small step budget. Each is a real HTTP service on localhost
(POST /tasks): a worker failure is therefore a real status code the manager's client really sees,
which is what "make the defined-terms worker return a 500" asks to test.

Every brief carries the governing effective date. Nothing carries the whole contract: a worker gets a
sub-task, the user's wording, and what its own tool returns.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agent"))

import tools as agent_tools  # noqa: E402  (agent/tools.py: search_contract)
from contract_agent import _parse_action, _format_history  # noqa: E402  (Week 7 loop mechanics)

CLAUSE_MAX_STEPS = 3
TERMS_MAX_STEPS = 3
WORKER_MAX_SECONDS = 45

CLAUSE_PROMPT = """You are the CLAUSE worker on a contract-research team. Your one job: find the contract text that answers the sub-task and report it verbatim. You do not interpret defined terms (another worker does that) and you do not write the final answer (the manager does).

Governing agreement: {governing}

Sub-task from the manager: {task}
User's original question (for wording only): {question}

Tools, ONE per turn:
1. search_clauses(query, k) - semantic search over the agreement's clauses; returns the top k chunks, each labelled "[chunk N]". A short contract-style phrase beats a colloquial question.
2. report(found, quotes, chunk_ids) - ends your task. found: true or false. quotes: the exact clause sentences that answer the sub-task (the shortest that suffice). chunk_ids: the chunk numbers they came from. If, after searching, the agreement does not contain it, report found=false with no quotes.

Rules:
- Call search_clauses at least once before report. Search again with different wording only if the first results clearly miss.
- Respond with ONLY one JSON object per turn, no other text, no markdown fencing:
{{"thought": "one short sentence", "tool": "<tool name>", "args": {{...}}}}

History so far (your previous tool calls and their results):
{history}

What do you do next? Respond with exactly one JSON object."""

TERMS_PROMPT = """You are the DEFINED-TERMS worker on a contract-research team. Your one job: report exactly how the agreement defines the terms the manager names. You never read other clauses and you never answer the user's question.

Governing agreement: {governing}

Terms to define: {terms}

Tools, ONE per turn:
1. lookup_defined_terms(terms) - returns the agreement's definition for each term in `terms` (a list of strings), or NOT DEFINED.
2. report(definitions) - ends your task. definitions: an object mapping each term to its definition exactly as the lookup returned it (NOT DEFINED where it said so).

Rules:
- Call lookup_defined_terms once with all the terms, then report.
- Respond with ONLY one JSON object per turn, no other text, no markdown fencing:
{{"thought": "one short sentence", "tool": "<tool name>", "args": {{...}}}}

History so far (your previous tool calls and their results):
{history}

What do you do next? Respond with exactly one JSON object."""


def lookup_defined_terms(facts, terms):
    if isinstance(terms, str):
        terms = [terms]
    by_lower = {k.lower(): k for k in facts.defined_terms}
    lines = []
    for t in terms or []:
        key = by_lower.get(str(t).strip().lower())
        if key:
            lines.append(f'"{key}" - {facts.defined_terms[key]["definition"]}')
        else:
            lines.append(f'"{t}" - NOT DEFINED in this agreement')
    return "\n".join(lines) or "lookup_defined_terms needs at least one term."


def _worker_loop(llm, *, role, hand_off, case, arm, prompt_for, tools, final_tool, max_steps):
    """-> (final_args | None, transcript, forced_text | None). Same shape as the Week 7 loop, smaller."""
    start = time.time()
    history, transcript = [], []
    for step in range(1, max_steps + 1):
        if time.time() - start > WORKER_MAX_SECONDS:
            break
        raw = llm(prompt_for(_format_history(history)), role=role, hand_off=hand_off, case=case, arm=arm)
        action = _parse_action(raw)
        transcript.append({"step": step, **action})
        if action["tool"] == final_tool:
            return action["args"], transcript, None
        tool = tools.get(action["tool"])
        result = tool(action["args"]) if tool else (
            f"Unknown tool '{action['tool']}'. Available tools: {', '.join(tools)}, {final_tool}.")
        history.append({"tool": action["tool"] or "(unparsed)", "args": action["args"], "result": result})
        transcript[-1]["result"] = result

    forced_prompt = (
        f"Your step budget is used up. Everything you found:\n{_format_history(history)}\n\n"
        "Give your report now in plain text, using ONLY the above."
    )
    forced = llm(forced_prompt, role=role, hand_off=hand_off, case=case, arm=arm).strip()
    transcript.append({"step": max_steps + 1, "tool": f"{final_tool} (forced by budget)", "result": forced})
    return None, transcript, forced


def make_clause_handler(llm, index):
    def handle(body):
        case, arm = body["case"], body.get("arm", "multi")
        tools = {"search_clauses": lambda a: agent_tools.search_contract(
            index, a.get("query", ""), min(int(a.get("k", 3) or 3), 5))}

        def prompt_for(history):
            return CLAUSE_PROMPT.format(governing=body["governing"], task=body["task"],
                                        question=body["question"], history=history)

        args, transcript, forced = _worker_loop(
            llm, role="clause", hand_off="manager -> clause_worker", case=case, arm=arm,
            prompt_for=prompt_for, tools=tools, final_tool="report", max_steps=CLAUSE_MAX_STEPS)
        if args is not None:
            result = {"found": bool(args.get("found", True)),
                      "quotes": [str(q) for q in (args.get("quotes") or [])],
                      "chunk_ids": args.get("chunk_ids") or []}
        else:
            result = {"found": None, "quotes": [forced], "chunk_ids": [], "note": "step budget exhausted; forced report"}
        return {"result": result, "transcript": transcript}
    return handle


def make_terms_handler(llm, facts):
    def handle(body):
        case, arm = body["case"], body.get("arm", "multi")
        tools = {"lookup_defined_terms": lambda a: lookup_defined_terms(facts, a.get("terms"))}

        def prompt_for(history):
            return TERMS_PROMPT.format(governing=body["governing"], terms=json.dumps(body["terms"]), history=history)

        args, transcript, forced = _worker_loop(
            llm, role="terms", hand_off="manager -> terms_worker", case=case, arm=arm,
            prompt_for=prompt_for, tools=tools, final_tool="report", max_steps=TERMS_MAX_STEPS)
        if args is not None and isinstance(args.get("definitions"), dict):
            result = {"definitions": {str(k): str(v) for k, v in args["definitions"].items()}}
        else:
            result = {"definitions": {}, "note": "step budget exhausted or malformed report", "raw": forced or ""}
        return {"result": result, "transcript": transcript}
    return handle


class WorkerServer:
    """A worker as a localhost HTTP service. `fail_cases`: case ids for which EVERY request gets a 500."""

    def __init__(self, name, handle, fail_cases=()):
        self.name = name
        self.handle = handle
        self.fail_cases = set(fail_cases)
        self.hits = []          # one dict per request the service received
        self.url = None
        self._httpd = None

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                case = body.get("case")
                if case in outer.fail_cases:
                    outer.hits.append({"case": case, "status": 500, "injected": True})
                    self._send(500, {"error": "injected fault: worker crashed"})
                    return
                try:
                    out, status = outer.handle(body), 200
                except Exception as exc:  # a real worker bug is a 500 too
                    out, status = {"error": repr(exc)}, 500
                outer.hits.append({"case": case, "status": status, "injected": False})
                self._send(status, out)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}/tasks"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


def post_task(url, payload, *, meter, arm, case, worker, attempts=2, backoff=0.5, timeout=180):
    """
    POST one brief to a worker. 5xx and connection errors get ONE retry (attempts=2): what any HTTP
    client library does by default, and not more, so a persistent worker failure is visible instead of
    being absorbed by a retry loop. Every attempt is logged as a hand-off event (0 LLM tokens when it
    fails before the worker reaches the model).
    """
    body = json.dumps(payload).encode()
    for n in range(1, attempts + 1):
        t0 = time.perf_counter()
        status, out, ok = None, {}, False
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, out, ok = resp.status, json.loads(resp.read()), True
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                out = json.loads(exc.read())
            except Exception:
                out = {"error": f"HTTP {exc.code}"}
        except Exception as exc:  # refused / reset / timeout
            out = {"error": repr(exc)}
        dt = time.perf_counter() - t0
        meter.add_event(arm=arm, case=case, worker=worker, attempt=n, status=status, ok=ok, t0=t0,
                        latency_s=dt, bytes_out=len(body), error=None if ok else out.get("error"))
        if ok:
            return {"ok": True, "status": status, "attempts": n, "out": out}
        if n == attempts or not (status is None or status >= 500):
            return {"ok": False, "status": status, "attempts": n, "error": out.get("error")}
        time.sleep(backoff)
