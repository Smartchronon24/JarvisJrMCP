from typing import Dict, List
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig

class CopilotAdapter(FrameworkAdapter):
    """
    Adapter for the GitHub Copilot CLI (@github/copilot).
    Handles GitHub auth propagation and Copilot-specific prompts.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.COPILOT

    def build_command(self, config: RuntimeConfig) -> List[str]:
        cmd = [config.executable_path]
        
        if config.model_name:
            cmd.extend(["--model", config.model_name])
            
        if not config.interactive:
            # Copilot CLI uses -p/--prompt for non-interactive.
            # --allow-all-tools is required per CLI help: "required for non-interactive mode"
            # Without it Copilot may pause mid-run for tool permission prompts.
            cmd.append("--allow-all-tools")
            if config.prompt:
                cmd.extend(["--prompt", config.prompt])
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
