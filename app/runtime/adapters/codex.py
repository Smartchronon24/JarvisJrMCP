from typing import Dict, List
from app.runtime.contract import FrameworkAdapter, FrameworkIdentity, RuntimeConfig

class CodexAdapter(FrameworkAdapter):
    """
    Adapter for the OpenAI Codex CLI.
    Handles explicit provider routing (e.g. --oss, --local-provider)
    and Codex's model flags.
    """
    
    def get_identity(self) -> FrameworkIdentity:
        return FrameworkIdentity.CODEX

    def build_command(self, config: RuntimeConfig) -> List[str]:
        # Always use the exec subcommand for single prompt runs
        cmd = [config.executable_path, "exec"]
        
        if config.model_name:
            cmd.extend(["--model", config.model_name])
            
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
            
        if config.prompt:
            cmd.append(config.prompt)
            
        return cmd

    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        env = dict(config.environment)
        # Auth typically handled via config files or OPENAI_API_KEY
        return env
