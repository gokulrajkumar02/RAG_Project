"""
Week 8 — trajectory checks for the contract agent (Track F: Legal Contracts).

Every check here is a FREE rule (no LLM, no API): it reads one run's result
dict — the same structure contract_agent.run_agent returns and race.py
already saves to race_traces.json — and answers "did the agent take a
defensible path?", independently of whether the final answer was right.

The point is the gap between the two. Week 7 only graded the endpoint
(rule check + judge on the final answer), which is exactly the setup the
week's brief warns about: a right answer reached through a wrong path is a
latent bug, because the path is what repeats in production.

Checks (each maps to a named topic in agent_eval/README.md):

  valid_turns         tool-choice accuracy — every model turn parses to one
                      of the three known tools (an empty/unparsed turn or an
                      unknown tool name is a wrong-tool step).
  expected_order      expected tool sequence — the first action is a lookup
                      tool, and final_answer is only reached after at least
                      one search_contract actually ran.
  self_terminated     the agent chose to finish (called final_answer itself)
                      instead of running out of the step/time budget and
                      getting a forced answer from the fallback prompt.
  citations_retrieved no fabricated evidence — every chunk id cited in the
                      final answer was actually returned by a search during
                      this run.
  no_repeat_search    no looping — the agent never re-ran an identical
                      search query twice (a search that returned nothing the
                      first time returns nothing the second time).
  args_in_bounds      tool argument sanity — search queries are non-empty,
                      k stays inside the documented 1..10 window (least
                      privilege on tool arguments, not just on tool names).

A trajectory PASSES only if all six pass. `score_run` also returns the
per-check booleans so a report can rank which mode is failing instead of
just saying "some path problem".
"""

import re

KNOWN_TOOLS = {"search_contract", "list_section_headings", "final_answer"}
LOOKUP_TOOLS = {"search_contract", "list_section_headings"}
CHUNK_RE = re.compile(r"\[chunk (\d+)\]")
K_MIN, K_MAX = 1, 10


def _model_turns(transcript):
    """Model turns only — the harness's own forced-answer marker is excluded."""
    return [
        t for t in transcript
        if not str(t.get("tool", "")).startswith("final_answer (forced")
    ]


def _retrieved_chunk_ids(transcript):
    ids = set()
    for t in _model_turns(transcript):
        if t.get("tool") == "search_contract":
            ids.update(int(m) for m in CHUNK_RE.findall(str(t.get("result", ""))))
    return ids


def check_valid_turns(transcript):
    bad = []
    for i, t in enumerate(_model_turns(transcript), 1):
        tool = str(t.get("tool", "")).strip()
        if tool not in KNOWN_TOOLS or t.get("parse_error"):
            bad.append({"turn": i, "tool": tool, "parse_error": t.get("parse_error", "")})
    return {"pass": not bad, "violations": bad}


def check_expected_order(transcript):
    turns = _model_turns(transcript)
    violations = []
    lookups_before_answer = 0
    searches_before_answer = 0
    for t in turns:
        tool = str(t.get("tool", "")).strip()
        if tool == "final_answer":
            break
        if tool in LOOKUP_TOOLS:
            lookups_before_answer += 1
        if tool == "search_contract":
            searches_before_answer += 1
    if turns:
        first = str(turns[0].get("tool", "")).strip()
        if first not in LOOKUP_TOOLS:
            violations.append(f"first action was {first or '(unparsed)'} , expected a lookup tool")
    if any(str(t.get("tool", "")).strip() == "final_answer" for t in turns) and searches_before_answer == 0:
        violations.append("final_answer reached with zero search_contract calls")
    if not turns:
        violations.append("no model turns at all")
    return {"pass": not violations, "violations": violations}


def check_self_terminated(result):
    forced = result.get("stopped_early", False)
    return {"pass": not forced, "violations": [] if not forced else ["budget exhausted: answer was forced by the fallback prompt"]}


def check_citations_retrieved(result, transcript):
    retrieved = _retrieved_chunk_ids(transcript)
    cited = result.get("chunk_ids") or []
    fabricated = [c for c in cited if int(c) not in retrieved]
    return {"pass": not fabricated, "violations": fabricated, "retrieved": sorted(retrieved), "cited": list(cited)}


def check_no_repeat_search(transcript):
    seen, dupes = set(), []
    for t in _model_turns(transcript):
        if t.get("tool") != "search_contract":
            continue
        q = str((t.get("args") or {}).get("query", "")).strip().lower()
        if q in seen:
            dupes.append(q)
        seen.add(q)
    return {"pass": not dupes, "violations": dupes}


def check_args_in_bounds(transcript):
    bad = []
    for i, t in enumerate(_model_turns(transcript), 1):
        if t.get("tool") != "search_contract":
            continue
        args = t.get("args") or {}
        q = str(args.get("query", "")).strip()
        if not q:
            bad.append({"turn": i, "problem": "empty query"})
        try:
            k = int(args.get("k", 3) or 3)
        except (TypeError, ValueError):
            k = -1
        if not (K_MIN <= k <= K_MAX):
            bad.append({"turn": i, "problem": f"k={args.get('k')!r} outside {K_MIN}..{K_MAX}"})
    return {"pass": not bad, "violations": bad}


CHECKS = {
    "valid_turns": lambda result, transcript: check_valid_turns(transcript),
    "expected_order": lambda result, transcript: check_expected_order(transcript),
    "self_terminated": lambda result, transcript: check_self_terminated(result),
    "citations_retrieved": lambda result, transcript: check_citations_retrieved(result, transcript),
    "no_repeat_search": lambda result, transcript: check_no_repeat_search(transcript),
    "args_in_bounds": lambda result, transcript: check_args_in_bounds(transcript),
}


def score_run(result):
    transcript = result.get("transcript", [])
    checks = {name: fn(result, transcript) for name, fn in CHECKS.items()}
    failed = [name for name, c in checks.items() if not c["pass"]]
    return {
        "trajectory_pass": not failed,
        "failed_checks": failed,
        "checks": checks,
        "n_model_turns": len(_model_turns(transcript)),
    }
