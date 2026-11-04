"""
Model backends for the agent: `llm.call(prompt) -> LLMResult`.

  GroqLLM  Week 11's GroqBackend (429 retry, API-reported usage) on openai/gpt-oss-120b, the Weeks 7-11 agent model.
           Not exercised live here: there was no GROQ_API_KEY.
  StubLLM  contractdesk/stub_model.py - deterministic rules, NOT a language model. Input tokens are tiktoken counts
           of the real prompt; output tokens and latency are MODELLED (ASSUMED_REASONING_TOKENS), and every result
           carries `usage_source` so a trace says which numbers were measured.
"""

import os
import time
from dataclasses import dataclass

from tracing import cost_usd, estimate_tokens, modelled_latency_ms  # Week 11, unchanged

# gpt-oss-120b is a reasoning model and Groq bills its reasoning tokens. The stub cannot know how many; this is an
# ASSUMPTION used only to model cost and latency in stub mode.
ASSUMED_REASONING_TOKENS = 250


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    usage_source: str
    latency_ms: float
    cost_usd: float


class StubLLM:
    mode = "stub"

    def __init__(self, model):
        self.model = model

    def call(self, prompt):
        from . import stub_model
        t0 = time.perf_counter()
        text = stub_model.decide(prompt)
        local_ms = (time.perf_counter() - t0) * 1000
        n_in, n_out = estimate_tokens(prompt), estimate_tokens(text) + ASSUMED_REASONING_TOKENS
        return LLMResult(text, n_in, n_out, "estimate (tiktoken + assumed reasoning)",
                         round(local_ms + modelled_latency_ms(self.model, n_out), 1), cost_usd(self.model, n_in, n_out))


class GroqLLM:
    mode = "groq"

    def __init__(self, api_key, model):
        from observability.pipeline import GroqBackend
        self.model = model
        self._b = GroqBackend(api_key, model=model)

    def call(self, prompt):
        t0 = time.perf_counter()
        text, usage, waited = self._b.invoke(prompt)
        wall = (time.perf_counter() - t0 - waited) * 1000
        if usage:
            n_in, n_out, src = usage["input_tokens"], usage["output_tokens"], "api"
        else:
            n_in, n_out, src = estimate_tokens(prompt), estimate_tokens(text), "estimate"
        return LLMResult(text, n_in, n_out, src, round(wall, 1), cost_usd(self.model, n_in, n_out))


def make_llm(kind, model):
    key = os.getenv("GROQ_API_KEY", "")
    if kind == "auto":
        kind = "groq" if key else "stub"
    if kind == "groq":
        if not key:
            raise SystemExit("--llm groq needs GROQ_API_KEY (in .env or the environment)")
        return GroqLLM(key, model)
    return StubLLM(model)
