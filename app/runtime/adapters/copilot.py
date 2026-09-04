from typing import Dict, List
from app.runtime.contract import (
    AdapterCapabilities,
    FrameworkAdapter,
    FrameworkIdentity,
    RuntimeConfig,
)

class CopilotAdapter(FrameworkAdapter):
    """
    Adapter for the GitHub Copilot CLI (@github/copilot).
    Handles GitHub auth propagation and Copilot-specific prompts.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.COPILOT

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_mcp=True,
            supports_tool_calls=True,
            supports_interactive_input=True,
            supports_cancellation=True,
            requires_authentication=True,
        )

    def build_command(self, config: RuntimeConfig) -> List[str]:
        cmd = [config.executable_path]

        if config.model_name:
            cmd.extend(["--model", config.model_name])

        gateway_config = config.extra.get("jarvis_mcp_config")
        if gateway_config:
            # Copilot expects either inline JSON or a file path prefixed with @.
            if gateway_config.startswith("@"):
                value = gateway_config
            else:
                value = f"@{gateway_config}"
            cmd.extend(["--additional-mcp-config", value])

        if not config.interactive:
            # Use the short prompt flag supported consistently by the
            # installed Copilot CLI and its Windows launcher.
            # --allow-all-tools is required per CLI help: "required for non-interactive mode"
            # Without it Copilot may pause mid-run for tool permission prompts.
            cmd.append("--allow-all-tools")
            if gateway_config:
                cmd.extend(["--allow-all-mcp-server-instructions", "--allow-all-urls"])
            if config.prompt:
                prompt = config.prompt
                jarvis_context = config.extra.get("jarvis_context")
                if jarvis_context:
                    prompt = f"{jarvis_context}\n\nUser request:\n{prompt}"
                # CMD treats embedded newlines as command separators even
                # when the value is quoted.
                prompt = " ".join(prompt.split())
                # The Windows CMD launcher expands a separate quoted value
                # into multiple argv entries. The equals form keeps the
                # complete prompt as one Copilot CLI option.
                cmd.append(f"-p={prompt}")
        else:
            if config.prompt:
                cmd.append(config.prompt)

        return cmd

    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        env = dict(config.environment)
        # Ensure GH auth tokens if provided in extra are mapped
        gh_token = config.extra.get("github_token")
        if gh_token:
            env["COPILOT_GITHUB_TOKEN"] = gh_token
        return env
