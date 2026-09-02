import pytest
from app.runtime.contract import RuntimeConfig, FrameworkIdentity
from app.runtime.adapters.claude import ClaudeAdapter
from app.runtime.adapters.codex import CodexAdapter
from app.runtime.adapters.copilot import CopilotAdapter
from app.runtime.events import OutputEvent, EventType

def test_runtime_config_representation():
    config = RuntimeConfig(
        executable_path="/bin/claude",
        prompt="hello world",
        model_name="claude-3-opus",
        environment={"API_KEY": "secret"}
    )
    assert config.executable_path == "/bin/claude"
    assert config.prompt == "hello world"
    assert config.model_name == "claude-3-opus"
    assert config.environment["API_KEY"] == "secret"

def test_claude_adapter():
    adapter = ClaudeAdapter()
    config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        model_name="claude-3-sonnet",
        interactive=False
    )
    
    assert adapter.get_identity() == FrameworkIdentity.CLAUDE
    cmd = adapter.build_command(config)
    
    assert cmd == [
        "claude",
        "--model",
        "claude-3-sonnet",
        "--bare",
        "--no-session-persistence",
        "--print",
        "test prompt",
    ]
    env = adapter.build_environment(config)
    assert env == {}

    gateway_config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        extra={"jarvis_mcp_config": "C:\\temp\\jarvis.json"},
    )
    assert ClaudeAdapter().build_command(gateway_config) == [
        "claude",
        "--mcp-config",
        "C:\\temp\\jarvis.json",
        "--strict-mcp-config",
        "--allowed-tools",
        "mcp__jarvis__jarvis_search",
        "mcp__jarvis__jarvis_execute",
        "--no-session-persistence",
        "--print",
        "test prompt",
    ]

    ollama_config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        model_name="gpt-oss:120b-cloud",
        environment={"ANTHROPIC_BASE_URL": "http://localhost:11434"},
    )
    ollama_env = adapter.build_environment(ollama_config)
    assert ollama_env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
    assert ollama_env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"

    ollama_provider_config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        model_name="gpt-oss:120b-cloud",
        provider_name="ollama",
        endpoint_url="http://localhost:11434",
    )
    ollama_provider_env = adapter.build_environment(ollama_provider_config)
    assert ollama_provider_env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert ollama_provider_env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"

def test_codex_adapter():
    adapter = CodexAdapter()
    config = RuntimeConfig(
        executable_path="codex",
        prompt="test prompt",
        model_name="gpt-oss:120b",
        provider_name="ollama"
    )

    assert adapter.get_identity() == FrameworkIdentity.CODEX
    cmd = adapter.build_command(config)

    assert cmd == [
        "codex", "exec",
        "--model", "gpt-oss:120b",
        "--oss", "--local-provider", "ollama",
        "--ephemeral",
        "test prompt"
    ]

    gateway_config = RuntimeConfig(
        executable_path="codex",
        prompt="test prompt",
        extra={"jarvis_mcp_config": "C:\\temp\\jarvis.json"},
    )
    assert CodexAdapter().build_command(gateway_config) == [
        "codex",
        "exec",
        "--ephemeral",
        "test prompt",
    ]

def test_codex_adapter_custom_provider():
    adapter = CodexAdapter()
    config = RuntimeConfig(
        executable_path="codex",
        prompt="hello",
        provider_name="custom",
        endpoint_url="http://localhost:8080/v1"
    )
    cmd = adapter.build_command(config)
    assert "codex" in cmd
    assert "exec" in cmd
    assert "-c" in cmd
    assert "model_provider='\"custom\"'" in cmd
    assert "-c" in cmd
    assert "model_providers.custom.base_url='\"http://localhost:8080/v1\"'" in cmd

def test_copilot_adapter():
    adapter = CopilotAdapter()
    config = RuntimeConfig(
        executable_path="copilot",
        prompt="test prompt",
        model_name="gpt-4",
        interactive=False,
        extra={"github_token": "ghp_12345"}
    )

    assert adapter.get_identity() == FrameworkIdentity.COPILOT
    cmd = adapter.build_command(config)

    assert cmd == ["copilot", "--model", "gpt-4", "--allow-all-tools", "-p", "test prompt"]

    gateway_config = RuntimeConfig(
        executable_path="copilot",
        prompt="test prompt",
        interactive=False,
        extra={"github_token": "ghp_12345", "jarvis_mcp_config": "C:\\temp\\jarvis.json"},
    )
    assert CopilotAdapter().build_command(gateway_config) == [
        "copilot",
        "--additional-mcp-config",
        "@C:\\temp\\jarvis.json",
        "--allow-all-tools",
        "-p",
        "test prompt",
    ]

    env = adapter.build_environment(config)
    assert env.get("COPILOT_GITHUB_TOKEN") == "ghp_12345"

def test_events_normalization():
    event = OutputEvent(timestamp_ms=123456789, text="hello", stream="stdout")
    assert event.event_type == EventType.OUTPUT
    assert event.text == "hello"
    assert event.stream == "stdout"
    assert event.timestamp_ms == 123456789
