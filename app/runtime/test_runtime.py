"""
Tests for B6 runtime state machine and event normalization.
"""

import asyncio
import pytest
import time

from app.runtime.contract import FrameworkIdentity, RuntimeConfig
from app.runtime.events import (
    EventType,
    ProcessStartedEvent,
    OutputEvent,
    InputRequiredEvent,
    ApprovalRequiredEvent,
    ProcessCompletedEvent,
    ProcessFailedEvent,
    ProcessInterruptedEvent,
    ErrorEvent,
)
from app.runtime.runtime import (
    RuntimeExecutionState,
    RuntimeStateTransitionError,
    RuntimeMetrics,
    RuntimeSessionEvent,
    RuntimeStateMachine,
    RuntimeSessionOrchestrator,
)


class TestRuntimeStateMachine:
    """Test the state machine logic."""

    def test_initial_state_is_idle(self):
        sm = RuntimeStateMachine()
        assert sm.current == RuntimeExecutionState.IDLE

    def test_valid_transition_idle_to_starting(self):
        sm = RuntimeStateMachine()
        assert sm.transition(RuntimeExecutionState.STARTING)
        assert sm.current == RuntimeExecutionState.STARTING

    def test_valid_transition_starting_to_running(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        assert sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.current == RuntimeExecutionState.RUNNING

    def test_valid_transition_running_to_completed(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.transition(RuntimeExecutionState.COMPLETED)
        assert sm.current == RuntimeExecutionState.COMPLETED

    def test_valid_transition_running_to_waiting_for_input(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.transition(RuntimeExecutionState.WAITING_FOR_INPUT)
        assert sm.current == RuntimeExecutionState.WAITING_FOR_INPUT

    def test_valid_transition_waiting_for_input_back_to_running(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        sm.transition(RuntimeExecutionState.WAITING_FOR_INPUT)
        assert sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.current == RuntimeExecutionState.RUNNING

    def test_valid_transition_running_to_waiting_for_approval(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.transition(RuntimeExecutionState.WAITING_FOR_APPROVAL)
        assert sm.current == RuntimeExecutionState.WAITING_FOR_APPROVAL

    def test_valid_transition_running_to_failed(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.transition(RuntimeExecutionState.FAILED)
        assert sm.current == RuntimeExecutionState.FAILED

    def test_valid_transition_running_to_cancelled(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.transition(RuntimeExecutionState.CANCELLED)
        assert sm.current == RuntimeExecutionState.CANCELLED

    def test_invalid_transition_idle_to_completed(self):
        sm = RuntimeStateMachine()
        assert not sm.transition(RuntimeExecutionState.COMPLETED)
        assert sm.current == RuntimeExecutionState.IDLE

    def test_invalid_transition_idle_to_running(self):
        sm = RuntimeStateMachine()
        assert not sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.current == RuntimeExecutionState.IDLE

    def test_invalid_transition_from_completed(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        sm.transition(RuntimeExecutionState.COMPLETED)
        assert not sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.current == RuntimeExecutionState.COMPLETED

    def test_invalid_transition_from_failed(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        sm.transition(RuntimeExecutionState.FAILED)
        assert not sm.transition(RuntimeExecutionState.RUNNING)
        assert sm.current == RuntimeExecutionState.FAILED

    def test_idempotent_same_state_transition(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        assert sm.transition(RuntimeExecutionState.STARTING)
        assert sm.current == RuntimeExecutionState.STARTING

    def test_try_transition_valid(self):
        sm = RuntimeStateMachine()
        sm.try_transition(RuntimeExecutionState.STARTING)
        assert sm.current == RuntimeExecutionState.STARTING

    def test_try_transition_invalid_raises(self):
        sm = RuntimeStateMachine()
        with pytest.raises(RuntimeStateTransitionError):
            sm.try_transition(RuntimeExecutionState.COMPLETED)

    def test_is_terminal_states(self):
        sm = RuntimeStateMachine()
        assert not sm.is_terminal()
        sm.transition(RuntimeExecutionState.STARTING)
        assert not sm.is_terminal()
        sm.transition(RuntimeExecutionState.RUNNING)
        assert not sm.is_terminal()
        sm.transition(RuntimeExecutionState.COMPLETED)
        assert sm.is_terminal()

    def test_is_terminal_on_failed(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        sm.transition(RuntimeExecutionState.FAILED)
        assert sm.is_terminal()

    def test_is_terminal_on_cancelled(self):
        sm = RuntimeStateMachine()
        sm.transition(RuntimeExecutionState.STARTING)
        sm.transition(RuntimeExecutionState.RUNNING)
        sm.transition(RuntimeExecutionState.CANCELLED)
        assert sm.is_terminal()


class TestRuntimeMetrics:
    """Test runtime metrics collection."""

    def test_metrics_initial_state(self):
        metrics = RuntimeMetrics(run_id="test-123")
        assert metrics.run_id == "test-123"
        assert metrics.framework is None
        assert metrics.model is None
        assert metrics.provider is None
        assert metrics.state == RuntimeExecutionState.IDLE
        assert metrics.stdout_lines == 0
        assert metrics.stderr_lines == 0
        assert metrics.input_required_count == 0
        assert metrics.approval_required_count == 0

    def test_metrics_elapsed_ms_before_start(self):
        metrics = RuntimeMetrics(run_id="test-123")
        assert metrics.elapsed_ms is None
        assert metrics.duration_seconds is None

    def test_metrics_elapsed_ms_calculation(self):
        start = int(time.time_ns() // 1_000_000)
        metrics = RuntimeMetrics(run_id="test-123", start_time_ms=start)
        end = start + 1000
        metrics.end_time_ms = end
        assert metrics.elapsed_ms == 1000
        assert metrics.duration_seconds == 1.0

    def test_metrics_with_framework_and_model(self):
        metrics = RuntimeMetrics(
            run_id="test-123",
            framework="codex",
            model="gpt-oss:120b",
            provider="ollama",
        )
        assert metrics.framework == "codex"
        assert metrics.model == "gpt-oss:120b"
        assert metrics.provider == "ollama"


class TestRuntimeSessionEvent:
    """Test normalized session event representation."""

    def test_session_event_to_dict(self):
        event = RuntimeSessionEvent(
            event_type="state_changed",
            run_id="test-run-123",
            timestamp_ms=1000,
            framework="codex",
            state=RuntimeExecutionState.RUNNING,
        )
        d = event.to_dict()
        assert d["event_type"] == "state_changed"
        assert d["run_id"] == "test-run-123"
        assert d["timestamp_ms"] == 1000
        assert d["framework"] == "codex"
        assert d["state"] == "running"

    def test_session_event_with_data(self):
        event = RuntimeSessionEvent(
            event_type="output",
            run_id="test-run-123",
            timestamp_ms=1000,
            data={"stream": "stdout", "text": "hello world"},
        )
        d = event.to_dict()
        assert d["data"]["stream"] == "stdout"
        assert d["data"]["text"] == "hello world"


@pytest.mark.asyncio
class TestRuntimeSessionOrchestrator:
    """Test the event orchestrator and normalization layer."""

    async def test_orchestrator_initial_state(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)
        assert orch.run_id is not None
        assert orch.state_machine.current == RuntimeExecutionState.IDLE
        assert orch.metrics.framework == "codex"

    async def test_orchestrator_handles_process_started_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        event = ProcessStartedEvent(timestamp_ms=1000, pid=1234, framework="codex")
        await orch.handle_executor_event(event)

        assert orch.state_machine.current == RuntimeExecutionState.RUNNING
        assert orch.metrics.start_time_ms == 1000

        # Consume the state change events
        session_event = await asyncio.wait_for(orch.get_session_event(), timeout=1)
        assert session_event.event_type == "state_changed"
        assert session_event.state == RuntimeExecutionState.STARTING

        session_event = await asyncio.wait_for(orch.get_session_event(), timeout=1)
        assert session_event.event_type == "state_changed"
        assert session_event.state == RuntimeExecutionState.RUNNING

        session_event = await asyncio.wait_for(orch.get_session_event(), timeout=1)
        assert session_event.event_type == "process_started"

    async def test_orchestrator_handles_output_events(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        # Start
        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        # Clear initial events
        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        # Output
        out_event = OutputEvent(timestamp_ms=2000, text="hello", stream="stdout")
        await orch.handle_executor_event(out_event)

        assert orch.metrics.stdout_lines == 1

        session_event = await asyncio.wait_for(orch.get_session_event(), timeout=1)
        assert session_event.event_type == "output"
        assert session_event.data["stream"] == "stdout"
        assert session_event.data["text"] == "hello"

    async def test_orchestrator_handles_stderr_output(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        err_event = OutputEvent(timestamp_ms=2000, text="error", stream="stderr")
        await orch.handle_executor_event(err_event)

        assert orch.metrics.stderr_lines == 1

    async def test_orchestrator_handles_input_required_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        input_event = InputRequiredEvent(timestamp_ms=2000, prompt_text="Enter your choice:")
        await orch.handle_executor_event(input_event)

        assert orch.metrics.input_required_count == 1
        assert orch.metrics.is_waiting_for_input
        assert orch.state_machine.current == RuntimeExecutionState.WAITING_FOR_INPUT

    async def test_orchestrator_handles_approval_required_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        approval_event = ApprovalRequiredEvent(timestamp_ms=2000, action_description="Apply changes?")
        await orch.handle_executor_event(approval_event)

        assert orch.metrics.approval_required_count == 1
        assert orch.metrics.is_waiting_for_approval
        assert orch.state_machine.current == RuntimeExecutionState.WAITING_FOR_APPROVAL

    async def test_orchestrator_handles_process_completed_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        complete_event = ProcessCompletedEvent(timestamp_ms=3000, exit_code=0)
        await orch.handle_executor_event(complete_event)

        assert orch.state_machine.current == RuntimeExecutionState.COMPLETED
        assert orch.metrics.exit_code == 0
        assert orch.metrics.end_time_ms == 3000

    async def test_orchestrator_handles_process_failed_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        failed_event = ProcessFailedEvent(timestamp_ms=3000, exit_code=1, reason="Process exited with code 1")
        await orch.handle_executor_event(failed_event)

        assert orch.state_machine.current == RuntimeExecutionState.FAILED
        assert orch.metrics.exit_code == 1

    async def test_orchestrator_handles_process_interrupted_event(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        interrupted_event = ProcessInterruptedEvent(timestamp_ms=2500)
        await orch.handle_executor_event(interrupted_event)

        assert orch.state_machine.current == RuntimeExecutionState.CANCELLED
        assert orch.metrics.end_time_ms == 2500

    async def test_orchestrator_input_provided_transitions_back_to_running(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        input_event = InputRequiredEvent(timestamp_ms=2000, prompt_text="Enter choice:")
        await orch.handle_executor_event(input_event)

        assert orch.state_machine.current == RuntimeExecutionState.WAITING_FOR_INPUT
        assert orch.metrics.is_waiting_for_input

        orch.handle_input_provided()

        assert orch.state_machine.current == RuntimeExecutionState.RUNNING
        assert not orch.metrics.is_waiting_for_input

    async def test_orchestrator_approval_provided_transitions_back_to_running(self):
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        try:
            while True:
                await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
        except asyncio.TimeoutError:
            pass

        approval_event = ApprovalRequiredEvent(timestamp_ms=2000, action_description="Apply?")
        await orch.handle_executor_event(approval_event)

        assert orch.state_machine.current == RuntimeExecutionState.WAITING_FOR_APPROVAL
        assert orch.metrics.is_waiting_for_approval

        orch.handle_approval_provided()

        assert orch.state_machine.current == RuntimeExecutionState.RUNNING
        assert not orch.metrics.is_waiting_for_approval

    async def test_orchestrator_run_id_consistency(self):
        """All events should have the same run_id."""
        config = RuntimeConfig(executable_path="python")
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)
        run_id = orch.run_id

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        output_event = OutputEvent(timestamp_ms=2000, text="test")
        await orch.handle_executor_event(output_event)

        complete_event = ProcessCompletedEvent(timestamp_ms=3000, exit_code=0)
        await orch.handle_executor_event(complete_event)

        events = []
        try:
            while True:
                event = await asyncio.wait_for(orch.get_session_event(), timeout=0.01)
                events.append(event)
        except asyncio.TimeoutError:
            pass

        assert len(events) > 0
        for event in events:
            assert event.run_id == run_id

    async def test_orchestrator_with_callback(self):
        """Test that event callback is called for each session event."""
        config = RuntimeConfig(executable_path="python")
        events_received = []

        async def callback(event):
            events_received.append(event)

        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX, event_callback=callback)

        start_event = ProcessStartedEvent(timestamp_ms=1000, pid=1234)
        await orch.handle_executor_event(start_event)

        assert len(events_received) > 0
        for event in events_received:
            assert event.run_id == orch.run_id

    async def test_orchestrator_full_execution_flow(self):
        """Test a complete execution flow from start to completion."""
        config = RuntimeConfig(
            executable_path="python",
            model_name="gpt-oss:120b",
            provider_name="ollama",
        )
        orch = RuntimeSessionOrchestrator(config, FrameworkIdentity.CODEX)

        # Start
        await orch.handle_executor_event(ProcessStartedEvent(timestamp_ms=1000, pid=5678))
        assert orch.state_machine.current == RuntimeExecutionState.RUNNING

        # Output
        await orch.handle_executor_event(OutputEvent(timestamp_ms=1100, text="Processing...", stream="stdout"))
        assert orch.metrics.stdout_lines == 1

        # Input required
        await orch.handle_executor_event(InputRequiredEvent(timestamp_ms=1200, prompt_text="Proceed?"))
        assert orch.state_machine.current == RuntimeExecutionState.WAITING_FOR_INPUT
        assert orch.metrics.input_required_count == 1

        # Input provided
        orch.handle_input_provided()
        assert orch.state_machine.current == RuntimeExecutionState.RUNNING

        # Completion
        await orch.handle_executor_event(ProcessCompletedEvent(timestamp_ms=1300, exit_code=0))
        assert orch.state_machine.current == RuntimeExecutionState.COMPLETED
        assert orch.state_machine.is_terminal()

        # Check metrics
        metrics = orch.get_metrics()
        assert metrics.framework == "codex"
        assert metrics.model == "gpt-oss:120b"
        assert metrics.provider == "ollama"
        assert metrics.exit_code == 0
        assert metrics.stdout_lines == 1
        assert metrics.input_required_count == 1
        assert metrics.elapsed_ms == 300
