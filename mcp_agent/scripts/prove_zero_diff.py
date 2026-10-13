"""
Requirement 2 — prove that adding server two changed ZERO lines of the agent module.

    python mcp_agent/scripts/prove_zero_diff.py

Compares agent_core/ as it is NOW against deliverables/snapshots/server_one/agent_core/,
a copy taken while mcp_servers.json still listed only the clause-search server (hashes
recorded at that moment in deliverables/agent_core.sha256.before). Uses `git diff
--no-index`, so no commit is needed to run it, and it keeps working later: if anyone
edits agent_core/ after this point, this script shows exactly which lines.

Writes deliverables/agent_diff.txt and deliverables/config.diff.
"""

import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_AGENT_DIR = os.path.dirname(HERE)
D = "deliverables"
SNAP = f"{D}/snapshots/server_one/agent_core"
LIVE = "agent_core"
GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "diff", "--no-index"]


def git(*args, cwd=MCP_AGENT_DIR):
    p = subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    return p.stdout.rstrip("\n")


def changed_lines(numstat):
    added = removed = 0
    for line in numstat.splitlines():
        a, r, _path = line.split("\t", 2)
        added += int(a)
        removed += int(r)
    return added, removed


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def mtime(path):
    ts = os.path.getmtime(os.path.join(MCP_AGENT_DIR, path))
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    # `git diff --no-index` ignores .gitignore, so running any other script first (which writes
    # agent_core/__pycache__) would show phantom differences. Diff clean copies instead.
    with tempfile.TemporaryDirectory() as tmp:
        skip = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(os.path.join(MCP_AGENT_DIR, SNAP), os.path.join(tmp, "before", "agent_core"), ignore=skip)
        shutil.copytree(os.path.join(MCP_AGENT_DIR, LIVE), os.path.join(tmp, "after", "agent_core"), ignore=skip)
        b, a = "before/agent_core", "after/agent_core"
        stat = git("--stat", b, a, cwd=tmp)
        numstat = git("--numstat", b, a, cwd=tmp)
        full = git(b, a, cwd=tmp)
    added, removed = changed_lines(numstat)

    files = sorted(f for f in os.listdir(os.path.join(MCP_AGENT_DIR, LIVE)) if f.endswith(".py"))
    rows = []
    for f in files:
        before = sha(os.path.join(MCP_AGENT_DIR, SNAP, f))
        now = sha(os.path.join(MCP_AGENT_DIR, LIVE, f))
        rows.append(f"{f:<12} {before[:16]}  {now[:16]}  {'identical' if before == now else 'CHANGED'}")

    cfg_numstat = git("--numstat", "mcp_servers.before.json", "mcp_servers.json")
    cfg_diff = git("mcp_servers.before.json", "mcp_servers.json")
    c_added, c_removed = changed_lines(cfg_numstat)

    verdict = "PASS" if (added, removed) == (0, 0) and "CHANGED" not in "\n".join(rows) else "FAIL"
    text = "\n".join([
        "# agent_diff.txt — adding server two changed ZERO lines of the agent module",
        "",
        f"BEFORE = {SNAP}/",
        f"         copy of mcp_agent/agent_core/ made {mtime(SNAP + '/host.py')} (file mtime), while mcp_servers.json",
        "         still listed only `clause-search`; sha256s recorded then in deliverables/agent_core.sha256.before",
        f"AFTER  = mcp_agent/{LIVE}/ as it is right now, with mcp_servers.json listing `clause-search` + `contract-repository`",
        "",
        "(both trees are copied to a temp dir first, without __pycache__, as before/ and after/)",
        "",
        "$ git diff --no-index --stat before/agent_core after/agent_core",
        stat or "(no output: no file differs)",
        "",
        "$ git diff --no-index --numstat before/agent_core after/agent_core",
        numstat or "(no output)",
        "",
        "$ git diff --no-index before/agent_core after/agent_core",
        full or "(no output)",
        "",
        f"CHANGED LINES IN THE AGENT MODULE: {added} added, {removed} removed  ->  {verdict}",
        "",
        "sha256 (first 16 hex)  file         before            now               verdict",
        *rows,
        "",
        "# For contrast — the ONLY thing that changed (config.diff)",
        "",
        "$ git diff --no-index --numstat mcp_servers.before.json mcp_servers.json",
        cfg_numstat,
        f"-> {c_added} lines added, {c_removed} removed, in a JSON config file",
        "",
        "$ git diff --no-index mcp_servers.before.json mcp_servers.json",
        cfg_diff,
        "",
    ])
    out_dir = os.path.join(MCP_AGENT_DIR, D)
    with open(os.path.join(out_dir, "agent_diff.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    with open(os.path.join(out_dir, "config.diff"), "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg_diff + "\n")
    print(text)
    if verdict != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
