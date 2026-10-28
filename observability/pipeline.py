"""
The Week 11 request path, observable: the app's unchanged retrieval + generation (rag_core.py), with every
request written down as ONE trace line that can be found again from a vague complaint.

    request
     |- retrieval                       stage=retrieval   (local CPU: $0 on any bill)
     |   |- retrieval.embed_query       all-MiniLM-L6-v2
     |   |- retrieval.vector_search     FAISS top-10
     |   |- retrieval.rerank            cross-encoder -> top-3 (the sources the UI shows)
     |   '- retrieval.expand_neighbors  Week 6 neighbour stitch -> what the model reads
     '- generation.llm                  stage=generation  (Groq; tokens x list price)
    tools: the served app makes no tool calls; the stage is reported as 0, not left out.

One trace line (schema w11.1) holds: who and when (trace_id, ts in UTC and IST, user_id, user_role,
session_id); what was asked and answered (question, input_type, answer, status); what answered it (model,
prompt_version, prompt_sha, context_format, llm_mode); what it read (source and context chunk ids, rerank
scores, a sha of each context chunk so the ids stay meaningful after a re-ingest); what it cost (each span's
latency, tokens and USD, totals, and cost by stage).
Schema w11.2 (after drill #1) adds an index on the output: answer_cited_clauses, context_clause_ids,
citation_support, citation_mismatch (index_fields.py).

llm_mode, recorded on every trace:
  groq       a real call to openai/gpt-oss-20b; tokens are what the API reports
  stub       offline stand-in (stub_llm.py) when there is no key; NOT a model
  synthetic  no model call: the answer is supplied (traffic.py's answer bank, or a drill plant); tokens are
             tiktoken estimates of the real prompt + that answer, generation latency is modelled from Groq's
             published speed. Used only to build the drill's haystack.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (REPO_ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import index_fields  # noqa: E402
import prompts  # noqa: E402
import tracing  # noqa: E402
from clauses import ClauseMap  # noqa: E402
from rag_core import RERANKER_MODEL, ContractIndex, load_pdf_chunks  # noqa: E402

PDF_PATH = os.path.join(REPO_ROOT, "data", "sample_contract.pdf")
LOG_DIR = os.path.join(HERE, "logs", "prod")
EVAL_LOG_DIR = os.path.join(HERE, "logs", "eval")
CONFIG_PATH = os.path.join(HERE, "config.json")

MODEL = "openai/gpt-oss-20b"   # rag_core.generate_answer's default: the model the app serves
K, POOL = 3, 10                 # what app.py has used since Week 6
APP_VERSION = "w11"
LOG_SCHEMA = index_fields.SCHEMA   # w11.1 + the output index (index_fields.py), added after drill #1
IST = timezone(timedelta(hours=5, minutes=30), "IST")
MAX_429_RETRIES = 6

# ---------------------------------------------------------------------------------------------------
# input type: a cheap rule tagger on the QUESTION, so traffic can be sliced by what was asked.
# First match wins; order matters ("fired for leaking data" is termination, not confidentiality).
# ---------------------------------------------------------------------------------------------------
PASTED_CHARS = 400
INPUT_TYPES = [
    ("non_compete", r"compet|rival|freelanc|non-solicit"),
    ("termination", r"terminat|\bfir(e|ed|ing)\b|dismiss|let (him|her|them|someone|me|an employee) go|\bsack|"
                    r"notice|resign|\bquit|lieu|misconduct|severance|\bend (the|this|my) (contract|agreement|employment)|"
                    r"on the spot|without cause|for cause"),
    ("confidentiality", r"confidential|secret|leak|disclos|\bnda\b"),
    ("ip", r"intellectual|invent|\bip\b|\bowns?\b|ownership of|assign"),
    ("compensation", r"salary|\bpay|paid|bonus|compensat|overtime|rupees|wage"),
    ("hours", r"hours|working time|what time|at work|schedule|lunch|9:00|6:00"),
    ("leave", r"leave|vacation|holiday|sick|time off|maternity|paternity|probation"),
    ("governing_law", r"\blaw\b|court|jurisdiction|dispute|governed"),
    ("parties_dates", r"part(y|ies)|signed|sign |start|begin|effective|commence|position|title|role|report|manager|end date|fixed[- ]term"),
]


def classify_input(question):
    if len(question) > PASTED_CHARS:
        return "pasted_clause"
    q = question.lower()
    for name, pattern in INPUT_TYPES:
        if re.search(pattern, q):
            return name
    return "other"


# ---------------------------------------------------------------------------------------------------
# prompt routing: config.json says which version is stable and which (if any) is on canary. A user is
# always in the same bucket, so a canary user does not flip between versions mid-conversation.
# ---------------------------------------------------------------------------------------------------
def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bucket(user_id):
    return int(hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:8], 16) % 100


def route(config, user_id, at_local=None):
    """Prompt version for this user: from the current config, or as it was at `at_local` (history)."""
    entry = config
    if at_local is not None:
        stamp = at_local.strftime("%Y-%m-%dT%H:%M")
        past = [h for h in config["history"] if h["from_local"] <= stamp]
        entry = past[-1] if past else config["history"][0]
    canary = entry.get("canary")
    if canary and bucket(user_id) < canary["percent"]:
        return canary["version"]
    return entry["stable"]


# ---------------------------------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------------------------------
def _is_rate_limit(exc):
    return exc.__class__.__name__ == "RateLimitError" or getattr(exc, "status_code", None) == 429


def _retry_after(exc):
    try:
        return float(exc.response.headers.get("retry-after"))
    except Exception:
        return None


class GroqBackend:
    mode = "groq"

    def __init__(self, api_key, model=MODEL):
        from langchain_groq import ChatGroq
        self._llm = ChatGroq(groq_api_key=api_key, model_name=model, temperature=0, max_retries=0)

    def invoke(self, prompt, hints=None):
        waited = 0.0
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                msg = self._llm.invoke(prompt)
                break
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == MAX_429_RETRIES:
                    raise
                pause = _retry_after(exc)
                pause = pause if pause is not None else min(2 ** attempt * 2, 30)
                time.sleep(pause)
                waited += pause
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            usage = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                     "reasoning_tokens": (usage.get("output_token_details") or {}).get("reasoning")}
        else:
            raw = (getattr(msg, "response_metadata", None) or {}).get("token_usage") or {}
            if raw.get("prompt_tokens") is not None:
                usage = {"input_tokens": raw["prompt_tokens"], "output_tokens": raw.get("completion_tokens", 0),
                         "reasoning_tokens": None}
        return str(msg.content), usage, waited


def make_backend(llm, api_key=None):
    api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
    if llm == "auto":
        llm = "groq" if api_key else "stub"
    if llm == "groq":
        if not api_key:
            raise SystemExit("--llm groq needs GROQ_API_KEY (in .env or the environment)")
        return GroqBackend(api_key)
    if llm == "stub":
        from stub_llm import StubBackend
        return StubBackend()
    if llm == "synthetic":
        return None
    raise ValueError(f"unknown llm mode {llm!r}")


def contract_id_for(pdf_path):
    with open(pdf_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:8]
    return f"{os.path.splitext(os.path.basename(pdf_path))[0]}@{digest}"


def iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------------------------------
class Pipeline:
    def __init__(self, llm="auto", pdf_path=PDF_PATH, index=None, contract_id=None, log_dir=LOG_DIR,
                 config_path=CONFIG_PATH, api_key=None):
        if index is None:
            index = ContractIndex(load_pdf_chunks(pdf_path))
            contract_id = contract_id or contract_id_for(pdf_path)
        self.index = index
        self.chunks = index.chunks
        self.clause_map = ClauseMap(self.chunks)
        self.contract_id = contract_id or "uploaded"
        self.chunk_sha = [hashlib.sha256(c.page_content.encode("utf-8")).hexdigest()[:10] for c in self.chunks]
        self.backend = make_backend(llm, api_key)
        self.llm_mode = self.backend.mode if self.backend else "synthetic"
        self.sink = tracing.JsonlSink(log_dir) if log_dir else None
        self.config_path = config_path

    def warm(self):
        """Load the reranker and tokenizer and run one throwaway retrieval, so no logged span pays a cold start."""
        _ = self.index.reranker
        tracing.estimate_tokens("warm-up")
        self._retrieve("warm-up question about notice", tracing.Trace())

    def _retrieve(self, question, tr, context_format="plain"):
        with tr.span("retrieval", stage="retrieval"):
            with tr.span("retrieval.embed_query", stage="retrieval", model="all-MiniLM-L6-v2", cost_usd=0.0):
                qvec = self.index.embeddings.embed_query(question)
            with tr.span("retrieval.vector_search", stage="retrieval", k=POOL, cost_usd=0.0):
                candidates = self.index.vector_store.similarity_search_by_vector(qvec, k=POOL)
            with tr.span("retrieval.rerank", stage="retrieval", model=RERANKER_MODEL, pairs=len(candidates),
                         cost_usd=0.0):
                scores = self.index.reranker.predict([(question, d.page_content) for d in candidates])
                ranked = sorted(zip(candidates, scores), key=lambda p: p[1], reverse=True)[:K]
            with tr.span("retrieval.expand_neighbors", stage="retrieval", cost_usd=0.0):
                sources = [d for d, _s in ranked]
                context_docs = self.index.expand_with_neighbors(sources)
            if context_format == "clause":   # answer-v3: serve every touched clause whole (clauses.py)
                with tr.span("retrieval.expand_clauses", stage="retrieval", cost_usd=0.0):
                    ids, _order = self.clause_map.expand_to_clauses([d.metadata["chunk_idx"] for d in context_docs])
                    context_docs = [self.chunks[i] for i in ids]
        return sources, [round(float(s), 4) for _d, s in ranked], context_docs

    def ask(self, question, *, user_id="anonymous", user_role="unknown", session_id=None, prompt_version=None,
            now=None, answer_fn=None, trace_id=None, rng=None, write=True, sink=None):
        """Answer one question and log it. Returns {"answer", "sources", "trace"}.
        A failed model call is still logged (status="error") before the exception is re-raised."""
        now = now or datetime.now(timezone.utc)
        if prompt_version is None:
            prompt_version = route(load_config(self.config_path), user_id)
        spec = prompts.get(prompt_version)
        tr = tracing.Trace(trace_id, rng)
        wall0 = time.perf_counter()

        sources, scores, context_docs = self._retrieve(question, tr, spec["context_format"])
        context = prompts.render_context(context_docs, spec["context_format"], self.clause_map)
        prompt = spec["template"].format(context=context, question=question)

        status, error, answer, measured = "ok", None, None, True
        try:
            if self.llm_mode == "synthetic":
                answer = answer_fn(context_docs, prompt_version, sources)
                p, c = tracing.estimate_tokens(prompt), tracing.estimate_tokens(answer)
                tr.add_span("generation.llm", "generation", tr.end_ms(), tracing.modelled_latency_ms(MODEL, c), **{
                    "gen_ai.request.model": MODEL, "gen_ai.usage.input_tokens": p, "gen_ai.usage.output_tokens": c,
                    "cost_usd": tracing.cost_usd(MODEL, p, c), "usage_source": "estimate",
                    "latency_source": f"modelled: output_tokens / {tracing.THROUGHPUT_TPS[MODEL]} tok/s (no model call)",
                })
                measured = False
            else:
                hints = {"cites": spec["cites"], "context_format": spec["context_format"],
                         "relevance": lambda texts, q=question: [float(s) for s in self.index.reranker.predict(
                             [(q, t) for t in texts])]}
                with tr.span("generation.llm", stage="generation", **{"gen_ai.request.model": MODEL}) as sp:
                    answer, usage, waited = self.backend.invoke(prompt, hints)
                if usage:
                    p, c, source = usage["input_tokens"], usage["output_tokens"], "api"
                else:
                    p, c, source = tracing.estimate_tokens(prompt), tracing.estimate_tokens(answer), "estimate"
                sp["attributes"].update({
                    "gen_ai.usage.input_tokens": p, "gen_ai.usage.output_tokens": c,
                    "cost_usd": tracing.cost_usd(MODEL, p, c), "usage_source": source,
                    "latency_source": "measured" if self.llm_mode == "groq" else "measured (stub: local string handling)",
                    "throttle_wait_ms": round(waited * 1000, 1),
                })
                if usage and usage.get("reasoning_tokens") is not None:
                    sp["attributes"]["gen_ai.usage.reasoning_tokens"] = usage["reasoning_tokens"]
        except Exception as exc:
            status, error = "error", f"{exc.__class__.__name__}: {str(exc)[:300]}"
            raise
        finally:
            spans = tr.finish((time.perf_counter() - wall0) * 1000 if measured else None)
            record = self._record(tr, spans, now, question, answer, status, error, user_id, user_role, session_id,
                                  spec, sources, scores, context_docs)
            if write:
                target = sink or self.sink
                if target:
                    target.write(record)
        return {"answer": answer, "sources": sources, "trace": record}

    def _record(self, tr, spans, now, question, answer, status, error, user_id, user_role, session_id, spec,
                sources, scores, context_docs):
        stages = tracing.stage_totals(spans)
        ctx_ids = [d.metadata["chunk_idx"] for d in context_docs]
        return {
            "schema": LOG_SCHEMA,
            "trace_id": tr.trace_id,
            "ts": iso_utc(now),
            "ts_local": now.astimezone(IST).isoformat(timespec="milliseconds"),
            "user_id": user_id,
            "user_role": user_role,
            "session_id": session_id,
            "contract_id": self.contract_id,
            "app_version": APP_VERSION,
            "model": MODEL,
            "llm_mode": self.llm_mode,
            "prompt_version": spec["version"],
            "prompt_sha": spec["sha"],
            "context_format": spec["context_format"],
            "input_type": classify_input(question),
            "question": question,
            "answer": answer,
            "status": status,
            "error": error,
            "retrieval": {
                "k": K, "pool": POOL, "reranker": RERANKER_MODEL,
                "source_chunk_ids": [d.metadata["chunk_idx"] for d in sources],
                "rerank_scores": scores,
                "context_chunk_ids": ctx_ids,
                "context_chunk_sha": {str(i): self.chunk_sha[i] for i in ctx_ids},
            },
            "spans": spans,
            "totals": {
                "latency_ms": spans[0]["latency_ms"],
                "input_tokens": sum(s["input_tokens"] for s in stages.values()),
                "output_tokens": sum(s["output_tokens"] for s in stages.values()),
                "cost_usd": round(sum(s["cost_usd"] for s in stages.values()), 10),
            },
            "cost_by_stage_usd": {k: v["cost_usd"] for k, v in stages.items()},
            "synthetic": self.llm_mode == "synthetic",
            **index_fields.derive(answer or "", ctx_ids, self.clause_map),
        }
