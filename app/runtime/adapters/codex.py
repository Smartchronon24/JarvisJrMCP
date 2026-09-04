from typing import Dict, List
import json
from app.runtime.contract import (
    AdapterCapabilities,
    FrameworkAdapter,
    FrameworkIdentity,
    RuntimeConfig,
)

class CodexAdapter(FrameworkAdapter):
    """
    Adapter for the OpenAI Codex CLI.
    Handles explicit provider routing (e.g. --oss, --local-provider)
    and Codex's model flags.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.CODEX

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_mcp=True,
            supports_tool_calls=True,
            supports_interactive_input=True,
            supports_cancellation=True,
            requires_authentication=True,
            experimental=True,
            experimental_reason="Codex/Ollama MCP dispatch is not certified.",
        )

    def build_command(self, config: RuntimeConfig) -> List[str]:
        # Always use the exec subcommand for single prompt runs
        cmd = [config.executable_path]

        cmd.append("exec")

        if config.model_name:
            cmd.extend(["--model", config.model_name])

        # The installed Codex CLI uses `codex mcp add` for MCP registration,
        # not a per-run `--mcp-config` flag. Registration is handled before the
        # session launch in the runtime wrapper when a Jarvis gateway is attached.
        if config.provider_name:
            if config.provider_name.lower() in ("ollama", "local"):
                cmd.extend(["--oss", "--local-provider", "ollama"])
            else:
                # E.g. openai or other provider via -c config override
                cmd.extend(["-c", f"model_provider='\"{config.provider_name}\"'"])

        # If endpoint URL is given, we might need to override base_url via -c
        if config.endpoint_url:
            provider = config.provider_name or "default"
            cmd.extend(["-c", f"model_providers.{provider}.base_url='\"{config.endpoint_url}\"'"])

        jarvis_context = config.extra.get("jarvis_context")
        if jarvis_context:
            cmd.extend(["-c", f"developer_instructions={json.dumps(jarvis_context)}"])
        if config.extra.get("jarvis_mcp_config"):
            cmd.extend([
                "-c",
                'mcp_servers.jarvis.default_tools_approval_mode="auto"',
            ])

        if not config.interactive:
            # Keep runtime requests isolated from prior Codex conversations.
            cmd.append("--ephemeral")

        if config.prompt:
            prompt = config.prompt
            if jarvis_context:
                prompt = (
                    f"{jarvis_context}\n\n"
                    "Use the available Jarvis MCP capability for this request before "
                    "explaining limitations. The exact MCP tool name is "
                    "`mcp__jarvis__external_action`; spell `jarvis` exactly and "
                    "never use `jarson` or any other server name.\n\n"
                    f"User request:\n{prompt}"
                )
            cmd.append(prompt)

        return cmd

    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        env = dict(config.environment)
        # Auth typically handled via config files or OPENAI_API_KEY
        return env
