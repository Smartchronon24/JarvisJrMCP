"""
Tool Selection — A4 Intelligent Tool Discovery & Selection
==========================================================
This module provides the selection layer that takes a candidate pool produced
by discovery and narrows it down to the minimal toolset the Worker actually needs.

Architecture
------------
::

    Discovery Candidates
           │
           ▼
    ┌──────────────────┐
    │   LLMToolSelector │  ← primary strategy (A4)
    └──────┬───────────┘
           │  on failure / no LLM configured
           ▼
    ┌──────────────────────────┐
    │ DeterministicToolSelector │  ← fallback strategy
    └──────────────────────────┘
           │
           ▼
    Final tool names → ToolSnapshot → Worker

Design principles
-----------------
* The selection layer is provider-agnostic.  ``LLMToolSelector`` calls
  ``get_provider(get_model_config("selector").provider)`` — the same
  dependency-injection pattern used by the Router and Worker.
* Python is responsible for: candidate marshalling, prompt construction,
  response parsing and validation, fallback.
* The LLM is responsible for: understanding the task, recognising
  multi-step workflows, filtering candidates by semantic relevance.
* ``DeterministicToolSelector`` is preserved intact as the fallback.
  Do NOT add more keyword rules to it in future phases.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Set

from app.tools.models import ToolMetadata

logger = logging.getLogger("jarvis.tool_selector")

MAX_SELECTED_TOOLS = max(1, int(os.getenv("JARVIS_MAX_SELECTED_TOOLS", "15")))


# ---------------------------------------------------------------------------
# Strategy base
# ---------------------------------------------------------------------------

class ToolSelectionStrategy(abc.ABC):
    """
    Extension point for tool-selection implementations.

    A strategy receives candidate ``ToolMetadata`` objects produced by
    discovery and returns a list of scoped tool names (``server__tool``)
    representing the minimal set that should be passed to the Worker.
    """

    @abc.abstractmethod
    def select(
        self,
        request: str,
        candidates: Iterable[ToolMetadata],
        max_tools: int | None = None,
        runtime_state: Mapping[str, object] | None = None,
    ) -> List[str]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Deterministic fallback selector  (preserved from A3 / TR-5)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "SEARCH": ("find", "search", "look up", "retrieve", "recent", "latest"),
    "READ": ("read", "show", "inspect", "view", "list", "contents", "remember", "check"),
    "WRITE": ("write", "save", "create", "update", "edit", "modify"),
    "SEND": ("send", "reply", "message", "notify", "replied"),
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
    "communication": ("whatsapp", "message", "contact", "chat", "reply", "replied"),
    "memory": ("memory", "remember", "recollect", "recall", "stored"),
    "web_research": ("web", "research", "news", "latest", "current", "search"),
    "browser": ("browser", "website", "webpage", "navigate", "click"),
}


@dataclass(frozen=True)
class _ScoredTool:
    metadata: ToolMetadata
    score: int
    direct: bool


class DeterministicToolSelector(ToolSelectionStrategy):
    """
    Rank registry metadata using task terms, intents, and workflows.

    Role: fallback selector — used when ``LLMToolSelector`` is unavailable
    or encounters an error.  Do NOT add more keyword rules here.
    """

    def __init__(self) -> None:
        self._token_pattern = re.compile(r"[a-z0-9]+", re.IGNORECASE)

    def _tokens(self, value: str) -> Set[str]:
        return set(self._token_pattern.findall(value.lower()))

    def _intents(self, request: str) -> Set[str]:
        lowered = request.lower()
        intents = {
            intent
            for intent, terms in _INTENT_PATTERNS.items()
            if any(
                term in lowered
                if " " in term
                else re.search(rf"\b{re.escape(term)}\b", lowered)
                for term in terms
            )
        }
        if "open_url" in lowered:
            intents.add("NAVIGATE")
        return intents

    def _capabilities(self, request: str) -> Set[str]:
        lowered = request.lower()
        capabilities = {
            capability
            for capability, terms in _CAPABILITY_TERMS.items()
            if any(term in lowered for term in terms)
        }
        if any(
            re.search(rf"\b{re.escape(term)}\b", lowered)
            for term in _INTENT_PATTERNS["NAVIGATE"]
        ):
            capabilities.add("browser")
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
        phone_requested = bool(
            re.search(r"(?<!\w)\+?[0-9][0-9()\s.-]{6,}[0-9](?!\w)", request)
        )
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
        if phone_requested:
            parameter_names = {
                str(name).lower()
                for name in tool.input_schema.get("properties", {})
            } if isinstance(tool.input_schema, dict) else set()
            if parameter_names.intersection({"phone", "phone_number", "identifier", "query"}):
                score += 20
                direct = True
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
        if "NAVIGATE" in intents:
            if "navigate" in name:
                score += 14
                direct = True
            elif "open" in name:
                score += 10
                direct = True
            elif "click" in name and "click" in self._tokens(request):
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
        selected = [item for item in scored if item.direct and item.score >= 6]

        for item in scored:
            if item.metadata.name in workflow_names and item not in selected:
                selected.append(item)

        if not selected:
            logger.info("[SELECTOR:deterministic] No confident matches; checking for partial matches.")
            selected = [item for item in scored if item.score > 4]

        selected.sort(key=lambda item: (-item.score, item.metadata.name))
        selected_names = [item.metadata.name for item in selected[:limit]]
        logger.info(
            "[SELECTOR:deterministic] Task: %s | Candidates: %d | Selected: %d | Intents: %s",
            request[:60], len(candidate_list), len(selected_names), ",".join(sorted(intents)),
        )
        return selected_names


# ---------------------------------------------------------------------------
# LLM Tool Selector  (A4 primary strategy)
# ---------------------------------------------------------------------------

_SELECTION_PROMPT_TEMPLATE = """\
You are a tool selection assistant for an AI agent called Jarvis.

Your task: Given a user request and a list of available tools, choose the MINIMAL set of tools the agent needs to complete the task.

RULES:
- Only select tools that are genuinely needed for this specific task.
- If the task requires multiple steps (e.g. find a contact then read their messages), include all tools needed for the full workflow.
- Do NOT include tools for actions not requested (e.g. do not include send_message unless the user wants to send something).
- If no tools are needed (e.g. simple greeting), return an empty list.
- Return ONLY a JSON array of tool names from the provided list. No explanation.

USER REQUEST:
{request}

AVAILABLE TOOLS:
{tools_block}

Respond with ONLY a valid JSON array, for example:
["tool_name_1", "tool_name_2"]
"""


def _format_tools_block(candidates: list[ToolMetadata]) -> str:
    """
    Create a compact, LLM-readable description of candidate tools.
    Uses name + description + parameter names — NOT the full JSON schema.
    """
    lines = []
    for meta in candidates:
        params = ", ".join(meta.parameter_names) if meta.parameter_names else "none"
        lines.append(f"- {meta.name}: {meta.description or '(no description)'} [params: {params}]")
    return "\n".join(lines)


def _parse_llm_selection(
    raw: str,
    valid_names: set[str],
) -> list[str] | None:
    """
    Parse and validate the LLM's JSON response.
    Returns None if the response is unparseable or contains no valid names.
    """
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first and last fence lines
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    # Try to extract the first JSON array from the response
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if not match:
        logger.warning("[SELECTOR:llm] Response contains no JSON array: %r", text[:120])
        return None

    try:
        names = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.warning("[SELECTOR:llm] JSON parse error: %s | raw: %r", exc, text[:120])
        return None

    if not isinstance(names, list):
        return None

    # Validate: only return names that are in the candidate set
    validated = [n for n in names if isinstance(n, str) and n in valid_names]
    return validated


def _validate_selected_tools(selected: Iterable[str], valid_names: set[str]) -> list[str]:
    """Keep the final selection within the candidate set and drop hallucinated names."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in selected:
        if not isinstance(name, str):
            continue
        norm = name.strip()
        if not norm or norm in seen or norm not in valid_names:
            continue
        cleaned.append(norm)
        seen.add(norm)
    return cleaned


class LLMToolSelector(ToolSelectionStrategy):
    """
    Intelligent tool selector that uses an LLM to choose the minimal relevant
    toolset from the discovery candidates.

    The LLM is given a compact, structured description of candidates (name +
    description + parameter names).  It is NOT given the full JSON schema —
    that remains in the ToolSnapshot for the Worker.

    On any failure (LLM unavailable, parse error, empty result) this selector
    falls back to ``DeterministicToolSelector`` and logs a warning.

    Provider-agnostic: uses ``get_provider(get_model_config("selector").provider)``
    — the same pattern as Router and Worker.  Never imports Ollama/Gemini/etc.
    directly.
    """

    def __init__(
        self,
        fallback: ToolSelectionStrategy | None = None,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._fallback = fallback or DeterministicToolSelector()
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def select(
        self,
        request: str,
        candidates: Iterable[ToolMetadata],
        max_tools: int | None = None,
        runtime_state: Mapping[str, object] | None = None,
    ) -> List[str]:
        candidate_list = list(candidates)
        if not candidate_list:
            return []

        limit = max(1, max_tools if max_tools is not None else MAX_SELECTED_TOOLS)
        valid_names = {meta.name for meta in candidate_list}

        logger.info(
            "[SELECTOR:llm] Task: %s | Candidates: %d",
            request[:80], len(candidate_list),
        )

        try:
            selected = self._select_via_llm(request, candidate_list, limit)
        except Exception as exc:
            logger.warning(
                "[SELECTOR:llm] LLM selection failed (%s: %s) — falling back to deterministic.",
                type(exc).__name__, exc,
            )
            selected = None

        if selected is None:
            logger.info("[SELECTOR:llm] Using deterministic fallback.")
            return self._fallback.select(request, candidate_list, max_tools, runtime_state)

        if selected == []:
            logger.info("[SELECTOR:llm] Model returned an explicit empty tool list (task requires no tools).")
            return []

        selected = _validate_selected_tools(selected, valid_names)
        if not selected:
            logger.info("[SELECTOR:llm] Model returned no valid candidates from the discovered set.")
            return self._fallback.select(request, candidate_list, max_tools, runtime_state)

        # Enforce limit after validation
        selected = selected[:limit]

        # Log selected vs rejected
        rejected = sorted(valid_names - set(selected))
        logger.info("[SELECTOR:llm] Selected (%d): %s", len(selected), ", ".join(selected))
        if rejected:
            logger.info("[SELECTOR:llm] Rejected (%d): %s", len(rejected), ", ".join(rejected))

        return selected

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _select_via_llm(
        self,
        request: str,
        candidates: list[ToolMetadata],
        limit: int,
    ) -> list[str] | None:
        """
        Call the configured LLM and return validated tool names.
        Returns None on failure so the caller can trigger fallback.
        """
        from app.llm import get_model_config, get_provider  # deferred — stays provider-agnostic

        model_cfg = get_model_config("selector")
        provider = get_provider(model_cfg.provider)

        tools_block = _format_tools_block(candidates)
        prompt = _SELECTION_PROMPT_TEMPLATE.format(
            request=request,
            tools_block=tools_block,
        )

        messages = [
            {"role": "system", "content": "You are a precise tool selection assistant. Always respond with only a valid JSON array."},
            {"role": "user", "content": prompt},
        ]

        logger.debug("[SELECTOR:llm] Calling %s/%s for tool selection.",
                     model_cfg.provider, model_cfg.model)

        try:
            response = provider.chat(
                model=model_cfg.model,
                messages=messages,
                tools=None,   # selector never uses tools itself
                stream=False,
                response_format="json",
            )
        except TypeError:
            # Some providers don't support response_format — retry without it
            response = provider.chat(
                model=model_cfg.model,
                messages=messages,
                tools=None,
                stream=False,
            )

        # Handle both streaming and non-streaming responses
        if hasattr(response, "__iter__") and not hasattr(response, "message"):
            # Streaming response — collect chunks
            raw_content = ""
            for chunk in response:
                delta = (
                    getattr(chunk, "message", None)
                    and getattr(chunk.message, "content", None)
                )
                if delta:
                    raw_content += delta
        else:
            raw_content = getattr(response.message, "content", "") or ""

        if not raw_content.strip():
            logger.warning("[SELECTOR:llm] Empty response from model.")
            return None

        valid_names = {meta.name for meta in candidates}
        parsed = _parse_llm_selection(raw_content, valid_names)

        if parsed is None:
            logger.warning("[SELECTOR:llm] Could not parse model response: %r", raw_content[:200])
            return None

        if not parsed:
            logger.info("[SELECTOR:llm] Model returned empty tool list (task needs no tools).")
            return []

        return parsed


# ---------------------------------------------------------------------------
# Singleton instances
# ---------------------------------------------------------------------------

#: Deterministic fallback (preserved from TR-5 / A3 — do not add more rules)
_deterministic_selector: DeterministicToolSelector = DeterministicToolSelector()

#: Primary intelligent selector (A4) with deterministic fallback
selector: LLMToolSelector = LLMToolSelector(fallback=_deterministic_selector)

__all__ = [
    "ToolSelectionStrategy",
    "DeterministicToolSelector",
    "LLMToolSelector",
    "MAX_SELECTED_TOOLS",
    "selector",
]
