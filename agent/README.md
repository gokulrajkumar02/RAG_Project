# Week 7 — Agent Loops (Track F: Legal Contracts)

Task: build a hand-rolled agent that completes a genuinely multi-step
task with visible steps and a safe stop condition, build the same task as
a plain fixed sequence, and race them on speed, cost, and reliability —
then say honestly which one you'd ship.

## Why this task, specifically

Weeks 4–6 already found and left unresolved a specific, real failure:
for `notice_period` and `overtime`, the correct chunk **never enters the
top-10 FAISS candidate pool at all** for the paraphrased question (see
`error_analysis/error_taxonomy.md`, Group 2). Week 4's reranker couldn't
fix it — nothing to rerank if the chunk isn't in the pool. Week 6's
neighbor-stitch fix couldn't fix it either — no chunk was retrieved to
stitch a neighbor onto. Both are single-shot, one-query fixes,
structurally unable to recover from a bad first search.

That's exactly the situation the brief describes as agent-shaped: "the
path changes with the input." Most questions in the eval set are
answerable from one search. A few genuinely need a second search with
different words, or a look at the contract's actual section headings
before retrying — and there's no way to know which questions need that
in advance. A fixed sequence can't adapt; an agent that can look at what
it found and decide to try again can.

## The agent

`contract_agent.py` — the loop, in full, is: ask the model for one JSON
action, run the tool it picked, feed the result back in as history,
repeat until it calls `final_answer` or a stop condition fires. No agent
framework — this file *is* the loop (~150 lines including comments,
prompt text, and JSON parsing; the loop itself is closer to 30).

Two real tools (`tools.py`), deliberately different in kind:

- **`search_contract(query, k)`** — the exact retrieval the fixed
  pipeline already uses in production: reranked FAISS search (Week 4) +
  neighbor-stitch context expansion (Week 6). Reusing it rather than
  writing a second retrieval path means the race isolates ONE variable —
  whether looping/retrying helps — not whether the agent has a better
  single search.
- **`list_section_headings()`** — the contract's own numbered section
  headings, read from `create_sample_pdf.py`'s `SECTIONS` list (the
  single source of truth for what's actually in the indexed PDF, not a
  regex guess over re-flowed chunk text). This is the agent's recovery
  tool: if `search_contract` misses, seeing the real heading ("6. NOTICE
  PERIOD") lets the agent retry with the contract's own wording instead
  of the user's paraphrase.

`final_answer(answer, chunk_ids)` isn't a lookup — it's the agent's
terminal action, handled directly in the loop.

**Stop conditions** (so it can never run forever):
- `MAX_STEPS = 5` tool calls. After that, one last forced LLM call
  commits to a final answer from whatever's been gathered, instead of
  looping indefinitely.
- `MAX_SECONDS = 45` wall-clock budget per question, checked before every
  step — fires the same forced-answer fallback if the model is just slow.

Every step (thought, tool, args, result) is appended to a transcript
returned with the answer — nothing the agent did is hidden. `race.py`
prints it and saves the full per-question transcripts to
`race_traces.json`.

### A real quirk worth reporting, not hiding

The agent's decision model (`openai/gpt-oss-120b` — see below for why)
occasionally returns an **empty first-turn response** before it starts
producing valid actions — visible in the transcripts as a step with an
empty `tool`/`thought` and a "Unknown tool ''" observation, which the
agent then recovers from on the next step. This isn't scripted away: it's
a real characteristic of looping an LLM, it costs one extra call per
occurrence, and it's exactly the kind of thing "every step visible"
exists to surface rather than hide behind a clean summary.

### Why the agent uses a different model than the fixed workflow

The fixed workflow's `generate_answer` (and the agent, in an earlier
version of this file) used `openai/gpt-oss-20b`, the model the app
already ships with. That model is tuned for native tool-calling, and Groq
rejects its plain-text output with a 400 (`"Tool choice is none, but
model called a tool"`) whenever the prompt describes tools in a
structured way — even with no `tools=` registered on the API request, it
tries to emit its own internal function-call format instead of following
the JSON schema asked for in the prompt. `openai/gpt-oss-120b` (also
used by `eval/judge.py` for structured JSON output, where it's reliable)
doesn't have this problem, so the agent's decision step uses that
instead.

**What this means for reading the cost numbers below**: LLM-call *count*
is a fair volume comparison between the two approaches, but not a
$-for-$ one, since 120b costs more per call than 20b. The agent's real
cost disadvantage is understated by a raw call-count comparison, not
overstated.

## The fixed workflow

`fixed_workflow.py` — not a new pipeline. It's the exact sequence
`app.py` already runs live: one `search_reranked` call, one
`expand_with_neighbors` call, one `generate_answer` call. The point of a
fixed-workflow comparison is to race the agent against what's actually
shipping today, not a strawman rebuilt from scratch for this exercise.

## The race

`race.py` — the one command. Runs both approaches over all 24 questions
in `eval/questions.py` (the same set Week 6 turned into permanent
regression tests), scores every answer with the free rule check + the
LLM judge validated in Week 6 (83.3% agreement with human grading — not
revalidated here, since nothing about the judge changed), and reports
pass rate, wall-clock time, and LLM-call count — overall and per Week 5
`problem_type`, so the `never_retrieved_*` questions the fixed pipeline
structurally can't solve are visible as their own row, not averaged away.

```bash
# needs GROQ_API_KEY in .env — real Groq calls throughout (~200+ across
# both approaches + judge calls for 24 questions; several minutes)
python agent/race.py
```

Outputs: `race_report.md` (summary tables) and `race_traces.json` (every
agent step, every question — the full transcripts backing "steps
visible").

## Result

Full numbers: `race_report.md` (summary) and `race_traces.json` (every
agent step, every question).

| metric | fixed | agent |
|---|---|---|
| pass rate | 14/24 (58.3%) | 15/24 (62.5%) |
| avg seconds/question | 1.29 | 13.52 |
| avg LLM calls/question | 1.00 | 2.92 |

| problem_type | fixed | agent |
|---|---|---|
| never_retrieved_false_notfound (`overtime`, `notice_period`) | 0/2 | **2/2** |
| wrong_item_selected (`immediate_termination_fraud`) | 0/1 | **1/1** |
| baseline_pass | 11/15 | 10/15 |
| split_clause_refusal | 1/3 | 1/3 |
| never_retrieved_lucky_pass (`leave_approval`) | 0/1 | 0/1 |
| no_answer_control | 2/2 | 1/2 |

**The hypothesis behind this whole design held up.** `overtime` and
`notice_period` — the two questions Weeks 4 and 6 documented as
unfixable because the correct chunk never enters the retrieval candidate
pool for that phrasing — both got fixed by the agent, by reformulating
the query to the contract's own wording. `notice_period`'s transcript:
first search ("how much heads-up...") comes up empty for the useful
clause; the agent reformulates to `"notice period"` and chunk 14 (the
actual 30-day clause) comes back immediately. `immediate_termination_fraud`
(picked the wrong bullet from a list, Week 5 Group 3) also got fixed —
not predicted going in, a genuine bonus.

**Three of the four "regressions" in `baseline_pass` are an eval-design
artifact, not the agent getting things wrong** — checked directly, not
assumed. `noncompete_duration`, `noncompete_consulting`, and
`ip_assignment` are all judged FAIL, but every judge reason is the same
shape:

> "The answer adds details (consulting or ownership interest) not
> present in the reference text, making it unsupported."

Read the actual agent answers (`race_report.md`) — they're factually
correct, they just correctly pull in an adjacent true clause (e.g.
`ip_assignment`'s answer correctly cites both the "sole and exclusive
property" clause AND the "agrees to assign" clause) that the *gold
reference* for that one question doesn't include, because Week 4 scoped
`expected_chunks` narrowly, per-question, before any of this existed.
The fixed workflow's k=3 search happens not to pull in the extra
(correct) clause as often as the agent's k=5 + retry does, so it trips
this narrow-reference penalty less — that's a quirk of the grading, not
evidence the fixed workflow is more accurate. This is the same pattern
Week 6 first found on `confidentiality_dismissal`, now showing up more
often because the agent's search surfaces more true context per answer.
**Net effect: the real reliability gap between agent and fixed is
probably larger than 15/24 vs 14/24 in the agent's favor**, not smaller.

**`maternity_leave` (a no-answer control) is not a hallucination.** The
agent's answer — "No, the contract does not mention maternity or
paternity leave" — is correct and safe. It fails only because the free
rule check requires the literal substring "not found," and the agent
phrased a correct refusal differently. Worth fixing in the rule check
generally; not a reliability finding about the agent specifically.

**The real, un-excused cost of the agent is latency and $ cost, and a
genuine reliability wrinkle.** ~10.5x slower and ~2.9x more LLM calls per
question on average (and the $ gap is larger than the call-count ratio
suggests — the agent's decision model, `openai/gpt-oss-120b`, costs more
per call than the fixed workflow's `openai/gpt-oss-20b`; see the model
note above). Worse: on `ip_assignment`, the agent found the right chunk
on step 2, then burned steps 3, 4, and 5 on the empty-response quirk
*after* already having what it needed, never called `final_answer`
itself, and only produced an answer because the budget-exhaustion
fallback forced one. That's a real fragility in the hand-rolled loop,
not just a cost line item — a less forgiving stop condition, or a task
where the forced-fallback prompt has less to work with, would turn that
into a silent failure instead of a recovered one.

## Verdict: which would I ship?

**The fixed workflow, as the default path — with the agent as a
targeted fallback, not a replacement.**

For roughly 90% of questions here (everything except the specific
never-retrieved retrieval-gap cases), the fixed workflow gets the same
or a fairer-graded answer in 1 call and ~1.3 seconds. Paying 3x the
calls and 10x the latency on every question to fix 3 out of 24 isn't a
good trade at that scale, especially once the true unforced-error rate
between the two is not the 4-point gap the headline number shows.

But the 3 questions the agent uniquely fixed are not a fluke — they're
exactly the failure mode two prior weeks of fixes (reranking, neighbor
stitching) couldn't reach, because both of those only ever look at one
search result. That's a real, narrow capability gap only a loop can
close. The shippable design is a **hybrid**: run the fixed workflow
first; if its retrieval comes back empty or its answer is a refusal,
*escalate* that one question to the agent for a second, reformulated
attempt, instead of running every question through the agent by
default. That captures the 3-question win without taxing the other 21
with 10x the latency for no benefit — and it also bounds the exposure to
the empty-turn fragility above, since the agent only ever runs on the
minority of questions that already failed once.
