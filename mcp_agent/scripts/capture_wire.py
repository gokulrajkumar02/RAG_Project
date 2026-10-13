"""
Requirement 4 — capture the raw JSON-RPC exchange between OUR host and the new
(contract-repository) server, and merge it with the hand-written annotations in
wire_annotations.json.

How: the real McpHost connects to server two through wiretap.py, which logs every
line in both directions. The host then runs the three phases an agent run does —
initialize (implicit in connect), tools/list (implicit in connect), tools/call
(host.call_tool). Nothing here is a hand-built message: it is the SDK's own traffic.

    python mcp_agent/scripts/capture_wire.py

Writes deliverables/wire.json and fails loudly if any top-level field of any captured
message lacks an annotation (the annotations themselves are written by hand).
"""

import asyncio
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
sys.path.insert(0, MCP_AGENT_DIR)

from agent_core.host import McpHost  # noqa: E402

OUT = os.path.join(MCP_AGENT_DIR, "deliverables", "wire.json")
ANNOTATIONS = os.path.join(HERE, "wire_annotations.json")
CALL = ("get_amendment_chain", {"contract_id": "MSA-2021-0142"})


REQUEST_LABELS = {"initialize": "initialize", "tools/list": "tools_list", "tools/call": "tools_call"}


def label_frames(messages):
    """initialize.request / initialize.response / initialized.notification / ...
    A response is labelled after the request carrying the same id."""
    by_id, labels = {}, []
    for msg in messages:
        method = msg.get("method")
        if method in REQUEST_LABELS and "id" in msg:
            by_id[msg["id"]] = REQUEST_LABELS[method]
            labels.append(f"{REQUEST_LABELS[method]}.request")
        elif method == "notifications/initialized":
            labels.append("initialized.notification")
        elif "result" in msg or "error" in msg:
            labels.append(f"{by_id.get(msg.get('id'), 'unmatched')}.response")
        else:
            labels.append(f"other:{method}")
    return labels


def required_paths(msg):
    """Every field a hand annotation must cover: the top-level keys, the keys one level
    inside params/result, and the keys of the first item of result.tools / result.content."""
    paths = list(msg)
    for top in ("params", "result"):
        inner = msg.get(top)
        if isinstance(inner, dict):
            for k, v in inner.items():
                paths.append(f"{top}.{k}")
                if top == "result" and k in ("tools", "content") and v and isinstance(v[0], dict):
                    paths.extend(f"{top}.{k}[].{item_key}" for item_key in v[0])
    return paths


async def capture(tap_log):
    cfg = {"mcpServers": {"contract-repository": {
        "command": "${PYTHON}",
        "args": [os.path.join(HERE, "wiretap.py"), tap_log, "--", sys.executable,
                 os.path.join(MCP_AGENT_DIR, "third_party", "contract_repo_server.py")],
        "env": {"CONTRACT_REPO_TOKEN": "demo-token-not-a-secret"},
    }}}
    cfg_path = os.path.join(os.path.dirname(tap_log), "tap_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    errlog = open(os.path.join(os.path.dirname(tap_log), "server_stderr.log"), "w", encoding="utf-8")
    try:
        async with McpHost(cfg_path, errlog=errlog) as host:
            assert not host.failed, host.failed
            outcome = await host.call_tool(*CALL)
    finally:
        errlog.close()
    return outcome


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tap_log = os.path.join(tmp, "tap.jsonl")
        outcome = asyncio.run(capture(tap_log))
        with open(tap_log, encoding="utf-8") as f:
            tapped = [json.loads(line) for line in f if line.strip()]
    labels = label_frames([json.loads(t["raw"]) for t in tapped])

    if "--show" in sys.argv:  # read the real frames before writing annotations for them
        for t, label in zip(tapped, labels):
            print(f"\n#{t['n']} {t['dir']}  [{label}]\n{json.dumps(json.loads(t['raw']), indent=2)}")
        return

    with open(ANNOTATIONS, encoding="utf-8") as f:
        notes = json.load(f)

    frames, problems = [], []
    for t, label in zip(tapped, labels):
        msg = json.loads(t["raw"])
        ann = notes["frames"].get(label)
        if ann is None:
            problems.append(f"no annotations for frame {label!r}")
            ann = {}
        missing = [p for p in required_paths(msg) if p not in ann.get("fields", {})]
        if missing:
            problems.append(f"{label}: field(s) without a hand annotation: {missing}")
        frames.append({"n": t["n"], "direction": t["dir"], "label": label, "raw": t["raw"], "message": msg,
                       "what_it_is": ann.get("what_it_is", ""), "annotations": ann.get("fields", {})})
    if problems:
        sys.exit("annotation coverage failed:\n  " + "\n  ".join(problems))

    doc = {
        "about": notes["about"],
        "where_the_model_runs": notes["where_the_model_runs"],
        "server": "contract-repository (STAND-IN, synthetic data) over stdio",
        "captured_with": "scripts/wiretap.py between the agent's real McpHost and the server; raw = the exact line on the wire",
        "tool_call_made": {"tool": CALL[0], "arguments": CALL[1], "isError": outcome.is_error},
        "frames": frames,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {len(frames)} frames: " + ", ".join(fr["label"] for fr in frames))


if __name__ == "__main__":
    main()
