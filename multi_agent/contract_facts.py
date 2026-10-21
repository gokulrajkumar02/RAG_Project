"""
Facts the squad derives from the contract itself - the governing effective date and the
defined-terms table - read from create_sample_pdf.SECTIONS, the same single source of truth
agent/tools.list_section_headings already uses for the indexed PDF. Nothing here is typed in by
hand, so it cannot drift from the contract the retrieval index was built from.

Two consumers:
  - the manager puts `effective_date` (+ "no amendments on file") in EVERY brief it hands a worker.
    The brief's "common mistakes" list a worker answering off a superseded clause because the
    governing date was dropped from its context; passing it costs a few tokens per hand-off.
  - the defined-terms worker's one tool reads `defined_terms`. Definitions here are whole, not
    150-character chunks - that is the capability the second specialist adds over plain search.
"""

import os
import re
import sys
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# "TechCorp Pvt. Ltd. ("Company")"  ->  referent, term
_PAREN_DEF = re.compile(r'((?:[A-Z][\w.]*\s)*[A-Z][\w.]*)\s\("([^"]+)"\)')
# "Confidential Information includes but is not limited to: a, b, and c."  ->  term, list
_LIST_DEF = re.compile(r"([A-Z][A-Za-z ]+?)\s+includes but is not limited to:\s*(.+?)\.(?:\s|$)")
_EFFECTIVE = re.compile(r"entered into as of ([A-Z][a-z]+ \d{1,2}, \d{4})")


@dataclass
class Facts:
    agreement: str            # "Employment Agreement"
    effective_date: str       # "January 1, 2024"
    amendments: list          # none on file for this single executed agreement
    defined_terms: dict       # term -> {"definition": str, "items": [str]}

    def governing_line(self):
        amend = "no amendments on file" if not self.amendments else f"{len(self.amendments)} amendment(s) on file"
        return f"{self.agreement}, effective {self.effective_date} ({amend}; this is the governing text)"


def _split_items(listing):
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", listing)
    return [p.strip() for p in parts if p.strip()]


def load_facts(sections=None):
    if sections is None:
        from create_sample_pdf import SECTIONS
        sections = SECTIONS

    preamble = " ".join(sections[0][1].split())
    m = _EFFECTIVE.search(preamble)
    if not m:
        raise ValueError("no 'entered into as of <date>' in the preamble")
    effective_date = m.group(1)

    terms = {}
    for referent, term in _PAREN_DEF.findall(preamble):
        if term == "Agreement":
            referent = referent.removeprefix("This ")
            terms[term] = {"definition": f"this {referent}, entered into as of {effective_date}", "items": [effective_date]}
            agreement = referent
        else:
            terms[term] = {"definition": referent, "items": [referent]}

    for _heading, body in sections[1:]:
        flat = " ".join(body.split())
        for term, listing in _LIST_DEF.findall(flat):
            items = _split_items(listing)
            terms[term.strip()] = {
                "definition": f"includes but is not limited to: {', '.join(items)}",
                "items": items,
            }

    return Facts(agreement=agreement, effective_date=effective_date, amendments=[], defined_terms=terms)
