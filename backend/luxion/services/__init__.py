"""Service layer: use-case orchestration between the API and the core."""

from luxion.services.chat import (
    ChatDelta,
    ChatDone,
    ChatError,
    ChatStreamEvent,
    stream_reply,
)
from luxion.services.conversations import (
    ConversationNotFound,
    append_message,
    apply_auto_title,
    create_conversation,
    delete_conversation,
    get_conversation,
    history,
    list_conversations,
)

__all__ = [
    "ChatDelta",
    "ChatDone",
    "ChatError",
    "ChatStreamEvent",
    "ConversationNotFound",
    "append_message",
    "apply_auto_title",
    "create_conversation",
    "delete_conversation",
    "get_conversation",
    "history",
    "list_conversations",
    "stream_reply",
]
