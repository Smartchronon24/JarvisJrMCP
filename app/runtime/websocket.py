"""
B7: WebSocket Runtime Bridge
============================

Transport boundary between the B6 RuntimeSessionOrchestrator and the
Claudex Studio browser UI.

Responsibilities:
  - Accept WebSocket connections (via websockets library, already in requirements)
  - Route inbound browser messages (input / approval / cancel) to the
    correct RuntimeProcess / RuntimeSessionOrchestrator
  - Stream B6 RuntimeSessionEvent objects to connected clients as JSON
  - Preserve run_id correlation end-to-end
  - Validate all inbound messages; return structured errors for bad input
  - Handle client disconnects without killing the backing runtime session

What B7 does NOT do:
  - Parse ANSI codes
  - Render terminal UI
  - Implement Xterm.js
  - Perform framework-specific CLI logic (that is B4)
  - Execute subprocesses (that is B5)
  - Normalise raw events (that is B6)

Wire protocol
-------------
Inbound (browser → server):

    { "type": "input",    "run_id": "...", "data": { "text": "..." } }
    { "type": "approval", "run_id": "...", "data": { "approved": true } }
    { "type": "cancel",   "run_id": "..." }
    { "type": "ping" }

Outbound (server → browser):

    RuntimeSessionEvent.to_dict()  — see B6 RuntimeSessionEvent. Every event
    includes protocol_version, run_id, timestamp_ms, framework, state, and data.
    Standard data event types include output, tool_call_started,
    tool_call_completed, input_required, approval_required, error,
    process_completed, process_failed, and process_cancelled.

Error frame:

    { "type": "error", "code": "...", "message": "..." }

Acknowledgement frame:

    { "type": "ack", "run_id": "..." }
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Dict, Optional, Set

from app.runtime.executor import RuntimeProcess
from app.runtime.runtime import RuntimeSessionEvent, RuntimeSessionOrchestrator

logger = logging.getLogger("jarvis.b7.websocket")

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class BridgeErrorCode:
    INVALID_JSON      = "INVALID_JSON"
    MISSING_TYPE      = "MISSING_TYPE"
    UNKNOWN_TYPE      = "UNKNOWN_TYPE"
    MISSING_RUN_ID    = "MISSING_RUN_ID"
    UNKNOWN_SESSION   = "UNKNOWN_SESSION"
    INVALID_PAYLOAD   = "INVALID_PAYLOAD"
    SESSION_INACTIVE  = "SESSION_INACTIVE"
    SEND_FAILED       = "SEND_FAILED"


def _error_frame(code: str, message: str) -> str:
    """Return a JSON-encoded error frame for the browser."""
    return json.dumps({"type": "error", "code": code, "message": message})


def _ack_frame(run_id: str) -> str:
    return json.dumps({"type": "ack", "run_id": run_id})


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


# ---------------------------------------------------------------------------
# Session handle — one per run_id
# ---------------------------------------------------------------------------

class _SessionHandle:
    """
    Ties a B6 RuntimeSessionOrchestrator (and its backing B5 RuntimeProcess)
    to a set of WebSocket send functions that should receive events.

    The separation of WebSocket lifetime from session lifetime is deliberate:
    a client may disconnect and reconnect to the same run_id.
    """

    def __init__(
        self,
        orchestrator: RuntimeSessionOrchestrator,
        process: Optional[RuntimeProcess] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.process = process
        self.run_id: str = orchestrator.run_id
        # Set of async callables that take a string (JSON payload) and send it
        self._senders: Set[Callable[[str], asyncio.Future]] = set()
        self._closed = False

    def add_sender(self, send: Callable) -> None:
        self._senders.add(send)

    def remove_sender(self, send: Callable) -> None:
        self._senders.discard(send)

    async def broadcast(self, payload: str) -> None:
        """Send a serialised event to all connected WebSocket clients."""
        if not self._senders:
            return
        dead: Set[Callable] = set()
        for send in list(self._senders):
            try:
                await send(payload)
            except Exception as exc:
                logger.warning("Failed to send to client for run=%s: %s", self.run_id, exc)
                dead.add(send)
        for fn in dead:
            self._senders.discard(fn)

    @property
    def is_terminal(self) -> bool:
        return self.orchestrator.state_machine.is_terminal()

    async def send_input(self, text: str) -> None:
        if self.process is None:
            raise RuntimeError("No process attached to session")
        await self.process.send_input(text)
        self.orchestrator.handle_input_provided()

    async def send_approval(self, approved: bool) -> None:
        if self.process is None:
            raise RuntimeError("No process attached to session")
        if approved:
            # Signal approval via newline (generic "yes" to the CLI)
            await self.process.send_input("\n")
        else:
            # Signal rejection
            await self.process.send_input("n\n")
        self.orchestrator.handle_approval_provided()

    async def cancel(self) -> None:
        if self.process is not None and not self.is_terminal:
            await self.process.terminate()


# ---------------------------------------------------------------------------
# Session registry
# ---------------------------------------------------------------------------

class _SessionRegistry:
    """Thread-safe registry mapping run_id → _SessionHandle."""

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionHandle] = {}

    def register(self, handle: _SessionHandle) -> None:
        self._sessions[handle.run_id] = handle

    def get(self, run_id: str) -> Optional[_SessionHandle]:
        return self._sessions.get(run_id)

    def unregister(self, run_id: str) -> None:
        self._sessions.pop(run_id, None)

    def __len__(self) -> int:
        return len(self._sessions)


# ---------------------------------------------------------------------------
# Main bridge class
# ---------------------------------------------------------------------------

class RuntimeWebSocketBridge:
    """
    Framework-neutral WebSocket transport bridge.

    Usage
    -----
    Create the bridge once and attach sessions before the WS server starts:

        bridge = RuntimeWebSocketBridge()
        bridge.attach_session(orchestrator, process)

    Then pass ``bridge.handle_connection`` as the WebSocket handler:

        async with websockets.serve(bridge.handle_connection, host, port):
            await asyncio.Future()

    Sessions can also be attached after the server is started (thread-safe
    as long as you stay within a single asyncio event loop).
    """

    def __init__(
        self,
        session_factory: Optional[Callable[[dict], object]] = None,
    ) -> None:
        self._registry = _SessionRegistry()
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Session attachment API (used by callers before/after server start)
    # ------------------------------------------------------------------

    def attach_session(
        self,
        orchestrator: RuntimeSessionOrchestrator,
        process: Optional[RuntimeProcess] = None,
    ) -> _SessionHandle:
        """
        Register a B6 orchestrator (and optional B5 process) with the bridge.

        The orchestrator's event_callback will be replaced with one that
        broadcasts events to all connected WebSocket clients for this run_id.
        """
        handle = _SessionHandle(orchestrator, process)
        self._registry.register(handle)

        # Wire up the orchestrator's callback to fan-out to WebSocket clients
        async def _on_session_event(event: RuntimeSessionEvent) -> None:
            payload = json.dumps(event.to_dict())
            await handle.broadcast(payload)

        # Overwrite the event callback so events flow to WS clients
        orchestrator._event_callback = _on_session_event  # type: ignore[assignment]
        logger.info("Session attached: run_id=%s", handle.run_id)
        return handle

    def detach_session(self, run_id: str) -> None:
        """Remove a session from the bridge (e.g., after it has completed)."""
        self._registry.unregister(run_id)
        logger.info("Session detached: run_id=%s", run_id)

    # ------------------------------------------------------------------
    # WebSocket connection handler
    # ------------------------------------------------------------------

    async def handle_connection(self, websocket) -> None:
        """
        Entry-point for each WebSocket connection.

        The websocket object must expose:
          - async for message in websocket  (iteration)
          - await websocket.send(str)
          - websocket.remote_address (optional, for logging)
        """
        remote = getattr(websocket, "remote_address", "unknown")
        logger.info("WebSocket client connected: %s", remote)

        # The client's send callable — captured for clean add/remove
        send = websocket.send

        # Track which sessions this connection has subscribed to
        subscribed: Set[str] = set()

        try:
            async for raw_message in websocket:
                await self._handle_message(
                    raw_message=raw_message,
                    send=send,
                    subscribed=subscribed,
                )
        except Exception as exc:
            logger.warning("WebSocket connection error (%s): %s", remote, exc)
        finally:
            # Unsubscribe this client from all sessions it joined
            for run_id in subscribed:
                handle = self._registry.get(run_id)
                if handle:
                    handle.remove_sender(send)
            logger.info("WebSocket client disconnected: %s", remote)

    # ------------------------------------------------------------------
    # Inbound message routing
    # ------------------------------------------------------------------

    async def _handle_message(
        self,
        raw_message: str,
        send: Callable,
        subscribed: Set[str],
    ) -> None:
        """Parse, validate, and route a single inbound WebSocket message."""
        # 1. Parse JSON
        try:
            msg = json.loads(raw_message)
        except (json.JSONDecodeError, ValueError) as exc:
            await send(_error_frame(BridgeErrorCode.INVALID_JSON, f"JSON parse error: {exc}"))
            return

        if not isinstance(msg, dict):
            await send(_error_frame(BridgeErrorCode.INVALID_JSON, "Message must be a JSON object"))
            return

        # 2. Require 'type'
        msg_type = msg.get("type")
        if not msg_type:
            await send(_error_frame(BridgeErrorCode.MISSING_TYPE, "Missing required field: type"))
            return

        # 3. Route by type
        if msg_type == "ping":
            await send(json.dumps({"type": "pong", "timestamp_ms": _now_ms()}))
            return

        if msg_type == "subscribe":
            await self._handle_subscribe(msg, send, subscribed)
            return

        if msg_type == "start":
            await self._handle_start(msg, send, subscribed)
            return

        if msg_type in ("input", "approval", "cancel"):
            await self._handle_session_command(msg_type, msg, send, subscribed)
            return

        await send(_error_frame(BridgeErrorCode.UNKNOWN_TYPE, f"Unknown message type: {msg_type!r}"))

    async def _handle_start(
        self,
        msg: dict,
        send: Callable,
        subscribed: Set[str],
    ) -> None:
        """Create a new runtime session from a browser start request."""
        if self._session_factory is None:
            await send(_error_frame(
                BridgeErrorCode.UNKNOWN_TYPE,
                "Session creation is not configured on this bridge",
            ))
            return

        try:
            result = await self._session_factory(msg)
        except ValueError as exc:
            await send(_error_frame(BridgeErrorCode.INVALID_PAYLOAD, str(exc)))
            return
        except Exception as exc:
            logger.exception("Failed to create runtime session from browser request")
            await send(_error_frame(BridgeErrorCode.SEND_FAILED, f"Failed to start session: {exc}"))
            return

        run_id = None
        if isinstance(result, tuple) and len(result) == 2:
            _, run_id = result
        elif isinstance(result, dict):
            run_id = result.get("run_id")
            if run_id is None and "session" in result:
                session = result["session"]
                if hasattr(session, "run_id"):
                    run_id = session.run_id
        elif hasattr(result, "run_id"):
            run_id = result.run_id

        if not run_id:
            await send(_error_frame(BridgeErrorCode.INVALID_PAYLOAD, "Session start did not return a run_id"))
            return

        handle = self._registry.get(run_id)
        if handle is None:
            await send(_error_frame(BridgeErrorCode.UNKNOWN_SESSION, f"Session was created but not registered: {run_id}"))
            return

        handle.add_sender(send)
        subscribed.add(run_id)
        await send(_ack_frame(run_id))

    async def _handle_subscribe(
        self,
        msg: dict,
        send: Callable,
        subscribed: Set[str],
    ) -> None:
        """Subscribe this WebSocket connection to a specific run_id's events."""
        run_id = msg.get("run_id")
        if not run_id:
            await send(_error_frame(BridgeErrorCode.MISSING_RUN_ID, "Missing required field: run_id"))
            return

        handle = self._registry.get(run_id)
        if handle is None:
            await send(_error_frame(BridgeErrorCode.UNKNOWN_SESSION, f"Unknown session: {run_id}"))
            return

        handle.add_sender(send)
        subscribed.add(run_id)
        await send(_ack_frame(run_id))

    async def _handle_session_command(
        self,
        msg_type: str,
        msg: dict,
        send: Callable,
        subscribed: Set[str],
    ) -> None:
        """Route input / approval / cancel commands to the correct session."""
        run_id = msg.get("run_id")
        if not run_id:
            await send(_error_frame(BridgeErrorCode.MISSING_RUN_ID, "Missing required field: run_id"))
            return

        handle = self._registry.get(run_id)
        if handle is None:
            await send(_error_frame(BridgeErrorCode.UNKNOWN_SESSION, f"Unknown session: {run_id}"))
            return

        # Auto-subscribe if not already (convenience for direct command senders)
        if run_id not in subscribed:
            handle.add_sender(send)
            subscribed.add(run_id)

        if handle.is_terminal:
            await send(_error_frame(
                BridgeErrorCode.SESSION_INACTIVE,
                f"Session {run_id} is already in a terminal state",
            ))
            return

        try:
            if msg_type == "input":
                data = msg.get("data")
                if not isinstance(data, dict) or "text" not in data:
                    await send(_error_frame(BridgeErrorCode.INVALID_PAYLOAD, "input requires data.text"))
                    return
                await handle.send_input(data["text"])
                await send(_ack_frame(run_id))

            elif msg_type == "approval":
                data = msg.get("data")
                if not isinstance(data, dict) or "approved" not in data:
                    await send(_error_frame(BridgeErrorCode.INVALID_PAYLOAD, "approval requires data.approved"))
                    return
                await handle.send_approval(bool(data["approved"]))
                await send(_ack_frame(run_id))

            elif msg_type == "cancel":
                await handle.cancel()
                await send(_ack_frame(run_id))

        except Exception as exc:
            logger.error("Error handling %s for run=%s: %s", msg_type, run_id, exc)
            await send(_error_frame(BridgeErrorCode.SEND_FAILED, str(exc)))
