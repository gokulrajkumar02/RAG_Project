"""
Week 9 — MCP host plumbing for the contract agent.

This file and loop.py are THE AGENT MODULE (everything under agent_core/). They
never name a tool and never name a server: which servers exist is read from
mcp_servers.json at start-up, and which tools exist is whatever each server
answers to `tools/list`. Adding a server is therefore a config edit, and
`git diff` over this directory stays empty — that is the whole point of MCP.

Roles (the three the brief asks you to keep straight):
- host   = this process: owns the model call (loop.py) and decides what the model sees.
- client = one ClientSession per server, created below — a thin JSON-RPC speaker.
- server = someone else's process. It offers tools/resources; it never sees a
           prompt and has no idea which model, if any, is on the other end.

Config entry shapes (see mcp_servers.json):
  stdio : {"command": "...", "args": [...], "env": {...}, "cwd": "..."}
  http  : {"url": "https://.../mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}
Optional on either: "attach_resources": ["uri", ...] — resources the APP (not the
model) attaches to every prompt. Resources are never attached unless allow-listed:
a third-party server does not get to decide what lands in our prompt.

Values may use ${VAR}, ${VAR:-default}, and ${PYTHON} (this interpreter).
Relative paths in `args`/`cwd` resolve against the config file's directory.
"""

import inspect
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

CONNECT_TIMEOUT_SECONDS = 30
CALL_TIMEOUT_SECONDS = 30

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


def _describe(exc):
    """anyio wraps transport failures in ExceptionGroups; report the leaf that says why."""
    while getattr(exc, "exceptions", None):
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


@dataclass
class DiscoveredTool:
    server: str
    name: str          # the name the model uses; == remote_name unless two servers collide
    remote_name: str   # the name on the wire
    description: str
    input_schema: dict


@dataclass
class AttachedResource:
    server: str
    uri: str
    text: str


@dataclass
class ToolOutcome:
    text: str
    is_error: bool
    server: str
    remote_name: str


@dataclass
class _Connection:
    name: str
    session: ClientSession
    server_info: dict = field(default_factory=dict)


def _expand(value, config_path):
    """Expand ${VAR}, ${VAR:-default} and ${PYTHON} in one config string."""

    def sub(m):
        name, default = m.group(1), m.group(2)
        if name == "PYTHON":
            return sys.executable
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise ConfigError(f"{config_path}: references ${{{name}}} but it is not set in the environment")

    return _VAR.sub(sub, value)


def load_config(config_path):
    config_path = os.path.abspath(config_path)
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    servers = raw.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise ConfigError(f"{config_path}: needs a non-empty \"mcpServers\" object")
    return config_path, servers


class McpHost:
    """Connects to every server in the config, runs initialize + tools/list on each,
    and routes a tool name back to the server that advertised it."""

    def __init__(self, config_path, errlog=None):
        self.config_path, self._servers_cfg = load_config(config_path)
        self.config_dir = os.path.dirname(self.config_path)
        self.errlog = errlog if errlog is not None else sys.stderr
        self._stack = AsyncExitStack()
        self._connections = {}
        self.tools = []                # list[DiscoveredTool], straight from tools/list
        self.attached = []             # list[AttachedResource]
        self.failed = {}               # server name -> why it could not be used
        self._by_name = {}

    async def __aenter__(self):
        await self._stack.__aenter__()
        try:
            for name, cfg in self._servers_cfg.items():
                try:
                    await self._connect(name, cfg)
                except ConfigError:
                    raise
                except Exception as exc:  # one dead server must not take the agent down
                    self.failed[name] = _describe(exc)
            self._build_registry()
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc_info):
        return await self._stack.__aexit__(*exc_info)

    # -- connection / discovery ------------------------------------------------

    def _expand_cfg(self, cfg):
        def walk(v):
            if isinstance(v, str):
                return _expand(v, self.config_path)
            if isinstance(v, list):
                return [walk(x) for x in v]
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            return v

        return walk(cfg)

    async def _open_transport(self, server_stack, cfg):
        if "url" in cfg:
            client = httpx.AsyncClient(
                headers=cfg.get("headers") or {},
                timeout=httpx.Timeout(CALL_TIMEOUT_SECONDS, read=300),
            )
            await server_stack.enter_async_context(client)
            read, write, _get_session_id = await server_stack.enter_async_context(
                streamable_http_client(cfg["url"], http_client=client)
            )
            return read, write
        if "command" in cfg:
            cwd = os.path.normpath(os.path.join(self.config_dir, cfg.get("cwd", ".")))
            params = StdioServerParameters(
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env") or None,
                cwd=cwd,
            )
            read, write = await server_stack.enter_async_context(stdio_client(params, errlog=self.errlog))
            return read, write
        raise ConfigError(f"{self.config_path}: server entry needs either \"command\" (stdio) or \"url\" (http)")

    async def _connect(self, name, cfg):
        cfg = self._expand_cfg(cfg)
        server_stack = AsyncExitStack()
        try:
            read, write = await self._open_transport(server_stack, cfg)
            session = await server_stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS))
            )
            init = await session.initialize()  # JSON-RPC: initialize, then notifications/initialized

            tools, cursor = [], None
            while True:  # tools/list is paginated; follow nextCursor to the end
                page = await session.list_tools(cursor)
                tools.extend(page.tools)
                cursor = page.nextCursor
                if not cursor:
                    break

            attached = []
            for uri in cfg.get("attach_resources") or []:
                res = await session.read_resource(uri)
                text = "\n".join(c.text for c in res.contents if getattr(c, "text", None))
                attached.append(AttachedResource(name, uri, text))
        except BaseException:
            await server_stack.aclose()
            raise
        # Register only once the whole connect succeeded: a half-connected server must
        # leave no tools behind for the model to call.
        self._stack.push_async_callback(server_stack.aclose)
        self.attached.extend(attached)
        for t in tools:
            self.tools.append(
                DiscoveredTool(name, t.name, t.name, inspect.cleandoc(t.description or ""), t.inputSchema or {})
            )
        info = init.serverInfo
        self._connections[name] = _Connection(
            name, session, {"name": info.name, "version": info.version, "protocolVersion": init.protocolVersion}
        )

    def _build_registry(self):
        counts = {}
        for t in self.tools:
            counts[t.remote_name] = counts.get(t.remote_name, 0) + 1
        for t in self.tools:  # two servers advertising one name: disambiguate both, never silently shadow
            if counts[t.remote_name] > 1:
                t.name = f"{t.server}__{t.remote_name}"
        self._by_name = {t.name: t for t in self.tools}

    @property
    def server_info(self):
        return {n: c.server_info for n, c in self._connections.items()}

    # -- calling ---------------------------------------------------------------

    async def call_tool(self, name, arguments):
        tool = self._by_name.get(name)
        if tool is None:
            known = ", ".join(sorted(self._by_name)) or "(none)"
            return ToolOutcome(f"Unknown tool '{name}'. Discovered tools: {known}.", True, "", name)
        session = self._connections[tool.server].session
        try:
            result = await session.call_tool(
                tool.remote_name, arguments, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS)
            )
        except Exception as exc:
            # Transport / protocol failure, NOT an answer about the contract. Say so, so the
            # model cannot mistake "the repository is down" for "that record does not exist".
            return ToolOutcome(
                f"[host] Server '{tool.server}' did not answer tools/call {tool.remote_name} "
                f"({_describe(exc)}). This is an infrastructure failure; it says "
                "nothing about whether the requested record exists.",
                True,
                tool.server,
                tool.remote_name,
            )
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            parts.append(text if text is not None else f"[non-text content omitted: {block.type}]")
        return ToolOutcome("\n".join(parts), bool(result.isError), tool.server, tool.remote_name)
