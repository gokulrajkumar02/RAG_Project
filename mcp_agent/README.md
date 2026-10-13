# Week 9 — MCP: bolt on the contract-repository server without touching the agent

Task Set F. The agent discovers its tools over MCP (`tools/list`) instead of having them wired in;
adding a second server is an edit to `mcp_servers.json` and nothing else.

| Number that moved | Value | Where |
|---|---|---|
| Tools discovered, from `tools/list` | **3 -> 6** (`get_contract`, `get_effective_date`, `get_amendment_chain` are new) | [deliverables/tool_counts.md](deliverables/tool_counts.md) |
| Changed lines in the agent module | **0** (4 files, sha256 identical) | [deliverables/agent_diff.txt](deliverables/agent_diff.txt) |
| Lines changed to add server two | **+5 / -0**, one JSON file | [deliverables/config.diff](deliverables/config.diff) |
| Wire frames captured and hand-annotated | **7** (initialize, initialized, tools/list, tools/call, each side) | [deliverables/wire.json](deliverables/wire.json) |
| `get_clause("12.4")` error text | `Error 3` -> names the range 1-11 and the next tool to call | [deliverables/error_before_after.md](deliverables/error_before_after.md) |

## Read this first — what is real, what is a stand-in

1. **The Week 9 base app was not in the repository** (history stops at Week 8; no MCP code, no `mcp` package).
   I rebuilt it: `agent_core/` is the host + loop, `servers/clause_search_server.py` is "server one". If you have
   your original Week 9 agent elsewhere, re-prove the claim on it: add the same JSON entry to its config, then diff.
2. **Server two is a stand-in.** The knowledge team's server (URL, credentials, source) was not provided, so
   `third_party/contract_repo_server.py` imitates its documented surface over **synthetic** records. When the real
   one is reachable, replace its entry in `mcp_servers.json` (`command`/`args`, or `url`/`headers` for a remote one).
3. **No real model has run.** There was no `GROQ_API_KEY` where this was built. Every transcript produced offline is
   labelled **STUB** (`scripts/offline_llm.py`, a rule-based stand-in, not a language model). The MCP traffic in them is
   real — servers really spawn, `tools/call` really crosses MCP, server two's own stderr confirms receipt — but the
   choice of tool and the answer text are the stub's. In particular the before/after in `error_before_after.md` shows
   exactly what the model is *given* in each case (real); how a real model *reacts* needs the run below.

To finish item 3 (needs a key in `.env`):

```bash
python mcp_agent/scripts/error_demo.py --llm groq --runs 3   # rewrites error_before_after.md with the real model
python mcp_agent/scripts/demo_query.py --llm groq "Which amendments changed MSA-2021-0142?"   # rewrites query_trace.md
```

## Where the model call happens

Only in the host process — `agent_core/loop.py`, the `llm(prompt)` call. Not in the MCP client, not on the wire
(which carries tool names and arguments, never a prompt), not in either server — and the client advertises no
`sampling` capability, so a server could not ask the host to run one.

## Run it

```bash
pip install -r requirements.txt                    # Python 3.10+; mcp is pinned <2 (see requirements.txt)
python mcp_agent/scripts/selfcheck.py              # re-verifies every claim here; no API key needed
python mcp_agent/scripts/discover.py               # tool counts before -> after
python mcp_agent/scripts/prove_zero_diff.py        # agent_diff.txt + config.diff
python mcp_agent/scripts/capture_wire.py           # wire.json (real traffic via scripts/wiretap.py)
python mcp_agent/scripts/demo_query.py             # a query that calls a server-two tool; STUB unless GROQ_API_KEY is set
python mcp_agent/agent_core/run.py "question"      # the agent proper (real model only)
```

## Layout

```
mcp_agent/
├── agent_core/              THE AGENT MODULE — never names a tool or a server
│   ├── host.py                config -> connect -> initialize -> tools/list -> route tools/call (stdio + http)
│   ├── loop.py                the Week 7/8 JSON-action loop; the tool list in its prompt is rendered from tools/list
│   └── run.py                 CLI
├── mcp_servers.json         the only file that changes (now: clause-search + contract-repository)
├── mcp_servers.before.json  frozen copy from when only server one existed (for the config diff)
├── servers/                 OUR server: search_clauses, get_clause, list_section_headings + defined-terms resource
│   └── clause_search_server_v1_before.py   frozen "before" for the docstring/error rewrite
├── third_party/             STAND-IN for the knowledge team's server (synthetic data)
├── gateway/ + mcp_servers.{upstream,gateway}.json     bonus: one front door
├── scripts/                 discover, prove_zero_diff, capture_wire (+ wiretap, hand annotations), demo_query,
│                            error_demo, selfcheck, offline_llm (the STUB)
└── deliverables/            outputs; snapshots/server_one/ = agent_core as it was before server two
```

## Submission checklist -> file

| Item | File |
|---|---|
| agent diff, 0 changed lines | `deliverables/agent_diff.txt` |
| config diff adding server two | `deliverables/config.diff` |
| raw initialize / tools/list / tools/call, annotated | `deliverables/wire.json` (+ model-location line inside it) |
| tool count N before -> M after, with names | `deliverables/tool_counts.md` |
| query that calls a server-two tool, tool name in trace | `deliverables/query_trace.md` (STUB model; see above) |
| same failing call, old vs new docstring/error | `deliverables/error_before_after.md` (STUB model; see above) |
| risk note, exactly 5 lines | `deliverables/risk_note.md` |
| bonus: gateway, audit line, scoped token, denial as message | `deliverables/gateway_*` |

## Design notes

- **No hard-coded tools.** `loop.py` renders each tool's name, argument list and docstring from `tools/list`; the only
  tool name in `agent_core/` is the terminal `final_answer`. `selfcheck.py` fails if a discovered name appears in it.
- **No model inside a server.** Servers expose capabilities; `selfcheck.py` fails if one imports an LLM client.
- **Defined terms are a resource, not a tool.** The app attaches `contract://sample/defined-terms` to every prompt
  (`attach_resources` in config) so the model is handed definitions with the clause instead of having to ask. Resources
  are attached only if allow-listed: a third-party server does not get to decide what enters our prompt.
- **Errors are for the model.** A tool failure comes back as `isError` text the model reads. A dead server is reported
  by the host as an infrastructure failure, never as "not found", so the two cannot be confused. In the stand-in, a date
  that predates the contract and an unknown id read differently.
- **Trust boundary.** Tool results are wrapped as untrusted data in the prompt (Week 8's rule). Spawned servers get only a
  minimal OS environment plus their configured `env` — tested: a child cannot see `GROQ_API_KEY`.
- **HTTP transport.** `host.py` also accepts `{"url", "headers"}` entries (a real contract-repository server is likely
  remote). I tested it by hand against the stand-in's `--transport http` with a bearer token (right token: same 3 tools;
  wrong token: reported as an unavailable server, others unaffected); no script in this folder covers it.

## Bonus — one front door

`gateway/gateway_server.py` is the only server the agent sees (`mcp_servers.gateway.json`). It fans out to the real
ones, checks each `tools/call` against the caller's token scope (`gateway/tokens.json`, default-deny), and writes one
audit line per call — caller, tool, contract id; never the token or the result (`deliverables/gateway_audit.log`).
With the read-only token `get_amendment_chain` is denied with a message saying it is a permission limit, not a missing
record or an outage, and what can still be called; `get_contract` still works (`gateway_trace_readonly.md`, then
`gateway_trace_full.md` for contrast). Agent code unchanged here too — it is the same zero-diff check.

Limits to know: scoping is **per tool, not per record** — `get_contract` still returns NDA record metadata and
`amendments_on_file`, which is why the risk note asks for NDA exclusion on the repository side. Tokens in
`tokens.json` are plaintext demo values. A stdio-spawned gateway is a demonstration; a real one is a separately
run HTTP service holding the upstream credentials so the agent never has them.

## Known limits

- Server one's search is lexical, not the Week 4 FAISS + cross-encoder pipeline (this week tests the protocol, not
  retrieval); the MCP surface is the same whichever ranker sits behind `_rank()`.
- Python 3.10+ (the `mcp` SDK requires it), a step up from the repo's stated 3.9.
