"""
Ingestion: manifest + extracted text -> registry.json (parsed, redacted, quality-scored) -> FAISS index.

    python capstone/run.py build

Each document is parsed from what extraction gave us (pypdf text layer or OCR). Nothing here reads truth.json.
What is recorded per document, so a reader of the registry can see how far to trust it:
  source           text-layer | ocr
  mean_conf        mean OCR confidence over the page (None for a text layer)
  date_check       does the "takes effect on ..." sentence in the document agree with the manifest's date
  missing_clauses  MSA clause numbers that every clean (text-layer) MSA has but this one lacks after parsing
  edits_parsed / edits_unparsed   for amendments: how many paragraphs became a machine-readable edit, and the
                   paragraphs that did not (the chain resolver refuses to answer around those)
  redactions       personal-data strings masked per kind
"""

import datetime as dt
import json
import os
import statistics
import time
from collections import Counter

from . import extract, paths, redact
from . import parse as P

REGISTRY_VERSION = "cap.1"


def build_registry(manifest, progress=print):
    parsed = {}
    for doc_id, rec in manifest["documents"].items():
        ex = extract.load_extracted(doc_id)
        parsed[doc_id] = (rec, ex, P.parse_clauses(ex["pages"], rec["type"]))

    # The MSA template's clause list, learned from the clean (text-layer) MSAs: a clause number that ~every clean
    # MSA has is part of the template. A scanned MSA that lacks one lost it in extraction.
    clean = [set(c["no"] for c in cl if c["no"] not in ("0", "sig")) for (rec, ex, cl) in parsed.values()
             if rec["type"] == "MSA" and ex["source"] == "text-layer"]
    counts = Counter(n for s in clean for n in s)
    expected = sorted((n for n, c in counts.items() if c >= 0.9 * len(clean)), key=lambda n: [int(x) for x in n.split(".")])

    reg = dict(version=REGISTRY_VERSION, built_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               ocr_engine=extract.engine_version(), supplier=manifest["supplier"], msa_template_clauses=expected,
               counterparties={}, documents={}, clauses={}, edits={}, definitions={}, playbook=[])
    totals = Counter()
    for doc_id, (rec, ex, clauses) in parsed.items():
        red_counts = Counter()
        for c in clauses:
            red_counts.update(redact.redact_clause(c))
        pre = next((c for c in clauses if c["no"] == "0"), None)
        date_in_text = P.parse_effective_date(pre["text"]) if pre else None
        date_check = "ok" if date_in_text == rec["effective_date"] else ("unparsed" if not date_in_text
                                                                       else f"mismatch (text says {date_in_text})")
        confs = [p["mean_conf"] for p in ex["pages"] if p.get("mean_conf") is not None]
        d = dict(rec, pages=len(ex["pages"]), source=ex["source"],
                 mean_conf=round(statistics.fmean(confs), 4) if confs else None, date_in_text=date_in_text,
                 date_check=date_check, clause_count=len([c for c in clauses if c["no"] not in ("0", "sig")]),
                 redactions=dict(red_counts))
        if rec["type"] == "MSA":
            found = {c["no"] for c in clauses}
            d["missing_clauses"] = [n for n in expected if n not in found]
            d["numeric_flags"] = [b for c in clauses for b in P.numeric_consistency(c["text"])]
        if rec["type"] == "AMENDMENT":
            edits, unparsed = P.parse_edits(clauses)
            d["edits_parsed"], d["edits_unparsed"] = len(edits), unparsed
            reg["edits"][doc_id] = edits
        reg["documents"][doc_id] = d
        reg["clauses"][doc_id] = clauses
        totals.update(red_counts)
        if rec["counterparty"]:
            reg["counterparties"].setdefault(rec["counterparty"], dict(
                name=manifest["counterparties"][rec["counterparty"]]["name"], docs=[]))["docs"].append(doc_id)

    law = P.parse_law_table(parsed["shared/governing-law-table"][1]["pages"])
    for slug, c in reg["counterparties"].items():
        row = law.get(slug)
        c.update(governing_law=("the " + row["law"]) if row else None, venue=("the " + row["venue"]) if row else None,
                 law_reviewed=row["reviewed"] if row else None, law_row_found=bool(row))
    for c in reg["clauses"]["shared/definitions-schedule"]:
        if c["no"] not in ("0", "sig") and c["title"]:
            reg["definitions"][P.normalise_term(c["title"])] = dict(doc_id="shared/definitions-schedule", clause=c["no"])
    reg["playbook"] = [c for c in reg["clauses"]["shared/fallback-playbook"] if c["no"] not in ("0", "sig")]
    reg["stats"] = dict(documents=len(reg["documents"]), redactions=dict(totals),
                        ocr_documents=sum(1 for d in reg["documents"].values() if d["source"] == "ocr"))
    with open(paths.REGISTRY, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    if progress:
        progress(f"registry: {len(reg['documents'])} documents, {len(reg['counterparties'])} counterparties, "
                 f"{reg['stats']['ocr_documents']} read by OCR, redactions {dict(totals)}")
    return reg


def build_chunks(reg):
    """One chunk per clause of every contract document and of the playbook. Text is the REDACTED registry text."""
    from langchain_core.documents import Document

    chunks = []
    for doc_id, rec in reg["documents"].items():
        if rec["type"] not in ("MSA", "SOW", "AMENDMENT", "PLAYBOOK"):
            continue
        label = {"MSA": "MSA", "SOW": f"SOW No.{rec['number']}", "AMENDMENT": f"Amendment No.{rec['number']}",
                 "PLAYBOOK": "Playbook"}[rec["type"]]
        for c in reg["clauses"][doc_id]:
            if c["no"] in ("0", "sig") or not c["text"]:
                continue
            head = f"{label} cl. {c['no']}" + (f" {c['title']}" if c["title"] else "")
            chunks.append(Document(
                page_content=f"[{head}] {c['text']}",
                metadata=dict(doc_id=doc_id, counterparty=rec["counterparty"], type=rec["type"], number=rec["number"],
                              clause=c["no"], title=c["title"], page=c["page"], effective_date=rec["effective_date"])))
    return chunks


def build_index(reg, progress=print):
    from .index import CorpusIndex
    t0 = time.time()
    chunks = build_chunks(reg)
    idx = CorpusIndex(chunks)
    idx.save()
    if progress:
        progress(f"index: {len(chunks)} clause chunks embedded and saved in {time.time() - t0:.1f}s")
    return idx
