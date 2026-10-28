"""
At 10x today's query volume, what breaks first - cost, latency, or a rate limit? Computed from the logs.

    python observability/tenx.py --out observability/deliverables/tenx.md

"Today" = the busiest day in the production logs (conservative). For each candidate it takes today's value
from the logs, multiplies by 10, and divides the limit by today's value: that quotient is the multiple of
today's volume at which it breaks. The smallest quotient is what breaks first.

  rate limits  Groq's published limits for openai/gpt-oss-20b (RPM, RPD, TPM, TPD) - see LIMITS
  latency      retrieval runs on the app's own CPU, one request at a time: it saturates when
               peak requests/second x retrieval seconds per request reaches 1
  cost         has no hard ceiling - it is reported in $/day and $/month, against no budget

Token counts in synthetic traces are estimates that leave out gpt-oss reasoning tokens, so real tokens per
request are higher and token limits break sooner than printed. When a real-model suite run exists
(logs/eval/<label>, llm_mode=groq) its measured tokens per request are used instead, and the output says so.
"""

import argparse
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tracing  # noqa: E402
from cost_report import before_after, eval_runs  # noqa: E402
from logq import LOG_DIRS  # noqa: E402
from pipeline import MODEL, load_config  # noqa: E402
from tracing import read_logs, stage_totals  # noqa: E402

LIMITS = {"RPM": 30, "RPD": 1_000, "TPM": 8_000, "TPD": 200_000}
LIMITS_SOURCE = ("https://console.groq.com/docs/rate-limits (checked 2026-10-28): openai/gpt-oss-20b "
                 "30 RPM, 1K RPD, 8K TPM, 200K TPD. The page does not name the plan; these are the base-org "
                 "limits a free key gets (app.py's sidebar asks for a free key). Check your org's limits page.")
MULT = 10


def peak_window(times, values, seconds=60):
    """Max sum of `values` over any rolling window of `seconds` (times sorted)."""
    best, j, run = 0, 0, 0
    for i, t in enumerate(times):
        run += values[i]
        while times[j] <= t - timedelta(seconds=seconds):
            run -= values[j]
            j += 1
        best = max(best, run)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    a = ap.parse_args()

    records = [r for r in read_logs(LOG_DIRS["prod"]) if r["status"] == "ok"]
    by_day = Counter(r["ts_local"][:10] for r in records)
    day, n_day = by_day.most_common(1)[0]
    rs = [r for r in records if r["ts_local"].startswith(day)]
    times = [datetime.fromisoformat(r["ts_local"]) for r in rs]

    real = [r for runs in eval_runs().values() for r in runs if r["llm_mode"] == "groq"]
    if real:
        tok_per_req = statistics.fmean(r["totals"]["input_tokens"] + r["totals"]["output_tokens"] for r in real)
        tok_source = f"measured: mean of {len(real)} real {MODEL} calls in the suite runs (API-reported, reasoning included)"
        tokens = [tok_per_req] * len(rs)
    else:
        tokens = [r["totals"]["input_tokens"] + r["totals"]["output_tokens"] for r in rs]
        tok_per_req = statistics.fmean(tokens)
        tok_source = "ESTIMATED: tiktoken counts in the synthetic logs; excludes reasoning tokens, so a lower bound"

    peak_req_min = peak_window(times, [1] * len(rs))
    peak_tok_min = peak_window(times, tokens)
    tok_day = sum(tokens)
    cost_day = sum(r["totals"]["cost_usd"] for r in rs)
    if real:
        cost_day = statistics.fmean(r["totals"]["cost_usd"] for r in real) * n_day
    retr_s = statistics.fmean(stage_totals(r["spans"])["retrieval"]["latency_ms"] for r in rs) / 1000
    peak_rps = peak_req_min / 60
    cpu_util = peak_rps * retr_s

    rows = [
        ("rate limit: TPD (tokens/day)", tok_day, LIMITS["TPD"]),
        ("rate limit: RPD (requests/day)", n_day, LIMITS["RPD"]),
        ("rate limit: TPM (tokens in the peak minute)", peak_tok_min, LIMITS["TPM"]),
        ("rate limit: RPM (requests in the peak minute)", peak_req_min, LIMITS["RPM"]),
        ("latency: retrieval CPU busy share at the peak minute", cpu_util, 1.0),
    ]
    breaks = sorted(((lim / val if val else float("inf")), name, val, lim) for name, val, lim in rows)
    first = breaks[0]

    # when, on the busiest day at 10x, would the daily token quota run out?
    cum, exhausted_at, after = 0.0, None, 0
    for t, tok in zip(times, tokens):
        cum += tok * MULT
        if exhausted_at is None and cum > LIMITS["TPD"]:
            exhausted_at = t
        if exhausted_at is not None:
            after += 1
    minutes_over_tpm = sum(1 for t in sorted({t.replace(second=0, microsecond=0) for t in times})
                           if sum(tok for tt, tok in zip(times, tokens)
                                  if t <= tt < t + timedelta(minutes=1)) * MULT > LIMITS["TPM"])

    L = []
    w = L.append
    w("# 10x - what breaks first\n")
    if first[0] <= MULT:
        headline = (f"**At 10x, the Groq daily token limit breaks first: 10x of {day} is "
                    f"{tok_day * MULT:,.0f} tokens/day against {LIMITS['TPD']:,} TPD - it breaks at "
                    f"{first[0]:.1f}x today's volume, long before cost (${cost_day * MULT:.2f}/day at 10x) or "
                    f"latency (retrieval CPU {cpu_util * MULT:.0%} busy at the 10x peak minute) matter.**"
                    if first[1].startswith("rate limit: TPD") else
                    f"**At 10x, {first[1]} breaks first: {first[2] * MULT:,.0f} vs a limit of {first[3]:,} - it "
                    f"breaks at {first[0]:.1f}x today's volume.**")
    else:
        headline = f"**Nothing in the table breaks at 10x; the first limit is {first[1]} at {first[0]:.1f}x.**"
    w(headline + "\n")
    if exhausted_at:
        w(f"On the {day} timeline replayed at 10x, the 200,000-token day is used up at "
          f"**{exhausted_at:%H:%M} IST**; every request after that - {after * MULT:,} of {n_day * MULT:,} "
          f"({after / n_day:.0%}) - would get a 429 until the quota resets. {minutes_over_tpm} of that day's "
          f"active minutes would also exceed 8,000 TPM at 10x.\n")

    w(f"## Today = {day} (busiest day in the logs: {n_day} requests)\n")
    w("| candidate | today | at 10x | limit | breaks at |")
    w("|---|---|---|---|---|")
    for mult, name, val, lim in breaks:
        fmt = (lambda v: f"{v:.1%}") if name.startswith("latency") else (lambda v: f"{v:,.0f}")
        w(f"| {name} | {fmt(val)} | {fmt(val * MULT)} | {fmt(lim)} | **{mult:.1f}x** |")
    w(f"| cost (no hard limit) | ${cost_day:.4f}/day | ${cost_day * MULT:.3f}/day (${cost_day * MULT * 30:.2f}/month) | "
      f"none set | - |\n")

    w("## Inputs\n")
    w(f"- Tokens per request: {tok_per_req:.0f} ({tok_source}).")
    w(f"- Peak minute (rolling 60 s) on {day}: {peak_req_min} requests, {peak_tok_min:,.0f} tokens.")
    w(f"- Retrieval: {retr_s * 1000:.0f} ms of CPU per request on average (measured spans); the peak minute is "
      f"{peak_rps:.2f} req/s, so retrieval is {cpu_util:.1%} busy today and {cpu_util * MULT:.1%} at 10x.")
    w(f"- Limits: {LIMITS_SOURCE}")
    if records and all(r["llm_mode"] == "synthetic" for r in records):
        w("- Volume: the production logs are the synthetic week (traffic.py) - the app has no real users yet. "
          "Re-run this script on real logs; every number above is recomputed from them.")
    # what shipping the fix does to the binding limit: like-for-like input tokens from the suite runs
    runs = eval_runs()
    pair = before_after(runs)
    if pair:
        before, after = runs[pair[0]], runs[pair[1]]
        d_in = (statistics.fmean(r["totals"]["input_tokens"] for r in after)
                - statistics.fmean(r["totals"]["input_tokens"] for r in before))
        tok_v3 = tok_per_req + d_in
        w(f"- After the fix ships (`{after[0]['prompt_version']}`): the suite ({pair[0]} -> {pair[1]}) measured {d_in:+.0f} input "
          f"tokens per request on the same questions, so about {tok_v3:.0f} tokens per request, and TPD breaks at "
          f"**{LIMITS['TPD'] / (n_day * tok_v3):.1f}x** instead of {LIMITS['TPD'] / (n_day * tok_per_req):.1f}x. "
          f"The citation fix spends quota, which is the scarce thing.")
    import prompts
    stable = prompts.get(load_config()["stable"])
    prefix = tracing.estimate_tokens(stable["template"].split("{context}")[0])
    w("\n## The plan this implies\n")
    w(f"1. Quota first, because that's what breaks: move off the free key before traffic grows (a paid tier lifts "
      f"TPD/RPD), and keep the free key for development only.")
    w(f"2. Count fewer tokens per request. Groq lists a cached-input price for {MODEL} and says cached tokens don't "
      f"count toward rate limits. The serving prompt's static prefix (everything before the context) is "
      f"{prefix} tokens of the ~{tok_per_req:.0f} per request, so prefix caching alone buys about "
      f"{prefix / tok_per_req:.0%}. The rest is retrieved context: trimming it trades directly against the "
      f"citation fix above.")
    w("3. Cost isn't the constraint at 10x and won't be soon. Latency isn't either: retrieval CPU has about "
      f"{1 / (cpu_util * MULT):.0f}x headroom even at 10x.")
    w("4. Before caching whole answers, measure how often real questions repeat. The synthetic week repeats "
      "phrasings by construction, so it can't answer that.")

    text = "\n".join(L) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {a.out}")
    print(text)


if __name__ == "__main__":
    main()
