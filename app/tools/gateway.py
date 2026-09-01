"""Jarvis-owned boundary for external workers requesting tool capabilities.

This module deliberately contains no MCP client or tool-selection logic. It
serializes registry metadata for discovery and delegates execution to the
existing :class:`ToolExecutionGateway`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.discovery import DiscoveryRequest, DiscoveryResult
from app.tools.execution import ExecutionResult, ToolExecutionGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class GatewaySearchRequest:
    """Provider-neutral discovery request exposed to a worker boundary."""

    query: str = ""
    capabilities: tuple[str, ...] = ()
    servers: tuple[str, ...] = ()
    tool_name: str | None = None
    description: str | None = None
    parameter_name: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "GatewaySearchRequest":
        if not isinstance(payload, dict):
            raise ValueError("search request must be an object")

        def values(name: str) -> tuple[str, ...]:
            value = payload.get(name, ())
            if isinstance(value, str):
                return (value,) if value.strip() else ()
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{name} must be a string or array")
            return tuple(str(item).strip() for item in value if str(item).strip())

        query = payload.get("query", "")
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        return cls(
            query=query.strip(),
            capabilities=values("capabilities"),
            servers=values("servers"),
            tool_name=_optional_text(payload, "tool_name"),
            description=_optional_text(payload, "description"),
            parameter_name=_optional_text(payload, "parameter_name"),
        )


@dataclass(frozen=True)
class GatewaySearchResponse:
    """Sanitized candidate metadata returned to an external worker."""

    tools: list[dict[str, Any]]
    total_candidates: int

    def to_dict(self) -> dict[str, Any]:
        return {"tools": self.tools, "total_candidates": self.total_candidates}


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    return value or None


def _serialize_metadata(meta: ToolMetadata) -> dict[str, Any]:
    """Expose only capability metadata needed to form a later execute call."""
    return {
        "name": meta.name,
        "tool_name": meta.tool_name,
        "description": meta.description,
        "input_schema": meta.input_schema,
        "parameter_names": meta.parameter_names,
        "capability": meta.capability,
        "server": meta.server,
    }


class JarvisToolGateway:
    """Thin worker-facing facade over the canonical registry and executor."""

    def __init__(
        self,
        registry: ToolRegistry,
        execution_gateway: ToolExecutionGateway,
    ) -> None:
        self.registry = registry
        self.execution_gateway = execution_gateway

    def search(
        self,
        request: GatewaySearchRequest | dict[str, Any],
    ) -> GatewaySearchResponse:
        """Return enabled and available candidate metadata deterministically."""
        if isinstance(request, dict):
            request = GatewaySearchRequest.from_mapping(request)
        if not isinstance(request, GatewaySearchRequest):
            raise TypeError("request must be a GatewaySearchRequest or object")

        discovery_request = DiscoveryRequest(
            query=request.query,
            capabilities=request.capabilities,
            servers=request.servers,
            tool_name=request.tool_name,
            description=request.description,
            parameter_name=request.parameter_name,
            enabled_only=True,
            available_only=True,
        )
        result: DiscoveryResult = self.registry.discover(discovery_request)
        return GatewaySearchResponse(
            tools=[_serialize_metadata(meta) for meta in result.candidates],
            total_candidates=result.total_candidates,
        )

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Delegate execution and preserve its normalized result contract."""
        return await self.execution_gateway.execute(tool_name, arguments)
