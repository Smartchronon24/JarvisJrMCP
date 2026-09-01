"""
B8: Runtime Server & Session Lifecycle
========================================

Application-level runtime server that wires B4 (framework adapters),
B5 (process execution), B6 (normalization), and B7 (WebSocket transport)
into a cohesive local runtime service.

Responsibilities:
  - Accept WebSocket connections from Claudex Studio
  - Validate session creation requests
  - Instantiate appropriate FrameworkAdapter based on client request
  - Create RuntimeConfig from client request
  - Spawn B5 RuntimeProcess via adapter
  - Attach B6 RuntimeSessionOrchestrator to B7 bridge
  - Monitor session lifecycle and clean up terminal sessions
  - Implement graceful server shutdown

The server is intentionally framework-agnostic; all framework-specific
logic is delegated to B4 adapters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Optional

from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.executor import RuntimeProcessExecutor, RuntimeExecutionError
from app.runtime.runtime import RuntimeSessionOrchestrator, RuntimeExecutionState
from app.runtime.events import ErrorEvent
from app.runtime.websocket import RuntimeWebSocketBridge

logger = logging.getLogger("jarvis.b8.server")


class FrameworkResolver:
    """
    Maps framework name strings to FrameworkAdapter instances.
    Keeps framework knowledge isolated from server logic.
    """

    _ADAPTERS = {
        "claude": ClaudeAdapter(),
        "codex": CodexAdapter(),
        "copilot": CopilotAdapter(),
    }

    @staticmethod
    def resolve(framework: str) -> Optional[FrameworkAdapter]:
        """Return adapter for framework name, or None if unsupported."""
        return FrameworkResolver._ADAPTERS.get(framework.lower())

    @staticmethod
    def supported_frameworks() -> list[str]:
        """Return list of supported framework names."""
        return list(FrameworkResolver._ADAPTERS.keys())


class RuntimeServer:
    """
    Local runtime server for Claudex Studio.

    Orchestrates the complete lifecycle:
      1. Accept WebSocket connections
      2. Validate session start requests
      3. Create RuntimeConfig and select adapter
      4. Spawn B5 RuntimeProcess
      5. Attach to B7 bridge
      6. Monitor for terminal state and clean up
      7. Graceful shutdown
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._server = None
        self._active_sessions: dict[str, RuntimeSessionOrchestrator] = {}
        self._process_registry: dict[str, object] = {}
        self._shutdown = asyncio.Event()
        self._cleanup_tasks: set[asyncio.Task] = set()
        self.bridge = RuntimeWebSocketBridge(session_factory=self._handle_start_request)

    async def start(self) -> None:
        """Start the WebSocket server and begin accepting connections."""
        import websockets

        logger.info("Starting RuntimeServer on ws://%s:%d", self.host, self.port)

        try:
            async with websockets.serve(
                self.bridge.handle_connection,
                self.host,
                self.port,
            ) as server:
                self._server = server
                logger.info("RuntimeServer started successfully")
                await self._shutdown.wait()
        except OSError as exc:
            if getattr(exc, 'errno', None) in {10048, 98}:
                logger.warning(
                    "Runtime server already listening on ws://%s:%d; not starting a duplicate instance.",
                    self.host,
                    self.port,
                )
                return
            raise

        logger.info("RuntimeServer shutting down")
        await self._shutdown_sessions()

    async def _shutdown_sessions(self) -> None:
        """Terminate all active sessions on server shutdown."""
        logger.info("Shutting down %d active session(s)", len(self._active_sessions))
        for orchestrator in list(self._active_sessions.values()):
            try:
                # Get the session handle from the bridge registry
                handle = self.bridge._registry.get(orchestrator.run_id)
                if handle and handle.process:
                    await handle.cancel()
                    await handle.process.close()
            except Exception as exc:
                logger.warning("Error terminating session %s: %s", orchestrator.run_id, exc)

        # Wait for cleanup tasks
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Signal server shutdown."""
        logger.info("RuntimeServer shutdown requested")
        self._shutdown.set()

    async def _handle_start_request(self, msg: dict) -> tuple[RuntimeSessionOrchestrator, str]:
        """Create a runtime session from a browser start request."""
        if not isinstance(msg, dict):
            raise ValueError("Start request must be a JSON object")

        payload = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        framework = str(payload.get("framework") or msg.get("framework") or "").strip().lower()
        prompt = payload.get("prompt") if payload.get("prompt") is not None else msg.get("prompt")
        if not framework:
            raise ValueError("Start request requires 'framework'")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required and must be a non-empty string")

        model = payload.get("model") or msg.get("model")
        provider = payload.get("provider") or msg.get("provider")
        endpoint_url = payload.get("endpoint_url") or msg.get("endpoint_url")
        executable_path = payload.get("executable_path") or msg.get("executable_path")
        working_directory = payload.get("working_directory") or msg.get("working_directory")
        environment = payload.get("environment") or msg.get("environment") or {}
        if not isinstance(environment, dict):
            raise ValueError("environment must be an object if provided")

        return await self.create_session(
            framework=framework,
            prompt=prompt,
            model=model,
            provider=provider,
            endpoint_url=endpoint_url,
            executable_path=executable_path,
            working_directory=working_directory,
            environment=environment,
        )

    async def create_session(
        self,
        framework: str,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        executable_path: Optional[str] = None,
        working_directory: Optional[str] = None,
        environment: Optional[dict[str, str]] = None,
    ) -> tuple[RuntimeSessionOrchestrator, str]:
        """
        Create a new runtime session.

        Returns:
            (orchestrator, run_id)

        Raises:
            ValueError: For invalid framework, missing prompt, etc.
            RuntimeExecutionError: If process spawn fails
        """
        # Validate framework
        adapter = FrameworkResolver.resolve(framework)
        if adapter is None:
            supported = ", ".join(FrameworkResolver.supported_frameworks())
            raise ValueError(
                f"Unknown framework: {framework}. Supported: {supported}"
            )

        # Validate prompt
        if not prompt or not isinstance(prompt, str):
            raise ValueError("prompt is required and must be a non-empty string")

        # Determine executable path
        if not executable_path:
            # Try to use framework name as executable (e.g., "claude", "codex")
            executable_path = framework.lower()

        # Create RuntimeConfig
        config = RuntimeConfig(
            executable_path=executable_path,
            prompt=prompt,
            model_name=model,
            provider_name=provider,
            endpoint_url=endpoint_url,
            working_directory=working_directory,
            environment=environment or {},
            interactive=False,
        )

        # Create B6 orchestrator
        orchestrator = RuntimeSessionOrchestrator(config, adapter.get_identity())
        run_id = orchestrator.run_id

        logger.info(
            "Creating session: run_id=%s, framework=%s, model=%s",
            run_id,
            framework,
            model,
        )

        # Spawn B5 process
        try:
            process = await RuntimeProcessExecutor.execute(adapter, config)
        except RuntimeExecutionError as exc:
            logger.error("Failed to spawn process for run_id=%s: %s", run_id, exc)
            raise

        # Attach to B7 bridge
        await self._attach_session_to_bridge(orchestrator, process)

        # Track session
        self._active_sessions[run_id] = orchestrator
        self._process_registry[run_id] = process

        # Start cleanup monitor
        cleanup_task = asyncio.create_task(
            self._monitor_and_cleanup(orchestrator, process, run_id)
        )
        self._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._cleanup_tasks.discard)

        logger.info("Session created successfully: run_id=%s", run_id)
        return orchestrator, run_id

    async def _attach_session_to_bridge(
        self,
        orchestrator: RuntimeSessionOrchestrator,
        process,
    ) -> None:
        """Attach B6 orchestrator to B7 bridge and wire event pipeline."""
        handle = self.bridge.attach_session(orchestrator, process)

        # Start feeding B5 executor events to B6 orchestrator
        async def _event_forwarder():
            try:
                first_event = True
                # Only apply a startup timeout for non-interactive sessions
                startup_timeout = 8.0 if not orchestrator.config.interactive else None
                while not orchestrator.state_machine.is_terminal():
                    timeout = startup_timeout if first_event and startup_timeout is not None else None
                    try:
                        event = await process.wait_for_event(timeout=timeout)
                    except TimeoutError:
                        # No output from the process in the expected startup window — fail fast.
                        logger.warning(
                            "No events from process for run_id=%s within %s seconds; terminating",
                            orchestrator.run_id,
                            startup_timeout,
                        )
                        try:
                            await process.terminate()
                        except Exception:
                            logger.exception("Failed to terminate stalled process for run_id=%s", orchestrator.run_id)
                        # Emit a synthetic error event so the orchestrator and UI see the failure.
                        await orchestrator.handle_executor_event(
                            ErrorEvent(int(time.time_ns() // 1_000_000), "Startup timeout: process produced no output", "startup_timeout")
                        )
                        break
                    first_event = False
                    await orchestrator.handle_executor_event(event)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(
                    "Error forwarding events for run_id=%s: %s",
                    orchestrator.run_id,
                    exc,
                )

        # Run event forwarder in background
        forwarder_task = asyncio.create_task(_event_forwarder())
        # Store it so we can cancel if needed
        if not hasattr(handle, "_event_forwarder_task"):
            handle._event_forwarder_task = forwarder_task

    async def _monitor_and_cleanup(
        self,
        orchestrator: RuntimeSessionOrchestrator,
        process,
        run_id: str,
    ) -> None:
        """
        Monitor orchestrator for terminal state and clean up when complete.
        """
        try:
            timeout_value = os.environ.get("JARVIS_RUNTIME_TIMEOUT_SECONDS", "120")
            try:
                timeout_seconds = max(1.0, float(timeout_value))
            except ValueError:
                timeout_seconds = 120.0

            async def wait_for_terminal() -> None:
                while not orchestrator.state_machine.is_terminal():
                    await asyncio.sleep(0.1)

            try:
                await asyncio.wait_for(wait_for_terminal(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                reason = f"Runtime timed out after {timeout_seconds:g} seconds"
                logger.warning("Runtime timeout for run_id=%s", run_id)
                await process.terminate(reason=reason)

            logger.info("Session reached terminal state: run_id=%s, state=%s",
                       run_id,
                       orchestrator.metrics.state.value)

            # Allow final events to be delivered
            await asyncio.sleep(0.5)

            # Detach from bridge
            self.bridge.detach_session(run_id)

            # Clean up
            await process.close()
            self._active_sessions.pop(run_id, None)
            self._process_registry.pop(run_id, None)
            logger.info("Session cleaned up: run_id=%s", run_id)

        except Exception as exc:
            logger.error("Error monitoring session %s: %s", run_id, exc)
            try:
                await process.close()
            finally:
                self._active_sessions.pop(run_id, None)
                self._process_registry.pop(run_id, None)

    def get_process_status(self, run_id: str) -> Optional[dict]:
        """Return diagnostic process ownership information for a live session."""
        process = self._process_registry.get(run_id)
        if process is None:
            return None
        return {
            "run_id": run_id,
            "pid": process.pid,
            "alive": process.returncode is None,
            "started_at_ms": process.started_at_ms,
            "state": process.state.value,
        }

    async def get_session_status(self, run_id: str) -> Optional[dict]:
        """Return current status of a session, or None if not found."""
        orchestrator = self._active_sessions.get(run_id)
        if not orchestrator:
            return None

        metrics = orchestrator.get_metrics()
        return {
            "run_id": run_id,
            "state": metrics.state.value,
            "framework": metrics.framework,
            "model": metrics.model,
            "provider": metrics.provider,
            "elapsed_ms": metrics.elapsed_ms,
            "exit_code": metrics.exit_code,
            "stdout_lines": metrics.stdout_lines,
            "stderr_lines": metrics.stderr_lines,
            "is_terminal": orchestrator.state_machine.is_terminal(),
        }


async def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Run the runtime server until interrupted.

    Usage:
        await run_server()
    """
    server = RuntimeServer(host=host, port=port)

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        await server.shutdown()


async def main() -> None:
    """Simple CLI entry point for testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        await run_server()
    except Exception as exc:
        logger.error("Server error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
