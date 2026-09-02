from typing import Dict, List
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig

class ClaudeAdapter(FrameworkAdapter):
    """
    Adapter for the Claude Code CLI (@anthropic-ai/claude-code).
    Handles Anthropic-specific auth expectations and Claude CLI flags.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.CLAUDE

    def build_command(self, config: RuntimeConfig) -> List[str]:
        import hashlib
        
        cmd = [config.executable_path]
        
        if config.model_name:
            cmd.extend(["--model", config.model_name])

        gateway_config = config.extra.get("jarvis_mcp_config")
        if gateway_config:
            cmd.extend(["--mcp-config", gateway_config, "--strict-mcp-config"])
            
        if not config.interactive:
            # Keep each print invocation isolated from Claude's implicit project
            # plugins, hooks, memory, prefetches, and persisted sessions.
            cmd.extend(["--bare", "--no-session-persistence"])
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

        if config.endpoint_url:
            env.setdefault("ANTHROPIC_BASE_URL", config.endpoint_url)

        if config.provider_name and config.provider_name.lower() in {"ollama", "local"}:
            env.setdefault("ANTHROPIC_AUTH_TOKEN", "ollama")
            env.setdefault("ANTHROPIC_API_KEY", "")
            env.setdefault("ANTHROPIC_BASE_URL", config.endpoint_url or "http://localhost:11434")

        if config.model_name and ":" in config.model_name:
            # Claude Code does not know metadata for many Ollama model IDs.
            # Let the configured endpoint decide whether the model is usable.
            env.setdefault("CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT", "1")
            if "ANTHROPIC_BASE_URL" not in env and config.endpoint_url is None:
                env.setdefault("ANTHROPIC_BASE_URL", "http://localhost:11434")

        return env
