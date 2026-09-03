"""Focused tests for the C1.12 capability-selection boundary."""

from app.agents.context import (
    CAPABILITY_AWARENESS_CONTRACT,
    CAPABILITY_TAXONOMY,
    JARVIS_IDENTITY,
    canonical_jarvis_context,
)
from app.agents.multi_agent import CAPABILITY_SELECTION_CONTRACT, Router, Worker


def _responding_decision() -> dict:
    return {
        "action": "respond",
        "response": "I can help with that.",
        "task_type": "general_chat",
        "capabilities": [],
        "worker_instruction": "",
        "reason": "direct response",
    }


def test_external_requests_are_delegated_to_the_matching_capability() -> None:
    assert Router._enforce_capability_intent(
        _responding_decision(), "read my recent WhatsApp messages"
    )["capabilities"] == ["messaging"]
    assert Router._enforce_capability_intent(
        _responding_decision(), "open YouTube"
    )["capabilities"] == ["browser_automation"]


def test_repository_requests_are_not_reclassified_as_external_actions() -> None:
    decision = Router._enforce_capability_intent(
        _responding_decision(), "explain this concept"
    )
    assert decision["action"] == "respond"


def test_router_prompt_contains_the_capability_selection_contract() -> None:
    prompt = Router(model="test")._build_system_prompt()
    assert CAPABILITY_SELECTION_CONTRACT in prompt
    assert "Do not inspect the repository to discover or simulate those capabilities." in prompt


def test_canonical_context_is_single_shared_identity_and_contract() -> None:
    context = canonical_jarvis_context()
    assert JARVIS_IDENTITY in context
    assert CAPABILITY_AWARENESS_CONTRACT in context
    assert all(domain in context for domain in CAPABILITY_TAXONOMY)
    assert "not a tool registry" in context


def test_worker_prompt_preserves_capability_failure_semantics() -> None:
    prompt = Worker(model="test").build_system_prompt("Open a website")
    assert JARVIS_IDENTITY in prompt
    assert "execution failure" in prompt
    assert "missing capability" in prompt
