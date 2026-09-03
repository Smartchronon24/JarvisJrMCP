"""Local HTTP-facing transport primitives for the Jarvis tool gateway."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.tools.gateway import GatewaySearchRequest, JarvisToolGateway


@dataclass
class _GatewaySession:
    token: str
    gateway: JarvisToolGateway
    expires_at: float


class GatewayTransport:
    """Validate external gateway requests and bind them to a Jarvis gateway."""

    def __init__(self, *, ttl_seconds: int = 3600) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, _GatewaySession] = {}

    def create_session(self, gateway: JarvisToolGateway) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = _GatewaySession(
            token=token,
            gateway=gateway,
            expires_at=time.time() + self.ttl_seconds,
        )
        return {"token": token, "expires_in": self.ttl_seconds}

    def revoke_session(self, token: str) -> bool:
        return self._sessions.pop(token, None) is not None

    def clear_sessions(self) -> None:
        self._sessions.clear()

    def _get_gateway(self, token: str) -> JarvisToolGateway:
        if not isinstance(token, str) or not token.strip():
            raise PermissionError("gateway bearer token is required")
        session = self._sessions.get(token)
        if session is None:
            raise PermissionError("invalid gateway bearer token")
        if session.expires_at <= time.time():
            self._sessions.pop(token, None)
            raise PermissionError("gateway session expired")
        return session.gateway

    @staticmethod
    def _operation(payload: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("gateway request must be an object")
        operation = payload.get("operation")
        if operation not in {"search", "execute", "external_action"}:
            raise ValueError("operation must be 'search', 'execute', or 'external_action'")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        return operation, arguments

    async def dispatch(self, token: str, payload: Any) -> dict[str, Any]:
        gateway = self._get_gateway(token)
        operation, arguments = self._operation(payload)

        if operation == "search":
            result = gateway.search(GatewaySearchRequest.from_mapping(arguments))
            return {"ok": True, "operation": operation, **result.to_dict()}

        if operation == "external_action":
            request = arguments.get("request")
            if not isinstance(request, str) or not request.strip():
                raise ValueError("external_action requires a non-empty request")
            tool_arguments = arguments.get("arguments", {})
            if not isinstance(tool_arguments, dict):
                raise ValueError("external_action arguments must be an object")
            result = await gateway.external_action(request, tool_arguments)
            return {"operation": operation, **result}

        tool_name = arguments.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("execute requires a non-empty tool_name")
        tool_arguments = arguments.get("arguments", {})
        if not isinstance(tool_arguments, dict):
            raise ValueError("execute arguments must be an object")
        result = await gateway.execute(tool_name, tool_arguments)
        return {
            "ok": not result.is_error,
            "operation": operation,
            "status": result.status,
            "content": result.content,
            "is_error": result.is_error,
            "error_type": result.error_type,
            "retryable": result.retryable,
            "metadata": result.metadata,
        }
