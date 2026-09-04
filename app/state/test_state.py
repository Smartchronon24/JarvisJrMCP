import pytest

from app.state import (
    ConversationMessage,
    MemoryEntry,
    PersistentStateStore,
    SharedSession,
)


def test_conversation_persists_across_store_instances(tmp_path):
    path = tmp_path / "state.db"
    session = SharedSession("user-1", "conversation-1", active_framework="copilot")
    store = PersistentStateStore(path)
    store.save_session(session)
    store.append_message(ConversationMessage(session.conversation_id, "user", "hello"))

    restored = PersistentStateStore(path)
    assert restored.load_session(session.conversation_id) == session
    assert restored.list_messages(session.conversation_id)[0].content == "hello"


def test_memory_requires_explicit_write_and_supports_delete(tmp_path):
    store = PersistentStateStore(tmp_path / "state.db")
    entry = MemoryEntry("user-1", "User prefers concise answers", source="user")
    with pytest.raises(PermissionError):
        store.write_memory(entry)
    store.write_memory(entry, explicit=True)
    assert store.list_memories("user-1")[0].source == "user"
    assert store.delete_memory("user-1", entry.memory_id)
    assert store.list_memories("user-1") == []


def test_context_is_scoped_to_user_and_conversation(tmp_path):
    store = PersistentStateStore(tmp_path / "state.db")
    session = SharedSession("user-1", "conversation-1")
    store.save_session(session)
    store.append_message(ConversationMessage(session.conversation_id, "user", "task"))
    store.write_memory(MemoryEntry("user-1", "shared preference"), explicit=True)
    store.write_memory(MemoryEntry("user-2", "private preference"), explicit=True)

    context = store.assemble_context(session, active_task="preference")
    assert len(context.recent_messages) == 1
    assert [memory.content for memory in context.relevant_memories] == ["shared preference"]
