"""Framework-neutral persistent Jarvis state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SharedSession:
    user_id: str
    conversation_id: str
    jarvis_id: str = "jarvis"
    runtime_session_id: str | None = None
    active_framework: str | None = None
    tool_context: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationMessage:
    conversation_id: str
    role: str
    content: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    framework: str | None = None
    runtime_session_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEntry:
    user_id: str
    content: str
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str | None = None
    source: str = "user"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    expires_at: str | None = None
    active: bool = True


@dataclass(frozen=True)
class ContextPackage:
    session: SharedSession
    recent_messages: list[ConversationMessage]
    relevant_memories: list[MemoryEntry]
    active_task: str | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JarvisState:
    session: SharedSession
    messages: list[ConversationMessage]
    memories: list[MemoryEntry]
