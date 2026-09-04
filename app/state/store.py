"""SQLite-backed shared state, conversation, memory, and context services."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    ContextPackage,
    ConversationMessage,
    MemoryEntry,
    SharedSession,
    utc_now,
)


class PersistentStateStore:
    """Small durable store independent of any framework runtime."""

    def __init__(self, path: str | Path = "data/jarvis_state.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    jarvis_id TEXT NOT NULL,
                    runtime_session_id TEXT,
                    active_framework TEXT,
                    tool_context TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    framework TEXT,
                    runtime_session_id TEXT,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_idx
                    ON messages(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    active INTEGER NOT NULL
                );
                """
            )

    def save_session(self, session: SharedSession) -> SharedSession:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id=excluded.user_id, jarvis_id=excluded.jarvis_id,
                    runtime_session_id=excluded.runtime_session_id,
                    active_framework=excluded.active_framework,
                    tool_context=excluded.tool_context,
                    permissions=excluded.permissions,
                    updated_at=excluded.updated_at
                """,
                (
                    session.conversation_id,
                    session.user_id,
                    session.jarvis_id,
                    session.runtime_session_id,
                    session.active_framework,
                    json.dumps(session.tool_context),
                    json.dumps(session.permissions),
                    utc_now(),
                ),
            )
        return session

    def load_session(self, conversation_id: str) -> SharedSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        if row is None:
            return None
        return SharedSession(
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            jarvis_id=row["jarvis_id"],
            runtime_session_id=row["runtime_session_id"],
            active_framework=row["active_framework"],
            tool_context=json.loads(row["tool_context"]),
            permissions=json.loads(row["permissions"]),
        )

    def append_message(self, message: ConversationMessage) -> ConversationMessage:
        if message.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {message.role}")
        if not message.content:
            raise ValueError("message content must not be empty")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.message_id,
                    message.conversation_id,
                    message.role,
                    message.content,
                    message.framework,
                    message.runtime_session_id,
                    message.created_at,
                    json.dumps(message.metadata),
                ),
            )
        return message

    def list_messages(self, conversation_id: str, limit: int | None = None) -> list[ConversationMessage]:
        query = "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid"
        params: list[Any] = [conversation_id]
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            ConversationMessage(
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"],
                message_id=row["message_id"],
                framework=row["framework"],
                runtime_session_id=row["runtime_session_id"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def write_memory(self, entry: MemoryEntry, *, explicit: bool = False) -> MemoryEntry:
        if not explicit:
            raise PermissionError("memory writes require explicit confirmation")
        if not entry.content.strip():
            raise ValueError("memory content must not be empty")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.memory_id, entry.user_id, entry.conversation_id,
                    entry.content, entry.source, entry.created_at,
                    entry.updated_at, entry.expires_at, int(entry.active),
                ),
            )
        return entry

    def list_memories(self, user_id: str, query: str | None = None) -> list[MemoryEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE user_id = ? AND active = 1 "
                "AND (expires_at IS NULL OR expires_at > ?) ORDER BY updated_at DESC",
                (user_id, utc_now()),
            ).fetchall()
        entries = [
            MemoryEntry(
                user_id=row["user_id"], conversation_id=row["conversation_id"],
                content=row["content"], memory_id=row["memory_id"],
                source=row["source"], created_at=row["created_at"],
                updated_at=row["updated_at"], expires_at=row["expires_at"],
                active=bool(row["active"]),
            )
            for row in rows
        ]
        if query:
            terms = {term.lower() for term in query.split() if term.strip()}
            entries = [entry for entry in entries if terms & set(entry.content.lower().split())]
        return entries

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE memories SET active = 0, updated_at = ? "
                "WHERE memory_id = ? AND user_id = ? AND active = 1",
                (utc_now(), memory_id, user_id),
            )
        return cursor.rowcount == 1

    def assemble_context(
        self,
        session: SharedSession,
        *,
        active_task: str | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        user_preferences: dict[str, Any] | None = None,
        recent_limit: int = 12,
    ) -> ContextPackage:
        return ContextPackage(
            session=session,
            recent_messages=self.list_messages(session.conversation_id, recent_limit),
            relevant_memories=self.list_memories(session.user_id, active_task),
            active_task=active_task,
            tool_results=list(tool_results or []),
            user_preferences=dict(user_preferences or {}),
        )
