"""B4 reference-runtime certification.

The certification uses a deterministic child process so it verifies the
runtime boundary without requiring a Copilot account or model invocation.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.events import EventType
from app.runtime.executor import RuntimeProcessExecutor, RuntimeProcessState
from app.runtime.runtime import RuntimeExecutionState, RuntimeSessionOrchestrator


class ReferenceCopilotProcessAdapter(FrameworkAdapter):
    """A Copilot-identity adapter backed by a deterministic local process."""

    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.COPILOT

    def build_command(self, config: RuntimeConfig) -> list[str]:
        return [sys.executable, "-c", config.extra["script"]]

    def build_environment(self, config: RuntimeConfig) -> dict[str, str]:
        return dict(config.environment)


def test_copilot_adapter_keeps_reference_cli_contract() -> None:
    config = RuntimeConfig(
        executable_path="copilot",
        prompt="hello",
        model_name="gpt-4",
        interactive=False,
    )

    command = CopilotAdapter().build_command(config)

    assert command[0] == "copilot"
    assert "--model" in command
    assert "-p=hello" in command
    assert "--allow-all-tools" in command


@pytest.mark.asyncio
async def test_copilot_reference_pipeline_reaches_terminal_event() -> None:
    config = RuntimeConfig(
        executable_path=sys.executable,
        prompt="reference prompt",
        interactive=False,
        timeout_seconds=2,
        extra={"script": "print('reference runtime output')"},
    )
    adapter = ReferenceCopilotProcessAdapter()
    session_events = []
    orchestrator = RuntimeSessionOrchestrator(
        config,
        FrameworkIdentity.COPILOT,
        event_callback=session_events.append,
    )

    process = await RuntimeProcessExecutor.execute(
        adapter,
        config,
        event_callback=orchestrator.handle_executor_event,
    )
    exit_code = await process.wait(timeout=config.timeout_seconds)
    await process.close()

    assert exit_code == 0
    assert process.state is RuntimeProcessState.COMPLETED
    assert orchestrator.state_machine.current is RuntimeExecutionState.COMPLETED
    assert orchestrator.metrics.exit_code == 0
    assert orchestrator.metrics.stdout_lines == 1
    assert {event.framework for event in session_events} == {"copilot"}
    assert [event.event_type for event in session_events].count("process_completed") == 1
    assert any(
        event.event_type == "output"
        and event.data.get("text") == "reference runtime output"
        for event in session_events
    )


@pytest.mark.asyncio
async def test_copilot_reference_pipeline_preserves_run_identity() -> None:
    config = RuntimeConfig(
        executable_path=sys.executable,
        prompt="identity prompt",
        extra={"script": "print('identity output')"},
    )
    orchestrator = RuntimeSessionOrchestrator(
        config,
        FrameworkIdentity.COPILOT,
    )
    process = await RuntimeProcessExecutor.execute(
        ReferenceCopilotProcessAdapter(),
        config,
        event_callback=orchestrator.handle_executor_event,
    )

    await process.wait(timeout=2)
    await process.close()

    received = []
    while not orchestrator._session_events.empty():
        received.append(orchestrator._session_events.get_nowait())

    assert received
    assert all(event.run_id == orchestrator.run_id for event in received)
    assert all(event.to_dict()["protocol_version"] == "1" for event in received)
