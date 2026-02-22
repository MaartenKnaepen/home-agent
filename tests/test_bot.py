"""Tests for src/home_agent/bot.py.

Covers whitelist enforcement, typing indicator, and stub response behaviour.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User
from telegram.constants import ChatAction

from home_agent.bot import make_message_handler
from home_agent.config import AppConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_test_update(text: str, user_id: int = 123) -> Update:
    """Create a mock Telegram Update for testing.

    Args:
        text: The message text.
        user_id: The Telegram user ID of the sender.

    Returns:
        A mock :class:`telegram.Update` object wired with AsyncMock reply methods.
    """
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")

    message = MagicMock(spec=Message)
    message.text = text
    message.from_user = user
    message.chat = chat
    message.chat_id = user_id
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.send_action = AsyncMock()
    update.message = message

    return update


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_user_gets_stub_response(mock_config: AppConfig) -> None:
    """Whitelisted user receives the stub echo reply."""
    update = make_test_update("hello world", user_id=123)
    context = MagicMock()

    handler = make_message_handler(mock_config)
    await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    reply_text: str = call_args[0][0]
    assert "[Agent stub] You said: hello world" in reply_text


@pytest.mark.asyncio
async def test_unauthorized_user_gets_rejection(mock_config: AppConfig) -> None:
    """Non-whitelisted user receives the rejection message and no typing action."""
    update = make_test_update("hello", user_id=99999)
    context = MagicMock()

    handler = make_message_handler(mock_config)
    await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    rejection_text: str = call_args[0][0]
    assert "not authorized" in rejection_text.lower()

    # Typing indicator must NOT be sent for unauthorized users
    update.effective_chat.send_action.assert_not_called()


@pytest.mark.asyncio
async def test_typing_action_sent_before_response(mock_config: AppConfig) -> None:
    """Typing indicator is sent before the stub reply for authorized users."""
    update = make_test_update("ping", user_id=456)
    context = MagicMock()

    handler = make_message_handler(mock_config)
    await handler(update, context)

    update.effective_chat.send_action.assert_called_once_with(action=ChatAction.TYPING)
    update.message.reply_text.assert_called_once()
