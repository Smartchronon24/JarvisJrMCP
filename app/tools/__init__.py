"""
app.tools — Tool Registry package
==================================
Exposes the global ``tool_registry`` singleton.

Import this anywhere in Jarvis to access the registry::

    from app.tools import tool_registry

    tools = tool_registry.get_tools_for_capability("memory")
"""

from app.tools.registry import ToolRegistry
from app.tools.models import ToolMetadata, ToolSnapshot
from app.tools.discovery import (
    DeterministicToolDiscovery,
    DiscoveryRequest,
    DiscoveryResult,
    ToolDiscovery,
    tool_discovery,
)
from app.tools.gateway import (
    GatewaySearchRequest,
    GatewaySearchResponse,
    JarvisToolGateway,
)

# Global singleton — the single canonical tool catalog for Jarvis.
tool_registry: ToolRegistry = ToolRegistry()

__all__ = [
    "ToolRegistry",
    "ToolMetadata",
    "ToolSnapshot",
    "ToolDiscovery",
    "DiscoveryRequest",
    "DiscoveryResult",
    "DeterministicToolDiscovery",
    "tool_discovery",
    "tool_registry",
    "GatewaySearchRequest",
    "GatewaySearchResponse",
    "JarvisToolGateway",
]
