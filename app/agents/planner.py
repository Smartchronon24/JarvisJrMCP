"""Provider-agnostic planning stage for Jarvis requests."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from app.llm import ProviderError, get_model_config, get_provider

logger = logging.getLogger("jarvis.planner")


@dataclass(frozen=True)
class PlannerResult:
    """Small, advisory plan passed to the Router."""

    goal: str
    steps: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    complexity: str = "simple"
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True)


class Planner:
    """Generate an advisory execution plan using the configured LLM provider."""

    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        config = get_model_config("router")
        self.model = model or os.getenv("JARVIS_PLANNER_MODEL", config.model)
        provider_name = provider or os.getenv("JARVIS_PLANNER_PROVIDER", config.provider)
        self.provider = get_provider(provider_name)

    def _build_prompt(self, user_message: str) -> str:
        return f"""You are Jarvis's planning stage.
Analyze the user's request and return ONLY valid JSON with this shape:
{{"goal":"string","steps":["string"],"capabilities":["string"],"complexity":"simple|medium|complex","hints":["string"]}}

Produce an advisory plan, not tool names or MCP calls. Keep it concise.
Do not invent capabilities with certainty; use broad concepts such as messaging,
filesystem, terminal, memory, web_research, or browser_automation when appropriate.

User request:
{user_message}"""

    @staticmethod
    def _parse(raw: str) -> PlannerResult:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Planner response must be a JSON object")

        goal = data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("Planner result requires a non-empty goal")

        def strings(value: object) -> list[str]:
            if not isinstance(value, list):
                return []
            return [item.strip() for item in value if isinstance(item, str) and item.strip()]

        complexity = data.get("complexity", "simple")
        if complexity not in {"simple", "medium", "complex"}:
            complexity = "simple"
        return PlannerResult(
            goal=goal.strip(),
            steps=strings(data.get("steps")),
            capabilities=strings(data.get("capabilities")),
            complexity=complexity,
            hints=strings(data.get("hints")),
        )

    def plan(self, user_message: str) -> PlannerResult | None:
        logger.info("[PLANNER] Starting | Model: %s", self.model)
        try:
            response = self.provider.chat(
                model=self.model,
                messages=[{"role": "user", "content": self._build_prompt(user_message)}],
                response_format="json",
            )
            content = getattr(getattr(response, "message", None), "content", None)
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Planner returned empty content")
            result = self._parse(content.strip())
            logger.info(
                "[PLANNER] Complexity: %s | Goal: %s | Steps: %d | Capabilities: %s",
                result.complexity,
                result.goal,
                len(result.steps),
                ",".join(result.capabilities),
            )
            logger.info("[PLANNER] Completed")
            return result
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("[PLANNER] Failed: %s", exc)
            logger.info("[PLANNER] Continuing without plan")
            return None

