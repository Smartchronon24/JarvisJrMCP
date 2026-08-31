from __future__ import annotations
import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

class FrameworkIdentity(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    UNKNOWN = "unknown"

@dataclass
class RuntimeConfig:
    """
    Provider and framework-neutral representation of a runtime launch request.
    This contains everything the Jarvis system needs to tell an adapter
    how to launch and configure a CLI agent.
    """
    executable_path: str
    prompt: Optional[str] = None
    working_directory: Optional[str] = None
    environment: Dict[str, str] = field(default_factory=dict)
    
    # Provider/Model selection (which may be mapped differently by each framework)
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    
    # Auth or session flags if needed broadly, though specifics go to adapters
    interactive: bool = False
    
    # Additional framework-specific kwargs should be avoided in the common contract,
    # but could be passed if strictly necessary via a dict.
    extra: Dict[str, str] = field(default_factory=dict)

class FrameworkAdapter(abc.ABC):
    """
    Boundary for translating the neutral RuntimeConfig into framework-specific
    commands, arguments, and execution environments.
    """
    
    @abc.abstractmethod
    def get_identity(self) -> FrameworkIdentity:
        """Return the framework identity this adapter supports."""
        pass
        
    @abc.abstractmethod
    def build_command(self, config: RuntimeConfig) -> List[str]:
        """
        Translate the neutral runtime configuration into a concrete
        command-line invocation for this specific framework.
        """
        pass
        
    @abc.abstractmethod
    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        """
        Produce the final environment variables needed for execution,
        handling framework-specific auth injection or overrides.
        """
        pass
