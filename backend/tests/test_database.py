from luxion.database import Conversation, Message, check_connection, get_session_factory, init_db


def test_connection_check() -> None:
    assert check_connection() is True


def test_create_and_read_conversation() -> None:
    init_db()
    factory = get_session_factory()

    with factory() as session:
        conversation = Conversation(title="Phase 0")
        conversation.messages.append(Message(role="user", content="hello"))
        conversation.messages.append(Message(role="assistant", content="hi"))
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    with factory() as session:
        loaded = session.get(Conversation, conversation_id)
        assert loaded is not None
        assert loaded.title == "Phase 0"
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == "user"


def test_cascade_delete_removes_messages() -> None:
    init_db()
    factory = get_session_factory()

    with factory() as session:
        conversation = Conversation(title="to-delete")
        conversation.messages.append(Message(role="user", content="bye"))
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    with factory() as session:
        loaded = session.get(Conversation, conversation_id)
        session.delete(loaded)
        session.commit()

    with factory() as session:
        remaining = (
            session.query(Message).filter(Message.conversation_id == conversation_id).count()
        )
        assert remaining == 0
