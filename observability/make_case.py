"""
Turn a found trace into a permanent eval case (eval/regression/<id>.json), BEFORE anything is fixed.

    python observability/make_case.py <trace id prefix> --expect 7 [--allow 7,8] --keywords confidentiality \\
        --id reg_termination_wrong_clause --why "cited clause 8 for a clause 7 right"

The question is taken verbatim from the trace and the bad answer is stored verbatim as `logged_answer`.
What the RIGHT answer must cite (--expect / --allow) and which words it must contain (--keywords) are a
human's call, read off the contract - the tool only fills in the chunk ids of those clauses, from the
clause map, as the judge's gold reference.
"""

import argparse
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (REPO_ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clauses import ClauseMap  # noqa: E402
from logq import LOG_DIRS, find_one  # noqa: E402
from pipeline import PDF_PATH  # noqa: E402
from rag_core import load_pdf_chunks  # noqa: E402
from tracing import read_logs  # noqa: E402

REGRESSION_DIR = os.path.join(REPO_ROOT, "eval", "regression")
COMPLAINT = "a lawyer said it cited the wrong clause on termination, maybe Thursday."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--expect", required=True, help="clause number(s) a correct answer must cite, comma list")
    ap.add_argument("--allow", help="clause numbers it may also cite (default: only --expect)")
    ap.add_argument("--keywords", required=True, help="comma list; a correct answer contains at least one")
    ap.add_argument("--id", required=True)
    ap.add_argument("--why", required=True, help="one line: what was wrong, read off the contract")
    ap.add_argument("--complaint", default=COMPLAINT)
    ap.add_argument("--logs", default="prod")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    rec = find_one(read_logs(LOG_DIRS.get(a.logs, a.logs)), a.trace)
    required = [c.strip() for c in a.expect.split(",")]
    allowed = sorted(set(required) | {c.strip() for c in (a.allow or "").split(",") if c.strip()}, key=int)
    clause_map = ClauseMap(load_pdf_chunks(PDF_PATH))
    expected_chunks = sorted({i for c in required for i in clause_map.chunks_with_body(c)})

    case = {
        "id": a.id,
        "problem_type": "wrong_clause_citation",
        "question": rec["question"],
        "expected_chunks": expected_chunks,
        "answer_keywords": [k.strip() for k in a.keywords.split(",")],
        "citation": {"required": required, "allowed": allowed},
        "why": a.why,
        "complaint": a.complaint,
        "logged_answer": rec["answer"],
        "source": {
            "trace_id": rec["trace_id"], "ts_local": rec["ts_local"], "user_role": rec["user_role"],
            "prompt_version": rec["prompt_version"], "prompt_sha": rec["prompt_sha"],
            "source_chunk_ids": rec["retrieval"]["source_chunk_ids"],
            "context_chunk_ids": rec["retrieval"]["context_chunk_ids"],
        },
        "added": date.today().isoformat(),
    }
    os.makedirs(REGRESSION_DIR, exist_ok=True)
    path = os.path.join(REGRESSION_DIR, f"{a.id}.json")
    if os.path.exists(path) and not a.force:
        sys.exit(f"{path} exists (--force to overwrite)")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.relpath(path, REPO_ROOT)}")
    print(json.dumps(case, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
