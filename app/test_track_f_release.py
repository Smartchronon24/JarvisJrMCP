"""Track F release gates and certified B-C-F vertical slice."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.events import ToolCallCompletedEvent, ToolCallStartedEvent
from app.runtime.runtime import RuntimeExecutionState, RuntimeSessionOrchestrator
from app.runtime.executor import RuntimeProcessExecutor


def test_claudex_studio_smoke_surfaces_are_present():
    studio = Path(__file__).parent.parent / "claudex-studio"
    html = (studio / "index.html").read_text(encoding="utf-8")
    app = (studio / "app.js").read_text(encoding="utf-8")
    for element_id in (
        "connectionStatus",
        "startSessionBtn",
        "resumeBtn",
        "toolActivityList",
        "conversationStatus",
    ):
        assert f'id="{element_id}"' in html
    assert "tool_call_started" in app
    assert "tool_call_completed" in app


def test_cross_framework_matrix_declares_supported_contract():
    adapters = (ClaudeAdapter, CopilotAdapter, CodexAdapter)
    for adapter_type in adapters:
        adapter = adapter_type()
        config = RuntimeConfig(
            executable_path="runtime",
            prompt="exact prompt !? & spaces",
            model_name="test-model",
            extra={"jarvis_mcp_config": "jarvis.json"},
        )
        command = adapter.build_command(config)
        assert command
        assert any("exact prompt" in value for value in command)
        assert adapter.get_capabilities().supports_mcp
        assert adapter.get_capabilities().supports_tool_calls
    assert CodexAdapter().get_capabilities().experimental


def test_certified_vertical_slice_normalizes_runtime_tool_events():
    async def run_slice():
        config = RuntimeConfig(
            executable_path=sys.executable,
            prompt="certified slice",
            extra={"script": "print('slice complete')"},
        )
        events = []
        orchestrator = RuntimeSessionOrchestrator(
            config, FrameworkIdentity.COPILOT, event_callback=events.append
        )
        process = await RuntimeProcessExecutor.execute(
            _SliceAdapter(),
            config,
            event_callback=orchestrator.handle_executor_event,
        )
        await orchestrator.handle_executor_event(
            ToolCallStartedEvent(1, "memory__search", "inv-1", {"query": "slice"})
        )
        await orchestrator.handle_executor_event(
            ToolCallCompletedEvent(2, "memory__search", "inv-1", {"ok": True})
        )
        await process.wait(timeout=2)
        await process.close()
        return orchestrator, events

    orchestrator, events = asyncio.run(run_slice())
    assert orchestrator.metrics.state is RuntimeExecutionState.COMPLETED
    assert [event.data["call_id"] for event in events if event.event_type == "tool_call_started"] == ["inv-1"]
    assert events[-1].event_type == "process_completed"


class _SliceAdapter(FrameworkAdapter):
    def get_identity(self):
        return FrameworkIdentity.COPILOT

    def build_command(self, config):
        return [sys.executable, "-c", config.extra["script"]]

    def build_environment(self, config):
        return {}
