"""Jarvis-owned boundary for external workers requesting tool capabilities.

This module deliberately contains no MCP client or tool-selection logic. It
serializes registry metadata for discovery and delegates execution to the
existing :class:`ToolExecutionGateway`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.tools.discovery import DiscoveryRequest, DiscoveryResult
from app.tools.execution import ExecutionResult, ToolExecutionGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.selector import DeterministicToolSelector


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

    async def external_action(
        self,
        request: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve and execute one external capability for a natural-language request."""
        if not isinstance(request, str) or not request.strip():
            raise ValueError("external_action requires a non-empty request")

        resolved_arguments = dict(arguments or {})
        query = request
        if "url" in resolved_arguments:
            query = f"{query} browser navigate"
        discovery = self.search(GatewaySearchRequest(query=query))
        if not discovery.tools:
            return {
                "ok": False,
                "status": "capability_not_found",
                "error_type": "capability_not_found",
                "message": "No enabled Jarvis capability matched the request.",
                "candidates": [],
            }

        selector = DeterministicToolSelector()
        metadata = [self.registry.get_tool(tool["name"]) for tool in discovery.tools]
        candidates = [tool for tool in metadata if tool is not None]
        selected = selector.select(request, candidates, max_tools=1)
        if not selected:
            # Navigation verbs can omit the word "browser"; broaden discovery
            # without binding the proxy to a particular website or capability.
            broadened = self.search(
                GatewaySearchRequest(query=f"{request} browser")
            )
            metadata = [self.registry.get_tool(tool["name"]) for tool in broadened.tools]
            candidates = [tool for tool in metadata if tool is not None]
            selected = selector.select(request, candidates, max_tools=1)
            if selected:
                discovery = broadened
        if not selected:
            return {
                "ok": False,
                "status": "capability_not_found",
                "error_type": "capability_not_found",
                "message": "No enabled Jarvis capability could be selected.",
                "candidates": discovery.tools,
            }

        selected_meta = self.registry.get_tool(selected[0])
        if selected_meta is not None:
            resolved_arguments = self._infer_arguments(
                request, selected_meta, resolved_arguments
            )
        result = await self.execute(selected[0], resolved_arguments)
        return {
            "ok": not result.is_error,
            "status": result.status,
            "error_type": result.error_type,
            "message": result.content,
            "tool_name": selected[0],
            "metadata": result.metadata,
            "retryable": result.retryable,
        }

    @staticmethod
    def _infer_arguments(
        request: str,
        metadata: ToolMetadata,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Fill obvious scalar targets using the selected tool's schema."""
        parameter_names = {
            str(name).lower(): str(name) for name in metadata.parameter_names
        }
        if "url" in parameter_names and "url" not in arguments:
            url_match = re.search(r"https?://[^\s]+", request, re.IGNORECASE)
            if url_match:
                arguments[parameter_names["url"]] = url_match.group(0).rstrip(".,!?")
            else:
                target_match = re.search(
                    r"\b(?:open|launch|visit|navigate to|go to|take me to)\s+"
                    r"([a-z0-9][a-z0-9.-]*)",
                    request,
                    re.IGNORECASE,
                )
                if target_match:
                    target = target_match.group(1).rstrip(".")
                    if "." not in target:
                        target = f"{target}.com"
                    arguments[parameter_names["url"]] = f"https://{target}"

        phone_match = re.search(
            r"(?<!\w)\+?[0-9][0-9()\s.-]{6,}[0-9](?!\w)", request
        )
        if phone_match:
            phone = re.sub(r"[()\s.-]", "", phone_match.group(0))
            for name in ("phone_number", "phone", "identifier", "query"):
                schema_name = parameter_names.get(name)
                if schema_name and schema_name not in arguments:
                    arguments[schema_name] = phone
                    break
        return arguments
