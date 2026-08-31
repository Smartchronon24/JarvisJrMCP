"""Tool discovery boundary.

This module defines the provider-neutral discovery abstraction used to turn a
registry catalog into a candidate set for the selector and downstream worker.

The current implementation is intentionally deterministic and lightweight; it can
be replaced later by a semantic or hybrid strategy without altering the
registry, worker, or MCP execution boundary.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from app.tools.models import ToolMetadata

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class DiscoveryRequest:
    """Context needed to ask the registry for relevant candidate tools."""

    query: str = ""
    capabilities: tuple[str, ...] = ()
    servers: tuple[str, ...] = ()
    tool_name: str | None = None
    description: str | None = None
    parameter_name: str | None = None
    enabled_only: bool = True
    available_only: bool = True


@dataclass(frozen=True)
class DiscoveryResult:
    """A deterministic candidate set for downstream selection."""

    request: DiscoveryRequest
    candidates: list[ToolMetadata]
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    total_candidates: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_terms", dict(self.matched_terms or {}))
        object.__setattr__(self, "total_candidates", len(self.candidates))


class ToolDiscovery(ABC):
    """Abstract boundary for candidate discovery from registry metadata."""

    @abstractmethod
    def discover(self, registry: "ToolRegistry", request: DiscoveryRequest) -> DiscoveryResult:
        raise NotImplementedError


def _normalize_token(token: str) -> str:
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


_GENERIC_SYNONYMS = {
    "msg": "message",
    "msgs": "message",
    "message": "message",
    "messages": "message",
    "chat": "message",
    "chats": "message",
    "contact": "contact",
    "contacts": "contact",
    "person": "contact",
    "people": "contact",
    "phone": "contact",
    "number": "contact",
    "search": "find",
    "finds": "find",
    "lookup": "find",
    "look": "find",
    "read": "view",
    "reads": "view",
    "view": "view",
    "views": "view",
    "show": "view",
    "shows": "view",
    "list": "view",
    "lists": "view",
    "recent": "latest",
    "latest": "latest",
    "new": "latest",
    "send": "message",
    "sends": "message",
    "reply": "message",
    "replies": "message",
    "replied": "message",
    "fetch": "get",
    "get": "get",
    "gets": "get",
    "retrieve": "get",
    "retrieves": "get",
    "check": "view",
    "checks": "view",
}


_STOP_WORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "if", "in", "into", "is", "it", "its", "just", "my", "name", "not",
    "of", "on", "or", "our", "should", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "tool", "up",
    "was", "we", "were", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
}


def _normalize_query_token(token: str) -> str:
    normalized = _normalize_token(token)
    if not normalized:
        return ""
    return _GENERIC_SYNONYMS.get(normalized, normalized)


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    tokens = {
        _normalize_query_token(token)
        for token in re.findall(r"[a-z0-9_]+", value.lower())
        if token and token not in _STOP_WORDS
    }
    return {token for token in tokens if token}


class DeterministicToolDiscovery(ToolDiscovery):
    """Current discovery implementation for registry-backed candidate lookup."""

    def _candidate_terms(self, meta: ToolMetadata) -> dict[str, set[str]]:
        return {
            "name": _tokenize(meta.name),
            "tool_name": _tokenize(meta.tool_name),
            "server": _tokenize(meta.server),
            "capability": _tokenize(meta.capability),
            "description": _tokenize(meta.description),
            "parameters": _tokenize(" ".join(meta.parameter_names)),
        }

    def discover(self, registry: "ToolRegistry", request: DiscoveryRequest) -> DiscoveryResult:
        candidates = registry.get_tools(
            servers=request.servers,
            capabilities=request.capabilities,
            enabled_only=request.enabled_only,
            available_only=request.available_only,
        )

        if not request.query and request.tool_name is None and request.description is None and request.parameter_name is None and not request.capabilities and not request.servers:
            return DiscoveryResult(request=request, candidates=[])

        query_terms = _tokenize(request.query)
        if request.tool_name is not None:
            tool_tokens = _tokenize(request.tool_name)
            query_terms |= tool_tokens
        if request.description is not None:
            query_terms |= _tokenize(request.description)
        if request.parameter_name is not None:
            query_terms |= _tokenize(request.parameter_name)

        scored: list[tuple[int, ToolMetadata, dict[str, list[str]]]] = []
        seen: set[str] = set()
        for meta in candidates:
            if meta.name in seen:
                continue
            seen.add(meta.name)

            if request.tool_name is not None:
                tool_name_text = str(meta.tool_name).lower()
                request_name = request.tool_name.lower()
                if request_name not in tool_name_text and request_name not in str(meta.name).lower():
                    continue

            if request.description is not None:
                desc_text = (meta.description or "").lower()
                if request.description.lower() not in desc_text:
                    continue

            if request.parameter_name is not None:
                parameter_match = request.parameter_name.lower() in " ".join(meta.parameter_names).lower()
                if not parameter_match:
                    continue

            field_hits: dict[str, list[str]] = {}
            score = 0
            if not query_terms:
                query_terms = set()
                score = 1

            for field_name, field_tokens in self._candidate_terms(meta).items():
                hits = sorted(query_terms.intersection(field_tokens))
                if not hits:
                    continue
                field_hits[field_name] = hits
                weight = {
                    "name": 12,
                    "tool_name": 10,
                    "server": 6,
                    "capability": 8,
                    "description": 4,
                    "parameters": 5,
                }.get(field_name, 2)
                score += len(hits) * weight

            if request.query and not field_hits:
                # Allow a lightweight fallback for natural-language queries that match
                # the tool name or description even when token normalization is not exact.
                combined = meta.search_text.lower()
                raw_query_terms = set(request.query.lower().split())
                if not any(term in combined for term in raw_query_terms if len(term) > 3):
                    continue
                # If we passed the fallback but have no field_hits, we should still give it a minimal score
                score = 1

            scored.append((score, meta, field_hits))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        deduped = [(score, meta, field_hits) for score, meta, field_hits in scored if meta.name]
        results = [meta for _, meta, _ in deduped]
        matched_terms = {meta.name: sorted(field_hits) for _, meta, field_hits in deduped}
        return DiscoveryResult(request=request, candidates=results, matched_terms=matched_terms)


def _as_tuple(value: Iterable[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def default_discovery_request(
    query: str = "",
    *,
    capabilities: Iterable[str] | str | None = None,
    servers: Iterable[str] | str | None = None,
    tool_name: str | None = None,
    description: str | None = None,
    parameter_name: str | None = None,
    enabled_only: bool = True,
    available_only: bool = True,
) -> DiscoveryRequest:
    return DiscoveryRequest(
        query=query,
        capabilities=_as_tuple(capabilities),
        servers=_as_tuple(servers),
        tool_name=tool_name,
        description=description,
        parameter_name=parameter_name,
        enabled_only=enabled_only,
        available_only=available_only,
    )


def create_default_discovery() -> ToolDiscovery:
    return DeterministicToolDiscovery()


tool_discovery: ToolDiscovery = create_default_discovery()

__all__ = [
    "DiscoveryRequest",
    "DiscoveryResult",
    "ToolDiscovery",
    "DeterministicToolDiscovery",
    "default_discovery_request",
    "tool_discovery",
]
