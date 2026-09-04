"""Framework-independent security and failure classification helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class FailureType(str, Enum):
    UNAVAILABLE_CAPABILITY = "unavailable_capability"
    INVALID_ARGUMENTS = "invalid_arguments"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PERMISSION_REJECTION = "permission_rejection"
    TOOL_EXECUTION_FAILURE = "tool_execution_failure"
    RUNTIME_FAILURE = "runtime_failure"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"


def classify_failure(error_type: str | None, message: str = "") -> FailureType:
    value = f"{error_type or ''} {message}".lower()
    if "permission" in value or "authoriz" in value or "forbidden" in value:
        return FailureType.PERMISSION_REJECTION
    if "auth" in value or "token" in value:
        return FailureType.AUTHENTICATION_FAILURE
    if "invalid" in value or "argument" in value:
        return FailureType.INVALID_ARGUMENTS
    if "unavailable" in value or "not connected" in value or "not found" in value:
        return FailureType.UNAVAILABLE_CAPABILITY
    if "timeout" in value:
        return FailureType.TIMEOUT
    if "cancel" in value or "interrupt" in value:
        return FailureType.CANCELLATION
    if "tool" in value or "mcp" in value:
        return FailureType.TOOL_EXECUTION_FAILURE
    return FailureType.RUNTIME_FAILURE


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Remove credential-like values before logging or displaying payloads."""
    sensitive = ("token", "secret", "password", "api_key", "authorization")
    return {
        str(key): ("[REDACTED]" if any(part in str(key).lower() for part in sensitive) else item)
        for key, item in value.items()
    }


class PermissionPolicy:
    """Composable server/tool permission policy independent of a framework."""

    def __init__(self, *, allowed_servers: set[str] | None = None, allowed_tools: set[str] | None = None):
        self.allowed_servers = allowed_servers
        self.allowed_tools = allowed_tools

    def allows(self, metadata: Any, arguments: dict[str, Any]) -> bool:
        if self.allowed_servers is not None and metadata.server not in self.allowed_servers:
            return False
        if self.allowed_tools is not None and metadata.name not in self.allowed_tools:
            return False
        return True
