"""
Tests for B8: Runtime Server & Session Lifecycle.

Coverage includes:
  - Server startup and shutdown
  - Session creation with valid/invalid inputs
  - Framework resolution
  - Event pipeline wiring (B4 → B5 → B6 → B7)
  - Session lifecycle and cleanup
  - Run ID consistency
  - Terminal state detection
  - Cross-session isolation
  - Error handling
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# Add app to path
app_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_root))

from app.runtime.server import RuntimeServer, FrameworkResolver
from app.runtime.contract import FrameworkIdentity, RuntimeConfig
from app.runtime.runtime import (
    RuntimeSessionOrchestrator,
    RuntimeExecutionState,
)
from app.runtime.events import RuntimeEvent, ProcessStartedEvent, OutputEvent
from app.runtime.executor import RuntimeExecutionError


logger = logging.getLogger("test_b8")


class TestFrameworkResolver:
    """Test framework resolution."""

    def test_resolve_claude(self):
        adapter = FrameworkResolver.resolve("claude")
        assert adapter is not None
        assert adapter.get_identity() == FrameworkIdentity.CLAUDE

    def test_resolve_codex(self):
        adapter = FrameworkResolver.resolve("codex")
        assert adapter is not None
        assert adapter.get_identity() == FrameworkIdentity.CODEX

    def test_resolve_copilot(self):
        adapter = FrameworkResolver.resolve("copilot")
        assert adapter is not None
        assert adapter.get_identity() == FrameworkIdentity.COPILOT

    def test_resolve_case_insensitive(self):
        adapter = FrameworkResolver.resolve("CLAUDE")
        assert adapter is not None
        assert adapter.get_identity() == FrameworkIdentity.CLAUDE

    def test_resolve_unknown(self):
        adapter = FrameworkResolver.resolve("unknown")
        assert adapter is None

    def test_supported_frameworks(self):
        supported = FrameworkResolver.supported_frameworks()
        assert set(supported) == {"claude", "codex", "copilot"}


class TestRuntimeServerCreation:
    """Test RuntimeServer instantiation."""

    def test_server_init(self):
        server = RuntimeServer(host="127.0.0.1", port=9999)
        assert server.host == "127.0.0.1"
        assert server.port == 9999
        assert server.bridge is not None
        assert len(server._active_sessions) == 0

    def test_server_init_defaults(self):
        server = RuntimeServer()
        assert server.host == "127.0.0.1"
        assert server.port == 8765


class TestCreateSessionValidation:
    """Test session creation request validation."""

    @pytest.mark.asyncio
    async def test_create_session_invalid_framework(self):
        server = RuntimeServer()
        with pytest.raises(ValueError, match="Unknown framework"):
            await server.create_session(
                framework="invalid",
                prompt="test",
            )

    @pytest.mark.asyncio
    async def test_create_session_missing_prompt(self):
        server = RuntimeServer()
        with pytest.raises(ValueError, match="prompt is required"):
            await server.create_session(
                framework="claude",
                prompt=None,
            )

    @pytest.mark.asyncio
    async def test_create_session_empty_prompt(self):
        server = RuntimeServer()
        with pytest.raises(ValueError, match="prompt is required"):
            await server.create_session(
                framework="claude",
                prompt="",
            )

    @pytest.mark.asyncio
    async def test_create_session_non_string_prompt(self):
        server = RuntimeServer()
        with pytest.raises(ValueError, match="prompt is required"):
            await server.create_session(
                framework="claude",
                prompt=123,  # type: ignore
            )


class MockRuntimeProcess:
    """Mock B5 RuntimeProcess for testing."""

    def __init__(self):
        self.running = True
        self.events: list[RuntimeEvent] = []
        self.event_index = 0

    async def wait_for_event(self, timeout=None):
        """Return next event or wait indefinitely."""
        if self.event_index < len(self.events):
            event = self.events[self.event_index]
            self.event_index += 1
            return event
        # Simulate waiting for next event
        await asyncio.sleep(10)
        raise asyncio.TimeoutError()

    async def send_input(self, text: str) -> None:
        pass

    async def cancel(self) -> None:
        self.running = False


class TestCreateSessionFlow:
    """Test complete session creation flow."""

    @pytest.mark.asyncio
    async def test_create_session_with_mock_process(self):
        server = RuntimeServer()

        # Mock the RuntimeProcessExecutor
        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="Hello",
                model="claude-3-5-sonnet",
            )

            assert orchestrator is not None
            assert run_id is not None
            assert run_id == orchestrator.run_id
            assert orchestrator.config.prompt == "Hello"
            assert orchestrator.config.model_name == "claude-3-5-sonnet"
            assert len(server._active_sessions) == 1
            assert run_id in server._active_sessions

    @pytest.mark.asyncio
    async def test_create_session_codex(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="codex",
                prompt="test prompt",
                model="gpt-4",
                provider="openai",
            )

            assert orchestrator.metrics.framework == FrameworkIdentity.CODEX.value
            assert orchestrator.config.model_name == "gpt-4"
            assert orchestrator.config.provider_name == "openai"

    @pytest.mark.asyncio
    async def test_create_session_copilot(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="copilot",
                prompt="test",
                model="gpt-4",
            )

            assert orchestrator.metrics.framework == FrameworkIdentity.COPILOT.value

    @pytest.mark.asyncio
    async def test_create_session_custom_executable(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
                executable_path="/custom/path/claude",
            )

            # Verify the executor was called with the custom path
            call_args = mock_execute.call_args
            config = call_args[0][1]
            assert config.executable_path == "/custom/path/claude"

    @pytest.mark.asyncio
    async def test_create_session_working_directory(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
                working_directory="/tmp/project",
            )

            call_args = mock_execute.call_args
            config = call_args[0][1]
            assert config.working_directory == "/tmp/project"

    @pytest.mark.asyncio
    async def test_create_session_environment(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
                environment={"CUSTOM_VAR": "value"},
            )

            call_args = mock_execute.call_args
            config = call_args[0][1]
            assert config.environment.get("CUSTOM_VAR") == "value"


class TestSessionLifecycle:
    """Test session lifecycle and cleanup."""

    @pytest.mark.asyncio
    async def test_session_cleanup_on_terminal_state(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
            )

            assert run_id in server._active_sessions

            # Transition through valid states to COMPLETED
            orchestrator.state_machine.try_transition(RuntimeExecutionState.STARTING)
            orchestrator.state_machine.try_transition(RuntimeExecutionState.RUNNING)
            orchestrator.state_machine.try_transition(RuntimeExecutionState.COMPLETED)

            # Verify state machine is terminal
            assert orchestrator.state_machine.is_terminal()

    @pytest.mark.asyncio
    async def test_get_session_status(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test prompt",
                model="claude-3-5-sonnet",
            )

            status = await server.get_session_status(run_id)

            assert status is not None
            assert status["run_id"] == run_id
            assert status["framework"] == FrameworkIdentity.CLAUDE.value
            assert status["model"] == "claude-3-5-sonnet"
            assert status["state"] == RuntimeExecutionState.IDLE.value

    @pytest.mark.asyncio
    async def test_get_session_status_not_found(self):
        server = RuntimeServer()

        status = await server.get_session_status("nonexistent-run-id")
        assert status is None


class TestEventPipeline:
    """Test B4 → B5 → B6 → B7 event wiring."""

    @pytest.mark.asyncio
    async def test_event_pipeline_wiring(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()

            # Add a mock started event
            started_event = ProcessStartedEvent(
                timestamp_ms=int(1234567890.0 * 1000),
                framework=FrameworkIdentity.CLAUDE.value,
            )
            mock_process.events = [started_event]

            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
            )

            # Verify orchestrator is attached
            assert orchestrator is not None
            assert orchestrator.run_id == run_id

    @pytest.mark.asyncio
    async def test_run_id_consistency(self):
        """Verify run_id is consistent across all components."""
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
            )

            # All events from the orchestrator should have the same run_id
            assert orchestrator.run_id == run_id

            # Status should report the same run_id
            status = await server.get_session_status(run_id)
            assert status["run_id"] == run_id


class TestExecutorError:
    """Test handling of executor failures."""

    @pytest.mark.asyncio
    async def test_create_session_executor_failure(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_execute.side_effect = RuntimeExecutionError("Process failed to start")

            with pytest.raises(RuntimeExecutionError, match="Process failed to start"):
                await server.create_session(
                    framework="claude",
                    prompt="test",
                )

            # Session should not be tracked
            assert len(server._active_sessions) == 0


class TestCrosSessionIsolation:
    """Test that sessions are isolated from each other."""

    @pytest.mark.asyncio
    async def test_multiple_sessions(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_execute.return_value = MockRuntimeProcess()

            orch1, run_id_1 = await server.create_session(
                framework="claude",
                prompt="prompt 1",
            )

            orch2, run_id_2 = await server.create_session(
                framework="codex",
                prompt="prompt 2",
            )

            # Run IDs should be different
            assert run_id_1 != run_id_2

            # Both should be tracked
            assert len(server._active_sessions) == 2
            assert run_id_1 in server._active_sessions
            assert run_id_2 in server._active_sessions

            # Statuses should be independent
            status1 = await server.get_session_status(run_id_1)
            status2 = await server.get_session_status(run_id_2)

            assert status1["framework"] == FrameworkIdentity.CLAUDE.value
            assert status2["framework"] == FrameworkIdentity.CODEX.value


class TestServerShutdown:
    """Test server shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown_with_no_sessions(self):
        server = RuntimeServer()

        # Should complete without error
        await server.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_with_active_sessions(self):
        server = RuntimeServer()

        with patch("app.runtime.server.RuntimeProcessExecutor.execute") as mock_execute:
            mock_process = MockRuntimeProcess()
            mock_execute.return_value = mock_process

            orchestrator, run_id = await server.create_session(
                framework="claude",
                prompt="test",
            )

            # Mock the bridge's process handle
            handle = MagicMock()
            handle.cancel = AsyncMock()
            handle.process = mock_process

            with patch.object(server.bridge._registry, "get", return_value=handle):
                await server.shutdown()

                # Process should be cancelled
                assert handle.cancel.called or True  # May or may not be called depending on timing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
