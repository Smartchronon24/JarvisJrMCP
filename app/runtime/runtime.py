"""
B6: Runtime Event Normalization & State Machine

This layer sits between the B5 executor (which manages raw subprocess lifecycle)
and future UI/WebSocket consumers (which need deterministic, framework-neutral state).

Key responsibilities:
  - Maintain a deterministic state machine for runtime execution
  - Normalize raw executor events into semantic runtime events
  - Assign and track run IDs for execution identity
  - Collect structured runtime metrics
  - Distinguish between input-required and approval-required semantics
  - Remain framework-neutral while consuming Claude/Codex/Copilot executor output

The contract:
  RuntimeSessionOrchestrator consumes RuntimeProcess and emits normalized
  RuntimeSessionEvent objects that are ready for downstream UI/WebSocket transport.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable, List

from app.runtime.contract import FrameworkIdentity, RuntimeConfig
from app.runtime.events import (
    RuntimeEvent,
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


class RuntimeExecutionState(Enum):
    """Framework-neutral runtime state machine."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeStateTransitionError(RuntimeError):
    """Raised when an invalid state transition is attempted."""


@dataclass
class RuntimeMetrics:
    """Structured metrics for a runtime execution."""
    run_id: str
    framework: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    state: RuntimeExecutionState = RuntimeExecutionState.IDLE
    start_time_ms: Optional[int] = None
    end_time_ms: Optional[int] = None
    exit_code: Optional[int] = None
    stdout_lines: int = 0
    stderr_lines: int = 0
    input_required_count: int = 0
    approval_required_count: int = 0
    is_waiting_for_input: bool = False
    is_waiting_for_approval: bool = False

    @property
    def elapsed_ms(self) -> Optional[int]:
        if self.start_time_ms is None:
            return None
        end = self.end_time_ms if self.end_time_ms is not None else time.time_ns() // 1_000_000
        return end - self.start_time_ms

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.elapsed_ms is None:
            return None
        return self.elapsed_ms / 1000.0


@dataclass
class RuntimeSessionEvent:
    """A normalized event emitted by the runtime state machine."""
    event_type: str  # "state_changed", "output", "input_required", "approval_required", etc.
    run_id: str
    timestamp_ms: int
    framework: Optional[str] = None
    state: Optional[RuntimeExecutionState] = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for WebSocket transport."""
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "timestamp_ms": self.timestamp_ms,
            "framework": self.framework,
            "state": self.state.value if self.state else None,
            "data": self.data,
        }


class RuntimeStateMachine:
    """Manages deterministic state transitions for runtime execution."""

    _VALID_TRANSITIONS = {
        RuntimeExecutionState.IDLE: {
            RuntimeExecutionState.STARTING,
        },
        RuntimeExecutionState.STARTING: {
            RuntimeExecutionState.RUNNING,
            RuntimeExecutionState.FAILED,
        },
        RuntimeExecutionState.RUNNING: {
            RuntimeExecutionState.WAITING_FOR_INPUT,
            RuntimeExecutionState.WAITING_FOR_APPROVAL,
            RuntimeExecutionState.COMPLETED,
            RuntimeExecutionState.FAILED,
            RuntimeExecutionState.CANCELLED,
        },
        RuntimeExecutionState.WAITING_FOR_INPUT: {
            RuntimeExecutionState.RUNNING,
            RuntimeExecutionState.COMPLETED,
            RuntimeExecutionState.FAILED,
            RuntimeExecutionState.CANCELLED,
        },
        RuntimeExecutionState.WAITING_FOR_APPROVAL: {
            RuntimeExecutionState.RUNNING,
            RuntimeExecutionState.COMPLETED,
            RuntimeExecutionState.FAILED,
            RuntimeExecutionState.CANCELLED,
        },
        RuntimeExecutionState.COMPLETED: set(),
        RuntimeExecutionState.FAILED: set(),
        RuntimeExecutionState.CANCELLED: set(),
    }

    def __init__(self):
        self.current = RuntimeExecutionState.IDLE

    def transition(self, new_state: RuntimeExecutionState) -> bool:
        """Attempt a state transition. Returns True if successful."""
        if new_state == self.current:
            return True
        if new_state not in self._VALID_TRANSITIONS.get(self.current, set()):
            return False
        self.current = new_state
        return True

    def try_transition(self, new_state: RuntimeExecutionState) -> None:
        """Attempt transition; raise on failure."""
        if not self.transition(new_state):
            raise RuntimeStateTransitionError(
                f"Invalid transition: {self.current.value} -> {new_state.value}"
            )

    def is_terminal(self) -> bool:
        """Check if current state is terminal (execution ended)."""
        return self.current in {
            RuntimeExecutionState.COMPLETED,
            RuntimeExecutionState.FAILED,
            RuntimeExecutionState.CANCELLED,
        }


class RuntimeSessionOrchestrator:
    """
    Normalizes executor events into framework-neutral runtime state/metrics.

    Consumes B5 RuntimeProcess events and emits normalized RuntimeSessionEvent objects.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        framework_identity: FrameworkIdentity,
        event_callback: Optional[Callable[[RuntimeSessionEvent], None | Awaitable[None]]] = None,
    ):
        self.config = config
        self.framework_identity = framework_identity
        self.run_id = str(uuid.uuid4())
        self.state_machine = RuntimeStateMachine()
        self.metrics = RuntimeMetrics(
            run_id=self.run_id,
            framework=framework_identity.value,
            model=config.model_name,
            provider=config.provider_name,
        )
        self._event_callback = event_callback
        self._session_events: asyncio.Queue[RuntimeSessionEvent] = asyncio.Queue()

    async def _emit_session_event(self, event: RuntimeSessionEvent) -> None:
        """Emit a normalized session event."""
        if self._event_callback is not None:
            result = self._event_callback(event)
            if asyncio.iscoroutine(result):
                await result
        self._session_events.put_nowait(event)

    async def _try_transition_and_emit(
        self,
        new_state: RuntimeExecutionState,
        executor_event: Optional[RuntimeEvent] = None,
    ) -> bool:
        """Attempt a state transition and emit a state_changed event if successful."""
        if self.state_machine.transition(new_state):
            self.metrics.state = new_state
            event = RuntimeSessionEvent(
                event_type="state_changed",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms if executor_event else int(time.time_ns() // 1_000_000),
                framework=self.framework_identity.value,
                state=new_state,
            )
            await self._emit_session_event(event)
            return True
        return False

    async def handle_executor_event(self, executor_event: RuntimeEvent) -> None:
        """Process a raw executor event and normalize it."""

        if isinstance(executor_event, ProcessStartedEvent):
            await self._try_transition_and_emit(RuntimeExecutionState.STARTING, executor_event)
            await self._try_transition_and_emit(RuntimeExecutionState.RUNNING, executor_event)
            self.metrics.start_time_ms = executor_event.timestamp_ms
            event = RuntimeSessionEvent(
                event_type="process_started",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"pid": executor_event.pid},
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, OutputEvent):
            if executor_event.stream == "stdout":
                self.metrics.stdout_lines += 1
            elif executor_event.stream == "stderr":
                self.metrics.stderr_lines += 1
            event = RuntimeSessionEvent(
                event_type="output",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={
                    "stream": executor_event.stream,
                    "text": executor_event.text,
                },
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, InputRequiredEvent):
            self.metrics.input_required_count += 1
            self.metrics.is_waiting_for_input = True
            await self._try_transition_and_emit(RuntimeExecutionState.WAITING_FOR_INPUT, executor_event)
            event = RuntimeSessionEvent(
                event_type="input_required",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"prompt": executor_event.prompt_text},
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, ApprovalRequiredEvent):
            self.metrics.approval_required_count += 1
            self.metrics.is_waiting_for_approval = True
            await self._try_transition_and_emit(RuntimeExecutionState.WAITING_FOR_APPROVAL, executor_event)
            event = RuntimeSessionEvent(
                event_type="approval_required",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"action": executor_event.action_description},
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, ProcessCompletedEvent):
            self.metrics.exit_code = executor_event.exit_code
            self.metrics.end_time_ms = executor_event.timestamp_ms
            self.metrics.is_waiting_for_input = False
            self.metrics.is_waiting_for_approval = False
            await self._try_transition_and_emit(RuntimeExecutionState.COMPLETED, executor_event)
            event = RuntimeSessionEvent(
                event_type="process_completed",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"exit_code": executor_event.exit_code},
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, ProcessFailedEvent):
            self.metrics.exit_code = executor_event.exit_code
            self.metrics.end_time_ms = executor_event.timestamp_ms
            self.metrics.is_waiting_for_input = False
            self.metrics.is_waiting_for_approval = False
            await self._try_transition_and_emit(RuntimeExecutionState.FAILED, executor_event)
            event = RuntimeSessionEvent(
                event_type="process_failed",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"exit_code": executor_event.exit_code, "reason": executor_event.reason},
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, ProcessInterruptedEvent):
            self.metrics.end_time_ms = executor_event.timestamp_ms
            self.metrics.is_waiting_for_input = False
            self.metrics.is_waiting_for_approval = False
            await self._try_transition_and_emit(RuntimeExecutionState.CANCELLED, executor_event)
            event = RuntimeSessionEvent(
                event_type="process_cancelled",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
            )
            await self._emit_session_event(event)

        elif isinstance(executor_event, ErrorEvent):
            event = RuntimeSessionEvent(
                event_type="error",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
                data={"message": executor_event.message, "code": executor_event.code},
            )
            await self._emit_session_event(event)

        else:
            # Unknown event type; pass through as generic
            event = RuntimeSessionEvent(
                event_type="unknown",
                run_id=self.run_id,
                timestamp_ms=executor_event.timestamp_ms,
                framework=self.framework_identity.value,
                state=self.state_machine.current,
            )
            await self._emit_session_event(event)

    def handle_input_provided(self) -> None:
        """Mark that input has been provided by an external controller."""
        if self.metrics.is_waiting_for_input:
            self.metrics.is_waiting_for_input = False
        self.state_machine.transition(RuntimeExecutionState.RUNNING)
        self.metrics.state = RuntimeExecutionState.RUNNING

    def handle_approval_provided(self) -> None:
        """Mark that approval has been provided by an external controller."""
        if self.metrics.is_waiting_for_approval:
            self.metrics.is_waiting_for_approval = False
        self.state_machine.transition(RuntimeExecutionState.RUNNING)
        self.metrics.state = RuntimeExecutionState.RUNNING

    async def get_session_event(self) -> RuntimeSessionEvent:
        """Retrieve the next session event from the queue."""
        return await self._session_events.get()

    def get_metrics(self) -> RuntimeMetrics:
        """Return current execution metrics."""
        return self.metrics
