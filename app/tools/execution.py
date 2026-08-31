"""
Tool Execution Gateway — A8 Provider-neutral execution abstraction
===================================================================

This module provides the execution boundary between the orchestrator/worker
and the MCP/tool runtime. It abstracts away provider-specific execution details
while preserving full error information and result propagation.

Conceptual flow:

    Worker requests execution
         ↓
    Execution Gateway
         ↓
    MCP session/provider dispatch
         ↓
    Tool result
         ↓
    Normalized result
         ↓
    Worker

The gateway is intentionally thin and does not contain reasoning, scoring,
or selection logic. Those remain in the Registry/Discovery/Selection layers.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

if TYPE_CHECKING:
    from mcp import ClientSession

logger = logging.getLogger("jarvis.execution")


@dataclass(frozen=True)
class ExecutionResult:
    """Normalized result from a tool execution attempt."""

    status: str  # "success", "error", "invalid_arguments", "unknown_tool", "unavailable_tool", "runtime_error"
    content: str  # result text or error message
    is_error: bool = False  # True if this represents an error condition
    error_type: Optional[str] = None  # specific error classification
    retryable: bool = False  # whether the Worker may choose to retry later
    metadata: Optional[dict[str, Any]] = None  # optional execution metadata (includes duration_ms, etc.)

    @property
    def message(self) -> str:
        """Compatibility alias for normalized error/success messages."""
        return self.content

    @classmethod
    def from_error(
        cls,
        *,
        status: str,
        error_type: str,
        message: str,
        retryable: bool,
        duration_ms: Optional[int] = None,
    ) -> "ExecutionResult":
        metadata = {"duration_ms": duration_ms} if duration_ms is not None else None
        return cls(
            status=status,
            content=message,
            is_error=True,
            error_type=error_type,
            retryable=retryable,
            metadata=metadata,
        )


class ToolExecutionGateway:
    """
    Provider-neutral abstraction for tool execution.

    The gateway receives a tool name and arguments, resolves the tool,
    dispatches execution to the appropriate MCP server/session, and
    returns a normalized result.

    Does not contain tool-specific branching. Routing is generic.
    Bookkeeping/usage tracking can be delegated via optional callbacks.
    """

    @staticmethod
    def _is_retryable_exception(exc: BaseException) -> bool:
        """Classify transport/runtime failures as potentially retryable."""
        text = str(exc).lower()
        retryable_markers = (
            "timeout",
            "temporar",
            "transport",
            "connection",
            "unavailable",
            "network",
            "reset by peer",
            "busy",
            "resource temporarily unavailable",
            "service unavailable",
        )
        return any(marker in text for marker in retryable_markers)

    @staticmethod
    def _validate_arguments(arguments: Any, input_schema: Any) -> tuple[bool, Optional[str]]:
        """Validate basic structure and explicit schema constraints.

        Returns (is_valid, error_message)
        """
        if not isinstance(arguments, dict):
            return False, "Arguments must be provided as a dictionary."

        if not isinstance(input_schema, dict):
            return True, None

        allowed = input_schema.get("properties")
        if isinstance(allowed, dict):
            unexpected = sorted(set(arguments.keys()) - set(allowed.keys()))
            if unexpected:
                return False, f"Unexpected arguments: {unexpected}"

        required = input_schema.get("required", [])
        if isinstance(required, (list, tuple)):
            missing = [name for name in required if name not in arguments]
            if missing:
                return False, f"Missing required arguments: {missing}"

        return True, None

    def __init__(
        self,
        tool_registry: Any,  # ToolRegistry instance
        sessions: Mapping[str, ClientSession],
        tool_map: Mapping[str, tuple[str, Any]],
        on_tool_executed: Optional[Callable[[str, str, int, bool, Optional[str]], None]] = None,
    ):
        """
        Initialize the execution gateway.

        Parameters
        ----------
        tool_registry : ToolRegistry
            The canonical tool registry for metadata and state lookup.

        sessions : Mapping[str, ClientSession]
            Map of server_name -> MCP ClientSession for active servers.

        tool_map : Mapping[str, tuple[str, Any]]
            Map of scoped_tool_name -> (server_name, mcp_tool_object)
            for resolving which server owns a tool.

        on_tool_executed : Callable, optional
            Optional hook for recording tool execution (for bookkeeping).
            Signature: (tool_name, real_tool_name, duration_ms, success, error_info) -> None
        """
        self.tool_registry = tool_registry
        self.sessions = sessions
        self.tool_map = tool_map
        self.on_tool_executed = on_tool_executed

    async def execute(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
    ) -> ExecutionResult:
        """
        Execute a tool by name with the given arguments.

        Validation is intentionally lightweight and deterministic:
        - verify tool exists
        - ensure tool is enabled and available
        - reject malformed argument payloads
        - validate required keys from the tool schema
        - return a normalized result to the Worker for reasoning
        """
        arguments = arguments or {}
        t0 = time.time()

        if not isinstance(tool_name, str) or not tool_name.strip():
            return ExecutionResult.from_error(
                status="unknown_tool",
                error_type="unknown_tool",
                message="[Error] Unknown tool: empty name",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        if not isinstance(arguments, dict):
            return ExecutionResult.from_error(
                status="invalid_arguments",
                error_type="invalid_arguments",
                message="[Validation Error] Arguments must be provided as a dictionary.",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 1: Resolve the tool identity ---
        tool_meta = self.tool_registry.get_tool(tool_name)
        if tool_meta is None:
            logger.warning("[EXEC] Unknown tool: %s", tool_name)
            return ExecutionResult.from_error(
                status="unknown_tool",
                error_type="unknown_tool",
                message=f"[Error] Unknown tool: {tool_name}",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 2: Check enabled/available state ---
        if not tool_meta.enabled:
            logger.warning("[EXEC] Tool disabled: %s", tool_name)
            return ExecutionResult.from_error(
                status="unavailable_tool",
                error_type="disabled",
                message=f"[Error] Tool '{tool_name}' is disabled",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        if not tool_meta.available:
            logger.warning("[EXEC] Tool unavailable: %s", tool_name)
            return ExecutionResult.from_error(
                status="unavailable_tool",
                error_type="unavailable",
                message=f"[Error] Tool '{tool_name}' is unavailable (server not connected)",
                retryable=True,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 3: Resolve the MCP server ---
        server_name = tool_meta.server
        session = self.sessions.get(server_name)
        if session is None:
            logger.warning("[EXEC] Server not connected: %s for tool %s", server_name, tool_name)
            return ExecutionResult.from_error(
                status="runtime_error",
                error_type="server_not_connected",
                message=f"[Error] MCP server '{server_name}' is not connected",
                retryable=True,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 4: Resolve the raw MCP tool object ---
        mapped = self.tool_map.get(tool_name)
        if mapped is None:
            logger.warning("[EXEC] Tool not in tool_map: %s", tool_name)
            return ExecutionResult.from_error(
                status="runtime_error",
                error_type="execution_map_missing",
                message=f"[Error] Tool '{tool_name}' not found in execution map",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        server_name_check, _ = mapped
        if server_name_check != server_name:
            logger.warning("[EXEC] Server mismatch for tool %s: %s vs %s", tool_name, server_name, server_name_check)
            return ExecutionResult.from_error(
                status="runtime_error",
                error_type="server_mismatch",
                message=f"[Error] Internal server mismatch for tool '{tool_name}'",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 5: Validate arguments against schema ---
        input_schema = tool_meta.input_schema or {}
        is_valid, validation_error = self._validate_arguments(arguments, input_schema)
        if not is_valid:
            logger.warning("[EXEC] Invalid arguments for %s: %s", tool_name, validation_error)
            return ExecutionResult.from_error(
                status="invalid_arguments",
                error_type="invalid_arguments",
                message=f"[Validation Error] {validation_error}",
                retryable=False,
                duration_ms=int((time.time() - t0) * 1000),
            )

        # --- Step 6: Execute the tool via MCP ---
        real_tool_name = tool_meta.tool_name
        logger.info("[EXEC] Executing %s::%s with arguments: %s", server_name, real_tool_name, arguments)

        try:
            t_exec = time.time()
            result = await session.call_tool(real_tool_name, arguments)
            duration_ms = int((time.time() - t_exec) * 1000)
        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            logger.error("[EXEC] MCP call_tool failed for %s: %s", tool_name, exc)
            retryable = self._is_retryable_exception(exc)
            if self.on_tool_executed:
                self.on_tool_executed(tool_name, real_tool_name, duration_ms, False, str(exc))
            return ExecutionResult.from_error(
                status="runtime_error",
                error_type="mcp_execution_error",
                message=f"[Tool execution failed] {exc}",
                retryable=retryable,
                duration_ms=duration_ms,
            )

        # --- Step 7: Normalize the MCP result ---
        result_is_error = bool(
            getattr(result, "is_error", None)
            if hasattr(result, "is_error")
            else getattr(result, "isError", False)
        )

        if result_is_error:
            content_str = f"[Tool error] {result.content}"
            logger.warning("[EXEC] Tool returned error: %s", content_str)
            if self.on_tool_executed:
                error_info = str(result.content) if result.content else "Unknown error"
                self.on_tool_executed(tool_name, real_tool_name, duration_ms, False, error_info)
            return ExecutionResult.from_error(
                status="error",
                error_type="tool_error",
                message=content_str,
                retryable=False,
                duration_ms=duration_ms,
            )

        if result.content:
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            content_str = "\n".join(parts)
        else:
            content_str = "(no content returned)"

        logger.info("[EXEC] Tool executed successfully: %s", tool_name)
        if self.on_tool_executed:
            self.on_tool_executed(tool_name, real_tool_name, duration_ms, True, None)

        return ExecutionResult(
            status="success",
            content=content_str,
            is_error=False,
            metadata={"duration_ms": duration_ms},
        )
