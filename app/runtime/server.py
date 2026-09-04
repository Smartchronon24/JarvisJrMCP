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
import logging
import os
import subprocess
import sys
import time
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.executor import RuntimeProcessExecutor, RuntimeExecutionError
from app.runtime.runtime import RuntimeSessionOrchestrator, RuntimeExecutionState
from app.runtime.events import ErrorEvent
from app.runtime.websocket import RuntimeWebSocketBridge
from app.runtime.jarvis_mcp import JarvisMCPConfig
from app.agents.context import canonical_jarvis_context
from app.tools.gateway import JarvisToolGateway

logger = logging.getLogger("jarvis.b8.server")


def _set_codex_jarvis_approval_mode() -> None:
    """Make the session-owned Jarvis MCP server available without a prompt."""
    codex_home = os.environ.get("CODEX_HOME")
    config_path = (
        Path(codex_home) / "config.toml"
        if codex_home
        else Path.home() / ".codex" / "config.toml"
    )
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    marker = "[mcp_servers.jarvis]"
    start = text.find(marker)
    if start < 0:
        return
    end = text.find("\n[", start + len(marker))
    if end < 0:
        end = len(text)
    section = text[start:end]
    additions = []
    if "default_tools_approval_mode" not in section:
        additions.append('default_tools_approval_mode = "auto"')
    if "startup_timeout_sec" not in section:
        additions.append("startup_timeout_sec = 15")
    if "required" not in section:
        additions.append("required = true")
    updated = text[:start] + section.rstrip() + (
        "\n" + "\n".join(additions) + "\n" if additions else "\n"
    ) + text[end:]
    if "mcp_optional_startup_grace_ms" not in updated:
        updated = "mcp_optional_startup_grace_ms = 0\n" + updated
    if updated != text:
        config_path.write_text(updated, encoding="utf-8")


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
            executable_path = self._default_executable(framework)

        if working_directory is None:
            working_directory = os.getcwd()

        gateway_token = None
        gateway_config_path = None
        extra: dict[str, str] = {}
        needs_external_capability = any(
            word in prompt.lower()
            for word in (
                "open", "launch", "navigate", "send", "message", "email",
                "search", "find", "read", "retrieve", "play", "call",
            )
        )
        if framework.lower() in {"claude", "codex", "copilot"} and (
            framework.lower() != "claude"
            or needs_external_capability
        ):
            # Expose the canonical Tool Registry through the session-scoped JarvisMCP gateway
            # for every supported runtime, while preserving framework-specific adapter logic.
            extra["jarvis_context"] = canonical_jarvis_context()
            if framework.lower() == "claude" and (provider or "").lower() in {"ollama", "local"}:
                # Do not let host/user Claude plugins and skills steer local
                # Ollama sessions into unrelated coding tasks.
                extra["claude_config_dir"] = tempfile.mkdtemp(prefix="jarvis-claude-")
            try:
                from app.server import agent, gateway_transport
                if agent is not None:
                    mcp_config = JarvisMCPConfig(
                        gateway_transport,
                        JarvisToolGateway(
                            agent.execution_gateway.tool_registry,
                            agent.execution_gateway,
                        ),
                    )
                    gateway_token, gateway_config_path = mcp_config.create_config()
                    if gateway_config_path:
                        extra["jarvis_mcp_config"] = gateway_config_path
                        extra["jarvis_gateway_token"] = gateway_token or ""
                        extra["jarvis_mcp_generator"] = "jarvis_mcp"
                        logger.info("JarvisMCP configured for %s", framework)
            except ImportError:
                logger.warning("Could not import agent/gateway_transport for JarvisMCP")
            except Exception as exc:
                logger.warning("Failed to configure JarvisMCP for %s: %s", framework, exc)

        if framework.lower() == "codex" and gateway_token and gateway_config_path:
            try:
                bridge = Path(__file__).resolve().parents[1] / "tools" / "mcp_compat_stdio.py"
                codex_environment = os.environ.copy()
                codex_environment.update(environment or {})
                codex_cmd = [
                    executable_path,
                    "mcp",
                    "remove",
                    "jarvis",
                ]
                subprocess.run(
                    codex_cmd,
                    cwd=working_directory,
                    env=codex_environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                codex_cmd = [
                    executable_path,
                    "mcp",
                    "add",
                    "jarvis",
                    "--env",
                    "JARVIS_GATEWAY_URL=http://127.0.0.1:8000/api/jarvis/gateway",
                    "--env",
                    f"JARVIS_GATEWAY_TOKEN={gateway_token}",
                    "--",
                    sys.executable,
                    str(bridge),
                ]
                registration = subprocess.run(
                    codex_cmd,
                    cwd=working_directory,
                    env=codex_environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if registration.returncode != 0:
                    logger.error(
                        "Codex Jarvis MCP registration failed (exit %s): %s",
                        registration.returncode,
                        (registration.stderr or registration.stdout or "").strip(),
                    )
                else:
                    _set_codex_jarvis_approval_mode()
                    logger.info("Registered Jarvis MCP server with Codex using native `codex mcp add`")
            except Exception as exc:
                logger.warning("Failed to register Jarvis MCP server with Codex: %s", exc)

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
            extra=extra,
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
            self._cleanup_gateway(config)
            logger.error("Failed to spawn process for run_id=%s: %s", run_id, exc)
            raise

        # Attach to B7 bridge
        try:
            await self._attach_session_to_bridge(orchestrator, process)
        except Exception:
            await process.close()
            self._cleanup_gateway(config)
            raise

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

    @staticmethod
    def _default_executable(framework: str) -> str:
        """Prefer stable native launchers for each supported runtime."""
        if framework.lower() == "codex":
            configured = os.environ.get("JARVIS_CODEX_EXECUTABLE")
            if configured:
                return configured
            compatibility = Path(os.environ.get(
                "JARVIS_CODEX_COMPAT_PATH",
                str(
                    Path.home()
                    / "AppData"
                    / "Local"
                    / "Temp"
                    / "codex-c1.14a"
                    / "codex-rs"
                    / "target"
                    / "debug"
                    / "codex.exe"
                ),
            ))
            if compatibility.is_file():
                return str(compatibility)
            discovered = shutil.which("codex")
            if discovered:
                return discovered
        if framework.lower() in {"claude", "copilot"} and os.name == "nt":
            # PowerShell shims are not safe argv boundaries for prompts with
            # spaces. Prefer the generated CMD launcher on Windows.
            discovered = shutil.which(f"{framework.lower()}.cmd")
            if discovered:
                return discovered
        return framework.lower()

    @staticmethod
    def _cleanup_gateway(config: RuntimeConfig) -> None:
        """Clean up JarvisMCP session resources."""
        try:
            from app.server import gateway_transport
            token = config.extra.get("jarvis_gateway_token")
            config_path = config.extra.get("jarvis_mcp_config")
            if config_path and config.extra.get("jarvis_mcp_generator") == "jarvis_mcp":
                try:
                    subprocess.run(
                        [config.executable_path, "mcp", "remove", "jarvis"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except Exception:
                    pass
            JarvisMCPConfig.cleanup_config(token, config_path, gateway_transport)
            claude_config_dir = config.extra.get("claude_config_dir")
            if claude_config_dir:
                shutil.rmtree(claude_config_dir, ignore_errors=False)
        except ImportError:
            logger.warning("Unable to cleanup JarvisMCP session (gateway_transport not available)")
        except Exception as exc:
            logger.warning("Error during JarvisMCP cleanup: %s", exc)

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
            timeout_seconds = orchestrator.config.timeout_seconds
            if timeout_seconds is None:
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
            self._cleanup_gateway(orchestrator.config)
            self._active_sessions.pop(run_id, None)
            self._process_registry.pop(run_id, None)
            logger.info("Session cleaned up: run_id=%s", run_id)

        except Exception as exc:
            logger.error("Error monitoring session %s: %s", run_id, exc)
            try:
                await process.close()
                self._cleanup_gateway(orchestrator.config)
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
