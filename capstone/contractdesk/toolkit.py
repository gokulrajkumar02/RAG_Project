"""
The tools, as plain functions returning dicts. The MCP server (capstone/server.py) is a thin shell around these.

Rules every tool follows:
  * a counterparty is ALWAYS required and resolved first. If the name matches two customers (Halcyon Freight /
    Halcyon Foods) the answer is `ambiguous_counterparty` with the candidates, never a guess.
  * no tool returns another customer's text (scoping is the FAISS filter, not a check afterwards) and none returns
    raw extraction: only the REDACTED registry text. The fallback playbook is not a tool at all.
  * a failure that is the system's, not the contract's, says so (`uncertain` + why), so a model cannot mistake
    "I could not read the amendment" for "the amendment says nothing".
"""

import json
import os

from . import paths
from .registry import Registry

SNIPPET = 700


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def clip(text, n=SNIPPET):
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + " ...[clipped]"


def load_config():
    with open(paths.CONFIG, encoding="utf-8") as f:
        return json.load(f)


class Toolkit:
    def __init__(self, registry=None, index=None, variant=None):
        self.cfg = load_config()
        self.variant = variant or os.environ.get("CONTRACT_DESK_VARIANT") or self.cfg["default_variant"]
        self.vcfg = self.cfg["variants"][self.variant]
        self.reg = registry or Registry.load()
        self.index = index
        self.annotate = self.vcfg["annotate_status"]

    def _cp(self, counterparty):
        r = self.reg.resolve_counterparty(counterparty)
        if r["status"] == "ok":
            return r, None
        if r["status"] == "ambiguous":
            return None, dict(error="ambiguous_counterparty", given=counterparty, candidates=r["candidates"],
                              instruction="More than one customer matches. Ask the user which one; do not guess.")
        return None, dict(error="counterparty_not_found", given=counterparty, did_you_mean=r["candidates"],
                          instruction="No customer by that name is on file. Say so; do not answer from another customer's contract.")

    def _item(self, it, with_text=True):
        out = dict(doc_id=it["doc_id"], doc=it["doc_label"], clause=it["clause"], effective_date=it["effective_date"],
                   status=it["status"])
        for k in ("title", "note", "in_force_now"):
            if it.get(k):
                out[k] = it[k]
        if with_text:
            out["text"] = clip(it["text"])
        return out

    # -- registry tools -------------------------------------------------------------------------------------
    def lookup_contract(self, counterparty):
        r, err = self._cp(counterparty)
        if err:
            return err
        slug = r["slug"]
        docs = []
        for d in self.reg.docs(slug):
            q = "text layer" if d["source"] == "text-layer" else f"scanned, read by OCR (mean confidence {d['mean_conf']})"
            row = dict(doc_id=d["doc_id"], doc=self.reg.label(d["doc_id"]), effective_date=d["effective_date"],
                       pages=d["pages"], extraction=q)
            if d.get("edits_unparsed"):
                row["unreadable_paragraphs"] = len(d["edits_unparsed"])
            docs.append(row)
        out = dict(counterparty=slug, name=r["name"], matched_by=r["match"], documents=docs)
        if "resolve_amendment_chain" in self.vcfg["tools"]:
            c = self.reg.d["counterparties"][slug]
            out.update(governing_law=c.get("governing_law"), venue=c.get("venue"))
            n_am = sum(1 for d in docs if d["doc"].startswith("Amendment"))
            if n_am:
                out["amendments_on_file"] = n_am
                out["note"] = "The MSA may not be the operative text: amendments are on file. Resolve the chain before quoting."
        return out

    def resolve_amendment_chain(self, counterparty, clause):
        r, err = self._cp(counterparty)
        if err:
            return err
        target = self.reg.resolve_target(clause)
        if target is None:
            return dict(error="unknown_clause", given=clause, instruction="Give a clause number (e.g. '11.3') or 'def:<Term>'.")
        return self._chain_out(self.reg.chain(r["slug"], target))

    def _chain_out(self, ch):
        if ch["resolution"] == "not_found":
            return dict(counterparty=ch["counterparty"], target=ch["target"], resolution="not_found", note=ch.get("note"))
        if ch.get("parent"):
            changed = [s for s in ch["subclauses"] if len(s["chain"]) > 1]
            return dict(counterparty=ch["counterparty"], name=ch["name"], target=ch["target"], as_of=ch["as_of"],
                        resolution="uncertain" if any(s["resolution"] == "uncertain" for s in ch["subclauses"]) else "resolved",
                        unmodified=[s["target"].split(":")[1] for s in ch["subclauses"] if len(s["chain"]) <= 1],
                        modified=[self._chain_out(s) for s in changed])
        out = dict(counterparty=ch["counterparty"], name=ch["name"], target=ch["target"], as_of=ch["as_of"],
                   resolution=ch["resolution"], governing_law=ch["governing_law"],
                   in_force=self._item(ch["in_force"]) if ch["in_force"] else None,
                   chain=[self._item(it) for it in ch["chain"]])
        if ch["uncertain"]:
            out["uncertain"] = ch["uncertain"]
            out["instruction"] = ("Extraction could not support a firm answer. Do NOT state this clause as in force: say "
                                  "what could not be read, cite the documents, and refer to counsel.")
        if ch["warnings"]:
            out["warnings"] = ch["warnings"]
        return out

    def resolve_defined_term(self, counterparty, term):
        r, err = self._cp(counterparty)
        if err:
            return err
        t = self.reg.resolve_term(r["slug"], term)
        if not t["defined"]:
            return dict(counterparty=r["slug"], term=term, defined=False, note=t["note"])
        out = dict(counterparty=r["slug"], name=r["name"], term=t["term"], defined=True, resolution=t["resolution"],
                   definition=self._item(t["in_force"]), chain=[self._item(i, with_text=False) for i in t["chain"]],
                   warning=t["ordinary_meaning_warning"])
        if t["uncertain"]:
            out["uncertain"] = t["uncertain"]
        return out

    def get_governing_law(self, counterparty):
        r, err = self._cp(counterparty)
        if err:
            return err
        g = self.reg.governing_law(r["slug"])
        msa = self.reg.clause(self.reg.msa_id(r["slug"]), "18.1")
        return dict(counterparty=r["slug"], name=r["name"], governing_law=g["governing_law"], venue=g["venue"],
                    table_reviewed=g["reviewed"], msa_clause_18_1=clip(msa["text"], 300) if msa else None)

    # -- clause tools ---------------------------------------------------------------------------------------
    def search_clauses(self, counterparty, query, k=4, document_type="any", call=None):
        r, err = self._cp(counterparty)
        if err:
            return err
        slug = r["slug"]
        if call:
            call.counterparty = slug
        types = {"msa": {"MSA"}, "sow": {"SOW"}, "amendment": {"AMENDMENT"}}.get((document_type or "any").lower(),
                                                                                  {"MSA", "SOW", "AMENDMENT"})
        hits = self.index.search_scoped(query, lambda md: md.get("counterparty") == slug and md.get("type") in types,
                                        k=max(1, min(int(k or 4), 8)), span=call.span if call else None)
        results = []
        for doc, score in hits:
            md = doc.metadata
            c = self.reg.clause(md["doc_id"], md["clause"]) or {}
            item = dict(doc_id=md["doc_id"], doc=self.reg.label(md["doc_id"]), clause=md["clause"], title=md["title"],
                        effective_date=md["effective_date"], page=md["page"], score=round(score, 2),
                        text=clip(c.get("text", "")))
            if self.reg.doc(md["doc_id"])["source"] == "ocr":
                item["extraction"] = "scanned, read by OCR: the text may contain misreads"
            if self.annotate:
                st = self.reg.clause_status(slug, md["doc_id"], md["clause"])
                item["status"], item["status_note"] = st["status"], st["note"]
                if st.get("in_force_now"):
                    now = self.reg.clause(st["in_force_now"]["doc_id"], st["in_force_now"]["clause"]) or {}
                    item["in_force_now"] = dict(st["in_force_now"], text=clip(now.get("text", "")))
            results.append(item)
        out = dict(counterparty=slug, name=r["name"], matched_by=r["match"], query=query, results=results)
        notes = []
        if self.annotate and any(i.get("status") == "SUPERSEDED" for i in results):
            notes.append("Some results are SUPERSEDED; each carries `in_force_now`. Quote that, not the superseded text.")
        if self.annotate and any(i.get("status") == "UNCERTAIN" for i in results):
            notes.append("Some results are UNCERTAIN: the amendment chain could not be resolved from the scanned documents. "
                         "Do not quote them as in force; call resolve_amendment_chain or refer to counsel.")
        if notes:
            out["notice"] = " ".join(notes)
        return out

    def get_clause(self, counterparty, document, clause, call=None):
        r, err = self._cp(counterparty)
        if err:
            return err
        slug = r["slug"]
        if call:
            call.counterparty = slug
        doc = document if "/" in document else f"{slug}/{document.lower().replace(' ', '-').replace('no.', '')}"
        if not doc.startswith(slug + "/"):
            return dict(error="out_of_scope", instruction=f"{document!r} is not a document of {r['name']}.")
        if doc not in self.reg.d["documents"]:
            return dict(error="document_not_found", given=document, documents=[d["doc_id"] for d in self.reg.docs(slug)])
        c = self.reg.clause(doc, clause)
        if c is None:
            return dict(error="clause_not_found", doc_id=doc, given=clause, clauses=[x["no"] for x in self.reg.clauses(doc)][:80])
        out = dict(counterparty=slug, matched_by=r["match"], doc_id=doc, doc=self.reg.label(doc),
                   effective_date=self.reg.doc(doc)["effective_date"], clause=c["no"], title=c["title"], page=c["page"],
                   text=clip(c["text"]))
        if self.reg.doc(doc)["source"] == "ocr":
            out["extraction"] = "scanned, read by OCR: the text may contain misreads"
        if self.annotate:
            st = self.reg.clause_status(slug, doc, c["no"])
            out["status"], out["status_note"] = st["status"], st["note"]
            if st.get("in_force_now"):
                now = self.reg.clause(st["in_force_now"]["doc_id"], st["in_force_now"]["clause"]) or {}
                out["in_force_now"] = dict(st["in_force_now"], text=clip(now.get("text", "")))
        return out
