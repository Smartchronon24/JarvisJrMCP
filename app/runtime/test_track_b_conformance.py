"""Shared conformance and reference-workflow tests for Track B."""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.events import (
    ErrorEvent,
    OutputEvent,
    ProcessCompletedEvent,
    ProcessStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from app.runtime.executor import RuntimeProcessExecutor, RuntimeProcessState
from app.runtime.runtime import RuntimeExecutionState, RuntimeSessionOrchestrator


ADAPTERS = (ClaudeAdapter, CodexAdapter, CopilotAdapter)


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_each_adapter_declares_the_common_capability_contract(adapter_type):
    capabilities = adapter_type().get_capabilities()

    assert capabilities.supports_mcp
    assert capabilities.supports_tool_calls
    assert capabilities.supports_cancellation
    assert capabilities.requires_authentication
    if adapter_type is CodexAdapter:
        assert capabilities.experimental
        assert capabilities.experimental_reason
    else:
        assert not capabilities.experimental


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_each_adapter_preserves_prompt_and_mcp_configuration(adapter_type):
    adapter = adapter_type()
    prompt = "Find this exact value: punctuation !? & spaces"
    config = RuntimeConfig(
        executable_path="runtime",
        prompt=prompt,
        model_name="test-model",
        extra={"jarvis_mcp_config": "jarvis.json"},
    )

    command = adapter.build_command(config)

    assert command
    assert any(prompt in value for value in command)
    assert any("jarvis" in value.lower() for value in command)


class DeterministicAdapter(FrameworkAdapter):
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.COPILOT

    def build_command(self, config: RuntimeConfig) -> list[str]:
        return [sys.executable, "-c", config.extra["script"]]

    def build_environment(self, config: RuntimeConfig) -> dict[str, str]:
        return dict(config.environment)


@pytest.mark.asyncio
async def test_reference_runtime_supports_tool_workflow_and_failure_recovery():
    config = RuntimeConfig(
        executable_path=sys.executable,
        prompt="perform workflow",
        extra={"script": "print('ordinary conversation')"},
    )
    events = []
    orchestrator = RuntimeSessionOrchestrator(
        config,
        FrameworkIdentity.COPILOT,
        event_callback=events.append,
    )
    process = await RuntimeProcessExecutor.execute(
        DeterministicAdapter(),
        config,
        event_callback=orchestrator.handle_executor_event,
    )

    await orchestrator.handle_executor_event(
        ToolCallStartedEvent(2, "lookup", "call-1", {"query": "value"})
    )
    await orchestrator.handle_executor_event(
        ToolCallCompletedEvent(3, "lookup", "call-1", {"ok": False}, True)
    )
    await orchestrator.handle_executor_event(
        ToolCallStartedEvent(4, "lookup", "call-2", {"query": "retry"})
    )
    await orchestrator.handle_executor_event(
        ToolCallCompletedEvent(5, "lookup", "call-2", {"ok": True}, False)
    )
    await process.wait(timeout=2)
    await process.close()

    assert orchestrator.state_machine.current is RuntimeExecutionState.COMPLETED
    assert [e.data["call_id"] for e in events if e.event_type == "tool_call_started"] == [
        "call-1",
        "call-2",
    ]
    completed = [e for e in events if e.event_type == "tool_call_completed"]
    assert completed[0].data["is_error"] is True
    assert completed[1].data["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_reference_runtime_can_restart_and_hot_swap_identity():
    async def run(identity: FrameworkIdentity, text: str):
        config = RuntimeConfig(
            executable_path=sys.executable,
            prompt=text,
            extra={"script": f"print({text!r})"},
        )
        orchestrator = RuntimeSessionOrchestrator(config, identity)
        process = await RuntimeProcessExecutor.execute(
            DeterministicAdapter(),
            config,
            event_callback=orchestrator.handle_executor_event,
        )
        await process.wait(timeout=2)
        await process.close()
        return orchestrator

    first = await run(FrameworkIdentity.COPILOT, "first session")
    second = await run(FrameworkIdentity.CLAUDE, "second session")

    assert first.run_id != second.run_id
    assert first.metrics.state is RuntimeExecutionState.COMPLETED
    assert second.metrics.state is RuntimeExecutionState.COMPLETED
    assert first.config.prompt == "first session"
    assert second.config.prompt == "second session"
