import asyncio
import os
import sys

import pytest

from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig
from app.runtime.events import EventType, OutputEvent, ProcessCompletedEvent, ProcessFailedEvent, ProcessInterruptedEvent
from app.runtime.executor import RuntimeProcessExecutor, RuntimeProcessState


class EchoAdapter(FrameworkAdapter):
    def get_identity(self):
        return FrameworkIdentity.UNKNOWN

    def build_command(self, config):
        script = config.extra.get("script", "print('ok')")
        return [sys.executable, "-c", script]

    def build_environment(self, config):
        env = dict(config.environment)
        return env


@pytest.mark.asyncio
async def test_runtime_process_executes_successfully():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "print('hello from stdout')"},
        ),
    )
    code = await proc.wait()
    assert code == 0
    assert proc.state == RuntimeProcessState.COMPLETED
    completion = await proc.wait_for_event(EventType.PROCESS_COMPLETED, timeout=2)
    assert isinstance(completion, ProcessCompletedEvent)
    assert completion.exit_code == 0


@pytest.mark.asyncio
async def test_runtime_process_streams_stdout_and_stderr():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "import sys; print('line1'); print('line2', file=sys.stderr)"},
        ),
    )
    stdout_event = await proc.wait_for_event(EventType.OUTPUT, timeout=2)
    assert isinstance(stdout_event, OutputEvent)
    assert stdout_event.stream in {"stdout", "stderr"}
    code = await proc.wait()
    assert code == 0


@pytest.mark.asyncio
async def test_runtime_process_handles_stdin():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "import sys; data = sys.stdin.readline(); print(data.strip())"},
        ),
    )
    await proc.send_input("hello from stdin\n")
    code = await proc.wait()
    assert code == 0
    assert proc.state == RuntimeProcessState.COMPLETED


@pytest.mark.asyncio
async def test_runtime_process_reports_exit_codes_and_failures():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "import sys; sys.exit(7)"},
        ),
    )
    event = await proc.wait_for_event(EventType.PROCESS_FAILED, timeout=2)
    assert isinstance(event, ProcessFailedEvent)
    assert event.exit_code == 7
    assert proc.state == RuntimeProcessState.FAILED


@pytest.mark.asyncio
async def test_runtime_process_supports_cancellation():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "import time; time.sleep(60)"},
        ),
    )
    await asyncio.sleep(0.2)
    code = await proc.terminate(timeout=2)
    assert code in {0, 1, -15, None}
    assert proc.state == RuntimeProcessState.CANCELLED
    interrupted = await proc.wait_for_event(EventType.PROCESS_INTERRUPTED, timeout=2)
    assert isinstance(interrupted, ProcessInterruptedEvent)


@pytest.mark.asyncio
async def test_runtime_process_propagates_environment_and_workdir():
    adapter = EchoAdapter()
    working_dir = os.getcwd()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            working_directory=working_dir,
            environment={"RUNTIME_TEST_ENV": "present"},
            extra={"script": "import os; print(os.getenv('RUNTIME_TEST_ENV')); import pathlib; print(str(pathlib.Path.cwd()))"},
        ),
    )
    await proc.wait()
    assert proc.state == RuntimeProcessState.COMPLETED


@pytest.mark.asyncio
async def test_framework_adapters_build_valid_runtime_commands():
    config = RuntimeConfig(
        executable_path="python",
        prompt="hello",
        model_name="gpt-oss:120b-cloud",
        provider_name="ollama",
        endpoint_url="http://127.0.0.1:11434/v1",
        interactive=False,
        extra={"github_token": "ghp_test"},
    )

    claude = ClaudeAdapter()
    codex = CodexAdapter()
    copilot = CopilotAdapter()

    assert claude.build_command(config)[:2] == ["python", "--model"]
    assert codex.build_command(config)[0:3] == ["python", "exec", "--model"]
    assert copilot.build_command(config)[0:2] == ["python", "--model"]
    assert codex.build_environment(config) == {}
    assert copilot.build_environment(config)["COPILOT_GITHUB_TOKEN"] == "ghp_test"


@pytest.mark.asyncio
async def test_event_generation_for_start_and_output():
    adapter = EchoAdapter()
    proc = await RuntimeProcessExecutor.execute(
        adapter,
        RuntimeConfig(
            executable_path=sys.executable,
            extra={"script": "print('ready')"},
        ),
    )
    start_event = await proc.wait_for_event(EventType.PROCESS_STARTED, timeout=2)
    assert start_event.event_type == EventType.PROCESS_STARTED
    assert start_event.framework == "unknown"
    await proc.wait()
    assert proc.state == RuntimeProcessState.COMPLETED
