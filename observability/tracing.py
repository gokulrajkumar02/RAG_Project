"""
Per-request traces: one JSON line per request, holding every span with its own latency, tokens and cost.

The shape follows OpenTelemetry (32-hex trace_id, 16-hex span_id, parent span, start offset + duration,
attributes named after the OTel GenAI conventions: gen_ai.request.model, gen_ai.usage.input_tokens,
gen_ai.usage.output_tokens), so the same records can be shipped to Phoenix, LangSmith or an OTLP collector
later without renaming a field. Kept dependency-free on purpose: a JSONL file per day is something you can
grep at 3am when the dashboard is down.

Each span carries `stage` (retrieval | generation | tools), so cost and latency can be attributed per stage
before anyone optimises anything.
"""

import json
import os
import random
import secrets
import time
from contextlib import contextmanager

# USD per 1M tokens (input, output). Cached-input discounts are ignored, so cost is an upper bound.
PRICES_PER_M = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
}
PRICE_SOURCE = {
    "openai/gpt-oss-20b": "https://console.groq.com/docs/model/openai/gpt-oss-20b (checked 2026-10-28)",
    "openai/gpt-oss-120b": "https://console.groq.com/docs/model/openai/gpt-oss-120b (checked 2026-10-21)",
}
# Published output speed, used ONLY to model a generation latency for traces where no model call was made.
THROUGHPUT_TPS = {"openai/gpt-oss-20b": 1000, "openai/gpt-oss-120b": 500}

_enc = None


def estimate_tokens(text):
    """tiktoken o200k_base (gpt-oss's tokenizer family) when it loads, else chars/4."""
    global _enc
    if _enc is None:
        try:
            import tiktoken
            _enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            _enc = False
    return len(_enc.encode(text)) if _enc else max(1, len(text) // 4)


def cost_usd(model, input_tokens, output_tokens):
    price_in, price_out = PRICES_PER_M[model]
    return round(input_tokens * price_in / 1e6 + output_tokens * price_out / 1e6, 10)


def modelled_latency_ms(model, output_tokens):
    return round(output_tokens / THROUGHPUT_TPS[model] * 1000, 1)


def new_id(nbytes, rng=None):
    return f"{rng.getrandbits(nbytes * 8):0{nbytes * 2}x}" if rng else secrets.token_hex(nbytes)


class Trace:
    """Collects spans for one request. `span()` times a block; `add_span()` records one whose duration
    was not measured here (a modelled generation in a synthetic trace)."""

    def __init__(self, trace_id=None, rng=None):
        self.rng = rng or random.Random()
        self.trace_id = trace_id or new_id(16, rng)
        self.root_id = new_id(8, self.rng)
        self.spans = []
        self._t0 = time.perf_counter()
        self._stack = []

    def _now_ms(self):
        return (time.perf_counter() - self._t0) * 1000

    @contextmanager
    def span(self, name, stage, **attributes):
        sp = {
            "span_id": new_id(8, self.rng),
            "parent_id": self._stack[-1]["span_id"] if self._stack else self.root_id,
            "name": name,
            "stage": stage,
            "start_ms": round(self._now_ms(), 3),
            "latency_ms": None,
            "attributes": dict(attributes),
        }
        self._stack.append(sp)
        t = time.perf_counter()
        try:
            yield sp
        finally:
            sp["latency_ms"] = round((time.perf_counter() - t) * 1000, 3)
            self._stack.pop()
            self.spans.append(sp)

    def add_span(self, name, stage, start_ms, latency_ms, **attributes):
        sp = {
            "span_id": new_id(8, self.rng),
            "parent_id": self.root_id,
            "name": name,
            "stage": stage,
            "start_ms": round(start_ms, 3),
            "latency_ms": round(latency_ms, 3),
            "attributes": dict(attributes),
        }
        self.spans.append(sp)
        return sp

    def end_ms(self):
        return max((s["start_ms"] + s["latency_ms"] for s in self.spans), default=0.0)

    def finish(self, measured_wall_ms=None):
        """Root span + span list sorted by start. Leaf spans are the ones that carry cost.
        measured_wall_ms=None means a span was modelled, not run: the request then ends at its last span,
        so local bookkeeping (e.g. loading a tokenizer) never leaks into a trace as latency."""
        wall = measured_wall_ms if measured_wall_ms is not None else 0.0
        root = {
            "span_id": self.root_id, "parent_id": None, "name": "request", "stage": "request",
            "start_ms": 0.0, "latency_ms": round(max(wall, self.end_ms()), 3), "attributes": {},
        }
        return [root] + sorted(self.spans, key=lambda s: (s["start_ms"], s["name"]))


def leaf_spans(spans):
    parents = {s["parent_id"] for s in spans}
    return [s for s in spans if s["span_id"] not in parents]


def stage_totals(spans):
    """{stage: {latency_ms, input_tokens, output_tokens, cost_usd, spans}} over leaf spans, always
    listing retrieval, generation and tools (a stage with no spans is reported as zero, not omitted)."""
    out = {st: {"latency_ms": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "spans": 0}
           for st in ("retrieval", "generation", "tools")}
    for s in leaf_spans(spans):
        if s["stage"] not in out:
            continue
        a = s["attributes"]
        t = out[s["stage"]]
        t["latency_ms"] = round(t["latency_ms"] + (s["latency_ms"] or 0.0), 3)
        t["input_tokens"] += a.get("gen_ai.usage.input_tokens", 0)
        t["output_tokens"] += a.get("gen_ai.usage.output_tokens", 0)
        t["cost_usd"] = round(t["cost_usd"] + a.get("cost_usd", 0.0), 10)
        t["spans"] += 1
    return out


class JsonlSink:
    """traces-<IST date>.jsonl, one compact JSON object per line, in time order."""

    def __init__(self, log_dir):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def path_for(self, record):
        return os.path.join(self.log_dir, f"traces-{record['ts_local'][:10]}.jsonl")

    @staticmethod
    def dumps(record):
        return json.dumps(record, ensure_ascii=False, separators=(",", ":"))

    def write(self, record):
        with open(self.path_for(record), "a", encoding="utf-8") as f:
            f.write(self.dumps(record) + "\n")

    def insert_sorted(self, record):
        """Insert at its time position (a trace written after the fact, e.g. a drill plant)."""
        path = self.path_for(record)
        lines = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        pos = len(lines)
        for i, ln in enumerate(lines):
            if json.loads(ln)["ts"] > record["ts"]:
                pos = i
                break
        lines.insert(pos, self.dumps(record))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path, pos


def read_logs(log_dir):
    records = []
    if not os.path.isdir(log_dir):
        return records
    for name in sorted(os.listdir(log_dir)):
        if name.startswith("traces-") and name.endswith(".jsonl"):
            with open(os.path.join(log_dir, name), encoding="utf-8") as f:
                records.extend(json.loads(ln) for ln in f if ln.strip())
    records.sort(key=lambda r: r["ts"])
    return records
