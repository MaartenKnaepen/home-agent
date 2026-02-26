"""Tests for src/home_agent/bot.py.

Covers whitelist enforcement, typing indicator, and agent response behaviour.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User
from telegram.constants import ChatAction

from home_agent.bot import make_message_handler
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_test_update(
    text: str, user_id: int = 123, language_code: str | None = "en"
) -> Update:
    """Create a mock Telegram Update for testing.

    Args:
        text: The message text.
        user_id: The Telegram user ID of the sender.
        language_code: Telegram locale code (e.g. 'en', 'nl'). Defaults to 'en'.

    Returns:
        A mock :class:`telegram.Update` object wired with AsyncMock reply methods.
    """
    user = User(id=user_id, is_bot=False, first_name="Test", language_code=language_code)
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
async def test_authorized_user_gets_agent_response(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Whitelisted user receives the agent's reply."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Agent response"

    mock_agent = MagicMock()
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=False)
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=123)
    await handler(update, MagicMock())

    update.message.reply_text.assert_called_once_with("Agent response")


@pytest.mark.asyncio
async def test_unauthorized_user_gets_rejection(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Non-whitelisted user receives the rejection message and no typing action."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    update = make_test_update("hello", user_id=99999)
    context = MagicMock()

    mock_agent = MagicMock()
    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    rejection_text: str = call_args[0][0]
    assert "not authorized" in rejection_text.lower()

    # Typing indicator must NOT be sent for unauthorized users
    update.effective_chat.send_action.assert_not_called()


@pytest.mark.asyncio
async def test_typing_action_sent_before_response(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Typing indicator is sent before the agent reply for authorized users."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "pong"

    mock_agent = MagicMock()
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=False)
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("ping", user_id=456)
    await handler(update, MagicMock())

    update.effective_chat.send_action.assert_called_once_with(action=ChatAction.TYPING)
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_new_user_gets_language_from_locale(
    mock_config: AppConfig, test_db: Path
) -> None:
    """New user with Dutch Telegram locale gets reply_language='Dutch'."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Hallo!"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hallo", user_id=123, language_code="nl")
    await handler(update, MagicMock())

    # Verify the profile was created with Dutch
    profile = await profile_manager.get(123)
    assert profile.reply_language == "Dutch"


@pytest.mark.asyncio
async def test_existing_user_language_not_overwritten(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Existing user's reply_language is not overwritten on subsequent messages."""
    from home_agent.profile import resolve_language  # noqa: F401 – imported for clarity

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    # Pre-create profile with French
    profile = await profile_manager.get(456, language_code="fr")
    assert profile.reply_language == "French"

    mock_result = MagicMock()
    mock_result.output = "Reply"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    # Send message with different language_code — should NOT overwrite
    update = make_test_update("hello", user_id=456, language_code="en")
    await handler(update, MagicMock())

    # Profile should still be French
    profile = await profile_manager.get(456)
    assert profile.reply_language == "French"
