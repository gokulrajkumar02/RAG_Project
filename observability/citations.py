"""
Which clauses does an answer cite? One parser, shared by the eval suite (is the citation right?) and the
log index (what did this answer cite?), so the test and the search never disagree about what was cited.

Recognised: "Clause 7", "clause 7.2" (-> 7), "Clauses 6 and 7", "Section 6", "Sections 6, 7", "cl. 7", "§7".
Not a citation: a heading quoted as text ("7. TERMINATION"), a bare number ("30 days").
"""

import re

CITE = re.compile(
    r"(?:\bclauses?|\bsections?|\bcl\.|§{1,2})\s*"
    r"(\d{1,2}(?:\.\d+)*(?:\s*(?:,|and|&|or|/)\s*\d{1,2}(?:\.\d+)*)*)",
    re.I,
)


def cited_clauses(text, valid=None):
    """Sorted clause numbers (as strings) cited in `text`; `valid` drops numbers that are not clauses."""
    found = set()
    for m in CITE.finditer(text or ""):
        for num in re.findall(r"\d{1,2}(?:\.\d+)*", m.group(1)):
            top = num.split(".")[0]
            if valid is None or top in valid:
                found.add(top)
    return sorted(found, key=int)


def check(answer, required, allowed=None):
    """An answer passes when it cites every `required` clause and nothing outside `allowed`."""
    cited = cited_clauses(answer)
    allowed = list(allowed) if allowed is not None else list(required)
    missing = [c for c in required if c not in cited]
    outside = [c for c in cited if c not in allowed]
    return {"cited": cited, "required": list(required), "allowed": allowed, "missing": missing,
            "outside": outside, "pass": not missing and not outside}
