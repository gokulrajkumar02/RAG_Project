"""
Offline STAND-IN for openai/gpt-oss-20b, used only when there is no GROQ_API_KEY. It is NOT a language
model: every trace it produces says llm_mode="stub" and every suite output made with it is stamped STUB.

What it does, so its RED/GREEN can be read for what it is:
  * splits the context it was shown into its passages (blocks between "---"), scores each against the
    question with the app's own cross-encoder, and answers with the best passage's text (headings, labels
    and page furniture stripped). Whatever the passages are - 150-character chunks, or whole clauses - it
    answers from the one most relevant to the question, as a reader of that context would;
  * it never refuses: on this contract the reranker gives even correct passages negative logits (-2.8,
    -5.3), so any refusal threshold would be a number tuned on the eval set. The two no-answer controls
    therefore fail under the stub, before and after any fix;
  * when the prompt asks for a citation, cites the clause heading NEAREST to that text in the context it was
    shown - the way a reader with no clause labels would. On plain context that is often the NEXT clause's
    heading, because 150-character chunks end with it (clauses.py). On clause-labelled context it cites the
    label of the passage the text sits in.

(Revised once, before any suite run was recorded: it first answered with the top-1 retrieved chunk, which
for the drill's question is the preamble - a reader of the whole context would not do that.)

That nearest-heading rule is a hypothesis about how the real model goes wrong, not a measurement of it.
Only `python eval/run_suite.py --llm groq` says whether gpt-oss-20b actually does this.
"""

import re

from clauses import line_kind, parse_heading

NOT_FOUND = "This information was not found in the contract."
SEP = "\n\n---\n\n"
LABEL = re.compile(r"^\[(?:Clause (\d{1,2}) - [^\]]+|(Preamble|Signatures))\]$", re.M)


def _body_lines(text):
    return [ln for ln in text.split("\n") if line_kind(ln) == "body" and not LABEL.match(ln.strip())]


def _cite_plain(context, first, end):
    best = None
    for m in re.finditer(r"^.*$", context, re.M):
        head = parse_heading(m.group(0))
        if not head:
            continue
        if m.end() <= first:
            dist = first - m.end()
        elif m.start() >= end:
            dist = m.start() - end
        else:
            dist = 0
        if best is None or dist < best[0]:
            best = (dist, head[0])
    return best[1] if best else None


def _cite_labelled(context, first):
    labels = [m for m in LABEL.finditer(context) if m.start() < first]
    if not labels:
        return None
    m = labels[-1]
    return m.group(1) or m.group(2).lower()


def answer(prompt, hints):
    context = prompt.split("Contract Context:\n", 1)[-1].rsplit("\n\nQuestion:", 1)[0]
    passages, offset = [], 0
    for block in context.split(SEP):
        if _body_lines(block):
            passages.append((offset, block))
        offset += len(block) + len(SEP)
    if not passages:
        return NOT_FOUND
    scores = hints["relevance"]([block for _o, block in passages])
    offset, best = passages[max(range(len(passages)), key=lambda i: scores[i])]
    lines = _body_lines(best)
    body = " ".join(ln.strip().lstrip("-").strip() for ln in lines)
    if not hints["cites"]:
        return body

    first = offset + best.find(lines[0])
    end = offset + best.rfind(lines[-1]) + len(lines[-1])
    if hints["context_format"] == "plain":
        clause = _cite_plain(context, first, end)
    else:
        clause = _cite_labelled(context, first)
    return f"{body} (Clause {clause})" if clause and clause.isdigit() else body


class StubBackend:
    mode = "stub"

    def invoke(self, prompt, hints):
        return answer(prompt, hints), None, 0.0


def stub_judge(question, reference_context, answer_text):
    """The STUB judge defers to the rule + citation checks (scores PASS); those still run."""
    return {"verdict": "PASS", "reason": "STUB judge: no model available, rule and citation checks decide"}
