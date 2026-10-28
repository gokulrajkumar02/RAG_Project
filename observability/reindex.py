"""
Backfill the w11.2 output index (index_fields.py) into traces written before it existed.

    python observability/reindex.py              # logs/prod
    python observability/reindex.py --logs eval/before

Nothing is re-run: every new field is derived from what the trace already holds - the answer text and the
logged context chunk ids, mapped to clauses with the ingest-time clause map. That is the payoff of logging
context ids from day one. Records keep exactly the shape a newly written trace has (no "backfilled" marker
inside a record, which would make old and new traces distinguishable); the run is recorded in REINDEX.json
next to the logs instead.
"""

import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (REPO_ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import index_fields  # noqa: E402
from clauses import ClauseMap  # noqa: E402
from logq import LOG_DIRS  # noqa: E402
from pipeline import PDF_PATH  # noqa: E402
from rag_core import load_pdf_chunks  # noqa: E402
from tracing import JsonlSink  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", default="prod")
    a = ap.parse_args()
    log_dir = LOG_DIRS.get(a.logs, os.path.join(HERE, "logs", a.logs))
    clause_map = ClauseMap(load_pdf_chunks(PDF_PATH))

    total, changed, flagged = 0, 0, []
    for name in sorted(os.listdir(log_dir)):
        if not (name.startswith("traces-") and name.endswith(".jsonl")):
            continue
        path = os.path.join(log_dir, name)
        with open(path, encoding="utf-8") as f:
            records = [json.loads(ln) for ln in f if ln.strip()]
        for r in records:
            total += 1
            fields = index_fields.derive(r["answer"] or "", r["retrieval"]["context_chunk_ids"], clause_map)
            if r.get("schema") != index_fields.SCHEMA or any(r.get(k) != v for k, v in fields.items()):
                changed += 1
            r.update(fields)
            r["schema"] = index_fields.SCHEMA
            if fields["citation_mismatch"]:
                flagged.append(r["trace_id"])
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(JsonlSink.dumps(r) + "\n" for r in records))

    manifest = os.path.join(log_dir, "REINDEX.json")
    runs = []
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            runs = json.load(f)
    runs.append({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "schema": index_fields.SCHEMA,
                 "traces": total, "updated": changed, "citation_mismatch": len(flagged),
                 "fields": ["answer_cited_clauses", "context_clause_ids", "citation_support", "citation_mismatch"]})
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2)
        f.write("\n")
    print(f"{total} traces, {changed} updated to {index_fields.SCHEMA}; citation_mismatch on {len(flagged)}")


if __name__ == "__main__":
    main()
