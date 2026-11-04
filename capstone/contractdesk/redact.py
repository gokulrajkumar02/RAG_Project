"""
Ingest-time PII redaction. These are executed commercial contracts: notice clauses carry named individuals, their
e-mail addresses, phone numbers and street addresses, and every signature block names a signatory.

Where the line is drawn (see ARCHITECTURE.md, "What leaves the process"):
  * the raw extracted text stays in corpus/extracted/ on this machine and is read only by ingestion;
  * everything downstream - the FAISS index, registry.json, both MCP servers, every prompt sent to a model, every
    log line - holds REDACTED text only;
  * company names, dates, fees, clause numbers and the cap itself are NOT redacted: they are the answer.

The patterns work on structure (an "attention of" phrase, an e-mail shape, a "Signed ... by" phrase), not on a
list of known names, so they do not depend on anything the generator knows. They are tolerant of the spacing
damage OCR does. How well they hold is measured: eval/pii_check.py searches every prompt and log for the strings
that truth.json says are personal data.
"""

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+\s*@\s*[A-Za-z0-9\-]+(?:\s*\.\s*[A-Za-z0-9\-]+)*\s*\.\s*[A-Za-z]{2,}")
PHONE = re.compile(r"\+\s*\d[\d\s\-]{7,}\d")
ATTENTION = re.compile(r"(attention\s*of\s+)([^()]{2,90}?)(\s*\()", re.I)
SENT_TO = re.compile(r"(sent\s*to\s+)(.{5,140}?)(,\s*marked\s*for)", re.I)
SIGNED_BY = re.compile(r"(S[il1]g[nm]ed\s*for[^.]{0,60}?\s*by\s+)([^.]{2,90})(\.|$)", re.I)


NOTICE_TITLE = re.compile(r"^\s*notices?", re.I)


def redact_clause(c):
    """Structural first, patterns second. A notices clause is nothing but addresses and named contacts, and a signature
    block is nothing but names, so those are masked WHOLE; the phrase patterns below catch what is left. (The patterns
    alone, written for clean text, let 38 of 240 known personal-data strings through on scanned documents.)"""
    counts = {"email": 0, "phone": 0, "contact": 0, "address": 0, "signatory": 0}
    if c["no"] == "sig":
        c["text"] = "[SIGNATURE BLOCK REDACTED]"
        counts["signatory"] = 1
        return counts
    if NOTICE_TITLE.match(c["title"]):
        c["text"] = "[NOTICE ADDRESS AND CONTACT DETAILS REDACTED]"
        counts["address"] = 1
        return counts
    for field in ("title", "text"):
        c[field], rc = redact(c[field])
        for k, v in rc.items():
            counts[k] += v
    return counts


def redact(text):
    """-> (redacted text, {kind: count})."""
    counts = {"email": 0, "phone": 0, "contact": 0, "address": 0, "signatory": 0}

    def sub(rx, repl, kind, s):
        s, n = rx.subn(repl, s)
        counts[kind] += n
        return s

    text = sub(EMAIL, "[EMAIL]", "email", text)
    text = sub(PHONE, "[PHONE]", "phone", text)
    text = sub(ATTENTION, r"\1[CONTACT]\3", "contact", text)
    text = sub(SENT_TO, r"\1[ADDRESS]\3", "address", text)
    text = sub(SIGNED_BY, r"\1[SIGNATORY]\3", "signatory", text)
    return text, counts


def find_leaks(text, pii_strings):
    """Which known personal-data strings (from truth.json) survive in `text`. Whitespace-insensitive."""
    flat = re.sub(r"\s+", "", text).lower()
    return [p for p in pii_strings if re.sub(r"\s+", "", p).lower() in flat]
