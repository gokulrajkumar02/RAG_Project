"""
Builds the drill's haystack: a SYNTHETIC production week in observability/logs/prod/.

Why synthetic: the app has no production users. The Week 11 drill needs "one bad answer among thousands",
and 1,700 real generations would also blow the free tier's 1,000 requests/day for gpt-oss-20b.

What is real in it:  every request runs the app's real retrieval (FAISS + cross-encoder + neighbour stitch,
                     timed span by span), the real prompt routing for that minute (config.json history: v1,
                     then a 20% v2 canary on Wednesday 11:00 IST, v2 at 100% from Thursday 10:00 IST), the real
                     prompt text, and the same trace writer the app uses.
What is not:         who asked what and when (seeded schedule below), the answers (answer_bank.py: correct
                     answers, or not-found when retrieval missed the supporting text), token counts (tiktoken
                     estimates of the real prompt + that answer) and generation latency (modelled from Groq's
                     published ~1000 tok/s). Every such trace says llm_mode="synthetic".

    python observability/traffic.py            # refuses if logs/prod already has traces (a drill plant may be in them)
    python observability/traffic.py --force    # wipe logs/prod and regenerate (same seed -> same week)
"""

import argparse
import glob
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import answer_bank as bank  # noqa: E402
import prompts  # noqa: E402
from pipeline import IST, LOG_DIR, Pipeline, load_config, route  # noqa: E402

SEED = 11
DAYS = [("2026-10-19", 300), ("2026-10-20", 330), ("2026-10-21", 345), ("2026-10-22", 380),
        ("2026-10-23", 320), ("2026-10-24", 28), ("2026-10-25", 17)]
ROLES = {"lawyer": ("lw", 8, 0.30), "paralegal": ("pl", 5, 0.15), "hr": ("hr", 10, 0.30), "employee": ("em", 14, 0.25)}
SESSION_SIZES = ([1, 2, 3, 4, 5, 6], [30, 25, 18, 12, 9, 6])
PASTED_SHARE_LAWYER = 0.05

USERS = {role: [f"u-{code}-{i:02d}" for i in range(1, n + 1)] for role, (code, n, _w) in ROLES.items()}


def _start_minute(rng, weekend):
    if weekend:
        return rng.uniform(10 * 60, 20 * 60)
    r = rng.random()
    if r < 0.45:
        m = rng.gauss(11 * 60 + 15, 70)
    elif r < 0.90:
        m = rng.gauss(15 * 60 + 30, 80)
    else:
        m = rng.uniform(8 * 60, 21 * 60)
    return min(max(m, 7 * 60 + 30), 22 * 60 + 30)


def schedule(rng):
    """[(local datetime, user_id, role, session_id)] for the whole week, in time order."""
    roles = list(ROLES)
    weights = [ROLES[r][2] for r in roles]
    out = []
    for day, n in DAYS:
        d0 = datetime.fromisoformat(day).replace(tzinfo=IST)
        weekend = d0.weekday() >= 5
        reqs = []
        while len(reqs) < n:
            role = rng.choices(roles, weights)[0]
            user = rng.choice(USERS[role])
            size = rng.choices(*SESSION_SIZES)[0]
            t = d0 + timedelta(minutes=_start_minute(rng, weekend), seconds=rng.uniform(0, 60))
            sid = f"s-{rng.getrandbits(48):012x}"
            for _ in range(size):
                reqs.append((t, user, role, sid))
                t += timedelta(seconds=rng.uniform(20, 150))
        out.extend(reqs[:n])
    out.sort(key=lambda r: r[0])
    return out


def pick_question(rng, role):
    """(question, answer_fn_factory args): an intent phrasing, or for lawyers sometimes a pasted clause."""
    if role == "lawyer" and rng.random() < PASTED_SHARE_LAWYER:
        p = rng.choice(bank.PASTED)
        q = rng.choice(bank.PASTED_ASKS).format(source=p["source"], text=p["text"])
        return q, p["answer"], p["clause"], p["support"]
    weights = bank.ROLE_INTENT_WEIGHTS[role]
    name = rng.choices(list(weights), list(weights.values()))[0]
    it = bank.INTENTS[name]
    return rng.choice(it["phrasings"]), it["answer"], it["clause"], it["support"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="wipe logs/prod first")
    ap.add_argument("--log-dir", default=LOG_DIR)
    args = ap.parse_args()

    existing = glob.glob(os.path.join(args.log_dir, "traces-*.jsonl"))
    if existing and not args.force:
        sys.exit(f"{len(existing)} log files already in {args.log_dir}; a drill plant may be in them. "
                 f"Re-run with --force to wipe and regenerate.")
    for path in existing:
        os.remove(path)

    rng = random.Random(SEED)
    config = load_config()
    plan = schedule(rng)
    print(f"{len(plan)} requests scheduled; building the index (real retrieval for every request) ...")
    pipe = Pipeline(llm="synthetic", log_dir=args.log_dir)
    pipe.warm()

    t0 = time.time()
    counts = Counter()
    for i, (t_local, user, role, sid) in enumerate(plan, 1):
        question, answer, clause, support = pick_question(rng, role)
        pv = route(config, user, at_local=t_local)
        cites = prompts.get(pv)["cites"]
        style = rng.randrange(3)

        def answer_fn(context_docs, _pv, _sources, answer=answer, clause=clause, support=support, cites=cites,
                      style=style):
            return bank.render(answer, clause, cites, bank.supported(support, context_docs), style)

        rec = pipe.ask(question, user_id=user, user_role=role, session_id=sid, prompt_version=pv, now=t_local,
                       answer_fn=answer_fn, rng=rng)["trace"]
        counts[(rec["ts_local"][:10], rec["prompt_version"])] += 1
        if i % 250 == 0:
            print(f"  {i}/{len(plan)}  ({time.time() - t0:.0f}s)")

    print(f"done in {time.time() - t0:.0f}s -> {args.log_dir}")
    for (day, pv), n in sorted(counts.items()):
        print(f"  {day}  {pv:<10} {n}")


if __name__ == "__main__":
    main()
