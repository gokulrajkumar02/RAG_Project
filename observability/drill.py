"""
The support drill as a tool. A squadmate PLANTS one bad answer into the production logs; the finder gets
only the complaint; a timer runs from START until the correct SUBMIT.

    python observability/drill.py plant  --question "..." --answer "..." [--day 2026-10-22] [--time 14:05]
                                         [--user u-lw-03 | --role lawyer]        (squadmate only)
    python observability/drill.py start  --finder NAME --timer NAME             (prints the complaint)
    python observability/drill.py submit <trace id prefix> --slice "time -> input type -> ..."
    python observability/drill.py status
    python observability/drill.py report <drill number>                          (markdown for drill.md)

A plant goes through the same code path as every other logged request: real retrieval for the planted
question, the prompt version that was routing for that user at that minute, the same token/cost/latency
bookkeeping, a random trace id, inserted at its time position. Nothing but the answer text gives it away.
Without --day/--time/--user the plant lands on a random weekday (Thursday weighted 70%) at a random business
hour, as a random lawyer active that day - so "maybe Thursday" can be wrong, as complaints are.

The answer key goes to drill/answer_key_<n>.json. The finder does not open it; `submit` does.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tracing import JsonlSink, read_logs  # noqa: E402

DRILL_DIR = os.path.join(HERE, "drill")
STATE = os.path.join(DRILL_DIR, "state.json")
RESULTS = os.path.join(DRILL_DIR, "results.jsonl")
COMPLAINT = "a lawyer said it cited the wrong clause on termination, maybe Thursday."
PLANT_DAYS = (["2026-10-21", "2026-10-22", "2026-10-23"], [15, 70, 15])


def _load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _key_path(n):
    return os.path.join(DRILL_DIR, f"answer_key_{n}.json")


def _drill_numbers():
    if not os.path.isdir(DRILL_DIR):
        return []
    return sorted(int(n[len("answer_key_"):-5]) for n in os.listdir(DRILL_DIR)
                  if n.startswith("answer_key_") and n.endswith(".json"))


def _results():
    if not os.path.exists(RESULTS):
        return []
    with open(RESULTS, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _text(value, path):
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return value


# ---- plant ------------------------------------------------------------------------------------------
def plant(a):
    from pipeline import IST, LOG_DIR, Pipeline, load_config, route
    from traffic import USERS, _start_minute

    state = _load(STATE, {})
    if state.get("active"):
        sys.exit("a drill is running; submit or abandon it before planting another")
    question, answer = _text(a.question, a.question_file), _text(a.answer, a.answer_file)
    if not question or not answer:
        sys.exit("need --question/--question-file and --answer/--answer-file")

    rng = random.SystemRandom()
    day = a.day or rng.choices(*PLANT_DAYS)[0]
    d0 = datetime.fromisoformat(day).replace(tzinfo=IST)
    if a.time:
        hh, mm = (int(x) for x in a.time.split(":"))
        t = d0 + timedelta(hours=hh, minutes=mm, seconds=rng.uniform(0, 60))
    else:
        t = d0 + timedelta(minutes=_start_minute(rng, d0.weekday() >= 5), seconds=rng.uniform(0, 60))

    user = a.user
    if not user:
        active = sorted({r["user_id"] for r in read_logs(LOG_DIR)
                         if r["ts_local"].startswith(day) and r["user_role"] == a.role})
        user = rng.choice(active or USERS[a.role])
    role = next((r for r, ids in USERS.items() if user in ids), a.role)

    pipe = Pipeline(llm="synthetic", log_dir=LOG_DIR)
    pipe.warm()
    pv = route(load_config(), user, at_local=t)
    rec = pipe.ask(question, user_id=user, user_role=role, session_id=f"s-{rng.getrandbits(48):012x}",
                   prompt_version=pv, now=t, answer_fn=lambda *_: answer, write=False)["trace"]
    path, pos = JsonlSink(LOG_DIR).insert_sorted(rec)

    n = (max(_drill_numbers()) + 1) if _drill_numbers() else 1
    _save(_key_path(n), {
        "drill": n, "trace_id": rec["trace_id"], "ts_local": rec["ts_local"], "user_id": user, "user_role": role,
        "prompt_version": pv, "question": question, "answer": answer, "planted_by": a.by,
        "planted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    _save(STATE, {"active": False, "drill": n, "planted": True})
    print(f"Planted drill #{n} into {os.path.relpath(path, HERE)} ({sum(1 for _ in open(path, encoding='utf-8'))} "
          f"traces in that file). Answer key: drill/answer_key_{n}.json - the finder must not open it.")


# ---- start / submit ---------------------------------------------------------------------------------
def start(a):
    state = _load(STATE, {})
    if state.get("active"):
        sys.exit(f"drill #{state['drill']} is already running")
    nums = _drill_numbers()
    done = {r["drill"] for r in _results() if r["correct"]}
    pending = [n for n in nums if n not in done]
    if not pending:
        sys.exit("nothing planted: a squadmate runs `drill.py plant` first")
    n = pending[-1]
    now = time.time()
    _save(STATE, {"active": True, "drill": n, "started_at": now,
                  "started_at_local": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
                  "finder": a.finder, "timer": a.timer})
    open(os.path.join(DRILL_DIR, f"querylog_{n}.jsonl"), "w", encoding="utf-8").close()
    print(f"DRILL #{n} STARTED {datetime.fromtimestamp(now):%H:%M:%S} - finder: {a.finder}, timer: {a.timer}")
    print(f'Complaint: "{COMPLAINT}"')
    print("No trace id, no contract id, no timestamp. Logs only: observability/logq.py")


def submit(a):
    state = _load(STATE, {})
    if not state.get("active"):
        sys.exit("no drill running")
    if len(a.trace) < 8:
        sys.exit("give at least 8 characters of the trace id")
    elapsed = time.time() - state["started_at"]
    key = _load(_key_path(state["drill"]))
    correct = key["trace_id"].startswith(a.trace)
    row = {"drill": state["drill"], "submitted": a.trace, "correct": correct, "elapsed_s": round(elapsed, 1),
           "mm:ss": mmss(elapsed), "slice": a.slice, "finder": state["finder"], "timer": state["timer"],
           "started_at_local": state["started_at_local"]}
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if not correct:
        print(f"Not the planted trace. Timer still running: {mmss(elapsed)}")
        return
    state["active"] = False
    _save(STATE, state)
    verdict = "under 5:00" if elapsed < 300 else "OVER 5:00 - drill.md must name the log field whose absence cost the time"
    print(f"FOUND drill #{state['drill']} in {mmss(elapsed)} ({verdict})")
    print(f"Planted: {key['ts_local']}  {key['user_id']} ({key['user_role']})  {key['prompt_version']}")


def status(_a):
    state = _load(STATE, {})
    if state.get("active"):
        print(f"drill #{state['drill']} running for {mmss(time.time() - state['started_at'])} (finder {state['finder']})")
    else:
        print(f"no drill running; planted: {_drill_numbers()}; results: {len(_results())}")


def report(a):
    rows = [r for r in _results() if r["drill"] == a.n]
    key = _load(_key_path(a.n))
    found = next((r for r in rows if r["correct"]), None)
    if not found:
        sys.exit(f"drill #{a.n} has no correct submission yet")
    print(f"| | |\n|---|---|")
    print(f"| Time-to-find | **{found['mm:ss']}** ({'under' if found['elapsed_s'] < 300 else 'over'} 5:00) |")
    print(f"| Slice that found it | {found['slice']} |")
    print(f"| Finder / timer | {found['finder']} / {found['timer']} |")
    print(f"| Started | {found['started_at_local']} |")
    print(f"| Wrong submissions before it | {sum(1 for r in rows if not r['correct'])} |")
    print(f"| Planted by | {key['planted_by']} - {key['ts_local']}, {key['user_id']} ({key['user_role']}), "
          f"{key['prompt_version']} |")
    qlog = os.path.join(DRILL_DIR, f"querylog_{a.n}.jsonl")
    if os.path.exists(qlog):
        print("\n| elapsed | command | hits |\n|---|---|---|")
        with open(qlog, encoding="utf-8") as f:
            for ln in f:
                q = json.loads(ln)
                print(f"| {mmss(q['elapsed_s'])} | `logq.py {' '.join(q['argv'])}` | {q['hits']} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plant")
    p.add_argument("--question")
    p.add_argument("--question-file")
    p.add_argument("--answer")
    p.add_argument("--answer-file")
    p.add_argument("--day", help="YYYY-MM-DD (IST); default: random Wed/Thu/Fri, Thursday 70%%")
    p.add_argument("--time", help="HH:MM (IST); default: random business hour")
    p.add_argument("--user")
    p.add_argument("--role", default="lawyer")
    p.add_argument("--by", default="squadmate", help="who planted it (goes in the key and the report)")
    s = sub.add_parser("start")
    s.add_argument("--finder", required=True)
    s.add_argument("--timer", required=True)
    sb = sub.add_parser("submit")
    sb.add_argument("trace")
    sb.add_argument("--slice", required=True)
    sub.add_parser("status")
    r = sub.add_parser("report")
    r.add_argument("n", type=int)
    a = ap.parse_args()
    {"plant": plant, "start": start, "submit": submit, "status": status, "report": report}[a.cmd](a)


if __name__ == "__main__":
    main()
