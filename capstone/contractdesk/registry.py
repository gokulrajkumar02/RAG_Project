"""
The parsed knowledge base and the two resolvers the brief is really about.

    Registry.chain(slug, "cl:11.3")        which document's version of clause 11.3 is IN FORCE today, what it
                                           superseded, what is not yet in force, what conflicts and loses
    Registry.resolve_term(slug, "Affiliate")  the defined term's definition (not its ordinary meaning), with any
                                           amendment that redefined it

Both work from registry.json, i.e. from EXTRACTED text (pypdf or OCR), never from truth.json. When the extracted
text cannot support a firm answer (an amendment paragraph that could not be read, replacement words that cannot
be found in the clause they are meant to replace, a figure whose words and digits disagree), the result says
`resolution: "uncertain"` and lists why. Callers must then refer to counsel instead of quoting: fail closed.

Precedence is MSA clause 1.4: (a) any Amendment, the most recent in effect prevailing; (b) the body of the MSA;
(c) any SOW - and an SOW only displaces the body for a clause it names by number and says it "expressly
overrides". An Amendment outranks an SOW even when the SOW says "expressly overrides".
"""

import datetime as dt
import difflib
import json
import os
import re

from . import paths
from .parse import normalise_term, numeric_consistency, split_title_body

NAME_SUFFIX = re.compile(r"\s+(Pvt\.\s+Ltd\.|Pte\.\s+Ltd\.|Ltd|Plc|Inc\.|GmbH|DAC)$")
R_OVERRIDE = re.compile(r"expressly\s*overrides\s*clause\s*(\d+(?:\.\d+)*)\s*of\s*the\s*MSA", re.I)
CONFLICT = {   # SOW wording that touches the same subject as an MSA clause (so a conflict can be reported)
    "11.3": re.compile(r"liabilit.{0,80}(shall\s*not\s*exceed|cap)", re.I | re.S),
    "5.2": re.compile(r"invoice.{0,80}within", re.I | re.S),
    "14.2": re.compile(r"terminat.{0,80}notice", re.I | re.S),
}
TOPICS = [   # free-text subject -> chain target. First match wins.
    (r"excluded\s*claims?", "def:Excluded Claims"), (r"affiliate", "def:Affiliate"),
    (r"liabilit|\bcap\b|cap on|limitation", "cl:11.3"), (r"indemn", "cl:12"),
    (r"terminat|notice period|notice to (end|leave|terminate)|convenience", "cl:14.2"),
    (r"payment|invoice|pay\b", "cl:5.2"), (r"governing law|\blaw\b", "cl:18.1"),
    (r"venue|jurisdiction|court", "cl:18.2"), (r"renew", "cl:13.2"), (r"\bterm\b", "cl:13.1"),
    (r"confidential", "cl:9"), (r"precedence|conflict", "cl:1.4"), (r"authori[sz]ed user", "cl:3.2"),
]


def today():
    return dt.date.fromisoformat(os.environ.get("CONTRACT_DESK_TODAY") or dt.date.today().isoformat())


def short_name(name):
    return NAME_SUFFIX.sub("", name).strip()


def whitespace_tolerant(text):
    return r"\s*".join(re.escape(c) for c in text if not c.isspace())


def apply_edit(text, edit):
    """-> (new_text, ok, why, new_title_or_None)."""
    if edit["action"] == "replace_clause":
        m = re.match(r"^\s*\d+(?:\.\d+)*\s*(.{2,70}?)\.\s*(?=[A-Z(])(.*)$", edit["new"], re.S)
        if m and len(m.group(1).split()) <= 12:
            return m.group(2).strip(), True, "", m.group(1).strip()
        return edit["new"], True, "", None
    if edit["action"] == "replace_words":
        m = re.search(whitespace_tolerant(edit["old"]), text, re.I)
        if not m:
            return text, False, "the words the amendment replaces were not found in the clause text it amends", None
        return (text[:m.start()] + edit["new"] + text[m.end():]).strip(), True, "", None
    if edit["action"] == "redefine":
        return edit["new"], True, "", None
    return text, False, f"unknown edit action {edit['action']!r}", None


class Registry:
    def __init__(self, data, as_of=None):
        self.d = data
        self.as_of = as_of or today()
        self._chains, self._status = {}, {}
        self._names = {s: c["name"] for s, c in data["counterparties"].items()}

    @classmethod
    def load(cls, path=None, as_of=None):
        with open(path or paths.REGISTRY, encoding="utf-8") as f:
            return cls(json.load(f), as_of)

    # -- counterparties -------------------------------------------------------------------------------------
    def resolve_counterparty(self, text):
        """-> {status: ok|ambiguous|not_found, slug?, name?, candidates?, match}. Never guesses between look-alikes."""
        q = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not q:
            return dict(status="not_found", candidates=[], match="empty")
        full = {s: n.lower() for s, n in self._names.items()}
        short = {s: short_name(n).lower() for s, n in self._names.items()}
        exact = [s for s in self._names if q in (s, full[s], short[s], short[s].replace(" ", "-"))]
        if len(exact) == 1:
            return self._ok(exact[0], "exact")
        # Only three ways to match, none of them a guess: the exact name/slug above; the first word alone when it is
        # unique ("Brightwater"); or exactly one full customer name inside a longer string. Two customers named, or a
        # first word that two customers share ("Halcyon"), is `ambiguous`. A typo or a partial name is `not_found`
        # with near matches: a legal tool asks, it does not correct. (Fresh-eyes review found "Halcyon Freigth" and
        # "Halcyon Freight, Brightwater Analytics" silently resolving.)
        first = [s for s in self._names if short[s].split()[0] == q]
        if len(first) == 1:
            return self._ok(first[0], "first-word")
        if len(first) > 1:
            return dict(status="ambiguous", candidates=[self._cand(s) for s in sorted(first)], match="first-word")
        in_text = [s for s in self._names if re.search(r"\b" + re.escape(short[s]) + r"\b", q)]
        if len(in_text) == 1:
            return self._ok(in_text[0], "contained")
        if len(in_text) > 1:
            return dict(status="ambiguous", candidates=[self._cand(s) for s in sorted(in_text)], match="several named")
        near = difflib.get_close_matches(q, list(short.values()), n=3, cutoff=0.6)
        return dict(status="not_found", candidates=[self._cand(s) for s in self._names if short[s] in near], match="none")

    def _cand(self, slug):
        return dict(slug=slug, name=self._names[slug])

    def _ok(self, slug, how):
        return dict(status="ok", slug=slug, name=self._names[slug], match=how)

    def docs(self, slug):
        out = [self.d["documents"][i] for i in self.d["counterparties"][slug]["docs"]]
        return sorted(out, key=lambda x: (x["effective_date"], x["number"] or 0))

    def doc(self, doc_id):
        return self.d["documents"][doc_id]

    def label(self, doc_id):
        rec = self.d["documents"][doc_id]
        return {"MSA": "MSA", "SOW": f"SOW No.{rec['number']}", "AMENDMENT": f"Amendment No.{rec['number']}",
                "SCHEDULE": "Schedule 1 (Definitions)", "PLAYBOOK": "Fallback Playbook",
                "LAW_TABLE": "Governing Law Table"}[rec["type"]]

    def clauses(self, doc_id):
        return self.d["clauses"].get(doc_id, [])

    def clause(self, doc_id, no):
        no = re.sub(r"\s+", "", str(no))
        return next((c for c in self.clauses(doc_id) if c["no"] == no), None)

    def msa_id(self, slug):
        return next(i for i in self.d["counterparties"][slug]["docs"] if self.d["documents"][i]["type"] == "MSA")

    def of_type(self, slug, typ):
        return [d for d in self.docs(slug) if d["type"] == typ]

    def governing_law(self, slug):
        c = self.d["counterparties"][slug]
        return dict(governing_law=c.get("governing_law"), venue=c.get("venue"), reviewed=c.get("law_reviewed"),
                    source="shared/governing-law-table")

    # -- subject -> target ---------------------------------------------------------------------------------
    def resolve_target(self, text):
        t = (text or "").strip()
        if t.lower().startswith("def:"):
            canon = self.canon_term(t[4:])
            return f"def:{canon}" if canon else None
        if t.lower().startswith("cl:"):
            return "cl:" + re.sub(r"\s+", "", t[3:])
        if re.fullmatch(r"\d{1,2}(\.\d{1,2})?", t):
            return "cl:" + t
        m = re.search(r"(?:clause|cl\.?|section|s\.)\s*(\d{1,2}(?:\s*\.\s*\d{1,2})?)", t, re.I)
        if m:
            return "cl:" + re.sub(r"\s+", "", m.group(1))
        low = t.lower()
        for pat, target in TOPICS:
            if re.search(pat, low):
                return target
        return None

    # -- the chain -----------------------------------------------------------------------------------------
    def _item(self, doc_id, clause_no, status, text, title, page, note=""):
        rec = self.d["documents"][doc_id]
        return dict(doc_id=doc_id, doc_label=self.label(doc_id), clause=str(clause_no), title=title or "",
                    effective_date=rec["effective_date"], status=status, note=note, text=text, page=page)

    def chain(self, slug, target, as_of=None):
        as_of = as_of or self.as_of
        key = (slug, target, as_of.isoformat())
        if key in self._chains:
            return self._chains[key]
        out = self._chain(slug, target, as_of)
        self._chains[key] = out
        return out

    def _chain(self, slug, target, as_of):
        kind, _, ref = target.partition(":")
        name = self._names[slug]
        base_out = dict(counterparty=slug, name=name, target=target, as_of=as_of.isoformat(),
                        governing_law=self.d["counterparties"][slug].get("governing_law"))
        msa = self.msa_id(slug)
        if kind == "cl":
            if "." not in ref and any(c["no"].startswith(ref + ".") for c in self.clauses(msa)):
                subs = [c["no"] for c in self.clauses(msa) if c["no"].startswith(ref + ".")]
                return dict(base_out, resolution="resolved", parent=True,
                            subclauses=[self.chain(slug, f"cl:{n}", as_of) for n in subs], chain=[], in_force=None,
                            uncertain=[], warnings=[])
            base = self.clause(msa, ref)
            if base is None:
                return dict(base_out, resolution="not_found", chain=[], in_force=None, uncertain=[], warnings=[],
                            note=f"clause {ref} was not found in the {name} MSA")
            base_doc, base_no = msa, ref
        else:
            rec = self.d["definitions"].get(ref)
            if rec is None:
                return dict(base_out, resolution="not_found", chain=[], in_force=None, uncertain=[], warnings=[],
                            note=f"{ref!r} is not a defined term")
            base = self.clause(rec["doc_id"], rec["clause"])
            base_doc, base_no = rec["doc_id"], rec["clause"]
        items = [self._item(base_doc, base_no, "IN_FORCE", base["text"], base["title"], base["page"],
                            note="base text")]
        cur = items[0]
        uncertain, warnings = [], []
        amendments = self.of_type(slug, "AMENDMENT")
        amended = False
        for am in amendments:
            am_id, am_eff = am["doc_id"], am["effective_date"]
            label = self.label(am_id)
            for e in self.d["edits"].get(am_id, []):
                if e["target"] != target:
                    continue
                if am_eff > as_of.isoformat():
                    items.append(self._item(am_id, e["para"], "NOT_YET_IN_FORCE", e["new"], "", None,
                                            note=f"takes effect {am_eff}, after the as-of date {as_of}"))
                    continue
                new_text, ok, why, new_title = apply_edit(cur["text"], e)
                if not ok:
                    items.append(self._item(am_id, e["para"], "UNAPPLIED", e["new"], "", None, note=why))
                    uncertain.append(f"{label} para {e['para']} changes this clause but {why}")
                    continue
                for bad in numeric_consistency(e.get("new", "") + " " + e.get("old", "")):
                    uncertain.append(f"{label} para {e['para']}: the figure written as words ({bad['words']}) and "
                                     f"as digits ({bad['digits']}) disagree after extraction - one was misread")
                cur["status"] = "SUPERSEDED"
                cur["note"] = f"superseded by {label} cl. {e['para']} (eff {am_eff})"
                cur = self._item(am_id, e["para"], "IN_FORCE", new_text, new_title or cur["title"],
                                 self._edit_page(am_id, e["para"]),
                                 note=f"{e['action'].replace('_', ' ')} of {target.split(':')[1]}")
                items.append(cur)
                amended = True
            if am_eff <= as_of.isoformat():
                for u in self.d["documents"][am_id].get("edits_unparsed", []):
                    hay = f"{u.get('title', '')} {u.get('text', '')}"
                    if self._mentions(hay, target):
                        uncertain.append(f"{label} paragraph {u['para']} could not be read (extraction quality) and "
                                         f"appears to mention this clause")
                    else:
                        warnings.append(f"{label} paragraph {u['para']} could not be read; it may touch other clauses")
        if kind == "cl":
            for sow in self.of_type(slug, "SOW"):
                for c in self.clauses(sow["doc_id"]):
                    m = R_OVERRIDE.search(c["text"])
                    if m and m.group(1) == ref:
                        if sow["effective_date"] > as_of.isoformat():
                            items.append(self._item(sow["doc_id"], c["no"], "NOT_YET_IN_FORCE", c["text"], c["title"],
                                                    c["page"], note="SOW not yet effective"))
                        elif amended:
                            items.append(self._item(sow["doc_id"], c["no"], "NOT_PREVAILING", c["text"], c["title"], c["page"],
                                                    note=f"expressly overrides MSA cl. {ref}, but an Amendment prevails "
                                                         f"over any SOW (MSA cl. 1.4(a))"))
                        else:
                            cur["status"] = "SUPERSEDED"
                            cur["note"] = (f"overridden by {self.label(sow['doc_id'])} cl. {c['no']}, which names clause "
                                           f"{ref} and says it expressly overrides it (MSA cl. 1.4(c))")
                            cur = self._item(sow["doc_id"], c["no"], "IN_FORCE", c["text"], c["title"], c["page"],
                                             note=f"SOW express override of MSA cl. {ref}")
                            items.append(cur)
                    elif ref in CONFLICT and CONFLICT[ref].search(c["text"]) and "expressly" not in c["text"].lower():
                        items.append(self._item(sow["doc_id"], c["no"], "NOT_PREVAILING", c["text"], c["title"], c["page"],
                                                note=f"conflicts with MSA cl. {ref} but does not name it and say it "
                                                     f"expressly overrides it, so MSA cl. 1.4 gives it no priority"))
        for bad in numeric_consistency(cur["text"]):
            uncertain.append(f"in-force text: the figure written as words ({bad['words']}) and as digits "
                             f"({bad['digits']}) disagree after extraction - one was misread")
        for it in items:     # a superseded clause points at what is in force NOW, however many hops later
            if it["status"] == "SUPERSEDED":
                it["in_force_now"] = dict(doc_id=cur["doc_id"], doc_label=cur["doc_label"], clause=cur["clause"],
                                          effective_date=cur["effective_date"])
        items.sort(key=lambda it: (it["effective_date"], 0 if it["doc_id"] == base_doc else 1))
        return dict(base_out, resolution="uncertain" if uncertain else "resolved", chain=items, in_force=cur,
                    uncertain=uncertain, warnings=warnings, parent=False)

    def _edit_page(self, doc_id, para):
        c = self.clause(doc_id, para)
        return c["page"] if c else None

    @staticmethod
    def _mentions(hay, target):
        kind, _, ref = target.partition(":")
        if kind == "cl":
            return re.search(r"(?<!\d)" + r"\s*\.\s*".join(ref.split(".")) + r"(?!\d)", hay) is not None
        return ref.lower()[:6] in hay.lower()

    # -- defined terms -------------------------------------------------------------------------------------
    def canon_term(self, term):
        t = normalise_term(term).lower()
        terms = {k.lower(): k for k in self.d["definitions"]}
        for cand in (t, t[:-1] if t.endswith("s") else t, t[:-2] if t.endswith("es") else t):
            if cand in terms:
                return terms[cand]
        close = difflib.get_close_matches(t, list(terms), n=1, cutoff=0.86)
        return terms[close[0]] if close else None

    def resolve_term(self, slug, term):
        canon = self.canon_term(term)
        if canon is None:
            return dict(counterparty=slug, term=term, defined=False,
                        note=f"{term!r} is not a defined term in Schedule 1. Do not apply an ordinary meaning to it; "
                             f"if the question turns on it, refer to counsel.")
        ch = self.chain(slug, f"def:{canon}")
        cur = ch["in_force"]
        return dict(counterparty=slug, term=canon, defined=True, resolution=ch["resolution"], in_force=cur,
                    chain=ch["chain"], uncertain=ch["uncertain"], warnings=ch["warnings"],
                    ordinary_meaning_warning=f"'{canon}' means what the definition says, not what the word means in "
                                             f"ordinary speech.")

    # -- per-clause status, for annotating search hits -----------------------------------------------------
    def status_map(self, slug):
        if slug in self._status:
            return self._status[slug]
        targets = {e["target"] for am in self.of_type(slug, "AMENDMENT") for e in self.d["edits"].get(am["doc_id"], [])}
        targets |= {"cl:11.3", "cl:5.2", "cl:14.2"}
        for sow in self.of_type(slug, "SOW"):
            for c in self.clauses(sow["doc_id"]):
                m = R_OVERRIDE.search(c["text"])
                if m:
                    targets.add(f"cl:{m.group(1)}")
        m = {}
        for t in sorted(targets):
            ch = self.chain(slug, t)
            if ch["resolution"] == "uncertain":     # every link of an unresolved chain is UNCERTAIN, including the base text
                for it in ch["chain"]:
                    m[(it["doc_id"], it["clause"])] = dict(status="UNCERTAIN", in_force_now=None,
                                                           note="the chain for this clause could not be resolved: " + "; ".join(ch["uncertain"])[:240])
                continue
            for it in ch["chain"]:
                prior = m.get((it["doc_id"], it["clause"]))
                if prior is None or it["status"] in ("SUPERSEDED", "UNAPPLIED"):
                    m[(it["doc_id"], it["clause"])] = dict(status=it["status"], note=it["note"],
                                                           in_force_now=it.get("in_force_now"))
        self._status[slug] = m
        return m

    def clause_status(self, slug, doc_id, clause_no):
        hit = self.status_map(slug).get((doc_id, str(clause_no)))
        if hit:
            return hit
        unread = [self.label(a["doc_id"]) for a in self.of_type(slug, "AMENDMENT")
                  if self.d["documents"][a["doc_id"]].get("edits_unparsed") and a["effective_date"] <= self.as_of.isoformat()]
        if unread:
            return dict(status="IN_FORCE_UNVERIFIED",
                        note=f"no readable amendment changes this clause, but {', '.join(unread)} has paragraphs that "
                             f"could not be read")
        return dict(status="IN_FORCE", note="no amendment or SOW changes this clause")
