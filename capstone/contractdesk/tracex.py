"""
One trace id from question in to answer out, across the agent hop and the MCP hop.

Built on Week 11's tracing.py (Trace, JsonlSink, stage_totals, prices), unchanged. What is new is the hop:

  agent process                                   MCP server process
  -------------                                   ------------------
  Trace(trace_id)                                 ServerCall reads the id from the request's _meta
   |- agent.step                                   `contractdesk/trace` = {trace_id, parent_span_id}
   |   |- llm.call            (tokens, $)          builds its own spans under parent_span_id
   |   '- mcp.<tool>          (client latency) --> returns them, plus the id it saw, in the RESULT's _meta
   |        |- server.<tool>  <-- nested from the result        (and appends them to logs/servers/*.jsonl)
   |        |    '- retrieval.embed_query / vector_search / rerank
   |        '- mcp.transport  (client latency minus server latency: serialisation + pipe + process scheduling)

The agent checks the echoed id equals its own: that is the assertion `trace_id_survived`, on every tool call.
The server's own log holds the same trace id, so a request can be reconstructed from either side.

No prompt, answer or clause text goes into a server log line: only tool name, argument NAMES, counterparty slug,
sizes and spans (the privilege line; see ARCHITECTURE.md).
"""

import os
import time
from datetime import datetime, timedelta, timezone

from tracing import JsonlSink, Trace, stage_totals  # noqa: F401  (Week 11, unchanged)

from . import paths

META_KEY = "contractdesk/trace"
IST = timezone(timedelta(hours=5, minutes=30), "IST")
SERVER_LOG_DIR = os.path.join(paths.LOGS, "servers")
REQUEST_LOG_DIR = os.path.join(paths.LOGS, "requests")
EVAL_LOG_DIR = os.path.join(paths.LOGS, "eval")


def now_record_times():
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z"), now.astimezone(IST).isoformat(timespec="milliseconds")


def request_meta(trace_id, parent_span_id, variant):
    return {META_KEY: {"trace_id": trace_id, "parent_span_id": parent_span_id, "variant": variant}}


class ServerCall:
    """Spans for ONE tool call inside an MCP server. Use as: `with call.handler(): ...; return call.finish(text)`."""

    def __init__(self, server, tool, ctx, arguments, profile=None, variant=None, log_dir=None):
        meta = ctx.request_context.meta if ctx is not None else None
        info = (meta.model_dump().get(META_KEY) if meta is not None else None) or {}
        self.incoming_trace_id = info.get("trace_id")
        self.trace = Trace(trace_id=self.incoming_trace_id)
        if info.get("parent_span_id"):
            self.trace.root_id = info["parent_span_id"]      # our top span hangs under the caller's span
        self.server, self.tool, self.profile, self.variant = server, tool, profile, variant
        self.arg_names = sorted(arguments)
        self.counterparty = None
        self.sink = JsonlSink(log_dir or SERVER_LOG_DIR)
        self._t0 = time.perf_counter()
        self._cm = None

    def handler(self):
        self._cm = self.trace.span(f"server.{self.tool}", stage="tools", server=self.server, cost_usd=0.0)
        return self._cm

    def span(self, name, **attrs):
        return self.trace.span(name, stage="retrieval", cost_usd=0.0, **attrs)

    def finish(self, text, ok=True):
        from mcp.types import CallToolResult, TextContent

        spans = sorted(self.trace.spans, key=lambda s: s["start_ms"])
        ts, ts_local = now_record_times()
        self.sink.write(dict(
            schema="cap.server.1", ts=ts, ts_local=ts_local, trace_id=self.trace.trace_id,
            propagated=bool(self.incoming_trace_id), parent_span_id=self.trace.root_id, server=self.server,
            tool=self.tool, pid=os.getpid(), profile=self.profile, variant=self.variant, argument_names=self.arg_names,
            counterparty=self.counterparty, result_chars=len(text), ok=ok, spans=spans))
        return CallToolResult(
            content=[TextContent(type="text", text=text)], isError=not ok,
            _meta={META_KEY: {"trace_id": self.trace.trace_id, "propagated": bool(self.incoming_trace_id),
                              "server": self.server, "spans": spans}})


def extract_server_meta(result):
    """The META_KEY block from a CallToolResult (client side), or None."""
    meta = getattr(result, "meta", None) or {}
    return meta.get(META_KEY)
