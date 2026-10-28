"""
logq - search the request logs from a vague complaint. Every slice the drill names is a flag:

    time            --day thu | --day 2026-10-22,wed  --from 13:00 --to 16:30   (IST, the users' clock)
    user            --user u-lw-03   --role lawyer
    prompt version  --pv answer-v2
    input type      --type termination          (logq.py facet input_type lists them)
    cost outlier    --cost-outlier              (cost above the p99 of everything loaded)
    citation        --mismatch                  (schema w11.2: cited clause does not match what was read)
and text, on the question AND the answer (a complaint usually describes the output):
                    --q TEXT  --a TEXT  --text TEXT (either)   add --re for a regex
                    --where FIELD=VALUE  (any field, dotted for nested, e.g. retrieval.source_chunk_ids=18)

    python observability/logq.py summary
    python observability/logq.py find  --day thu --type termination --role lawyer [--wide] [--limit 50]
    python observability/logq.py facet input_type --day thu
    python observability/logq.py show  <trace id prefix>
    python observability/logq.py export <trace id prefix> --out observability/deliverables/trace.json

While a drill is running (drill.py start), every command is appended to the drill's query log with its hit
count and the elapsed time, so the search path in drill.md is the tool's record, not anyone's memory.
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tracing import read_logs  # noqa: E402

LOG_DIRS = {"prod": os.path.join(HERE, "logs", "prod"), "eval": os.path.join(HERE, "logs", "eval")}
DRILL_DIR = os.path.join(HERE, "drill")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---- field access -----------------------------------------------------------------------------------
def local_dt(rec):
    return datetime.fromisoformat(rec["ts_local"])


def get_field(rec, path):
    if path == "day":
        d = local_dt(rec)
        return f"{d:%Y-%m-%d} {WEEKDAYS[d.weekday()]}"
    if path == "hour":
        return f"{local_dt(rec):%H}:00"
    if path == "weekday":
        return WEEKDAYS[local_dt(rec).weekday()]
    cur = rec
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def matches_value(value, wanted):
    if isinstance(value, list):
        return any(matches_value(v, wanted) for v in value)
    if isinstance(value, bool):
        return str(value).lower() == wanted.lower()
    return value is not None and str(value).lower() == wanted.lower()


# ---- filters ----------------------------------------------------------------------------------------
INDEX_FIELDS = ("answer_cited_clauses", "context_clause_ids", "citation_support", "citation_mismatch")


def add_filters(p):
    p.add_argument("--logs", default="prod", help="prod | eval | a directory")
    p.add_argument("--schema", choices=["w11.1", "w11.2"], default="w11.2",
                   help="w11.1 hides the output index, for a fair base-schema drill")
    p.add_argument("--day", help="comma list: 2026-10-22, thu, ...")
    p.add_argument("--from", dest="t_from", help="HH:MM or 'YYYY-MM-DD HH:MM' (IST)")
    p.add_argument("--to", dest="t_to", help="HH:MM or 'YYYY-MM-DD HH:MM' (IST)")
    p.add_argument("--user")
    p.add_argument("--role")
    p.add_argument("--pv", help="prompt version")
    p.add_argument("--type", help="input type")
    p.add_argument("--status")
    p.add_argument("--q", help="question contains")
    p.add_argument("--a", help="answer contains")
    p.add_argument("--text", help="question OR answer contains")
    p.add_argument("--re", action="store_true", help="treat --q/--a/--text as regular expressions")
    p.add_argument("--cost-outlier", action="store_true", help="cost above the p99 of all loaded traces")
    p.add_argument("--mismatch", action="store_true",
                   help="schema w11.2: answers whose cited clause does not match the clauses they read")
    p.add_argument("--where", action="append", default=[], help="FIELD=VALUE, repeatable")


def _clock(spec):
    spec = spec.strip()
    if len(spec) <= 5:
        return None, spec.zfill(5)
    day, clock = spec.split()
    return day, clock.zfill(5)


def _text_hit(haystack, needle, use_re):
    if haystack is None:
        return False
    if use_re:
        return re.search(needle, haystack, re.I) is not None
    return needle.lower() in haystack.lower()


def apply_filters(records, a):
    days = None
    if a.day:
        days = set()
        for tok in a.day.lower().split(","):
            tok = tok.strip()
            days.add(("wd", WEEKDAYS.index(tok[:3])) if tok[:3] in WEEKDAYS else ("date", tok))
    p99 = None
    if a.cost_outlier and records:
        costs = sorted(r["totals"]["cost_usd"] for r in records)
        p99 = costs[min(len(costs) - 1, int(0.99 * len(costs)))]
        a._p99 = p99
    out = []
    for r in records:
        d = local_dt(r)
        if days and not (("wd", d.weekday()) in days or ("date", f"{d:%Y-%m-%d}") in days):
            continue
        if a.t_from and not _in_window(d, a.t_from, ">="):
            continue
        if a.t_to and not _in_window(d, a.t_to, "<="):
            continue
        if a.user and r["user_id"] != a.user:
            continue
        if a.role and r["user_role"] != a.role:
            continue
        if a.pv and r["prompt_version"] != a.pv:
            continue
        if a.type and r["input_type"] != a.type:
            continue
        if a.status and r["status"] != a.status:
            continue
        if a.q and not _text_hit(r["question"], a.q, a.re):
            continue
        if a.a and not _text_hit(r["answer"], a.a, a.re):
            continue
        if a.text and not (_text_hit(r["question"], a.text, a.re) or _text_hit(r["answer"], a.text, a.re)):
            continue
        if p99 is not None and r["totals"]["cost_usd"] <= p99:
            continue
        if getattr(a, "mismatch", False) and not r.get("citation_mismatch"):
            continue
        if any(not matches_value(get_field(r, w.split("=", 1)[0]), w.split("=", 1)[1]) for w in a.where):
            continue
        out.append(r)
    return out


def _in_window(d, spec, op):
    day, clock = _clock(spec)
    stamp = f"{d:%Y-%m-%d} {d:%H:%M}" if day else f"{d:%H:%M}"
    bound = f"{day} {clock}" if day else clock
    return stamp >= bound if op == ">=" else stamp <= bound


# ---- output -----------------------------------------------------------------------------------------
def one_line(text, width):
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 3] + "..."


def print_rows(rows, wide, limit):
    shown = rows[:limit] if limit else rows
    for i, r in enumerate(shown, 1):
        d = local_dt(r)
        head = (f"{i:>3}  {WEEKDAYS[d.weekday()]} {d:%m-%d %H:%M:%S}  {r['trace_id'][:8]}  {r['user_id']:<9}"
                f" {r['user_role']:<9} {r['prompt_version']:<10} {r['input_type']:<15} ${r['totals']['cost_usd']:.6f}")
        if wide:
            print(head)
            print(f"       Q: {one_line(r['question'], 400)}")
            print(f"       A: {one_line(r['answer'], 400)}")
            if "answer_cited_clauses" in r:
                print(f"       cited {r['answer_cited_clauses']}  read clauses {r['context_clause_ids']}  "
                      f"word support {r['citation_support']}  mismatch={r['citation_mismatch']}")
        else:
            print(f"{head}  Q: {one_line(r['question'], 50):<50}  A: {one_line(r['answer'], 70)}")
    if limit and len(rows) > limit:
        print(f"... {len(rows) - limit} more (use --limit 0 for all)")


def find_one(records, prefix):
    hits = [r for r in records if r["trace_id"].startswith(prefix)]
    if len(hits) != 1:
        sys.exit(f"{len(hits)} traces match {prefix!r}; give a longer prefix")
    return hits[0]


def drill_log(argv, hits):
    state_path = os.path.join(DRILL_DIR, "state.json")
    if not os.path.exists(state_path):
        return
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    if not state.get("active"):
        return
    elapsed = time.time() - state["started_at"]
    with open(os.path.join(DRILL_DIR, f"querylog_{state['drill']}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"elapsed_s": round(elapsed, 1), "argv": argv, "hits": hits}) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    add_filters(s)
    f = sub.add_parser("find")
    add_filters(f)
    f.add_argument("--wide", action="store_true", help="full question and answer on their own lines")
    f.add_argument("--limit", type=int, default=40)
    f.add_argument("--sort", choices=["time", "cost"], default="time")
    fc = sub.add_parser("facet")
    fc.add_argument("field", help="input_type, user_id, user_role, prompt_version, day, hour, status, ... (dotted ok)")
    add_filters(fc)
    sh = sub.add_parser("show")
    sh.add_argument("trace")
    sh.add_argument("--logs", default="prod")
    ex = sub.add_parser("export")
    ex.add_argument("trace")
    ex.add_argument("--out", required=True)
    ex.add_argument("--logs", default="prod")
    a = ap.parse_args()

    records = read_logs(LOG_DIRS.get(a.logs, a.logs))
    if getattr(a, "schema", "w11.2") == "w11.1":
        for r in records:
            for k in INDEX_FIELDS:
                r.pop(k, None)
    argv = sys.argv[1:]

    if a.cmd in ("show", "export"):
        rec = find_one(records, a.trace)
        if a.cmd == "show":
            print(json.dumps(rec, indent=2, ensure_ascii=False))
        else:
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            print(f"wrote {a.out}")
        drill_log(argv, 1)
        return

    rows = apply_filters(records, a)
    if a.cmd == "summary":
        print(f"{len(rows)} traces (of {len(records)} loaded)  schema: {dict(Counter(r['schema'] for r in rows))}")
        for field in ("day", "prompt_version", "user_role", "input_type", "llm_mode", "status"):
            c = Counter(get_field(r, field) for r in rows)
            print(f"\n{field}:")
            for k, v in sorted(c.items(), key=lambda kv: str(kv[0])):
                print(f"  {str(k):<22} {v}")
    elif a.cmd == "find":
        if a.sort == "cost":
            rows.sort(key=lambda r: r["totals"]["cost_usd"], reverse=True)
        extra = f"  (cost > p99 = ${a._p99:.6f})" if getattr(a, "_p99", None) is not None else ""
        print(f"{len(rows)} match{extra}")
        print_rows(rows, a.wide, a.limit)
    elif a.cmd == "facet":
        c = Counter()
        for r in rows:
            v = get_field(r, a.field)
            for item in (v if isinstance(v, list) else [v]):
                c[json.dumps(item) if isinstance(item, (dict, list)) else str(item)] += 1
        print(f"{len(rows)} traces; {a.field}:")
        for k, v in c.most_common():
            print(f"  {k:<40} {v}")
    drill_log(argv, len(rows))


if __name__ == "__main__":
    main()
