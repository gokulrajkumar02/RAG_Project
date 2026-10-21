"""
Metered LLM access for the Week 10 race: every model call by EITHER arm goes through here and is
recorded - who sent it (the hand-off), how many tokens in/out, how long, and how much of the prompt
was text already sent earlier in the same chain (the "context re-send").

Two backends behind one interface:
  GroqBackend  real. Token counts are what the API reports (usage_metadata), not an estimate.
  StubBackend  offline stand-in (stub_llm.py), used only when there is no GROQ_API_KEY. Its token
               counts are tiktoken/char estimates of the prompts this code really builds. Every
               artefact produced with it is stamped STUB.

The model is ONE constant for every role in both arms (AGENT_MODEL from agent/contract_agent.py,
openai/gpt-oss-120b). Week 7 raced two different models and had to caveat the cost column; here
the only variable is the pattern, so tokens and dollars move together.

Rate limits: ChatGroq's own retry is switched off (max_retries=0) and 429s are retried HERE, so the
seconds spent waiting for quota are measured and reported separately instead of silently inflating
a latency number.
"""

import os
import sys
import threading
import time
from dataclasses import dataclass, asdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agent"))

from contract_agent import AGENT_MODEL as MODEL  # noqa: E402  (the Week 7 single agent's model)

# Groq list price for openai/gpt-oss-120b, USD per 1M tokens. Cached-input discounts are ignored,
# so cost is an upper bound. Re-check before quoting: prices move.
PRICE_IN_PER_M = 0.15
PRICE_OUT_PER_M = 0.60
PRICE_SOURCE = "https://console.groq.com/docs/model/openai/gpt-oss-120b (checked 2026-10-21)"

MAX_429_RETRIES = 6

_enc = None


def estimate_tokens(text):
    """tiktoken o200k_base when it loads, else chars/4. Only used where the API reports nothing."""
    global _enc
    if _enc is None:
        try:
            import tiktoken
            _enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            _enc = False
    return len(_enc.encode(text)) if _enc else max(1, len(text) // 4)


def cost_usd(prompt_tokens, completion_tokens):
    return prompt_tokens * PRICE_IN_PER_M / 1e6 + completion_tokens * PRICE_OUT_PER_M / 1e6


@dataclass
class Call:
    case: str
    arm: str                # "single" | "multi" | "multi_fail"
    hand_off: str           # e.g. "manager -> clause_worker"
    call_no: int            # 1-based within (case, arm, hand_off): call 2+ re-sends call 1's context
    role: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float        # wall clock of the call, INCLUDING any 429 wait
    throttle_wait_s: float  # of which: seconds slept waiting for quota
    usage_source: str       # "api" | "estimate"
    resent_est: int         # tokens of this prompt that were byte-identical to the previous call's prefix
    prompt_chars: int
    t0: float = 0.0         # perf_counter at call start; only used to order the hand-off log

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens


class Meter:
    def __init__(self):
        self.calls = []
        self.events = []     # non-LLM hand-offs: one dict per HTTP attempt to a worker
        self._lock = threading.Lock()

    def add_call(self, call):
        with self._lock:
            self.calls.append(call)

    def add_event(self, **event):
        with self._lock:
            self.events.append(event)

    def calls_for(self, arm, case=None):
        return [c for c in self.calls if c.arm == arm and (case is None or c.case == case)]

    def events_for(self, arm, case=None):
        return [e for e in self.events if e["arm"] == arm and (case is None or e["case"] == case)]


class LLM:
    """backend.invoke(prompt, role) -> (text, usage|None, throttle_wait_s); this class does the bookkeeping."""

    def __init__(self, backend, meter):
        self.backend = backend
        self.meter = meter
        self.mode = backend.mode
        self._lock = threading.Lock()
        self._n = {}
        self._last = {}

    def __call__(self, prompt, *, role, hand_off, case, arm):
        key = (case, arm, hand_off)
        with self._lock:
            n = self._n[key] = self._n.get(key, 0) + 1
            prev = self._last.get(key)
            self._last[key] = prompt

        t0 = time.perf_counter()
        text, usage, waited = self.backend.invoke(prompt, role)
        latency = time.perf_counter() - t0

        if usage:
            p, c, source = usage["input_tokens"], usage["output_tokens"], "api"
        else:
            p, c, source = estimate_tokens(prompt), estimate_tokens(text), "estimate"

        resent = 0
        if prev:
            common = len(os.path.commonprefix([prev, prompt]))
            resent = round(p * common / max(1, len(prompt)))

        self.meter.add_call(Call(case, arm, hand_off, n, role, p, c, latency, waited, source, resent, len(prompt), t0))
        return text


def _is_rate_limit(exc):
    return exc.__class__.__name__ == "RateLimitError" or getattr(exc, "status_code", None) == 429


def _retry_after(exc):
    try:
        return float(exc.response.headers.get("retry-after"))
    except Exception:
        return None


class GroqBackend:
    mode = "groq"

    def __init__(self, api_key, model=MODEL, llm=None):
        if llm is None:
            from langchain_groq import ChatGroq
            llm = ChatGroq(groq_api_key=api_key, model_name=model, temperature=0, max_retries=0)
        self._llm = llm

    def invoke(self, prompt, role):
        waited = 0.0
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                msg = self._llm.invoke(prompt)
                break
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == MAX_429_RETRIES:
                    raise
                hinted = _retry_after(exc)
                pause = hinted if hinted is not None else min(2 ** attempt * 2, 30)
                time.sleep(pause)
                waited += pause

        usage = getattr(msg, "usage_metadata", None)
        if not usage:
            raw = (getattr(msg, "response_metadata", None) or {}).get("token_usage") or {}
            if raw.get("prompt_tokens") is not None:
                usage = {"input_tokens": raw["prompt_tokens"], "output_tokens": raw.get("completion_tokens", 0)}
        return str(msg.content), (dict(usage) if usage else None), waited


def meter_single_agent(llm, current):
    """
    Route the Week 7 single agent's model calls through the meter WITHOUT editing its file: swap
    contract_agent._call_llm (looked up as a module global on every call) for a metered one. The
    agent loop, prompt, tools, step budget and parsing stay exactly Week 7's.
    `current` is a dict the runner sets to {"case": id} before each run.
    """
    import contract_agent

    def metered(prompt, api_key, model=MODEL):
        return llm(prompt, role="single", hand_off="user -> single_agent", case=current["case"], arm="single")

    contract_agent._call_llm = metered
    return metered


def calls_as_rows(calls):
    return [asdict(c) for c in calls]
