from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class EventType(Enum):
    PROCESS_STARTED = "process_started"
    OUTPUT = "output"
    ERROR = "error"
    INPUT_REQUIRED = "input_required"
    APPROVAL_REQUIRED = "approval_required"
    PROCESS_COMPLETED = "process_completed"
    PROCESS_FAILED = "process_failed"
    PROCESS_INTERRUPTED = "process_interrupted"

@dataclass
class RuntimeEvent:
    """Base class for normalized runtime events emitted by framework adapters."""
    event_type: EventType
    timestamp_ms: int

@dataclass
class ProcessStartedEvent(RuntimeEvent):
    pid: Optional[int] = None
    framework: Optional[str] = None
    
    def __init__(self, timestamp_ms: int, pid: Optional[int] = None, framework: Optional[str] = None):
        super().__init__(EventType.PROCESS_STARTED, timestamp_ms)
        self.pid = pid
        self.framework = framework

@dataclass
class OutputEvent(RuntimeEvent):
    text: str
    stream: str = "stdout"  # "stdout" or "stderr"
    
    def __init__(self, timestamp_ms: int, text: str, stream: str = "stdout"):
        super().__init__(EventType.OUTPUT, timestamp_ms)
        self.text = text
        self.stream = stream

@dataclass
class ErrorEvent(RuntimeEvent):
    message: str
    code: Optional[str] = None
    
    def __init__(self, timestamp_ms: int, message: str, code: Optional[str] = None):
        super().__init__(EventType.ERROR, timestamp_ms)
        self.message = message
        self.code = code

@dataclass
class InputRequiredEvent(RuntimeEvent):
    prompt_text: str
    
    def __init__(self, timestamp_ms: int, prompt_text: str):
        super().__init__(EventType.INPUT_REQUIRED, timestamp_ms)
        self.prompt_text = prompt_text

@dataclass
class ApprovalRequiredEvent(RuntimeEvent):
    action_description: str
    
    def __init__(self, timestamp_ms: int, action_description: str):
        super().__init__(EventType.APPROVAL_REQUIRED, timestamp_ms)
        self.action_description = action_description

@dataclass
class ProcessCompletedEvent(RuntimeEvent):
    exit_code: int
    
    def __init__(self, timestamp_ms: int, exit_code: int):
        super().__init__(EventType.PROCESS_COMPLETED, timestamp_ms)
        self.exit_code = exit_code

@dataclass
class ProcessFailedEvent(RuntimeEvent):
    exit_code: int
    reason: str
    
    def __init__(self, timestamp_ms: int, exit_code: int, reason: str):
        super().__init__(EventType.PROCESS_FAILED, timestamp_ms)
        self.exit_code = exit_code
        self.reason = reason

@dataclass
class ProcessInterruptedEvent(RuntimeEvent):
    def __init__(self, timestamp_ms: int):
        super().__init__(EventType.PROCESS_INTERRUPTED, timestamp_ms)
