"""Conversation history management and processing for Home Agent.

Provides HistoryManager for database-backed conversation CRUD and
sliding_window_processor for use with PydanticAI's history_processors.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse

from home_agent.db import get_history, save_message

logger = logging.getLogger(__name__)


class HistoryManager:
    """Manages conversation history with database persistence.

    Wraps db.py for message CRUD operations, providing a higher-level
    interface for saving and retrieving conversation history.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize HistoryManager with the database path.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)

    async def save_message(self, *, user_id: int, role: str, content: str) -> None:
        """Save a message to conversation history.

        Args:
            user_id: Telegram user ID.
            role: Message role ('user', 'assistant', or 'system').
            content: Message text content.
        """
        await save_message(self.db_path, user_id=user_id, role=role, content=content)
        logger.debug("Saved message for user %s (role=%s)", user_id, role)

    async def get_history(
        self, *, user_id: int, limit: int | None = None
    ) -> list[dict[str, str]]:
        """Fetch conversation history for a user.

        Args:
            user_id: Telegram user ID.
            limit: Optional maximum number of messages to return.

        Returns:
            List of messages, oldest first, each with 'role' and 'content' keys.
        """
        return await get_history(self.db_path, user_id=user_id, limit=limit)


def sliding_window_processor(
    *, n: int
) -> Callable[[list[ModelMessage]], list[ModelMessage]]:
    """Create a history processor that keeps only the last N message pairs.

    Returns a processor compatible with PydanticAI's history_processors.
    Each 'pair' is a ModelRequest followed by its ModelResponse.
    Tool-call/tool-result pairs are never split across the window boundary.

    Args:
        n: Number of message pairs to retain.

    Returns:
        A processor function that trims history to the last N pairs.
    """

    def processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        """Trim history to the last N request/response pairs.

        PydanticAI calls this processor on every model step, not just the first.
        The processor MUST return a non-empty list that ends with a ModelRequest.
        Any trailing incomplete sequence (i.e. everything after the last complete
        request/response pair) is always preserved verbatim so as not to violate
        that contract.

        Args:
            messages: Full conversation message list from PydanticAI.

        Returns:
            Reduced list containing the last N complete pairs, followed by any
            trailing messages that do not form a complete pair.
        """
        # Walk forward collecting complete (ModelRequest, ModelResponse) pairs and
        # tracking any trailing messages that don't form a complete pair.
        pairs: list[tuple[ModelRequest, ModelResponse]] = []
        tail: list[ModelMessage] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if isinstance(msg, ModelRequest):
                next_msg = messages[i + 1] if i + 1 < len(messages) else None
                if isinstance(next_msg, ModelResponse):
                    pairs.append((msg, next_msg))
                    i += 2
                    tail = []  # consumed — reset tail
                else:
                    # Unpaired request — part of the trailing sequence
                    tail = list(messages[i:])
                    break
            else:
                # Response without a preceding request in this window — skip
                i += 1

        # Keep only the last n pairs
        kept_pairs = pairs[-n:] if n < len(pairs) else pairs

        # Flatten pairs back to a list of ModelMessage
        result: list[ModelMessage] = []
        for req, resp in kept_pairs:
            result.append(req)
            result.append(resp)

        # Re-append any trailing messages (current step's in-progress sequence)
        result.extend(tail)

        return result

    return processor
