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

from app.tools.discovery import DiscoveryRequest, DiscoveryResult, DeterministicToolDiscovery
from app.tools.models import ToolMetadata, ToolMetadataError, ToolSnapshot, guess_capability

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
    return guess_capability(server_name)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_STOP_WORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "if", "in", "into", "is", "it", "its", "just", "my", "name", "not",
    "of", "on", "or", "our", "should", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "tool", "up",
    "was", "we", "were", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
}


def _normalize_token(token: str) -> str:
    """Normalize common word variants to keep matching deterministic and lightweight."""
    value = token.lower().strip()
    if not value:
        return value
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("sses") and len(value) > 5:
        return value[:-2]
    if value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        return value[:-1]
    return value


def _tokenize(value: str | None) -> set[str]:
    """Return a deterministic token set for text matching."""
    if not value:
        return set()
    tokens = {
        _normalize_token(token)
        for token in re.findall(r"[a-z0-9_]+", value.lower())
        if token and token not in _STOP_WORDS
    }
    return {token for token in tokens if token}


def _matches_term(candidate: str | None, target: str | None) -> bool:
    """Match a field against a target using normalized substring semantics."""
    if target is None:
        return True
    candidate_text = (candidate or "").lower()
    target_text = (target or "").lower().strip()
    if not target_text:
        return True
    return target_text in candidate_text


class ToolRegistry:
    """
    In-memory catalog of all discovered MCP tools.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._discovery = DeterministicToolDiscovery()
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
        capability: Optional[str] = None,
    ) -> ToolMetadata:
        """
        Convenience method: build a ``ToolMetadata`` from a raw MCP tool
        object and register it.
        """
        raw_name = getattr(mcp_tool, "name", None)
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ToolMetadataError("MCP tool name must be a non-empty string")
        raw_name = raw_name.strip()
        server_name = str(server_name).strip()
        if not server_name:
            raise ToolMetadataError("MCP server name must be a non-empty string")
        description: str = getattr(mcp_tool, "description", "") or ""

        # Preserve the raw schema verbatim
        input_schema = getattr(mcp_tool, "inputSchema", None)
        if input_schema is None:
            input_schema = getattr(mcp_tool, "input_schema", None)
        if input_schema is None:
            input_schema = {}
        if not isinstance(input_schema, dict):
            raise ToolMetadataError("MCP tool input schema must be an object")

        scoped_name = f"{server_name}__{raw_name}"
        if capability is None:
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
        if isinstance(servers, str):
            srv_set = {servers}
        elif servers is not None:
            server_values = tuple(servers)
            srv_set = set(server_values) if server_values else None
        else:
            srv_set = None

        if isinstance(capabilities, str):
            cap_set = {capabilities}
        elif capabilities is not None:
            cap_values = tuple(capabilities)
            cap_set = set(cap_values) if cap_values else None
        else:
            cap_set = None

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

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def get_tools_for_server(self, server: str, *, enabled_only: bool = True, available_only: bool = False) -> list[ToolMetadata]:
        """Return all tools belonging to the given server name."""
        return self.get_tools(servers=server, enabled_only=enabled_only, available_only=available_only)

    def get_tools_for_servers(
        self,
        servers: Iterable[str] | str | None,
        *,
        enabled_only: bool = True,
        available_only: bool = False,
    ) -> list[ToolMetadata]:
        """Return all tools belonging to the given server set."""
        if servers is None:
            return []
        if isinstance(servers, str):
            return self.get_tools(servers=servers, enabled_only=enabled_only, available_only=available_only)
        server_values = tuple(servers)
        if not server_values:
            return []
        return self.get_tools(servers=server_values, enabled_only=enabled_only, available_only=available_only)

    def get_tools_for_capability(self, capability: str, *, enabled_only: bool = True, available_only: bool = False) -> list[ToolMetadata]:
        """Return all tools that belong to the given capability bucket."""
        return self.get_tools(capabilities=capability, enabled_only=enabled_only, available_only=available_only)

    def get_tools_for_capabilities(
        self,
        capabilities: Iterable[str] | str | None,
        *,
        enabled_only: bool = True,
        available_only: bool = False,
    ) -> list[ToolMetadata]:
        """Return all tools belonging to the given capability set."""
        if capabilities is None:
            return []
        if isinstance(capabilities, str):
            return self.get_tools(capabilities=capabilities, enabled_only=enabled_only, available_only=available_only)
        capability_values = tuple(capabilities)
        if not capability_values:
            return []
        return self.get_tools(capabilities=capability_values, enabled_only=enabled_only, available_only=available_only)

    def get_enabled_tool_names(
        self,
        *,
        server: str | None = None,
        capability: str | None = None,
    ) -> set[str]:
        """Return the enabled tool names for the requested server/capability."""
        query_servers = server
        query_capabilities = capability
        return {
            meta.name
            for meta in self.get_tools(
                servers=query_servers,
                capabilities=query_capabilities,
                enabled_only=True,
            )
        }

    # ------------------------------------------------------------------
    # Discovery Foundation
    # ------------------------------------------------------------------

    def discover_tools(
        self,
        query: str | None = None,
        *,
        capabilities: Iterable[str] | None = None,
        servers: Iterable[str] | None = None,
        tool_name: str | None = None,
        description: str | None = None,
        parameter_name: str | None = None,
        enabled_only: bool = True,
        available_only: bool = True,
    ) -> list[ToolMetadata]:
        """Discover candidate tools through the current provider-neutral discovery strategy."""
        request = DiscoveryRequest(
            query=query or "",
            capabilities=tuple(capabilities) if capabilities is not None else (),
            servers=tuple(servers) if servers is not None else (),
            tool_name=tool_name,
            description=description,
            parameter_name=parameter_name,
            enabled_only=enabled_only,
            available_only=available_only,
        )
        return self.discover(request).candidates

    def search_tools(
        self,
        query: str,
        *,
        capabilities: Iterable[str] | None = None,
        servers: Iterable[str] | None = None,
        enabled_only: bool = True,
        available_only: bool = True,
        tool_name: str | None = None,
        description: str | None = None,
        parameter_name: str | None = None,
    ) -> list[ToolMetadata]:
        """Backward-compatible query API for deterministic registry discovery."""
        if not query and not any((capabilities, servers, tool_name, description, parameter_name)):
            return []
        return self.discover_tools(
            query=query,
            capabilities=capabilities,
            servers=servers,
            tool_name=tool_name,
            description=description,
            parameter_name=parameter_name,
            enabled_only=enabled_only,
            available_only=available_only,
        )

    def set_discovery_strategy(self, strategy: object) -> None:
        """Replace the discovery implementation used by this registry."""
        self._discovery = strategy

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        """Run the current discovery strategy against this registry."""
        return self._discovery.discover(self, request)

    def find_tools(self, *args, **kwargs) -> list[ToolMetadata]:
        """Alias for discover_tools for clearer discovery semantics."""
        return self.discover_tools(*args, **kwargs)

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
            "capabilities": {cap: sorted(tools) for cap, tools in sorted(capabilities.items())},
        }
