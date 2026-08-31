# Track B — Complete Runtime Foundation (B4–B6)

## Overview

Track B has established a complete **runtime abstraction foundation** for the Jarvis/Claudex Studio project. Three phases have been implemented:

- **B4**: Framework contract and adapters
- **B5**: Process execution and lifecycle
- **B6**: Event normalization and state machine

The result is a neutral, framework-agnostic runtime layer ready for UI/WebSocket integration in B7.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│ Framework CLI (Claude Code, Codex, Copilot, Ollama)    │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ B4: Framework Contract Layer                            │
│ - FrameworkAdapter (abstract base)                      │
│ - RuntimeConfig (neutral config)                        │
│ - ClaudeAdapter, CodexAdapter, CopilotAdapter          │
│ - FrameworkIdentity enum                               │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ B5: Process Execution Layer                             │
│ - RuntimeProcessExecutor (spawn and manage)             │
│ - RuntimeProcess (managed subprocess)                   │
│ - stdin/stdout/stderr streaming                         │
│ - RuntimeProcessState (STARTING→RUNNING→COMPLETE)      │
│ - RuntimeEvent taxonomy                                 │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ B6: State Machine & Normalization Layer                 │
│ - RuntimeExecutionState (framework-neutral)             │
│ - RuntimeStateMachine (deterministic transitions)       │
│ - RuntimeMetrics (structured data collection)           │
│ - RuntimeSessionOrchestrator (event conversion)         │
│ - RuntimeSessionEvent (JSON-ready normalization)        │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ B7+ (FUTURE): WebSocket Bridge & UI                     │
│ - Consume RuntimeSessionEvent                           │
│ - WebSocket transport                                   │
│ - Claudex Studio (Xterm.js + Dashboard)                 │
└─────────────────────────────────────────────────────────┘
```

---

## B4: Framework Contract

### What B4 Does
- Defines the neutral `RuntimeConfig` object (executable, prompt, model, provider, etc.)
- Provides `FrameworkAdapter` abstract base class
- Implements three concrete adapters (Claude, Codex, Copilot)
- Normalizes framework-specific execution into a common interface

### Key Components
- `FrameworkIdentity`: Enum for framework type
- `RuntimeConfig`: Neutral execution configuration
- `FrameworkAdapter`: Abstract CLI/environment translator
  - `build_command(config)`: Framework-specific command construction
  - `build_environment(config)`: Framework-specific environment setup

### Design Principle
> Framework specifics (CLI flags, auth tokens, model routing) go in adapters.
> Everything else stays neutral.

### Status
✅ Stable (B1-B3 research + B4 implementation validated by B5/B6 integration)

---

## B5: Process Execution

### What B5 Does
- Spawns and manages async subprocesses
- Handles stdin/stdout/stderr independently
- Detects basic input/approval prompts via heuristics
- Tracks process lifecycle and exit codes
- Converts raw subprocess activity into normalized events

### Key Components
- `RuntimeProcessExecutor`: Static factory for spawning processes
- `RuntimeProcess`: Managed subprocess wrapper
- `RuntimeProcessState`: Subprocess state (STARTING, RUNNING, COMPLETED, FAILED, CANCELLED)
- `RuntimeEvent` taxonomy:
  - ProcessStartedEvent
  - OutputEvent (stdout/stderr)
  - InputRequiredEvent
  - ApprovalRequiredEvent
  - ProcessCompletedEvent
  - ProcessFailedEvent
  - ProcessInterruptedEvent
  - ErrorEvent

### Key Features
- Async-friendly (uses asyncio.create_subprocess_exec)
- Framework-neutral (doesn't care what process runs)
- Prompt detection via keyword matching (B5 only, not ML-based)
- Graceful cancellation/termination
- Event streaming via queue + callback

### Status
✅ Stable (14 tests, full integration with B4 adapters, validated by B6)

---

## B6: Event Normalization & State Machine

### What B6 Does
- Converts raw B5 executor events into semantic runtime state
- Maintains deterministic state machine for execution lifecycle
- Generates run IDs for execution identity tracking
- Collects structured metrics for UI consumption
- Normalizes events for JSON/WebSocket serialization

### Key Components
- `RuntimeExecutionState`: Framework-neutral state enum (8 states)
- `RuntimeStateMachine`: Deterministic state transition engine
- `RuntimeMetrics`: Structured metrics (timestamps, counts, flags, exit code)
- `RuntimeSessionEvent`: Normalized event with run_id, state, timestamp, data
- `RuntimeSessionOrchestrator`: Orchestrates B5→B6 conversion

### Key Features
- Deterministic state transitions (no ambiguous paths)
- Run ID tracking (UUID-based execution identity)
- Input vs Approval distinction (WAITING_FOR_INPUT vs WAITING_FOR_APPROVAL)
- No automatic approvals (strict policy, requires external action)
- Event callback support (sync/async)
- JSON serialization ready (`to_dict()` for WebSocket)
- Framework-neutral (same logic for Claude/Codex/Copilot)

### Status
✅ Complete (39 new tests, full Track A integration validation, 132/132 app tests pass)

---

## State Machine Diagram (B6)

```
                    ┌─────────────────┐
                    │      IDLE       │
                    └────────┬────────┘
                             │ executor.execute()
                    ┌────────v────────┐
                    │    STARTING     │
                    └────────┬────────┘
                             │ ProcessStartedEvent
                    ┌────────v────────┐
          ┌─────────→│     RUNNING     │←─────────────┐
          │         └────┬───────┬────┘              │
          │              │       │                   │
     input_provided()    │       │              approval_provided()
          │              │       │                   │
    ┌─────┴──────────┐   │       │         ┌────────┴──────────┐
    │                │   │       │         │                   │
┌───┴────────────────────┴──┐  ┌─┴────┐  ┌┴───────────────────┴──┐
│ WAITING_FOR_INPUT         │  │      │  │ WAITING_FOR_APPROVAL   │
└────────┬───────────────────┘  │      │  └┬──────────────────────┘
         │                      │      │   │
         └──────────┬───────────┘      └───┴────────┐
                    │                               │
         ┌──────────v──────────┐      ┌─────────────v────┐
         │ ProcessCompletedEvent       ProcessFailedEvent
         │      (exit 0)        │      │  (exit != 0)    │
         └──────────┬──────────┘      └────────┬─────────┘
                    │                          │
         ┌──────────v────────────────────────v──┐
         │         COMPLETED       FAILED       │
         │       (TERMINAL)       (TERMINAL)    │
         └─────────────────────────────────────┘

   Additional: ProcessInterruptedEvent → CANCELLED (TERMINAL)
```

---

## Integration Points

### B4 ↔ B5
- B5 receives `RuntimeConfig` from B4 adapters
- B5 calls `adapter.build_command(config)` and `adapter.build_environment(config)`
- B5 produces `RuntimeEvent` objects (framework-agnostic)

### B5 ↔ B6
- B6 receives `RuntimeEvent` objects from B5
- B6 converts them to `RuntimeSessionEvent` (normalized for transport)
- B6 manages state machine based on event types
- B6 tracks metrics automatically

### B6 ↔ B7 (Future)
- B7 subscribes to `RuntimeSessionOrchestrator.get_session_event()`
- B7 serializes events via `event.to_dict()`
- B7 sends over WebSocket to Claudex Studio UI
- B7 calls `executor.send_input()` when user responds
- B7 calls `orchestrator.handle_input_provided()` after sending

---

## Metrics Collection (B6)

B6 automatically collects the following metrics during execution:

```python
RuntimeMetrics(
    run_id="550e8400-e29b-41d4-a716-446655440000",  # UUID
    framework="codex",                               # From adapter
    model="gpt-oss:120b",                           # From config
    provider="ollama",                              # From config
    state=RuntimeExecutionState.RUNNING,            # Current state
    start_time_ms=1693512345000,                    # When started
    end_time_ms=None,                               # When completed (if done)
    exit_code=None,                                 # Exit code (if done)
    stdout_lines=42,                                # Count of stdout lines
    stderr_lines=3,                                 # Count of stderr lines
    input_required_count=2,                         # Times input requested
    approval_required_count=1,                      # Times approval requested
    is_waiting_for_input=False,                     # Current input state
    is_waiting_for_approval=False,                  # Current approval state
)

# Computed properties
metrics.elapsed_ms  # Milliseconds from start to now
metrics.duration_seconds  # Elapsed time in seconds
```

---

## Event Types and Flow

### Full Event Sequence Example

```
Executor Event          →  B6 Normalization           →  RuntimeSessionEvent
────────────────────────────────────────────────────────────────────────────

ProcessStartedEvent     →  IDLE→STARTING→RUNNING    →  state_changed (STARTING)
(pid=1234)                 + start_time_ms = T₁        state_changed (RUNNING)
                                                        process_started (pid=1234)

OutputEvent (stdout)    →  stdout_lines++            →  output (stream=stdout, text)
"Processing..."

InputRequiredEvent      →  RUNNING→WAITING_FOR_INPUT →  input_required (prompt)
"Enter choice:"         +  input_required_count++       state_changed (WAITING_FOR_INPUT)

[External: input provided]

[External: orchestrator.handle_input_provided()]
                        →  WAITING_FOR_INPUT→RUNNING →  (implicit state transition)
                        +  is_waiting_for_input=False

OutputEvent (stdout)    →  stdout_lines++            →  output (stream=stdout, text)
"Processing resumed"

ProcessCompletedEvent   →  RUNNING→COMPLETED        →  process_completed (exit_code=0)
(exit_code=0)           +  end_time_ms = T₂
                        +  final metrics calculated
```

---

## Design Philosophy

### Clean Boundaries
- **B4**: How to translate from neutral to framework-specific
- **B5**: How to execute processes
- **B6**: What is happening to an execution
- **B7**: How to show that to users

### Framework Neutrality
- No special logic for Claude, Codex, or Copilot in B6
- Framework differences handled by adapters (B4) or detectors (B5)
- Same state machine works for all frameworks

### Determinism
- State transitions are explicit and validated
- Invalid transitions raise errors or return False
- No probabilistic or ambiguous paths
- Metrics only collect observable facts

### No Over-Engineering
- No LLM-based semantic analysis
- No complex terminal parsing
- No automatic approval logic
- Only what is needed for the UI contract

---

## Validation Summary

### Test Coverage
- **B4 Adapters**: 7 tests (via B5 integration tests)
- **B5 Executor**: 14 tests (process management, event generation)
- **B6 Runtime**: 39 tests (state machine, metrics, normalization)
- **Track A Tools**: 79 tests (unchanged, fully compatible)

**Total: 132 tests passing**

### Quality Metrics
- ✅ Full app compilation successful
- ✅ No whitespace or merge issues
- ✅ All tests deterministic and fast (6.70s total)
- ✅ No breaking changes to Track A
- ✅ Framework-agnostic implementation
- ✅ WebSocket-ready serialization

---

## Files in Track B

### B4 (Framework Contract)
- `app/runtime/contract.py` (63 lines)
- `app/runtime/adapters/claude.py` (42 lines)
- `app/runtime/adapters/codex.py` (43 lines)
- `app/runtime/adapters/copilot.py` (43 lines)

### B5 (Process Execution)
- `app/runtime/events.py` (90 lines)
- `app/runtime/executor.py` (242 lines)
- `app/runtime/test_executor.py` (168 lines)
- `app/runtime/test_adapters.py` (80 lines)

### B6 (State Machine & Normalization)
- `app/runtime/runtime.py` (337 lines)
- `app/runtime/test_runtime.py` (425 lines)

### Reports
- `Implementation_Reports/B4_REPORT.md`
- `Implementation_Reports/B5_REPORT.md`
- `Implementation_Reports/B6_REPORT.md`
- `B6_IMPLEMENTATION_SUMMARY.md`
- `B6_ARCHITECTURE.md`

---

## Readiness for B7

B6 establishes a stable contract for B7:

1. **Deterministic events**: Every event has `run_id`, `state`, `timestamp_ms`, `framework`, and `data`
2. **JSON-ready**: `event.to_dict()` produces immediately serializable objects
3. **No subprocess knowledge needed**: B7 works purely with events and metrics
4. **Framework-agnostic**: Same logic for Claude/Codex/Copilot
5. **Extensible**: New event types can be added to `data` dict without breaking serialization
6. **No breaking changes**: B6 contract is stable and unlikely to change

B7 can now implement the WebSocket bridge with confidence that:
- No changes to B6 will be required
- The normalized event stream is complete and sufficient
- Metrics are structured and accessible
- User input/approval responses can be sent back safely

---

## Summary

Track B (B4–B6) has successfully built a **neutral, deterministic runtime abstraction** for the Jarvis/Claudex Studio project:

- **B4** translates neutral config into framework-specific execution
- **B5** manages process lifecycle and generates events
- **B6** normalizes events and maintains semantic state
- **B7+** can now build UI/transport layer without touching B4-B6

All phases are complete, tested, and ready for production use.

The foundation is solid. The contract is stable. B7 can proceed.
