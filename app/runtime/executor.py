from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.runtime.contract import FrameworkAdapter, RuntimeConfig
from app.runtime.events import (
    ApprovalRequiredEvent,
    ErrorEvent,
    InputRequiredEvent,
    OutputEvent,
    ProcessCompletedEvent,
    ProcessFailedEvent,
    ProcessInterruptedEvent,
    ProcessStartedEvent,
    RuntimeEvent,
)


class RuntimeProcessState(Enum):
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeExecutionError(RuntimeError):
    """Raised when a runtime process cannot be started or controlled safely."""


@dataclass
class RuntimeExecutionResult:
    state: RuntimeProcessState
    exit_code: Optional[int]
    events: list[RuntimeEvent]


class RuntimeProcess:
    """A managed asynchronous wrapper around a framework subprocess."""

    def __init__(self, adapter: FrameworkAdapter, config: RuntimeConfig, process: asyncio.subprocess.Process):
        self.adapter = adapter
        self.config = config
        self.process = process
        self.state = RuntimeProcessState.STARTING
        self.events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._completion = asyncio.Event()
        self._stdout_task: Optional[asyncio.Task[None]] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None
        self._watch_task: Optional[asyncio.Task[None]] = None
        self._event_callback: Optional[Callable[[RuntimeEvent], None | Awaitable[None]]] = None
        self._interrupted = False

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid

    @property
    def returncode(self) -> Optional[int]:
        return self.process.returncode

    def subscribe(self, callback: Callable[[RuntimeEvent], None | Awaitable[None]]) -> None:
        self._event_callback = callback

    async def _emit(self, event: RuntimeEvent) -> None:
        if self._event_callback is not None:
            result = self._event_callback(event)
            if asyncio.iscoroutine(result):
                await result
        self.events.put_nowait(event)

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000

    @staticmethod
    def _looks_like_approval_required(text: str) -> bool:
        lower = text.lower()
        indicators = (
            "approve",
            "approval required",
            "permission required",
            "allow this",
            "confirm",
            "authorize",
            "do you want to proceed",
        )
        return any(indicator in lower for indicator in indicators)

    @staticmethod
    def _looks_like_input_required(text: str) -> bool:
        lower = text.lower()
        if "input required" in lower or "please respond" in lower or "enter" in lower:
            return True
        return bool(("?" in text or ":" in text) and any(keyword in lower for keyword in ("type", "enter", "reply", "response")))

    async def _read_stream(self, stream: Optional[asyncio.StreamReader], stream_name: str) -> None:
        if stream is None:
            return
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue
                event = OutputEvent(self._now_ms(), text, stream_name)
                await self._emit(event)
                if self._looks_like_approval_required(text):
                    await self._emit(ApprovalRequiredEvent(self._now_ms(), text))
                if self._looks_like_input_required(text):
                    await self._emit(InputRequiredEvent(self._now_ms(), text))
        except Exception as exc:  # pragma: no cover - defensive runtime path
            await self._emit(ErrorEvent(self._now_ms(), f"{stream_name} stream failure: {exc}", "stream_error"))

    async def _watch_process(self) -> None:
        try:
            returncode = await self.process.wait()
        except Exception as exc:  # pragma: no cover - defensive runtime path
            self.state = RuntimeProcessState.FAILED
            await self._emit(ErrorEvent(self._now_ms(), f"Process wait failed: {exc}", "wait_failed"))
            self._completion.set()
            return

        if self._interrupted:
            self._completion.set()
            return

        if returncode == 0:
            self.state = RuntimeProcessState.COMPLETED
            await self._emit(ProcessCompletedEvent(self._now_ms(), returncode))
        else:
            self.state = RuntimeProcessState.FAILED
            await self._emit(ProcessFailedEvent(self._now_ms(), returncode, f"Process exited with code {returncode}"))
        self._completion.set()

    async def start(self) -> None:
        if self.state is not RuntimeProcessState.STARTING:
            return
        self.state = RuntimeProcessState.RUNNING
        self._stdout_task = asyncio.create_task(self._read_stream(self.process.stdout, "stdout"))
        self._stderr_task = asyncio.create_task(self._read_stream(self.process.stderr, "stderr"))
        self._watch_task = asyncio.create_task(self._watch_process())
        await self._emit(ProcessStartedEvent(self._now_ms(), self.process.pid, self.adapter.get_identity().name.lower()))

    async def send_input(self, data: str) -> None:
        if self.process.stdin is None:
            raise RuntimeExecutionError("Process has no stdin handle")
        if self.process.returncode is not None:
            raise RuntimeExecutionError("Process is already complete")
        self.process.stdin.write(data.encode("utf-8"))
        await self.process.stdin.drain()

    async def wait_for_event(self, event_type: Optional[Any] = None, timeout: Optional[float] = None) -> RuntimeEvent:
        if timeout is None:
            return await self.events.get()
        try:
            event = await asyncio.wait_for(self.events.get(), timeout=timeout)
        except asyncio.TimeoutError as exc:  # pragma: no cover - requires timing-specific failure
            raise TimeoutError("Event was not received in time") from exc
        if event_type is None or event.event_type == event_type:
            return event
        return await self.wait_for_event(event_type, timeout=timeout)

    async def wait(self) -> int:
        await self._completion.wait()
        if self.process.returncode is None:
            return 0
        return self.process.returncode

    async def terminate(self, timeout: float = 5.0) -> int:
        if self.process.returncode is not None:
            return self.process.returncode
        self._interrupted = True
        self.state = RuntimeProcessState.CANCELLED
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except ProcessLookupError:
            pass
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        finally:
            await self._emit(ProcessInterruptedEvent(self._now_ms()))
            self._completion.set()
        return self.process.returncode if self.process.returncode is not None else 0

    async def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.is_closing():
            self.process.stdin.close()
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()
        await self.wait()


class RuntimeProcessExecutor:
    """Neutral executor that turns a FrameworkAdapter + RuntimeConfig into a managed process."""

    @staticmethod
    async def execute(
        adapter: FrameworkAdapter,
        config: RuntimeConfig,
        *,
        event_callback: Optional[Callable[[RuntimeEvent], None | Awaitable[None]]] = None,
    ) -> RuntimeProcess:
        if not config.executable_path:
            raise RuntimeExecutionError("RuntimeConfig.executable_path is required")

        merged_env = os.environ.copy()
        merged_env.update(adapter.build_environment(config))

        command = adapter.build_command(config)
        if not command:
            raise RuntimeExecutionError("Adapter produced an empty command")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=config.working_directory,
                env=merged_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise RuntimeExecutionError(f"Failed to start process: {exc}") from exc

        runtime = RuntimeProcess(adapter, config, process)
        if event_callback is not None:
            runtime.subscribe(event_callback)
        await runtime.start()
        return runtime
