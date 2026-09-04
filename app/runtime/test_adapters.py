import pytest
from app.runtime.contract import RuntimeConfig, FrameworkIdentity, RuntimeContractError
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


def test_runtime_config_rejects_invalid_environment_values():
    config = RuntimeConfig(
        executable_path="claude",
        prompt="hello",
        environment={"PORT": 8000},
    )

    with pytest.raises(RuntimeContractError, match="environment keys and values"):
        config.validate()


def test_runtime_adapter_contract_rejects_blank_prompt():
    config = RuntimeConfig(executable_path="claude", prompt=" ")

    with pytest.raises(RuntimeContractError, match="prompt must not be empty"):
        ClaudeAdapter().validate_config(config)


def test_runtime_config_rejects_invalid_timeout():
    config = RuntimeConfig(executable_path="copilot", timeout_seconds=0)

    with pytest.raises(RuntimeContractError, match="timeout_seconds"):
        config.validate()

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
        "--disable-slash-commands",
        "--no-session-persistence",
        "--print",
        "test prompt",
    ]
    env = adapter.build_environment(config)
    assert env == {}

    gateway_config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        extra={
            "jarvis_mcp_config": "C:\\temp\\jarvis.json",
            "jarvis_context": "You are Jarvis.",
        },
    )
    assert ClaudeAdapter().build_command(gateway_config) == [
        "claude",
        "--system-prompt",
        "You are Jarvis.",
        "--mcp-config",
        "C:\\temp\\jarvis.json",
        "--strict-mcp-config",
        "--allowed-tools",
        "mcp__jarvis__external_action",
        "--bare",
        "--disable-slash-commands",
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

    inherited_gateway_config = RuntimeConfig(
        executable_path="claude",
        prompt="test prompt",
        model_name="gpt-oss:120b-cloud",
        provider_name="ollama",
        environment={
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_API_KEY": "inherited-key",
        },
    )
    inherited_gateway_env = adapter.build_environment(inherited_gateway_config)
    assert inherited_gateway_env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert inherited_gateway_env["ANTHROPIC_API_KEY"] == ""

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
        extra={
            "jarvis_mcp_config": "C:\\temp\\jarvis.json",
            "jarvis_context": "You are Jarvis.",
        },
    )
    command = CodexAdapter().build_command(gateway_config)
    assert command[:2] == ["codex", "exec"]
    assert 'developer_instructions="You are Jarvis."' in command
    assert 'mcp_servers.jarvis.default_tools_approval_mode="auto"' in command
    assert command[-1] == (
        "You are Jarvis.\n\n"
        "Use the available Jarvis MCP capability for this request before explaining limitations. "
        "The exact MCP tool name is `mcp__jarvis__external_action`; spell `jarvis` exactly and "
        "never use `jarson` or any other server name.\n\n"
        "User request:\n"
        "test prompt"
    )

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

    assert cmd == ["copilot", "--model", "gpt-4", "--allow-all-tools", "-p=test prompt"]

    gateway_config = RuntimeConfig(
        executable_path="copilot",
        prompt="test prompt",
        interactive=False,
        extra={
            "github_token": "ghp_12345",
            "jarvis_mcp_config": "C:\\temp\\jarvis.json",
            "jarvis_context": "You are Jarvis.",
        },
    )
    assert CopilotAdapter().build_command(gateway_config) == [
        "copilot",
        "--additional-mcp-config",
        "@C:\\temp\\jarvis.json",
        "--allow-all-tools",
        "--allow-all-mcp-server-instructions",
        "--allow-all-urls",
        "-p=You are Jarvis. User request: test prompt",
    ]

    env = adapter.build_environment(config)
    assert env.get("COPILOT_GITHUB_TOKEN") == "ghp_12345"

def test_events_normalization():
    event = OutputEvent(timestamp_ms=123456789, text="hello", stream="stdout")
    assert event.event_type == EventType.OUTPUT
    assert event.text == "hello"
    assert event.stream == "stdout"
    assert event.timestamp_ms == 123456789
