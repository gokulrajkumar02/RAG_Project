"""
The enforcement primitives. Legal's position is that this is a lookup tool that must be auditable, not an opinion
generator, so the rules that matter are enforced in CODE, on the model's output, and logged when they fire. A
prompt that politely asks is not a control.

  find_characterisations / neutralise   "this is standard", "looks fine", "market", ...  -> the sentence is
                                        removed and the answer is referred to counsel
  is_evaluative                         the QUESTION asks for a judgement; the answer must refer it to counsel
  has_referral                          does the answer already refer to counsel
  defined_terms_in                      which of the contract's non-ordinary defined terms a text depends on,
                                        including the lower-case words that stand in for them ("subsidiaries")

Text inside double quotes is a quotation of the contract and is never scanned: a clause that itself says
"standard of care" is not the assistant characterising anything.
"""

import re

CHAR_PATTERNS = [
    r"\b(?:this|that|the|it|these|those)\b[^.;:\n]{0,50}?\b(?:is|are|looks?|seems?|appears?|sounds?|reads?)\b[^.;:\n]{0,25}?"
    r"\b(?:standard|acceptable|fine|normal|typical|customary|usual|market|reasonable|ok|okay|common|"
    r"favou?rable|unfavou?rable|aggressive|risky|safe|unusual|boilerplate|balanced|one-sided|generous)\b",
    r"\b(?:market|industry)[- ](?:standard|norm|practice)\b",
    r"\bstandard (?:position|clause|term|terms|cap|provision|language|wording|practice|approach)\b",
    r"\bnothing (?:unusual|concerning|to worry|out of the ordinary)\b",
    r"\bno (?:red flags?|concerns?|issues?|problems?)\b",
    r"\blooks (?:fine|good|ok|okay|normal)\b",
    r"\bshould be (?:fine|ok|okay|acceptable)\b",
    r"\b(?:is|are) (?:acceptable|fine|ok|okay|reasonable)\b",
    r"\bwithin (?:normal|standard|usual) (?:limits|range|parameters)\b",
    r"\bcommonly (?:seen|used|agreed)\b",
]
CHAR_RES = [re.compile(p, re.I) for p in CHAR_PATTERNS]
QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
REFERRAL = re.compile(
    r"refer(?:red|ring)?\b[^.]{0,80}\bcounsel|question for counsel|for counsel\b|counsel (?:should|to|must|can) "
    r"(?:review|confirm|decide|advise|assess)|speak to (?:the )?(?:legal|counsel)|not (?:a )?(?:legal )?advice", re.I)
EVALUATIVE = re.compile(
    r"\b(?:standard|acceptable|fine|ok(?:ay)?|market|normal|typical|customary|reasonable|favou?rable|risky|safe|"
    r"unusual|worr(?:y|ied)|concern(?:s|ed)?|red flags?|good|bad|enforceable|legal advice|advis(?:e|able)|"
    r"should we (?:accept|sign|agree|push back|worry)|can we (?:sign|accept|agree)|is it (?:ok|safe|fine))\b", re.I)

REFERRAL_SENTENCE = ("That is a judgement for counsel: I report what the contract says and cite it, and have referred the "
                     "question to counsel instead of characterising it.")
DECLINED = re.compile(r"\b(?:could not|cannot|unable to|did not) (?:confirm|find|read|determine|recover)", re.I)


def is_referral_answer(text):
    """The system declined to answer (extraction could not support it) and referred to counsel."""
    return DECLINED.search(text or "") is not None and has_referral(text)
UNCERTAIN_SENTENCE = ("I could not confirm this from the documents as extracted (see the reasons above), so I am not "
                      "stating it as the clause in force; this is referred to counsel for review of the source documents.")

SYNONYMS = {   # lower-case words that mean the question depends on a defined term even if the term is never typed
    "Affiliate": ["subsidiar", "sister compan", "group compan", "parent compan", "related compan", "affiliated"],
    "Excluded Claims": ["uncapped", "carve-out", "carve out", "outside the cap", "exempt from the cap"],
}


def _strip_quotes(text):
    return QUOTED.sub(" ", text or "")


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def find_characterisations(text):
    """Sentences of the assistant's own prose that characterise a position as standard/acceptable/market/..."""
    hits = []
    for s in sentences(text):
        bare = _strip_quotes(s)
        for rx in CHAR_RES:
            m = rx.search(bare)
            if m:
                hits.append(dict(sentence=s.strip(), matched=m.group(0)))
                break
    return hits


def neutralise(text):
    """Remove every characterising sentence. -> (new_text, hits)."""
    hits = find_characterisations(text)
    if not hits:
        return text, []
    bad = {h["sentence"] for h in hits}
    kept = [s for s in sentences(text) if s.strip() not in bad]
    return " ".join(kept).strip(), hits


def has_referral(text):
    return REFERRAL.search(text or "") is not None


def is_evaluative(question):
    return EVALUATIVE.search(question or "") is not None


def defined_terms_in(text, terms):
    """Which of `terms` this text depends on: the term itself (any case, plural ok) or a stand-in word."""
    found = []
    low = (text or "").lower()
    for t in terms:
        stem = re.escape(t.lower())
        if re.search(rf"\b{stem}(?:s|es)?\b", low) or any(w in low for w in SYNONYMS.get(t, [])):
            found.append(t)
    return found
