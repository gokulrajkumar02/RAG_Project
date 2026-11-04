"""Week 12 capstone: Contract Review Assistant (Track F). One integrated app; see capstone/README.md."""

import os
import sys

CAPSTONE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(CAPSTONE_DIR)

# The reused weeks live in the repo root and in sibling packages. Put them on sys.path once, here,
# so every entry point (run.py, the two MCP servers, selfcheck) resolves them the same way.
for _p in (REPO_ROOT, CAPSTONE_DIR,
           os.path.join(REPO_ROOT, "observability"),   # Week 11 tracing.py (imported as `tracing`)
           os.path.join(REPO_ROOT, "mcp_agent"),       # Week 9 agent_core.host / agent_core.loop
           os.path.join(REPO_ROOT, "eval")):           # Week 6 judge.py
    if _p not in sys.path:
        sys.path.insert(0, _p)
