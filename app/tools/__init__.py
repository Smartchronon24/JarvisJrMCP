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

# Global singleton — the single canonical tool catalog for Jarvis.
tool_registry: ToolRegistry = ToolRegistry()

__all__ = [
    "ToolRegistry",
    "ToolMetadata",
    "ToolSnapshot",
    "tool_registry",
]
