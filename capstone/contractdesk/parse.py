"""
Extracted text -> structure: clauses, amendment edits, defined terms, playbook items, governing-law rows.

This module reads ONLY extracted text (pypdf or OCR output) and the manifest. It never sees truth.json and never
sees the generator. So an OCR error that mangles a clause number, drops the quotes around an amendment's
replacement words, or turns a dollar figure into `3000,00o*` shows up here as a real parse miss, not a staged one.

Whitespace is matched loosely everywhere (`\\s*` between words) because OCR drops spaces far more often than it
drops letters ("deletedandreplacedwith").
"""

import datetime as dt
import re
import unicodedata

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
QUOTE_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", " ": " "})

HEADING = re.compile(r"^(\d{1,2})\s*\.\s*([A-Z][A-Z ,&/\-]{3,})$")
SUBCLAUSE = re.compile(r"^(\d{1,2}\s*\.\s*\d{1,2})\s*([A-Z].*)$")
NUMBERED = re.compile(r"^(\d{1,2})\s*\.\s*([A-Z].*)$")
SIGNED = re.compile(r"^\s*S[il1]g[nm]ed\s*for", re.I)
TITLE_BODY = re.compile(r"^(.{2,80}?)\.\s*(?=[A-Z(\"])(.*)$", re.S)

# Q = a quotation mark, or what OCR makes of one: first run on the scanned amendments parsed 0 of 10 because OCR drops
# the quotes that delimit the replacement words (or turns them into '*'). Q is therefore optional.
Q = r'["*“”‘’\']?'
R_REPLACE_CLAUSE = re.compile(
    rf'Clause\s*(\d+(?:\.\d+)*)\s*of\s*the\s*MSA\s*is\s*deleted\s*and\s*replaced\s*with\s*:?\s*{Q}(.+?){Q}\s*\.?\s*$', re.I | re.S)
R_REPLACE_WORDS = re.compile(
    rf'In\s*Clause\s*(\d+(?:\.\d+)*)\s*of\s*the\s*MSA\s*,?\s*the\s*words\s*{Q}(.+?){Q}\s*are\s*deleted\s*and\s*replaced\s*with\s*{Q}(.+?){Q}\s*\.?\s*$',
    re.I | re.S)
R_REDEFINE = re.compile(
    rf'The\s*definition\s*of\s*(.+?)\s*in\s*Schedule\s*1\s*is\s*deleted\s*and\s*replaced\s*with\s*:?\s*{Q}(.+?){Q}\s*\.?\s*$', re.I | re.S)
R_CONTINUING = re.compile(r"ontinuing\s*effect|continues\s*in\s*full", re.I)
R_EFFECT = re.compile(r"takes\s*effect\s*on\s*(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})", re.I)
R_LAW_ROW = re.compile(
    r"([a-z0-9][a-z0-9\-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*reviewed\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


def norm(text):
    return re.sub(r"\s+", " ", (text or "").translate(QUOTE_MAP).replace("''", '"')).strip()


def normalise_no(no):
    return re.sub(r"\s+", "", no)


def parse_long_date(day, month, year):
    m = difflib_month(month)
    if m is None:
        return None
    try:
        return dt.date(int(year), m, int(day)).isoformat()
    except ValueError:
        return None


def difflib_month(word):
    import difflib
    hit = difflib.get_close_matches(word.lower(), MONTHS, n=1, cutoff=0.78)
    return MONTHS.index(hit[0]) + 1 if hit else None


def split_title_body(rest):
    m = TITLE_BODY.match(rest)
    if m and len(m.group(1).split()) <= 12:
        return m.group(1).strip(), m.group(2).strip()
    return "", rest.strip()


def parse_clauses(pages, doc_type):
    """pages: [{n, text}] -> [{no, title, text, page}]. Clause 0 is the preamble, 'sig' the signature block."""
    clauses, cur = [], None
    lines = []
    for p in pages:
        for ln in p["text"].split("\n"):
            ln = unicodedata.normalize("NFKC", ln).translate(QUOTE_MAP).strip()   # OCR emits fullwidth brackets etc.
            if ln:
                lines.append((p["n"], ln))

    def flush():
        nonlocal cur
        if cur is not None:
            body = norm(" ".join(cur["lines"]))
            title, text = (cur["title"], body) if cur["title"] or cur["no"] in ("0", "sig") else split_title_body(body)
            clauses.append(dict(no=cur["no"], title=title, text=text, page=cur["page"]))
        cur = None

    cur = dict(no="0", title="Preamble", lines=[], page=1)
    for page, ln in lines:
        if SIGNED.match(ln):
            if cur is None or cur["no"] != "sig":
                flush()
                cur = dict(no="sig", title="Signatures", lines=[], page=page)
            cur["lines"].append(ln)
            continue
        if cur is not None and cur["no"] == "sig":
            cur["lines"].append(ln)
            continue
        m_head = HEADING.match(ln)
        m_sub = SUBCLAUSE.match(ln) if doc_type == "MSA" else None
        m_num = NUMBERED.match(ln) if doc_type != "MSA" else None
        if m_head and doc_type == "MSA":
            flush()
            cur = dict(no=normalise_no(m_head.group(1)), title=m_head.group(2).strip(), lines=[], page=page,
                       heading=True)
        elif m_sub:
            flush()
            cur = dict(no=normalise_no(m_sub.group(1)), title="", lines=[m_sub.group(2)], page=page)
        elif m_num:
            flush()
            cur = dict(no=normalise_no(m_num.group(1)), title="", lines=[m_num.group(2)], page=page)
        else:
            cur["lines"].append(ln)
    flush()
    out = []
    for c in clauses:
        if c["no"] == "0" and not c["text"]:
            continue
        out.append(c)
    return out


def parse_effective_date(preamble_text):
    m = R_EFFECT.search(preamble_text or "")
    return parse_long_date(*m.groups()) if m else None


def parse_edits(clauses):
    """Amendment paragraphs -> edits. A paragraph that is neither an edit nor 'Continuing Effect' is reported as
    unparsed: that is the signal the chain resolver uses to say 'I could not fully read this amendment'."""
    edits, unparsed = [], []
    for c in clauses:
        if c["no"] in ("0", "sig"):
            continue
        body = c["text"]
        if R_CONTINUING.search(c["title"] + " " + body) and not re.search(r"Clause\s*\d", body):
            continue
        m = R_REPLACE_CLAUSE.search(body)
        if m:
            edits.append(dict(para=c["no"], target=f"cl:{m.group(1)}", action="replace_clause", new=norm(m.group(2))))
            continue
        m = R_REPLACE_WORDS.search(body)
        if m:
            edits.append(dict(para=c["no"], target=f"cl:{m.group(1)}", action="replace_words", old=norm(m.group(2)),
                              new=norm(m.group(3))))
            continue
        m = R_REDEFINE.search(body)
        if m:
            edits.append(dict(para=c["no"], target=f"def:{normalise_term(m.group(1))}", action="redefine",
                              new=norm(m.group(2))))
            continue
        unparsed.append(dict(para=c["no"], title=c["title"], text=body[:240]))
    return edits, unparsed


def normalise_term(term):
    return re.sub(r"\s+", " ", term.strip().strip('"').strip())


def parse_law_table(pages):
    text = norm(" ".join(p["text"] for p in pages))
    rows = {}
    for m in R_LAW_ROW.finditer(text):
        slug, name, law, venue, d, mo, y = m.groups()
        rows[slug] = dict(name=name.strip(), law=law.strip(), venue=venue.strip(), reviewed=parse_long_date(d, mo, y))
    return rows


# ----------------------------------------------------------------------------------------------------------
# numeric consistency: legal drafting writes a figure twice, "twenty-four (24)" or "three million United States
# dollars (USD 3,000,000)". If the two disagree after extraction, one of them was misread.
# ----------------------------------------------------------------------------------------------------------
_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


_VOCAB = sorted(list(_UNITS) + list(_TENS) + ["hundred", "thousand", "million", "and"], key=len, reverse=True)


def _segment(token):
    """Split an OCR-glued token ('onemillionfivehundred') into number words, or None if it is not made of them."""
    if token in _VOCAB:
        return [token]
    best = [None] * (len(token) + 1)          # exact segmentation first: 'twomillion' is two + million, not a typo of 'million'
    best[0] = []
    for i in range(len(token)):
        if best[i] is None:
            continue
        for w in _VOCAB:
            if token.startswith(w, i) and best[i + len(w)] is None:
                best[i + len(w)] = best[i] + [w]
    if best[len(token)] is not None:
        return best[len(token)]
    if len(token) >= 5:        # then one clipped/garbled letter ('wenty') is still that number word; the digits are cross-checked anyway
        import difflib
        close = difflib.get_close_matches(token, [w for w in _VOCAB if w != "and"], n=1, cutoff=0.8)
        if close:
            return close
    return None


def words_to_int(text):
    """'two million five hundred thousand' -> 2500000 (also when OCR glued the words together); None if any token is
    not made of number words."""
    total, current = 0, 0
    toks = []
    for t in re.split(r"[\s\-]+", text.lower().strip()):
        if not t:
            continue
        seg = _segment(t)
        if seg is None:
            return None
        toks += [w for w in seg if w != "and"]
    if not toks:
        return None
    for t in toks:
        if t in _UNITS:
            current += _UNITS[t]
        elif t in _TENS:
            current += _TENS[t]
        elif t == "hundred":
            current = max(1, current) * 100
        elif t == "thousand":
            total += max(1, current) * 1000
            current = 0
        elif t == "million":
            total += max(1, current) * 1_000_000
            current = 0
    return total + current


# the parenthesis is captured loosely on purpose: a misread figure ("3000,00o*") must register as a mismatch,
# not silently fail to match and so go unchecked.
R_WORDS_DIGITS = re.compile(r"((?:[A-Za-z]+[\s\-]+){0,7}[A-Za-z]+)\s*\(\s*(?i:usd\s*)?([^()]{0,24})")


def numeric_consistency(text):
    """-> [{words, digits, parsed_words, parsed_digits}] for every 'words (digits)' pair that disagrees or whose
    digits are unreadable. Pairs whose words are not a number (e.g. 'greater of (i)') are not pairs and are skipped."""
    bad = []
    for m in R_WORDS_DIGITS.finditer(text):
        w = re.sub(r"(?i)\bunited\s*states\s*dollars?\b", "", m.group(1)).strip()
        toks = [t for t in re.split(r"[\s\-]+", w) if t]
        k = len(toks)
        while k > 0 and words_to_int(" ".join(toks[k - 1:])) is not None:
            k -= 1
        run = " ".join(toks[k:])
        pw = words_to_int(run) if run else None
        if pw is None:
            continue
        digits = m.group(2).split(")")[0].strip().rstrip(".")
        if re.fullmatch(r"[\d,]+(?:\.\d+)?", digits):
            pd = int(float(digits.replace(",", "")))
            if pw != pd:
                bad.append(dict(words=run, digits=digits, parsed_words=pw, parsed_digits=pd))
        else:
            bad.append(dict(words=run, digits=digits, parsed_words=pw, parsed_digits=None))
    return bad
