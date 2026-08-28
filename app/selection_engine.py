"""Backward-compatible facade for the TR-5 tool selector."""

from __future__ import annotations

from app.tools.selector import selector


class SelectionEngine:
    """Compatibility wrapper around the provider-agnostic selector."""

    def select_tools(self, request: str) -> list[str]:
        return selector.select(request)


selection_engine = SelectionEngine()

__all__ = ["SelectionEngine", "selection_engine"]
