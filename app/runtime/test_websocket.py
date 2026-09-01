"""
B7 Tests — WebSocket Runtime Bridge

All tests use fakes/mocks. No real Claude/Codex/Copilot sessions are launched.
No network calls. No model downloads.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from app.runtime.contract import FrameworkIdentity, RuntimeConfig
from app.runtime.events import (
    ProcessStartedEvent,
    OutputEvent,
    InputRequiredEvent,
    ApprovalRequiredEvent,
    ProcessCompletedEvent,
    ProcessFailedEvent,
    ProcessInterruptedEvent,
)
from app.runtime.runtime import (
    RuntimeExecutionState,
    RuntimeSessionEvent,
    RuntimeSessionOrchestrator,
)
from app.runtime.websocket import (
    BridgeErrorCode,
    RuntimeWebSocketBridge,
    _error_frame,
    _ack_frame,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    import time
    return time.time_ns() // 1_000_000


def _make_config(**kwargs) -> RuntimeConfig:
    defaults = dict(executable_path="echo", prompt="hello")
    defaults.update(kwargs)
    return RuntimeConfig(**defaults)


def _make_orchestrator(framework=FrameworkIdentity.CODEX) -> RuntimeSessionOrchestrator:
    config = _make_config()
    return RuntimeSessionOrchestrator(config=config, framework_identity=framework)


class FakeWebSocket:
    """Minimal fake WebSocket that records sent messages and plays back a sequence."""

    def __init__(self, inbound: list[str] | None = None):
        self._inbound = inbound or []
        self.sent: list[str] = []
        self.remote_address = ("127.0.0.1", 9999)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._inbound:
            raise StopAsyncIteration
        return self._inbound.pop(0)

    def parsed(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


class FakeProcess:
    """Minimal fake RuntimeProcess that records inputs and supports cancel."""

    def __init__(self):
        self.inputs: list[str] = []
        self.terminated = False
        self.returncode = None

    async def send_input(self, data: str) -> None:
        self.inputs.append(data)

    async def terminate(self) -> int:
        self.terminated = True
        return 0


# ---------------------------------------------------------------------------
# Unit: error / ack frame helpers
# ---------------------------------------------------------------------------

class TestFrameHelpers:
    def test_error_frame_structure(self):
        frame = json.loads(_error_frame("MY_CODE", "bad thing"))
        assert frame["type"] == "error"
        assert frame["code"] == "MY_CODE"
        assert "bad thing" in frame["message"]

    def test_ack_frame_structure(self):
        frame = json.loads(_ack_frame("run-xyz"))
        assert frame["type"] == "ack"
        assert frame["run_id"] == "run-xyz"


# ---------------------------------------------------------------------------
# Unit: RuntimeSessionEvent serialisation
# ---------------------------------------------------------------------------

class TestEventSerialisation:
    @pytest.mark.asyncio
    async def test_session_event_to_dict_round_trip(self):
        orch = _make_orchestrator()
        events_received: list[RuntimeSessionEvent] = []

        async def cb(e: RuntimeSessionEvent) -> None:
            events_received.append(e)

        orch._event_callback = cb
        await orch.handle_executor_event(ProcessStartedEvent(_now_ms(), pid=1234, framework="codex"))

        assert events_received
        d = events_received[-1].to_dict()
        assert "event_type" in d
        assert "run_id" in d
        assert d["run_id"] == orch.run_id
        assert "timestamp_ms" in d
        assert "framework" in d
        assert "state" in d
        assert "data" in d

    @pytest.mark.asyncio
    async def test_output_event_data_preserved(self):
        orch = _make_orchestrator(FrameworkIdentity.CLAUDE)
        events_received: list[RuntimeSessionEvent] = []

        async def cb(e: RuntimeSessionEvent) -> None:
            events_received.append(e)

        orch._event_callback = cb
        await orch.handle_executor_event(ProcessStartedEvent(_now_ms(), pid=99))
        await orch.handle_executor_event(OutputEvent(_now_ms(), "hello world", "stdout"))

        output_events = [e for e in events_received if e.event_type == "output"]
        assert output_events
        d = output_events[0].to_dict()
        assert d["data"]["text"] == "hello world"
        assert d["data"]["stream"] == "stdout"
        assert d["framework"] == "claude"

    @pytest.mark.asyncio
    async def test_state_preserved_in_event(self):
        orch = _make_orchestrator()
        captured: list[dict] = []

        async def cb(e: RuntimeSessionEvent) -> None:
            captured.append(e.to_dict())

        orch._event_callback = cb
        await orch.handle_executor_event(ProcessStartedEvent(_now_ms(), pid=1))
        await orch.handle_executor_event(ProcessCompletedEvent(_now_ms(), exit_code=0))

        states = [e["state"] for e in captured]
        assert "running" in states
        assert "completed" in states


# ---------------------------------------------------------------------------
# Unit: Session registry / handle
# ---------------------------------------------------------------------------

class TestSessionHandle:
    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_senders(self):
        orch = _make_orchestrator()
        bridge = RuntimeWebSocketBridge()
        handle = bridge.attach_session(orch)

        received_a: list[str] = []
        received_b: list[str] = []

        async def send_a(msg: str) -> None:
            received_a.append(msg)

        async def send_b(msg: str) -> None:
            received_b.append(msg)

        handle.add_sender(send_a)
        handle.add_sender(send_b)

        await handle.broadcast("test-payload")
        assert received_a == ["test-payload"]
        assert received_b == ["test-payload"]

    @pytest.mark.asyncio
    async def test_remove_sender_stops_delivery(self):
        orch = _make_orchestrator()
        bridge = RuntimeWebSocketBridge()
        handle = bridge.attach_session(orch)

        received: list[str] = []

        async def send(msg: str) -> None:
            received.append(msg)

        handle.add_sender(send)
        await handle.broadcast("first")
        handle.remove_sender(send)
        await handle.broadcast("second")
        assert received == ["first"]

    @pytest.mark.asyncio
    async def test_cancel_calls_process_terminate(self):
        orch = _make_orchestrator()
        bridge = RuntimeWebSocketBridge()
        proc = FakeProcess()
        handle = bridge.attach_session(orch, proc)

        # Manually put orchestrator in RUNNING state
        orch.state_machine.transition(RuntimeExecutionState.STARTING)
        orch.state_machine.transition(RuntimeExecutionState.RUNNING)

        assert not handle.is_terminal
        await handle.cancel()
        assert proc.terminated


# ---------------------------------------------------------------------------
# Integration: handle_connection — validation path
# ---------------------------------------------------------------------------

class TestConnectionValidation:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket(["not valid json"])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.INVALID_JSON for m in msgs)

    @pytest.mark.asyncio
    async def test_missing_type_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"run_id": "x"})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.MISSING_TYPE for m in msgs)

    @pytest.mark.asyncio
    async def test_unknown_message_type_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"type": "frobnicate", "run_id": "x"})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.UNKNOWN_TYPE for m in msgs)

    @pytest.mark.asyncio
    async def test_ping_returns_pong(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"type": "ping"})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("type") == "pong" for m in msgs)

    @pytest.mark.asyncio
    async def test_start_message_creates_session(self):
        bridge = RuntimeWebSocketBridge()

        async def fake_session_factory(msg):
            orch = _make_orchestrator(FrameworkIdentity.CLAUDE)
            bridge.attach_session(orch)
            return orch, orch.run_id

        bridge = RuntimeWebSocketBridge(session_factory=fake_session_factory)
        ws = FakeWebSocket([json.dumps({
            "type": "start",
            "framework": "claude",
            "prompt": "hello",
        })])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("type") == "ack" and m.get("run_id") for m in msgs)

    @pytest.mark.asyncio
    async def test_subscribe_unknown_run_id_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"type": "subscribe", "run_id": "no-such-id"})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.UNKNOWN_SESSION for m in msgs)

    @pytest.mark.asyncio
    async def test_subscribe_missing_run_id_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"type": "subscribe"})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.MISSING_RUN_ID for m in msgs)

    @pytest.mark.asyncio
    async def test_input_missing_run_id_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps({"type": "input", "data": {"text": "hello"}})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.MISSING_RUN_ID for m in msgs)

    @pytest.mark.asyncio
    async def test_input_bad_payload_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        ws = FakeWebSocket([json.dumps({"type": "input", "run_id": orch.run_id, "data": {}})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.INVALID_PAYLOAD for m in msgs)

    @pytest.mark.asyncio
    async def test_approval_bad_payload_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        ws = FakeWebSocket([json.dumps({"type": "approval", "run_id": orch.run_id, "data": {}})])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.INVALID_PAYLOAD for m in msgs)

    @pytest.mark.asyncio
    async def test_non_dict_json_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([json.dumps(["an", "array"])])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.INVALID_JSON for m in msgs)


# ---------------------------------------------------------------------------
# Integration: session routing
# ---------------------------------------------------------------------------

class TestSessionRouting:
    @pytest.mark.asyncio
    async def test_subscribe_then_events_reach_client(self):
        """Attach session, subscribe client, emit executor event → client receives JSON."""
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        bridge.attach_session(orch)

        received: list[str] = []

        async def send(msg: str) -> None:
            received.append(msg)

        sub_msg = json.dumps({"type": "subscribe", "run_id": orch.run_id})
        ws = FakeWebSocket([sub_msg])

        # Run connection handler (will exhaust inbound messages then exit)
        await bridge.handle_connection(ws)

        # Manually emit an event after subscription (simulate executor output)
        # We need to set up the sender directly since the connection is closed
        handle = bridge._registry.get(orch.run_id)
        assert handle is not None

        handle.add_sender(send)
        await orch.handle_executor_event(OutputEvent(_now_ms(), "test output", "stdout"))

        assert received
        parsed = json.loads(received[0])
        assert parsed["event_type"] == "output"
        assert parsed["run_id"] == orch.run_id
        assert parsed["data"]["text"] == "test output"

    @pytest.mark.asyncio
    async def test_input_routes_to_correct_session(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        # Put orchestrator in RUNNING state
        orch.state_machine.transition(RuntimeExecutionState.STARTING)
        orch.state_machine.transition(RuntimeExecutionState.RUNNING)

        ws = FakeWebSocket([
            json.dumps({"type": "input", "run_id": orch.run_id, "data": {"text": "yes\n"}}),
        ])
        await bridge.handle_connection(ws)

        assert "yes\n" in proc.inputs
        msgs = ws.parsed()
        assert any(m.get("type") == "ack" and m.get("run_id") == orch.run_id for m in msgs)

    @pytest.mark.asyncio
    async def test_cancel_routes_to_correct_session(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        orch.state_machine.transition(RuntimeExecutionState.STARTING)
        orch.state_machine.transition(RuntimeExecutionState.RUNNING)

        ws = FakeWebSocket([
            json.dumps({"type": "cancel", "run_id": orch.run_id}),
        ])
        await bridge.handle_connection(ws)
        assert proc.terminated

    @pytest.mark.asyncio
    async def test_approval_approved_routes_to_process(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        orch.state_machine.transition(RuntimeExecutionState.STARTING)
        orch.state_machine.transition(RuntimeExecutionState.RUNNING)
        orch.state_machine.transition(RuntimeExecutionState.WAITING_FOR_APPROVAL)

        ws = FakeWebSocket([
            json.dumps({"type": "approval", "run_id": orch.run_id, "data": {"approved": True}}),
        ])
        await bridge.handle_connection(ws)
        assert "\n" in proc.inputs  # approved → sends newline

    @pytest.mark.asyncio
    async def test_command_on_unknown_session_returns_error(self):
        bridge = RuntimeWebSocketBridge()
        ws = FakeWebSocket([
            json.dumps({"type": "input", "run_id": "nonexistent-run", "data": {"text": "hi"}}),
        ])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.UNKNOWN_SESSION for m in msgs)

    @pytest.mark.asyncio
    async def test_run_ids_do_not_cross_contaminate(self):
        """Two sessions: input for run A must not reach run B."""
        bridge = RuntimeWebSocketBridge()
        orch_a = _make_orchestrator()
        orch_b = _make_orchestrator()
        proc_a = FakeProcess()
        proc_b = FakeProcess()
        bridge.attach_session(orch_a, proc_a)
        bridge.attach_session(orch_b, proc_b)

        for orch in (orch_a, orch_b):
            orch.state_machine.transition(RuntimeExecutionState.STARTING)
            orch.state_machine.transition(RuntimeExecutionState.RUNNING)

        ws = FakeWebSocket([
            json.dumps({"type": "input", "run_id": orch_a.run_id, "data": {"text": "only-for-a"}}),
        ])
        await bridge.handle_connection(ws)

        assert any("only-for-a" in inp for inp in proc_a.inputs)
        assert not proc_b.inputs  # run B should be untouched

    @pytest.mark.asyncio
    async def test_terminal_session_rejects_commands(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        # Drive to COMPLETED (terminal)
        orch.state_machine.transition(RuntimeExecutionState.STARTING)
        orch.state_machine.transition(RuntimeExecutionState.RUNNING)
        orch.state_machine.transition(RuntimeExecutionState.COMPLETED)

        ws = FakeWebSocket([
            json.dumps({"type": "input", "run_id": orch.run_id, "data": {"text": "late input"}}),
        ])
        await bridge.handle_connection(ws)
        msgs = ws.parsed()
        assert any(m.get("code") == BridgeErrorCode.SESSION_INACTIVE for m in msgs)


# ---------------------------------------------------------------------------
# Integration: lifecycle simulation
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_full_lifecycle_events_reach_client(self):
        """
        Simulate: STARTING → RUNNING → OUTPUT → WAITING_FOR_APPROVAL
                  → APPROVED → RUNNING → COMPLETED
        Using only fakes — no real CLI, no network.
        """
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator(FrameworkIdentity.COPILOT)
        bridge.attach_session(orch)

        delivered: list[dict] = []

        async def send(msg: str) -> None:
            delivered.append(json.loads(msg))

        handle = bridge._registry.get(orch.run_id)
        handle.add_sender(send)

        # Simulate executor firing events
        t = _now_ms()
        await orch.handle_executor_event(ProcessStartedEvent(t, pid=5000, framework="copilot"))
        await orch.handle_executor_event(OutputEvent(t + 1, "Analysing files...", "stdout"))
        await orch.handle_executor_event(ApprovalRequiredEvent(t + 2, "Allow write to main.py?"))
        await orch.handle_executor_event(OutputEvent(t + 3, "Writing main.py...", "stdout"))
        await orch.handle_executor_event(ProcessCompletedEvent(t + 4, exit_code=0))

        event_types = [e["event_type"] for e in delivered]
        assert "state_changed" in event_types
        assert "process_started" in event_types
        assert "output" in event_types
        assert "approval_required" in event_types
        assert "process_completed" in event_types

        # All events carry the same run_id
        run_ids = {e["run_id"] for e in delivered}
        assert run_ids == {orch.run_id}

        # Final state is completed
        final = delivered[-1]
        assert final["state"] == "completed"

    @pytest.mark.asyncio
    async def test_cancellation_lifecycle(self):
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        proc = FakeProcess()
        bridge.attach_session(orch, proc)

        delivered: list[dict] = []

        async def send(msg: str) -> None:
            delivered.append(json.loads(msg))

        handle = bridge._registry.get(orch.run_id)
        handle.add_sender(send)

        t = _now_ms()
        await orch.handle_executor_event(ProcessStartedEvent(t, pid=1))
        await orch.handle_executor_event(OutputEvent(t + 1, "Working...", "stdout"))
        # Simulate process being interrupted externally
        await orch.handle_executor_event(ProcessInterruptedEvent(t + 2))

        states = [e.get("state") for e in delivered if "state" in e]
        assert "cancelled" in states

    @pytest.mark.asyncio
    async def test_disconnect_does_not_kill_session(self):
        """
        Client disconnects mid-session. The session (orchestrator) should
        remain in the registry and still be queryable.
        """
        bridge = RuntimeWebSocketBridge()
        orch = _make_orchestrator()
        bridge.attach_session(orch)

        # Client connects and subscribes
        ws = FakeWebSocket([json.dumps({"type": "subscribe", "run_id": orch.run_id})])
        await bridge.handle_connection(ws)

        # After disconnect, session is still registered
        handle = bridge._registry.get(orch.run_id)
        assert handle is not None
        # Orchestrator state is unchanged
        assert not orch.state_machine.is_terminal()
