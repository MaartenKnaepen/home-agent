"""Tests for src/home_agent/bot.py.

Covers whitelist enforcement, typing indicator, and agent response behaviour.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.constants import ChatAction, ParseMode

from home_agent.bot import _split_message, create_application, make_callback_handler, make_message_handler
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.mcp.guarded_toolset import GuardedToolset
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

    update.message.reply_text.assert_called_once_with("Agent response\n", parse_mode=ParseMode.HTML)


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
async def test_rate_limit_sends_busy_message(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Bot sends busy message when rate limit is exhausted."""
    from pydantic_ai.exceptions import ModelHTTPError

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(
        side_effect=ModelHTTPError(
            status_code=429,
            model_name="test-model",
            body={"message": "rate limited"},
        )
    )

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("add Inception", user_id=123)
    await handler(update, MagicMock())

    update.message.reply_text.assert_called_once()
    call_arg = update.message.reply_text.call_args[0][0]
    assert "busy" in call_arg.lower() or "temporarily" in call_arg.lower()


@pytest.mark.asyncio
async def test_long_reply_is_split(mock_config: AppConfig, test_db: Path) -> None:
    """Agent reply exceeding 4096 chars is sent as multiple messages."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    long_reply = "a" * 5000
    mock_result = MagicMock()
    mock_result.output = long_reply

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=123)
    await handler(update, MagicMock())

    assert update.message.reply_text.call_count == 2


@pytest.mark.asyncio
async def test_short_reply_not_split(mock_config: AppConfig, test_db: Path) -> None:
    """Agent reply within 4096 chars is sent as a single message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Short reply"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=123)
    await handler(update, MagicMock())

    update.message.reply_text.assert_called_once()


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


# ---------------------------------------------------------------------------
# HTML parse_mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_reply_text_calls_use_html_parse_mode(
    mock_config: AppConfig, test_db: Path
) -> None:
    """All reply_text calls use parse_mode=ParseMode.HTML."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Hello world"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=123)
    await handler(update, MagicMock())

    for call in update.message.reply_text.call_args_list:
        kwargs = call.kwargs
        assert kwargs.get("parse_mode") == ParseMode.HTML, (
            f"reply_text called without parse_mode=HTML: {call}"
        )


@pytest.mark.asyncio
async def test_rejection_message_uses_html_parse_mode(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Rejection message for unauthorized users uses parse_mode=HTML."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_agent = MagicMock()
    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=99999)
    await handler(update, MagicMock())

    call_kwargs = update.message.reply_text.call_args.kwargs
    assert call_kwargs.get("parse_mode") == ParseMode.HTML


@pytest.mark.asyncio
async def test_error_message_uses_html_parse_mode(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Error messages use parse_mode=HTML."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(side_effect=Exception("boom"))

    handler = make_message_handler(mock_config, profile_manager, history_manager, mock_agent)
    update = make_test_update("hello", user_id=123)
    await handler(update, MagicMock())

    call_kwargs = update.message.reply_text.call_args.kwargs
    assert call_kwargs.get("parse_mode") == ParseMode.HTML


# ---------------------------------------------------------------------------
# create_application / CallbackQueryHandler registration tests
# ---------------------------------------------------------------------------


def test_create_application_registers_callback_handler(
    mock_config: AppConfig,
) -> None:
    """create_application registers a CallbackQueryHandler alongside the MessageHandler."""
    from telegram.ext import CallbackQueryHandler as TgCallbackQueryHandler

    profile_manager = MagicMock()
    history_manager = MagicMock()
    mock_agent = MagicMock()

    app = create_application(mock_config, profile_manager, history_manager, mock_agent)

    handler_types = [type(h) for h in app.handlers[0]]
    assert TgCallbackQueryHandler in handler_types, (
        "CallbackQueryHandler not registered in create_application"
    )


# ---------------------------------------------------------------------------
# Callback handler tests
# ---------------------------------------------------------------------------


def make_callback_update(
    data: str, user_id: int = 123
) -> tuple[Update, MagicMock]:
    """Create a mock Update containing a CallbackQuery.

    Args:
        data: The callback_data string (e.g. 'confirm:42:movie' or 'cancel').
        user_id: Telegram user ID.

    Returns:
        Tuple of (update, context).
    """
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = MagicMock()
    chat.id = user_id

    query = MagicMock(spec=CallbackQuery)
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = user
    update.effective_chat = chat

    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    return update, context


@pytest.mark.asyncio
async def test_callback_confirm_sets_confirmed_on_guarded_toolset(
    mock_config: AppConfig, test_db: Path
) -> None:
    """'confirm:{mediaId}:{mediaType}' callback sets confirmed=True on GuardedToolset."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    # Real GuardedToolset (not MagicMock) — AbstractToolset protocol enforced
    inner = MagicMock()
    inner.id = "test-server"
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="ok")

    guarded = GuardedToolset(inner)
    assert guarded.confirmed is False

    mock_result = MagicMock()
    mock_result.output = "Request submitted!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_callback_handler(
        mock_config, [guarded], mock_agent, profile_manager, history_manager
    )
    update, context = make_callback_update("confirm:42:movie", user_id=123)

    await handler(update, context)

    # GuardedToolset.set_confirmed must have been called — real flag is True
    assert guarded.confirmed is True
    update.callback_query.answer.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_cancel_sets_confirmed_false(
    mock_config: AppConfig, test_db: Path
) -> None:
    """'cancel' callback resets confirmed=False on GuardedToolset."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    inner = MagicMock()
    inner.id = "test-server"
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="ok")

    guarded = GuardedToolset(inner)
    # Pre-set confirmed=True to verify it gets reset
    guarded.confirmed = True

    mock_agent = MagicMock()
    handler = make_callback_handler(
        mock_config, [guarded], mock_agent, profile_manager, history_manager
    )
    update, context = make_callback_update("cancel", user_id=123)

    await handler(update, context)

    assert guarded.confirmed is False
    update.callback_query.answer.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_unauthorized_user_rejected(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Unauthorized user's callback query is rejected."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_agent = MagicMock()
    handler = make_callback_handler(
        mock_config, [], mock_agent, profile_manager, history_manager
    )
    update, context = make_callback_update("confirm:1:movie", user_id=99999)

    await handler(update, context)

    update.callback_query.answer.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once()
    call_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "authorized" in call_text.lower() or "not" in call_text.lower()


@pytest.mark.asyncio
async def test_callback_confirm_runs_agent(
    mock_config: AppConfig, test_db: Path
) -> None:
    """'confirm' callback re-runs the agent with a synthetic message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Done!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_callback_handler(
        mock_config, [], mock_agent, profile_manager, history_manager
    )
    update, context = make_callback_update("confirm:1:movie", user_id=123)

    await handler(update, context)

    mock_agent.run.assert_called_once()
    run_args = mock_agent.run.call_args
    # First positional arg is the synthetic message
    assert "confirm" in run_args[0][0].lower() or "proceed" in run_args[0][0].lower()
