"""
Citations are rendered by the SYSTEM from the registry, never typed by the model.

The model says which (document, clause) it relied on. This module looks that pair up and produces the citation
the brief demands: clause number, document (MSA / SOW / Amendment), effective date - and, because the brief also
asks for it, the governing law - as a clickable link to the page of the PDF. A model cannot fabricate an
effective date, because it never writes one; it can only cite a pair, and agent.py refuses a pair that no tool
returned during this request (`fabricated_citation`).
"""

import pathlib
import re

from . import paths

REQUIRED_FIELDS = ("doc_label", "clause", "effective_date", "governing_law")


def target_label(target):
    kind, _, ref = target.partition(":")
    return f"MSA cl. {ref}" if kind == "cl" else f"the definition of {ref}"


def file_uri(doc_id, page=None):
    uri = pathlib.Path(paths.pdf_path(doc_id)).resolve().as_uri()
    return uri + (f"#page={page}" if page else "")


def cite(reg, slug, doc_id, clause, status=None):
    """-> citation dict, or None when (doc_id, clause) does not exist in the registry."""
    if doc_id not in reg.d["documents"]:
        return None
    c = reg.clause(doc_id, clause)
    if c is None:
        return None
    rec = reg.doc(doc_id)
    amends = ""
    if rec["type"] == "AMENDMENT":
        e = next((e for e in reg.d["edits"].get(doc_id, []) if e["para"] == str(c["no"])), None)
        if e:
            amends = ("replaces " if e["action"] in ("replace_clause", "redefine") else "amends ") + target_label(e["target"])
    law = reg.d["counterparties"][slug].get("governing_law") if slug in reg.d["counterparties"] else None
    name = reg.d["counterparties"][slug]["name"] if slug in reg.d["counterparties"] else ""
    label = reg.label(doc_id)
    uri = file_uri(doc_id, c.get("page"))
    bits = [b for b in (name, label, f"cl. {c['no']}" + (f" ({amends})" if amends else ""),
                        f"eff. {rec['effective_date']}", f"law: {law}" if law else "law: n/a") if b]
    plain = " | ".join(bits)
    return dict(doc_id=doc_id, doc_label=label, clause=str(c["no"]), title=c["title"], effective_date=rec["effective_date"],
                governing_law=law, page=c.get("page"), uri=uri, amends=amends, status=status, plain=plain,
                markdown=f"[{plain}]({uri})")


def complete(c):
    """Does this citation name the clause number, the document and its effective date (and carry the governing law)?"""
    return all(c.get(f) for f in REQUIRED_FIELDS) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", c.get("effective_date", "")))
