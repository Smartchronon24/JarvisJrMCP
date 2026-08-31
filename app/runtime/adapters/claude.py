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
        cmd = [config.executable_path]
        
        if config.model_name:
            cmd.extend(["--model", config.model_name])
            
        if not config.interactive:
            # Claude Code uses --print for non-interactive output
            cmd.append("--print")
            if config.prompt:
                cmd.append(config.prompt)
        else:
            if config.prompt:
                # Assuming the prompt can still be passed in interactive mode
                cmd.append(config.prompt)
                
        return cmd

    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        env = dict(config.environment)
        # Claude heavily relies on ANTHROPIC_API_KEY if auth isn't in settings
        # The adapter boundary doesn't enforce key presence, but ensures env passes through
        return env
