"""
`python capstone/selfcheck.py` - the structural claims this capstone makes, checked (needs `run.py build` first).
  1. the earlier weeks' files it reuses are byte-identical to when it started (hashes in .reused_files.sha256)
  2. no module the running system imports reads truth.json or the generator (only eval code may)
  3. the registry (what both MCP tools and every prompt are built from) contains no personal data from truth.json
  4. citations are rendered by code: a model-supplied effective date has nowhere to go (no such argument)
"""

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contractdesk  # noqa: E402,F401
from contractdesk import paths, redact  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))


# 1 ---------------------------------------------------------------------------------------------------------
bad = []
for line in open(os.path.join(HERE, ".reused_files.sha256"), encoding="utf-8"):
    digest, name = line.split(None, 1)
    path = os.path.join(paths.REPO_ROOT, name.strip().lstrip("*"))
    if hashlib.sha256(open(path, "rb").read()).hexdigest() != digest:
        bad.append(name.strip())
check("reused files unchanged (rag_core, agent_core.host/loop, judge, questions, tracing)", not bad, f"changed: {bad}")

# 2 ---------------------------------------------------------------------------------------------------------
runtime = ["registry.py", "toolkit.py", "index.py", "agent.py", "citations.py", "guards.py", "parse.py", "ingest.py",
           "redact.py", "tracex.py", "stub_model.py", "llm.py", "extract.py"]
leaks = []
for m in runtime:
    src = open(os.path.join(HERE, "contractdesk", m), encoding="utf-8").read()
    if re.search(r"paths\.TRUTH|import corpus_gen|from \.corpus_gen|corpus_gen import|from \. import .*corpus_gen", src):
        leaks.append(m)
srv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
check("runtime modules never touch truth.json or the generator", not leaks and "truth" not in srv, f"{leaks}")

# 3 ---------------------------------------------------------------------------------------------------------
truth = json.load(open(paths.TRUTH, encoding="utf-8"))
pii = [p for a in truth["accounts"].values() for p in a["pii"]]
reg_text = open(paths.REGISTRY, encoding="utf-8").read()
found = redact.find_leaks(reg_text, pii)
check(f"registry holds none of the {len(pii)} known personal-data strings", not found, f"{len(found)} survive, e.g. {found[:2]}")

# 4 ---------------------------------------------------------------------------------------------------------
agent_src = open(os.path.join(HERE, "contractdesk", "agent.py"), encoding="utf-8").read()
check("final_answer takes (answer, citations[doc, clause]); dates/law are looked up by citations.cite()",
      "C.cite(self.reg" in agent_src and "effective_date" not in re.search(r"def _check_final.*?def _finish", agent_src, re.S).group(0))
sys.exit(0 if ok else 1)
