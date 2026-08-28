"""
Tool Registry
=============
The single source of truth for all discovered MCP tools in Jarvis.

Architecture position
---------------------
::

    MCP Servers
         |
    MCP Client  (connects, calls, manages sessions)
         |
    Tool Discovery  (list_tools from each server)
         |
    TOOL REGISTRY  <-- this module
         |
    Tool Selection / Filtering
         |
    Agent
         |
    MCP Client
         |
    Tool Execution

The registry is a catalog and filtering layer.
It does NOT execute tools.  The MCP client (JarvisAgent) remains
responsible for all MCP connections and tool calls.

Usage
-----
::

    from app.tools import tool_registry

    # Query all memory tools
    tools = tool_registry.list_tools(capability="memory")

    # Query tools from a specific server
    tools = tool_registry.list_tools(server="whatsapp")

    # Only enabled tools
    tools = tool_registry.list_tools(enabled_only=True)

    # Disable a tool at runtime
    tool_registry.disable_tool("filesystem__write_file")

    # Multi-capability retrieval
    tools = tool_registry.get_tools_for_capabilities(["memory", "terminal"])
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.tools.models import ToolMetadata, ToolSnapshot

logger = logging.getLogger("jarvis.tool_registry")

# ---------------------------------------------------------------------------
# Capability classification
# ---------------------------------------------------------------------------
# Deterministic mapping: MCP server name -> capability bucket.
# This is the authoritative classification for TR-1.
# Future phases may replace or augment this with LLM-based classification.

_SERVER_CAPABILITY_MAP: dict[str, str] = {
    "memory":     "memory",
    "filesystem": "filesystem",
    "playwright": "browser",
    "exa":        "web_research",
    "tavily":     "web_research",
    "firecrawl":  "web_research",
    "whatsapp":   "communication",
    "terminal":   "terminal",
}

_DEFAULT_CAPABILITY = "general"


def _classify_server(server_name: str) -> str:
    """Return the capability bucket for a given server name."""
    return _SERVER_CAPABILITY_MAP.get(server_name, _DEFAULT_CAPABILITY)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    In-memory catalog of all discovered MCP tools.

    Populated at startup by MCP tool discovery.
    Queried by agents and orchestration layers.
    """

    def __init__(self) -> None:
        # Primary store: scoped tool name -> ToolMetadata
        self._tools: dict[str, ToolMetadata] = {}
        logger.info("ToolRegistry initialised (empty).")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_tool(self, metadata: ToolMetadata) -> None:
        """
        Add or replace a tool in the registry.

        If a tool with the same ``name`` already exists it will be
        overwritten (useful for server reconnects).
        """
        if metadata.name in self._tools:
            logger.debug("Replacing existing registry entry: %s", metadata.name)
        self._tools[metadata.name] = metadata
        logger.debug("Registered tool: %s [server=%s, capability=%s]",
                     metadata.name, metadata.server, metadata.capability)

    def register_mcp_tool(
        self,
        server_name: str,
        mcp_tool: object,
        *,
        available: bool = True,
        enabled: bool = True,
    ) -> ToolMetadata:
        """
        Convenience method: build a ``ToolMetadata`` from a raw MCP tool
        object and register it.

        ``mcp_tool`` is the object returned by ``session.list_tools().tools``.
        The MCP SDK exposes ``.name``, ``.description``, and
        ``.inputSchema`` / ``.input_schema`` on these objects.

        Returns the created ``ToolMetadata``.
        """
        raw_name: str = mcp_tool.name  # type: ignore[attr-defined]
        description: str = getattr(mcp_tool, "description", "") or ""

        # Preserve the raw schema verbatim — do NOT normalise or simplify.
        input_schema: dict = (
            getattr(mcp_tool, "inputSchema", None)
            or getattr(mcp_tool, "input_schema", None)
            or {}
        )

        scoped_name = f"{server_name}__{raw_name}"
        capability = _classify_server(server_name)

        meta = ToolMetadata(
            name=scoped_name,
            server=server_name,
            tool_name=raw_name,
            capability=capability,
            description=description,
            input_schema=input_schema,
            enabled=enabled,
            available=available,
        )
        self.register_tool(meta)
        return meta

    def remove_tool(self, name: str) -> bool:
        """Remove a tool from the registry. Returns True if it existed."""
        existed = name in self._tools
        self._tools.pop(name, None)
        if existed:
            logger.debug("Removed tool: %s", name)
        return existed

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def enable_tool(self, name: str) -> bool:
        """Enable a tool by its scoped name. Returns True if found."""
        if name in self._tools:
            self._tools[name].enabled = True
            logger.info("Tool enabled: %s", name)
            return True
        logger.warning("enable_tool: unknown tool '%s'", name)
        return False

    def disable_tool(self, name: str) -> bool:
        """Disable a tool by its scoped name. Returns True if found."""
        if name in self._tools:
            self._tools[name].enabled = False
            logger.info("Tool disabled: %s", name)
            return True
        logger.warning("disable_tool: unknown tool '%s'", name)
        return False

    def set_server_enabled(self, server_name: str, enabled: bool) -> int:
        """
        Bulk enable/disable all tools belonging to a server.

        Returns the number of tools affected.
        """
        affected = 0
        for meta in self._tools.values():
            if meta.server == server_name:
                meta.enabled = enabled
                affected += 1
        logger.info(
            "Server '%s' set to %s (%d tools affected).",
            server_name, "enabled" if enabled else "disabled", affected
        )
        return affected

    def set_server_available(self, server_name: str, available: bool) -> int:
        """
        Bulk mark all tools from a server as available/unavailable.
        Called when a server reconnects or goes offline.

        Returns the number of tools affected.
        """
        affected = 0
        for meta in self._tools.values():
            if meta.server == server_name:
                meta.available = available
                affected += 1
        return affected

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> ToolMetadata | None:
        """Look up a single tool by its scoped name."""
        return self._tools.get(name)

    def list_tools(
        self,
        *,
        server: str | None = None,
        capability: str | None = None,
        enabled_only: bool = False,
        available_only: bool = False,
    ) -> list[ToolMetadata]:
        """
        Return a filtered list of registered tools.

        Parameters
        ----------
        server : str, optional
            Filter to tools from a specific MCP server, e.g. ``"memory"``.
        capability : str, optional
            Filter to tools in a specific capability bucket,
            e.g. ``"web_research"``.
        enabled_only : bool
            If True, exclude disabled tools.
        available_only : bool
            If True, exclude tools whose server is not available.
        """
        results: list[ToolMetadata] = []
        for meta in self._tools.values():
            if server is not None and meta.server != server:
                continue
            if capability is not None and meta.capability != capability:
                continue
            if enabled_only and not meta.enabled:
                continue
            if available_only and not meta.available:
                continue
            results.append(meta)
        return results

    def get_tools_for_capabilities(
        self,
        capabilities: Iterable[str],
        *,
        enabled_only: bool = True,
    ) -> list[ToolMetadata]:
        """
        Return all tools that belong to any of the given capability buckets.

        Example::

            tools = registry.get_tools_for_capabilities(
                ["memory", "communication"],
                enabled_only=True,
            )
        """
        cap_set = set(capabilities)
        return [
            meta for meta in self._tools.values()
            if meta.capability in cap_set
            and (not enabled_only or meta.enabled)
        ]

    def get_tools_for_servers(
        self,
        servers: Iterable[str],
        *,
        enabled_only: bool = True,
    ) -> list[ToolMetadata]:
        """Return all tools belonging to any of the given server names."""
        srv_set = set(servers)
        return [
            meta for meta in self._tools.values()
            if meta.server in srv_set
            and (not enabled_only or meta.enabled)
        ]

    def get_enabled_tool_names(
        self,
        *,
        server: str | None = None,
        capability: str | None = None,
    ) -> set[str]:
        """
        Return a set of scoped tool names for all currently-enabled tools.

        Optionally filter by server or capability.  This is the fast path
        for the Worker's allowed_tool_names enforcement check.

        Example::

            names = registry.get_enabled_tool_names(capability="memory")
            # → {"memory__search_nodes", "memory__open_nodes", ...}
        """
        return {
            meta.name
            for meta in self._tools.values()
            if meta.enabled
            and (server is None or meta.server == server)
            and (capability is None or meta.capability == capability)
        }

    def get_tools_for_server(
        self,
        server: str,
        *,
        enabled_only: bool = True,
    ) -> list[ToolMetadata]:
        """Singular alias for get_tools_for_servers() with a single server name."""
        return self.get_tools_for_servers([server], enabled_only=enabled_only)

    def create_snapshot(
        self,
        *,
        servers: Iterable[str] | None = None,
        capabilities: Iterable[str] | None = None,
    ) -> ToolSnapshot:
        """
        Create an immutable ToolSnapshot containing only eligible, enabled tools.
        
        If servers or capabilities are provided, the snapshot is restricted to those.
        If neither is provided, returns all currently enabled tools.
        """
        if servers is not None:
            tools = self.get_tools_for_servers(servers, enabled_only=True)
        elif capabilities is not None:
            tools = self.get_tools_for_capabilities(capabilities, enabled_only=True)
        else:
            tools = self.list_tools(enabled_only=True)
            
        return ToolSnapshot(tools=tools)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_servers(self) -> list[str]:
        """Return a sorted list of all known server names."""
        return sorted({meta.server for meta in self._tools.values()})

    def all_capabilities(self) -> list[str]:
        """Return a sorted list of all known capability buckets."""
        return sorted({meta.capability for meta in self._tools.values()})

    def summary(self) -> dict:
        """
        Return a structured summary of the current registry state.

        Useful for logging and debugging.
        """
        servers: dict[str, list[str]] = {}
        for meta in self._tools.values():
            servers.setdefault(meta.server, []).append(meta.name)

        capabilities: dict[str, list[str]] = {}
        for meta in self._tools.values():
            capabilities.setdefault(meta.capability, []).append(meta.name)

        return {
            "total_tools": len(self._tools),
            "enabled_tools": sum(1 for m in self._tools.values() if m.enabled),
            "disabled_tools": sum(1 for m in self._tools.values() if not m.enabled),
            "unavailable_tools": sum(1 for m in self._tools.values() if not m.available),
            "servers": {srv: sorted(tools) for srv, tools in sorted(servers.items())},
            "capabilities": {cap: sorted(tools) for cap, tools in sorted(capabilities.items())},
        }

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return (
            f"ToolRegistry("
            f"{len(self._tools)} tools, "
            f"{len(self.all_servers())} servers, "
            f"{len(self.all_capabilities())} capabilities)"
        )
