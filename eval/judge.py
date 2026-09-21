"""
LLM-as-judge for the Track F (Legal Contracts) clause-answer eval.

Why a judge at all, when eval/questions.py already has answer_keywords?
Keyword presence is a free rule check and catches most failures (see
run_evals.py), but Week 5's error analysis found at least one failure mode
a keyword rule structurally can't catch: an answer that happens to contain
(or, as with `leave_approval`, happens to avoid contradicting) the right
words while being un-grounded — reached by inference over the wrong
context rather than read off the clause that actually answers the
question (error_analysis/error_taxonomy.md, Group 4, "got lucky"). The
judge's job is narrower than "grade everything" — it's specifically "is
this answer actually supported by the reference contract text, not just
superficially on-topic."

Binary PASS/FAIL, not a 1-10 score: for a factual clause-lookup task
there's no meaningful middle ground between "grounded and correct" and
"not" — a 1-10 scale would just push the same yes/no judgment call onto a
noisier number.

Do not trust this judge's numbers without running eval/validate_judge.py
first (checks it against the human PASS/FAIL labels already recorded in
error_analysis/open_coding_notes.md).
"""

import json

JUDGE_MODEL = "openai/gpt-oss-120b"  # deliberately bigger than the 20b model that generates answers

JUDGE_PROMPT = """You are grading one answer from a legal-contract Q&A assistant. Be strict: an answer only passes if the reference text actually supports it.

Question: {question}

Reference contract text (the ground truth the answer must be grounded in):
{reference_context}

Assistant's answer:
{answer}

Grade the assistant's answer PASS or FAIL:
- PASS: the answer is factually correct AND is actually supported by the reference text above — not just superficially on-topic, not a lucky guess or an inference from unrelated context.
- FAIL: the answer is wrong, is unsupported/ungrounded even if it sounds plausible, states a fact from the wrong clause, or refuses/hedges ("not found in the contract") when the reference text clearly contains the fact.
- If the reference text is explicitly empty/absent, PASS only if the assistant correctly refused instead of inventing an answer.

Respond with ONLY a JSON object, no other text, no markdown fencing:
{{"verdict": "PASS", "reason": "one short sentence"}}"""


def judge_answer(question, reference_context, answer, api_key, model_name=JUDGE_MODEL):
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    prompt = ChatPromptTemplate.from_template(JUDGE_PROMPT)
    llm = ChatGroq(groq_api_key=api_key, model_name=model_name, temperature=0)
    chain = prompt | llm | StrOutputParser()

    raw = chain.invoke({
        "question": question,
        "reference_context": reference_context or "(none — this fact is not present anywhere in the contract)",
        "answer": answer,
    }).strip()

    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        verdict_raw = str(parsed.get("verdict", "")).strip().upper()
        reason = str(parsed.get("reason", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        verdict_raw = ""
        reason = f"judge returned non-JSON output: {raw[:200]!r}"

    # Exact match first; fall back to substring containment so a stray
    # trailing period/quote or a non-string JSON value (observed: some
    # models emit {"verdict": true}) doesn't silently fail the answer
    # closed just because it isn't byte-identical to "PASS"/"FAIL".
    if verdict_raw in ("PASS", "FAIL"):
        verdict = verdict_raw
    elif "FAIL" in verdict_raw:
        verdict = "FAIL"
    elif "PASS" in verdict_raw:
        verdict = "PASS"
    else:
        verdict = "FAIL"  # fail closed: a genuinely unparsable verdict should not count as a pass
        reason = reason or f"judge returned unrecognized verdict: {raw[:200]!r}"

    return {"verdict": verdict, "reason": reason}
