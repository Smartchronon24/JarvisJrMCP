# B6 Integration Architecture Overview

## Track B Runtime Stack

```
┌─────────────────────────────────────────────────────────────────┐
│ FUTURE: Claudex Studio UI                                       │
│ - Xterm.js rendering                                            │
│ - Dashboard metrics                                             │
│ - Approval/input overlays                                       │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│ B7 (FUTURE): WebSocket Bridge                                   │
│ - Serialize RuntimeSessionEvent to JSON                         │
│ - Send events over WebSocket                                    │
│ - Receive user input                                            │
│ - Call RuntimeProcess.send_input()                              │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│ B6 (NEW): Runtime State Machine & Normalization                │
│                                                                 │
│ RuntimeSessionOrchestrator                                      │
│   ├─ RuntimeStateMachine                                        │
│   ├─ RuntimeMetrics                                             │
│   └─ RuntimeSessionEvent → WebSocket-ready                      │
│                                                                 │
│ State Transitions:                                              │
│   IDLE → STARTING → RUNNING → {WAITING_FOR_INPUT,              │
│          WAITING_FOR_APPROVAL, COMPLETED, FAILED, CANCELLED}    │
│                                                                 │
│ Run ID: UUID-based execution identity                           │
│ Metrics: timestamps, line counts, exit codes                    │
│ Events: type, state, framework, data                            │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│ B5 (EXISTING): Process Execution & Lifecycle                    │
│                                                                 │
│ RuntimeProcessExecutor.execute()                                │
│   ├─ RuntimeProcess                                             │
│   ├─ stdin/stdout/stderr streams                                │
│   ├─ OutputEvent generation                                     │
│   ├─ InputRequiredEvent detection                               │
│   ├─ ApprovalRequiredEvent detection                            │
│   └─ ProcessCompletedEvent / ProcessFailedEvent                 │
│                                                                 │
│ Events: ProcessStartedEvent, OutputEvent, ErrorEvent, etc.      │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│ B4 (EXISTING): Framework Abstraction                            │
│                                                                 │
│ FrameworkAdapter (abstract)                                     │
│   ├─ ClaudeAdapter                                              │
│   ├─ CodexAdapter                                               │
│   └─ CopilotAdapter                                             │
│                                                                 │
│ RuntimeConfig (neutral configuration)                           │
│ FrameworkIdentity (CLAUDE, CODEX, COPILOT, UNKNOWN)             │
│                                                                 │
│ Methods:                                                        │
│   - build_command(config)                                       │
│   - build_environment(config)                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│ Framework CLIs (External)                                       │
│ - claude (Claude Code)                                          │
│ - codex (Codex)                                                 │
│ - copilot (GitHub Copilot)                                      │
│ - ollama (Local LLM provider)                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow Through B6

```
B5: ProcessStartedEvent
    │
    ├─ pid=1234, framework="codex"
    │
    ↓
B6: RuntimeSessionOrchestrator.handle_executor_event()
    │
    ├─ State: STARTING → RUNNING
    ├─ Metrics.start_time_ms = 1000
    ├─ Metrics.framework = "codex"
    │
    ├─ Emit: RuntimeSessionEvent
    │         event_type="state_changed"
    │         state=STARTING
    │         run_id="550e8400-e29b-41d4-a716-446655440000"
    │         timestamp_ms=1000
    │
    ├─ Emit: RuntimeSessionEvent
    │         event_type="state_changed"
    │         state=RUNNING
    │         run_id="550e8400-e29b-41d4-a716-446655440000"
    │         timestamp_ms=1000
    │
    └─ Emit: RuntimeSessionEvent
             event_type="process_started"
             state=RUNNING
             run_id="550e8400-e29b-41d4-a716-446655440000"
             timestamp_ms=1000
             data={pid: 1234}
                ↓
             B7: WebSocket Bridge serializes to JSON
                 and sends to UI
                 ↓
             UI: Renders dashboard, starts Xterm.js
```

## State Transition Diagram

```
                    ┌─ IDLE ─┐
                    │        ├─ start() ─→ STARTING
                    └────────┘              │
                                            ├─ process_started
                                            ↓
                                      ┌─ RUNNING ─┐
                                      │           │
                 ┌────────────────────┤           ├────────────────────┐
                 │                    └─────────┬─┘                    │
                 │                              │                      │
                 ↓                              ↓                      ↓
        ┌─ WAITING_FOR_INPUT ─┐      ┌─ WAITING_FOR_APPROVAL ─┐   COMPLETED
        │  (prompt detected)   │      │  (approval detected)   │   (exit 0)
        │                      │      │                        │
        └──────────┬───────────┘      └───────────┬────────────┘
                   │                              │
          input_provided()                approval_provided()
                   │                              │
                   └──────────→ RUNNING ←─────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ↓                 ↓                 ↓
            COMPLETED          FAILED            CANCELLED
           (exit 0 OK)      (exit != 0)       (terminated)
           (TERMINAL)         (TERMINAL)       (TERMINAL)
```

## B6 Classes and Methods

### RuntimeStateMachine
```python
current: RuntimeExecutionState
transition(new_state) -> bool         # Safe transition
try_transition(new_state) -> None     # Transition or raise
is_terminal() -> bool                 # Check if terminal state
```

### RuntimeMetrics
```python
run_id: str
framework, model, provider: Optional[str]
state: RuntimeExecutionState
start_time_ms, end_time_ms: Optional[int]
exit_code: Optional[int]
stdout_lines, stderr_lines: int
input_required_count, approval_required_count: int
is_waiting_for_input, is_waiting_for_approval: bool

# Properties
elapsed_ms -> Optional[int]
duration_seconds -> Optional[float]
```

### RuntimeSessionEvent
```python
event_type: str                       # "state_changed", "output", etc.
run_id: str                           # Execution identity
timestamp_ms: int
framework: Optional[str]              # "codex", "claude", etc.
state: Optional[RuntimeExecutionState]
data: dict                            # Event-specific data

# Methods
to_dict() -> dict                     # WebSocket-ready serialization
```

### RuntimeSessionOrchestrator
```python
# Core methods
handle_executor_event(event) -> None         # Process B5 events
get_session_event() -> RuntimeSessionEvent   # Pull normalized events
get_metrics() -> RuntimeMetrics               # Access metrics

# Input/Approval handling
handle_input_provided() -> None              # Mark input wait complete
handle_approval_provided() -> None           # Mark approval wait complete

# Properties
run_id: str                                  # Unique execution ID
state_machine: RuntimeStateMachine           # State management
metrics: RuntimeMetrics                      # Collected metrics
```

## Event Mapping (B5 → B6)

| B5 Event | B6 Event | State Transition | Key Semantics |
|----------|----------|------------------|---------------|
| ProcessStartedEvent | process_started | IDLE→STARTING→RUNNING | Process spawned, PID available |
| OutputEvent stdout | output | (no change) | stdout line received |
| OutputEvent stderr | output | (no change) | stderr line received |
| InputRequiredEvent | input_required | RUNNING→WAITING_FOR_INPUT | Prompt text in data.prompt |
| ApprovalRequiredEvent | approval_required | RUNNING→WAITING_FOR_APPROVAL | Action in data.action |
| ProcessCompletedEvent | process_completed | RUNNING→COMPLETED | Clean exit, exit_code=0 |
| ProcessFailedEvent | process_failed | RUNNING→FAILED | Error exit, exit_code!=0 |
| ProcessInterruptedEvent | process_cancelled | RUNNING→CANCELLED | User terminated |
| ErrorEvent | error | (no change) | Stream/process error in data.message |

## Integration Points for B7

### Input from B6
```python
# Subscribe to events
event = await orchestrator.get_session_event()

# Serialize to JSON
json.dumps(event.to_dict())

# Access metrics
metrics = orchestrator.get_metrics()
```

### Output to B6
```python
# Send user input
await executor.send_input("y\n")

# Mark input handled
orchestrator.handle_input_provided()

# Mark approval handled
orchestrator.handle_approval_provided()
```

## Design Guarantees for B7

1. **No framework-specific logic needed**: B7 works the same for Claude/Codex/Copilot
2. **Deterministic state**: State transitions are predictable and testable
3. **Run ID correlation**: All events share `run_id` for linking
4. **JSON-ready**: `event.to_dict()` is immediately WebSocket-sendable
5. **No subprocess knowledge**: B7 never touches process management details
6. **Extensible data field**: Future event types can be added to `data` dict without breaking serialization

---

## Files in B6

- **app/runtime/runtime.py** (337 lines)
  - RuntimeExecutionState
  - RuntimeStateTransitionError
  - RuntimeMetrics
  - RuntimeSessionEvent
  - RuntimeStateMachine
  - RuntimeSessionOrchestrator

- **app/runtime/test_runtime.py** (425 lines)
  - 39 unit tests

- **Implementation_Reports/B6_REPORT.md** (432 lines)
  - Detailed design documentation

- **app/runtime/__init__.py** (modified)
  - Exports B6 classes

---

## Validation Summary

✅ 39 B6 tests pass  
✅ 53 total runtime tests pass (B4+B5+B6)  
✅ 132 total app tests pass (all tracks)  
✅ No changes to Track A  
✅ No breaking changes  
✅ Ready for B7 implementation  

---

## Next Phase: B7

B7 should implement:

```
B6 RuntimeSessionOrchestrator
    ↓ [subscribe to events]
B7 WebSocket Bridge
    ├─ Serialize RuntimeSessionEvent to JSON
    ├─ Send over WebSocket to UI
    ├─ Receive user input from UI
    └─ Call executor.send_input()
    ↓ [no B6 changes needed]
Claudex Studio UI
    ├─ Xterm.js for terminal rendering
    ├─ Dashboard for metrics
    └─ Overlays for input/approval
```

B6 contract is stable and ready.
