"""Provider-agnostic, deterministic selection of task-relevant MCP tools."""

from __future__ import annotations

import abc
import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Set

from app.tools.models import ToolMetadata

logger = logging.getLogger("jarvis.tool_selector")
MAX_SELECTED_TOOLS = max(1, int(os.getenv("JARVIS_MAX_SELECTED_TOOLS", "15")))

_INTENT_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "SEARCH": ("find", "search", "look up", "retrieve", "recent", "latest"),
    "READ": ("read", "show", "inspect", "view", "list", "contents", "remember"),
    "WRITE": ("write", "save", "create", "update", "edit", "modify"),
    "SEND": ("send", "reply", "message", "notify"),
    "DELETE": ("delete", "remove", "destroy"),
    "EXECUTE": ("run", "execute", "command", "pytest", "npm", "shell"),
    "NAVIGATE": ("open", "navigate", "browse", "website", "webpage"),
    "SCREENSHOT": ("screenshot", "screen shot", "capture"),
    "RECORD": ("record", "recording"),
}

_NEGATIVE_TERMS = {
    "send", "delete", "destroy", "write", "modify", "upload", "record",
}

_WORKFLOWS: Mapping[str, tuple[str, ...]] = {
    "terminal_execute": ("createSession", "type", "sendKey", "getContent"),
    "whatsapp_find_messages": (
        "search_contacts",
        "get_direct_chat_by_contact",
        "list_messages",
    ),
}

_CAPABILITY_TERMS: Mapping[str, tuple[str, ...]] = {
    "filesystem": ("file", "folder", "directory", "path"),
    "terminal": ("terminal", "shell", "command", "pytest", "npm", "run", "execute"),
    "communication": ("whatsapp", "message", "contact", "chat"),
    "memory": ("memory", "remember", "recollect", "recall", "stored"),
    "web_research": ("web", "research", "news", "latest", "current", "search"),
    "browser": ("browser", "website", "webpage", "navigate", "click"),
}


class ToolSelectionStrategy(abc.ABC):
    """Extension point for future semantic or model-assisted selectors."""

    @abc.abstractmethod
    def select(
        self,
        request: str,
        candidates: Iterable[ToolMetadata] | None = None,
        max_tools: int | None = None,
        runtime_state: Mapping[str, object] | None = None,
    ) -> List[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class _ScoredTool:
    metadata: ToolMetadata
    score: int
    direct: bool


class DeterministicToolSelector(ToolSelectionStrategy):
    """Rank registry metadata using task terms, intents, and workflows."""

    def __init__(self) -> None:
        self._token_pattern = re.compile(r"[a-z0-9]+", re.IGNORECASE)

    def _tokens(self, value: str) -> Set[str]:
        return set(self._token_pattern.findall(value.lower()))

    def _intents(self, request: str) -> Set[str]:
        lowered = request.lower()
        return {
            intent
            for intent, terms in _INTENT_PATTERNS.items()
            if any(
                term in lowered
                if " " in term
                else re.search(rf"\b{re.escape(term)}\b", lowered)
                for term in terms
            )
        }

    def _capabilities(self, request: str) -> Set[str]:
        lowered = request.lower()
        capabilities = {
            capability
            for capability, terms in _CAPABILITY_TERMS.items()
            if any(term in lowered for term in terms)
        }
        terminal_terms = _CAPABILITY_TERMS["terminal"]
        if "filesystem" in capabilities and not any(
            re.search(rf"\b{re.escape(term)}\b", lowered)
            for term in terminal_terms
        ):
            capabilities.discard("terminal")
        return capabilities

    def _tool_text(self, tool: ToolMetadata) -> str:
        schema = tool.input_schema or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        parameter_text = " ".join(str(name) for name in properties)
        return " ".join((tool.name, tool.tool_name, tool.server, tool.capability,
                         tool.description, parameter_text))

    def _score(
        self,
        request: str,
        tool: ToolMetadata,
        intents: Set[str],
        capabilities: Set[str],
    ) -> _ScoredTool:
        task_tokens = self._tokens(request)
        tool_tokens = self._tokens(" ".join((
            tool.tool_name,
            tool.description,
            " ".join(
                str(name)
                for name in (
                    (tool.input_schema or {}).get("properties", {})
                    if isinstance(tool.input_schema, dict)
                    else {}
                )
            ),
        )))
        overlap = task_tokens & tool_tokens
        score = len(overlap) * 4
        direct = bool(overlap)
        name = tool.tool_name.lower()
        capability = tool.capability.lower()
        if capabilities:
            if capability in capabilities or (
                capability == "browser" and "browser" in capabilities
            ):
                score += 6
            else:
                score -= 10

        if "SEARCH" in intents and any(term in name for term in ("search", "find", "list", "get")):
            score += 8
            direct = True
        if "READ" in intents and any(term in name for term in ("read", "get", "list", "content", "search")):
            score += 5
            direct = True
        if "SEND" in intents and any(term in name for term in ("send", "reply", "message")):
            score += 10
            direct = True
        if "EXECUTE" in intents and capability == "terminal" and name in {"type", "sendkey", "getcontent", "createsession"}:
            score += 8
            direct = True
        if "SCREENSHOT" in intents and "screenshot" in name:
            score += 14
            direct = True
        if "RECORD" in intents and "record" in name:
            score += 12
            direct = True
        if "NAVIGATE" in intents and any(term in name for term in ("navigate", "open", "click")):
            score += 8
            direct = True
        if capability == "terminal" and "EXECUTE" not in intents and "SCREENSHOT" not in intents:
            score -= 20
            direct = False

        explicit_operation = any(
            intent in intents for intent in ("WRITE", "SEND", "DELETE", "RECORD", "SCREENSHOT")
        )
        if not explicit_operation and any(term in name for term in _NEGATIVE_TERMS):
            score -= 12
        return _ScoredTool(tool, score, direct)

    def _workflow_names(
        self,
        request: str,
        candidates: Iterable[ToolMetadata],
        intents: Set[str],
        runtime_state: Mapping[str, object] | None,
    ) -> Set[str]:
        candidate_names = {tool.name for tool in candidates}
        lowered = request.lower()
        names: Set[str] = set()
        if "EXECUTE" in intents and any(word in lowered for word in ("terminal", "command", "python", "shell", "run")):
            names.update(
                f"terminal__{name}" for name in _WORKFLOWS["terminal_execute"]
            )
            if runtime_state and runtime_state.get("terminal_session_available"):
                names.discard("terminal__createSession")
        if "SEARCH" in intents and "whatsapp" in lowered and "message" in lowered:
            names.update(
                f"whatsapp__{name}" for name in _WORKFLOWS["whatsapp_find_messages"]
            )
        return names & candidate_names

    def select(
        self,
        request: str,
        candidates: Iterable[ToolMetadata],
        max_tools: int | None = None,
        runtime_state: Mapping[str, object] | None = None,
    ) -> List[str]:
        if candidates is None:
            raise ValueError("candidates must be provided to the selector")
        candidate_list = list(candidates)
        limit = max(1, max_tools if max_tools is not None else MAX_SELECTED_TOOLS)
        intents = self._intents(request)
        capabilities = self._capabilities(request)
        workflow_names = self._workflow_names(request, candidate_list, intents, runtime_state)
        scored = [self._score(request, tool, intents, capabilities) for tool in candidate_list]
        # A positive lexical overlap alone is not sufficient: shared generic
        # words such as "file" or "message" must still clear a relevance bar.
        selected = [item for item in scored if item.direct and item.score >= 6]

        for item in scored:
            if item.metadata.name in workflow_names and item not in selected:
                selected.append(item)

        if not selected:
            logger.info("[SELECTOR] No confident tool matches; falling back to capability candidates.")
            selected = scored

        selected.sort(key=lambda item: (-item.score, item.metadata.name))
        selected_names = [item.metadata.name for item in selected[:limit]]
        logger.info(
            "[SELECTOR] Task: %s | Candidates: %d | Selected: %d | Intents: %s",
            request, len(candidate_list), len(selected_names), ",".join(sorted(intents)),
        )
        logger.info("[SELECTOR] Selected: %s", ", ".join(selected_names))
        rejected = [item.metadata.name for item in scored if item.metadata.name not in selected_names]
        if rejected:
            logger.info("[SELECTOR] Rejected: %s", ", ".join(rejected))
        return selected_names


selector = DeterministicToolSelector()

__all__ = ["DeterministicToolSelector", "MAX_SELECTED_TOOLS", "ToolSelectionStrategy", "selector"]
