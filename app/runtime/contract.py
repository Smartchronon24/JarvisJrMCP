from __future__ import annotations
import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class FrameworkIdentity(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    UNKNOWN = "unknown"


class RuntimeContractError(ValueError):
    """Raised when a runtime launch request violates the common contract."""


@dataclass(frozen=True)
class AdapterCapabilities:
    """Framework capabilities exposed without leaking CLI-specific behavior."""

    supports_mcp: bool = False
    supports_tool_calls: bool = False
    supports_interactive_input: bool = True
    supports_cancellation: bool = True
    requires_authentication: bool = False
    experimental: bool = False
    experimental_reason: Optional[str] = None


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
    timeout_seconds: Optional[float] = None
    
    # Additional framework-specific kwargs should be avoided in the common contract,
    # but could be passed if strictly necessary via a dict.
    extra: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate framework-neutral launch inputs before adapter translation."""
        if not isinstance(self.executable_path, str) or not self.executable_path.strip():
            raise RuntimeContractError("executable_path must be a non-empty string")
        if self.prompt is not None and not isinstance(self.prompt, str):
            raise RuntimeContractError("prompt must be a string when provided")
        if self.working_directory is not None and not isinstance(self.working_directory, str):
            raise RuntimeContractError("working_directory must be a string when provided")
        if not isinstance(self.environment, dict):
            raise RuntimeContractError("environment must be an object")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise RuntimeContractError("environment keys and values must be strings")
        if self.provider_name is not None and not isinstance(self.provider_name, str):
            raise RuntimeContractError("provider_name must be a string when provided")
        if self.model_name is not None and not isinstance(self.model_name, str):
            raise RuntimeContractError("model_name must be a string when provided")
        if self.endpoint_url is not None and not isinstance(self.endpoint_url, str):
            raise RuntimeContractError("endpoint_url must be a string when provided")
        if not isinstance(self.interactive, bool):
            raise RuntimeContractError("interactive must be a boolean")
        if self.timeout_seconds is not None and (
            not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise RuntimeContractError("timeout_seconds must be positive when provided")
        if not isinstance(self.extra, dict):
            raise RuntimeContractError("extra must be an object")

class FrameworkAdapter(abc.ABC):
    """
    Boundary for translating the neutral RuntimeConfig into framework-specific
    commands, arguments, and execution environments.
    """
    
    @abc.abstractmethod
    def get_identity(self) -> FrameworkIdentity:
        """Return the framework identity this adapter supports."""
        pass

    def get_capabilities(self) -> AdapterCapabilities:
        """Return declared capabilities for shared orchestration and testing."""
        return AdapterCapabilities()

    def validate_config(self, config: RuntimeConfig) -> None:
        """Validate a request before framework-specific command construction."""
        config.validate()
        if config.prompt is not None and not config.prompt.strip():
            raise RuntimeContractError("prompt must not be empty when provided")
        
    @abc.abstractmethod
    def build_command(self, config: RuntimeConfig) -> List[str]:
        """
        Translate the neutral runtime configuration into a concrete
        command-line invocation for this specific framework.
        """
        self.validate_config(config)
        raise NotImplementedError
        
    @abc.abstractmethod
    def build_environment(self, config: RuntimeConfig) -> Dict[str, str]:
        """
        Produce the final environment variables needed for execution,
        handling framework-specific auth injection or overrides.
        """
        self.validate_config(config)
        raise NotImplementedError
