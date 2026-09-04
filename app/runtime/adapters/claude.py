from typing import Dict, List
from app.runtime.contract import (
    AdapterCapabilities,
    FrameworkAdapter,
    FrameworkIdentity,
    RuntimeConfig,
)

class ClaudeAdapter(FrameworkAdapter):
    """
    Adapter for the Claude Code CLI (@anthropic-ai/claude-code).
    Handles Anthropic-specific auth expectations and Claude CLI flags.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.CLAUDE

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_mcp=True,
            supports_tool_calls=True,
            supports_interactive_input=True,
            supports_cancellation=True,
            requires_authentication=True,
        )

    def build_command(self, config: RuntimeConfig) -> List[str]:
        import hashlib
        
        cmd = [config.executable_path]
        
        if config.model_name:
            cmd.extend(["--model", config.model_name])

        gateway_config = config.extra.get("jarvis_mcp_config")
        jarvis_context = config.extra.get("jarvis_context")
        if jarvis_context:
            # Replace Claude Code's coding-agent instructions. They cause local
            # models to select skills such as code-review for ordinary prompts.
            cmd.extend(["--system-prompt", jarvis_context])
        if gateway_config:
            cmd.extend(["--mcp-config", gateway_config, "--strict-mcp-config"])
            # Claude's `--bare` mode explicitly ignores --mcp-config. Allow
            # only the two session-scoped Jarvis tools instead of prompting.
            cmd.extend([
                "--allowed-tools",
                "mcp__jarvis__external_action",
            ])
            
        if not config.interactive:
            # Bare mode prevents project hooks, plugins, auto-memory, and
            # inherited skills from rewriting a neutral user request. Claude
            # explicitly supports supplying MCP/configuration in bare mode.
            cmd.append("--bare")
            cmd.append("--disable-slash-commands")
            cmd.append("--no-session-persistence")
            # Claude Code uses --print for non-interactive output
            cmd.append("--print")
            if config.prompt:
                cmd.append(config.prompt)
                # B16 diagnostic: prompt integrity in adapter
                prompt_hash = hashlib.sha256(config.prompt.encode('utf-8')).hexdigest()[:16]
                import logging
                logger = logging.getLogger("jarvis.b4.claude.adapter")
                logger.info(
                    "[B16-BOUNDARY-ADAPTER] prompt_hash=%s, prompt_len=%d, cmd=%s",
                    prompt_hash, len(config.prompt), cmd
                )
        else:
            if config.prompt:
                # Assuming the prompt can still be passed in interactive mode
                cmd.append(config.prompt)
                
        return cmd

    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        env = dict(config.environment)
        config_dir = config.extra.get("claude_config_dir")
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        if config.endpoint_url:
            env.setdefault("ANTHROPIC_BASE_URL", config.endpoint_url)

        if config.provider_name and config.provider_name.lower() in {"ollama", "local"}:
            # Ollama model IDs are valid only when Claude is routed through the
            # configured Ollama-compatible endpoint. Override inherited Anthropic
            # settings so a host process cannot silently select another gateway.
            env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
            env["ANTHROPIC_API_KEY"] = ""
            env["ANTHROPIC_BASE_URL"] = config.endpoint_url or "http://localhost:11434"

        if config.model_name and ":" in config.model_name:
            # Claude Code does not know metadata for many Ollama model IDs.
            # Let the configured endpoint decide whether the model is usable.
            env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
            if "ANTHROPIC_BASE_URL" not in env and config.endpoint_url is None:
                env["ANTHROPIC_BASE_URL"] = "http://localhost:11434"

        return env
