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
    tools = tool_registry.get_tools_for_capability("memory")

    # Query tools from a specific server
    tools = tool_registry.get_tools_for_server("whatsapp")

    # Only enabled tools
    tools = tool_registry.get_tools(enabled_only=True)

    # Disable a tool at runtime
    tool_registry.disable_tool("filesystem__write_file")
"""

from __future__ import annotations

import logging
from typing import Iterable, Union
import re

from app.tools.models import ToolMetadata, ToolSnapshot

logger = logging.getLogger("jarvis.tool_registry")

# ---------------------------------------------------------------------------
# Capability classification
# ---------------------------------------------------------------------------
# Deterministic mapping: MCP server name -> capability bucket.
# This is the authoritative classification for TR-1.

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
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        logger.info("ToolRegistry initialised (empty).")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_tool(self, metadata: ToolMetadata) -> None:
        """Add or replace a tool in the registry."""
        if metadata.name in self._tools:
            logger.debug("Replacing existing registry entry: %s", metadata.name)
        self._tools[metadata.name] = metadata
        logger.debug("Registered tool: %s [server=%s, capability=%s]",
                     metadata.name, metadata.server, metadata.capability)

    def register_tools(self, tools: Iterable[ToolMetadata]) -> None:
        """Bulk register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

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
        """
        raw_name: str = mcp_tool.name  # type: ignore[attr-defined]
        description: str = getattr(mcp_tool, "description", "") or ""

        # Preserve the raw schema verbatim
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

    def unregister_tool(self, name: str) -> bool:
        """Remove a tool from the registry. Returns True if it existed."""
        existed = name in self._tools
        self._tools.pop(name, None)
        if existed:
            logger.debug("Removed tool: %s", name)
        return existed

    def remove_tool(self, name: str) -> bool:
        """Alias for unregister_tool to preserve backward compatibility."""
        return self.unregister_tool(name)

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    def enable_tool(self, name: str) -> bool:
        """Enable a tool by its scoped name."""
        if name in self._tools:
            self._tools[name].enabled = True
            logger.info("Tool enabled: %s", name)
            return True
        logger.warning("enable_tool: unknown tool '%s'", name)
        return False

    def disable_tool(self, name: str) -> bool:
        """Disable a tool by its scoped name."""
        if name in self._tools:
            self._tools[name].enabled = False
            logger.info("Tool disabled: %s", name)
            return True
        logger.warning("disable_tool: unknown tool '%s'", name)
        return False

    def set_server_enabled(self, server_name: str, enabled: bool) -> int:
        """Bulk enable/disable all tools belonging to a server."""
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
        """Bulk mark all tools from a server as available/unavailable."""
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

    def get_tools(
        self,
        *,
        servers: Union[str, Iterable[str], None] = None,
        capabilities: Union[str, Iterable[str], None] = None,
        enabled_only: bool = False,
        available_only: bool = False,
    ) -> list[ToolMetadata]:
        """
        Return a filtered list of registered tools.

        Parameters
        ----------
        servers : str or Iterable[str], optional
            Filter to tools from specific MCP servers.
        capabilities : str or Iterable[str], optional
            Filter to tools in specific capability buckets.
        enabled_only : bool
            If True, exclude disabled tools.
        available_only : bool
            If True, exclude tools whose server is not available.
        """
        srv_set = {servers} if isinstance(servers, str) else (set(servers) if servers is not None else None)
        cap_set = {capabilities} if isinstance(capabilities, str) else (set(capabilities) if capabilities is not None else None)

        results: list[ToolMetadata] = []
        for meta in self._tools.values():
            if srv_set is not None and meta.server not in srv_set:
                continue
            if cap_set is not None and meta.capability not in cap_set:
                continue
            if enabled_only and not meta.enabled:
                continue
            if available_only and not meta.available:
                continue
            results.append(meta)
        return results

    def list_tools(self, *, server: str | None = None, capability: str | None = None, enabled_only: bool = False, available_only: bool = False) -> list[ToolMetadata]:
        """Backward compatibility alias for get_tools."""
        return self.get_tools(servers=server, capabilities=capability, enabled_only=enabled_only, available_only=available_only)

    def get_tools_for_server(self, server: str, *, enabled_only: bool = True) -> list[ToolMetadata]:
        """Return all tools belonging to the given server name."""
        return self.get_tools(servers=server, enabled_only=enabled_only)

    def get_tools_for_capability(self, capability: str, *, enabled_only: bool = True) -> list[ToolMetadata]:
        """Return all tools that belong to the given capability bucket."""
        return self.get_tools(capabilities=capability, enabled_only=enabled_only)

    # ------------------------------------------------------------------
    # Discovery Foundation
    # ------------------------------------------------------------------

    def search_tools(
        self,
        query: str,
        *,
        capabilities: Iterable[str] | None = None,
        servers: Iterable[str] | None = None,
        enabled_only: bool = True,
        available_only: bool = True,
    ) -> list[ToolMetadata]:
        """
        Discover registry tools whose metadata contains terms from ``query``.
        """
        candidates = self.get_tools(
            servers=servers,
            capabilities=capabilities,
            enabled_only=enabled_only,
            available_only=available_only,
        )
        query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))

        matches: list[tuple[int, ToolMetadata]] = []
        for meta in candidates:
            searchable = " ".join(
                (
                    meta.name,
                    meta.tool_name,
                    meta.server,
                    meta.capability,
                    meta.description,
                    " ".join(
                        str(name)
                        for name in (meta.input_schema or {}).get("properties", {})
                    ),
                )
            ).lower()
            overlap = query_terms.intersection(
                set(re.findall(r"[a-z0-9]+", searchable))
            )
            if overlap:
                matches.append((len(overlap), meta))

        matches.sort(key=lambda item: (-item[0], item[1].name))
        logger.info(
            "[TOOL SEARCH] Query: %s | Candidates: %d",
            query,
            len(matches),
        )
        return [meta for _, meta in matches]

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        *,
        servers: Iterable[str] | None = None,
        capabilities: Iterable[str] | None = None,
    ) -> ToolSnapshot:
        """
        Create an immutable ToolSnapshot containing only eligible, enabled tools.
        """
        tools = self.get_tools(servers=servers, capabilities=capabilities, enabled_only=True)
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
        """Return a structured summary of the current registry state."""
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
        }
