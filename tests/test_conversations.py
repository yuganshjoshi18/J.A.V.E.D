from __future__ import annotations

import pytest

from memory.database import Database
from memory.repositories import ConversationRepository


@pytest.fixture
def db(app_paths):
    database = Database(app_paths.database_file)
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repository(db: Database) -> ConversationRepository:
    return ConversationRepository(db)


def test_create_list_and_rename(repository: ConversationRepository) -> None:
    first = repository.create("  First   conversation  ")
    second = repository.create()

    assert first.title == "First conversation"
    assert second.title == "New conversation"
    assert repository.count() == 2
    assert {item.id for item in repository.list()} == {first.id, second.id}

    assert repository.rename(first.id, "Renamed") is True
    reloaded = repository.get(first.id)
    assert reloaded is not None
    assert reloaded.title == "Renamed"
    assert repository.rename("missing", "Nope") is False

    with pytest.raises(ValueError):
        repository.rename(first.id, "   ")


def test_messages_are_ordered_and_update_the_conversation(
    repository: ConversationRepository,
) -> None:
    conversation = repository.create()
    user = repository.add_message(conversation.id, "user", "Hello")
    assistant = repository.add_message(
        conversation.id,
        "assistant",
        "Hi there",
        metadata={"model": "test"},
    )
    repository.add_message(conversation.id, "user", "Follow-up")

    messages = repository.messages(conversation.id)
    assert [message.id for message in messages] == [
        user.id,
        assistant.id,
        messages[2].id,
    ]
    assert [message.role for message in messages] == ["user", "assistant", "user"]
    assert messages[1].metadata == {"model": "test"}
    assert repository.message_count(conversation.id) == 3

    recent = repository.recent_messages(conversation.id, limit=2)
    assert [message.content for message in recent] == ["Hi there", "Follow-up"]

    updated = repository.get(conversation.id)
    assert updated is not None
    assert updated.updated_at >= conversation.updated_at


def test_rejects_invalid_messages(repository: ConversationRepository) -> None:
    conversation = repository.create()

    with pytest.raises(ValueError):
        repository.add_message(conversation.id, "user", "   ")
    with pytest.raises(ValueError):
        repository.add_message(conversation.id, "system", "not persisted")
    with pytest.raises(KeyError):
        repository.add_message("missing", "user", "Hello")


def test_delete_cascades_messages(repository: ConversationRepository) -> None:
    conversation = repository.create()
    repository.add_message(conversation.id, "user", "Hello")
    repository.add_message(conversation.id, "assistant", "Hi")

    assert repository.delete(conversation.id) is True
    assert repository.get(conversation.id) is None
    assert repository.messages(conversation.id) == []
    assert repository.delete(conversation.id) is False
